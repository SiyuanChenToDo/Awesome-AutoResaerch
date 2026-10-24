"""Authenticated HTTPS team adapter for the real SAGE RunStore; no copied results."""
import argparse
import getpass
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from .planning import Planner, PlanningError
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).with_name('team_console_static')
COOKIE = '__Host-sage_session'

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return {'salt': salt, 'hash': digest}

def password_ok(password, record):
    return hmac.compare_digest(password_hash(password, record['salt'])['hash'], record['hash'])

def private_json(path, value):
    temp = path.with_suffix('.tmp')
    with os.fdopen(os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), 'w') as f:
        json.dump(value, f)
    os.chmod(temp, 0o600)
    os.replace(temp, path)

class State:
    def __init__(self, directory, store, static, bundle=None):
        self.directory, self.store, self.static = Path(directory), store, Path(static)
        self.bundle = Path(bundle) if bundle else None
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.users = json.loads((self.directory / 'users.json').read_text())
        self.sessions = {}
        self.attempts = OrderedDict()
        self.lock = threading.RLock()
        self.dummy = password_hash(secrets.token_urlsafe(32))
        self.origin = ''
        self.planner = Planner()
        self.config_path = self.directory / 'provider.json'
        if self.config_path.exists():
            self.install_provider(json.loads(self.config_path.read_text())['key'])
        self.store.allow_live = bool(os.environ.get('SAGE_OPENAI_API_KEY'))

    def install_provider(self, key):
        os.environ.update(SAGE_MODEL_PROVIDER='deepseek', SAGE_OPENAI_API_KEY=key,
                          DEEPSEEK_API_KEY=key, SAGE_OPENAI_BASE_URL='https://api.deepseek.com',
                          SAGE_MAIN_MODEL='deepseek-flash', SAGE_CHEAP_MODEL='deepseek-flash')
        self.store.allow_live = True

    def audit(self, event, username, **fields):
        row = {'time': datetime.now(timezone.utc).isoformat(), 'event': event, 'username': username, **fields}
        with self.lock:
            with (self.directory / 'access-audit.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')

    def new_session(self, username):
        raw = secrets.token_urlsafe(32)
        record = {'username': username, 'csrf': secrets.token_urlsafe(32), 'expires': time.time() + 12*3600}
        with self.lock:
            self.sessions = {k:v for k,v in self.sessions.items() if v['expires'] > time.time()}
            if len(self.sessions) >= 2048:
                self.sessions.pop(next(iter(self.sessions)))
            self.sessions[hashlib.sha256(raw.encode()).hexdigest()] = record
        return raw, record

    def session(self, headers):
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get('Cookie', ''))
            raw = cookie[COOKIE].value
            digest = hashlib.sha256(raw.encode()).hexdigest()
        except (KeyError, ValueError):
            return None
        with self.lock:
            record = self.sessions.get(digest)
            if record and record['expires'] > time.time() and record['username'] in self.users:
                return {**record, 'digest': digest, 'admin': self.users[record['username']].get('admin', False)}
        return None

    def login_allowed(self, ip):
        now = time.time()
        with self.lock:
            for key in ('global', ip):
                old = [t for t in self.attempts.get(key, []) if t > now-300]
                self.attempts[key] = old
                if len(old) >= (100 if key == 'global' else 10):
                    return False
            self.attempts['global'].append(now)
            self.attempts[ip].append(now)
            while len(self.attempts) > 4096:
                self.attempts.popitem(last=False)
        return True

def handler(state):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'SAGE'
        def setup(self):
            super().setup()
            self.connection.settimeout(20)

        def log_message(self, *args):
            pass

        def send(self, body, status=200, mime='application/json; charset=utf-8', headers=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            defaults = {'Content-Type': mime, 'Content-Length': str(len(body)), 'Cache-Control': 'no-store',
                'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer', 'X-Frame-Options':'DENY',
                'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                'Strict-Transport-Security':'max-age=31536000'}
            for key, value in {**defaults, **(headers or {})}.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def external_ok(self):
            # Public origin is pinned after tunnel registration; no forwarded-host trust.
            origin_path = state.directory / 'public-origin.txt'
            origin = origin_path.read_text().strip() if origin_path.exists() else state.origin
            return origin and self.headers.get('Host') == urlsplit(origin).netloc

        def same_origin(self):
            origin_path = state.directory / 'public-origin.txt'
            origin = origin_path.read_text().strip() if origin_path.exists() else state.origin
            return self.external_ok() and self.headers.get('Origin') == origin

        def read_body(self):
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('Unsupported body encoding')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 100000:
                raise ValueError('Invalid request size')
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('JSON required')
            obj = json.loads(self.rfile.read(length))
            if not isinstance(obj, dict):
                raise ValueError('Object required')
            return obj

        def do_GET(self):
            if not self.external_ok():
                return self.send({'error':'Unknown host'}, 421)
            parsed = urlsplit(self.path)
            if parsed.path in ('/login', '/team.css', '/login.js'):
                name, mime = {'/login':('login.html','text/html; charset=utf-8'),
                    '/team.css':('team.css','text/css; charset=utf-8'),
                    '/login.js':('login.js','text/javascript; charset=utf-8')}[parsed.path]
                return self.send((HERE/name).read_bytes(), mime=mime)
            session = state.session(self.headers)
            if not session:
                if parsed.path.startswith('/api/') or parsed.path.startswith('/auth/'):
                    return self.send({'error':'请先登录'}, 401)
                return self.send(b'', 303, headers={'Location':'/login'})
            try:
                if parsed.path == '/auth/me':
                    return self.send({'username':session['username'], 'admin':session['admin'],
                        'csrf':session['csrf'], 'provider_ready':state.store.allow_live,
                        'bundle_available':bool(state.bundle and state.bundle.is_file()),
                        'users':[{'username':n,'admin':v.get('admin',False)} for n,v in state.users.items()] if session['admin'] else []})
                if parsed.path == '/settings':
                    return self.send((HERE/'settings.html').read_bytes(), mime='text/html; charset=utf-8')
                if parsed.path in ('/team.js','/settings.js'):
                    return self.send((HERE/parsed.path[1:]).read_bytes(), mime='text/javascript; charset=utf-8')
                if parsed.path == '/':
                    page = (state.static/'index.html').read_text(encoding='utf-8')
                    page = page.replace('<body>', '<body><div class="team-bar"><a href="/settings">账号与模型设置</a><button id="logout">退出登录</button></div>')
                    page = page.replace('</head>', '<link rel="stylesheet" href="/team.css"></head>')
                    page = page.replace('<script src="/app.js" defer></script>', '<script src="/team.js" defer></script><script src="/app.js" defer></script>')
                    return self.send(page.encode(), mime='text/html; charset=utf-8')
                if parsed.path == '/app.js':
                    return self.send((state.static/'app.js').read_bytes(), mime='text/javascript; charset=utf-8')
                if parsed.path in ('/style.css', '/planner.js', '/planner-ui.js', '/planner.css', '/reading.js', '/reading-ui.js', '/reading.css'):
                    mime = 'text/css; charset=utf-8' if parsed.path.endswith('.css') else 'text/javascript; charset=utf-8'
                    return self.send((state.static/parsed.path[1:]).read_bytes(), mime=mime)
                if parsed.path == '/api/runs':
                    return self.send({'runs':[state.store.summary(i) for i in state.store.run_ids()], 'allow_live':state.store.allow_live})
                query = parse_qs(parsed.query)
                ident = query.get('id', [''])[0]
                if parsed.path == '/api/run':
                    return self.send(state.store.section(ident, query.get('section',['summary'])[0]))
                if parsed.path == '/api/artifact':
                    name = query.get('name',[''])[0]
                    return self.send(state.store.artifact(ident,name), mime='application/octet-stream',
                                     headers={'Content-Disposition':'attachment; filename="'+name+'"'})
                if parsed.path == '/download/full-export' and state.bundle and state.bundle.is_file():
                    return self.send(state.bundle.read_bytes(), mime='application/zip',
                        headers={'Content-Disposition':'attachment; filename="research-complete.zip"'})
                return self.send({'error':'Not found'},404)
            except (ValueError, OSError):
                return self.send({'error':'文件或请求不可用'},400)

        def do_POST(self):
            if not self.same_origin():
                return self.send({'error':'Origin rejected'},403)
            path = urlsplit(self.path).path
            if path == '/auth/login':
                if not state.login_allowed(self.headers.get('CF-Connecting-IP', self.client_address[0])):
                    return self.send({'error':'登录尝试过多，请稍后再试'},429)
                try:
                    obj = self.read_body()
                    username, password = obj.get('username',''), obj.get('password','')
                    if not isinstance(username,str) or not isinstance(password,str) or len(password)>256:
                        raise ValueError()
                    record = state.users.get(username)
                    ok = password_ok(password, record or state.dummy)
                    if not record or not ok:
                        return self.send({'error':'账号或密码错误'},401)
                    raw, _ = state.new_session(username)
                    state.audit('login',username)
                    return self.send({'ok':True}, headers={'Set-Cookie':COOKIE+'='+raw+'; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=43200'})
                except (ValueError, TypeError):
                    return self.send({'error':'登录参数无效'},400)
            session = state.session(self.headers)
            if not session:
                return self.send({'error':'请先登录'},401)
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),session['csrf']):
                return self.send({'error':'CSRF rejected'},403)
            try:
                obj = self.read_body()
                username = session['username']
                if path == '/api/planning/next':
                    if not state.store.allow_live:
                        raise ValueError('请管理员先在账号与模型设置中配置模型密钥')
                    try:
                        result = state.planner.step(username, obj)
                    except PlanningError as exc:
                        return self.send({'error':str(exc)}, exc.status)
                    state.audit('planning_question',username,usage=result.get('usage',{}))
                    return self.send(result)
                if path == '/auth/logout':
                    with state.lock:
                        state.sessions.pop(session['digest'],None)
                    return self.send({'ok':True},headers={'Set-Cookie':COOKIE+'=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0'})
                if path == '/auth/password':
                    new = obj.get('password','')
                    current = obj.get('current_password', '')
                    if not isinstance(current, str) or len(current) > 256:
                        raise ValueError('当前密码格式无效')
                    if not isinstance(new,str) or not 12 <= len(new) <= 128:
                        raise ValueError('密码长度需为 12–128 个字符')
                    with state.lock:
                        if not password_ok(current,state.users[username]):
                            raise ValueError('当前密码不正确')
                        state.users[username].update(password_hash(new))
                        private_json(state.directory/'users.json',state.users)
                        state.sessions = {k:v for k,v in state.sessions.items() if v['username']!=username}
                    state.audit('password_changed',username)
                    return self.send({'ok':True})
                if path in ('/admin/users','/admin/provider') and not session['admin']:
                    return self.send({'error':'需要管理员账号'},403)
                if path == '/admin/users':
                    name, password = obj.get('username',''),obj.get('password','')
                    if not isinstance(name,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{3,40}',name):
                        raise ValueError('账号需为 3–40 位字母、数字、下划线或短横线')
                    if not isinstance(password,str) or not 12<=len(password)<=128:
                        raise ValueError('密码长度需为 12–128 个字符')
                    with state.lock:
                        if name in state.users:
                            raise ValueError('该账号已存在')
                        state.users[name]={**password_hash(password),'admin':False}
                        private_json(state.directory/'users.json',state.users)
                    state.audit('account_created',username,created_user=name)
                    return self.send({'ok':True})
                if path == '/admin/provider':
                    key=obj.get('key','')
                    if not isinstance(key,str) or not 16<=len(key)<=512 or any(c.isspace() for c in key):
                        raise ValueError('请输入有效的 DeepSeek API 密钥')
                    with state.lock, state.store.lock:
                        if any(state.store.summary(i).get('launcher_alive') for i in state.store.run_ids()):
                            raise ValueError('研究运行期间不能更换密钥')
                        private_json(state.config_path,{'key':key})
                        state.install_provider(key)
                    state.audit('provider_configured',username)
                    return self.send({'ok':True,'validation':'saved_without_paid_api_call'})
                if path == '/api/runs':
                    with state.lock:
                        if not state.store.allow_live:
                            raise ValueError('请管理员先在账号与模型设置中配置 DeepSeek API 密钥')
                        result=state.store.start(obj)
                    state.audit('research_started',username,run_id=result['id'])
                    return self.send(result,201)
                return self.send({'error':'Not found'},404)
            except (ValueError,TypeError,KeyError) as exc:
                return self.send({'error':str(exc) if isinstance(exc,ValueError) else '请求格式错误'},400)
            except OSError:
                return self.send({'error':'服务器操作失败；请管理员检查'},500)
    return Handler

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument('--state',required=True)
    parser.add_argument('--port',type=int,default=8780)
    parser.add_argument('--bundle')
    parser.add_argument('--init-admin', metavar='USERNAME', help='Create the first admin with a hidden password prompt, then exit')
    args=parser.parse_args()
    repo=Path(args.repo).resolve()
    directory=Path(args.state).resolve()
    if directory == repo or repo in directory.parents:
        parser.error('--state must be outside the public repository')
    if args.init_admin:
        if not re.fullmatch(r'[a-zA-Z0-9_-]{3,40}', args.init_admin):
            parser.error('Admin name must be 3..40 letters, numbers, underscores or hyphens')
        if (directory/'users.json').exists():
            parser.error('Accounts already exist; use the admin page to add members')
        password=getpass.getpass('Initial admin password (12..128 characters): ')
        if not 12 <= len(password) <= 128 or password != getpass.getpass('Repeat password: '):
            parser.error('Invalid length or passwords do not match')
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Exclusive creation: never overwrite accounts, even with concurrent initialization.
        with os.fdopen(os.open(directory/'users.json', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w') as f:
            json.dump({args.init_admin:{**password_hash(password), 'admin':True}}, f)
        print('Admin created. Configure an HTTPS origin before serving.')
        return
    from sage.console import RunStore
    store=RunStore(repo/'projects',allow_live=False,repo=repo)
    state=State(directory,store,repo/'sage/console_static',args.bundle)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(state))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__=='__main__':
    main()
