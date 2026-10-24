import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
from http.server import ThreadingHTTPServer
from sage.team_console import State, handler, password_hash, password_ok

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.previous=dict(os.environ)
        os.environ.pop('SAGE_OPENAI_API_KEY',None)
        self.password='testing-password-12345'
        (self.root/'users.json').write_text(json.dumps({'admin':{**password_hash(self.password),'admin':True},'member':{**password_hash(self.password),'admin':False}}))
        self.store=Mock()
        self.store.lock=threading.RLock()
        self.store.run_ids.return_value=['real-run']
        self.store.summary.return_value={'id':'real-run','launcher_alive':False}
        self.store.section.return_value={'data':{'real_artifact':True}}
        self.store.artifact.return_value=b'exact source bytes'
        self.store.start.return_value={'id':'new-test-run'}
        self.state=State(self.root,self.store,self.root)
        self.state.static=Path(__file__).resolve().parents[1]/'sage/console_static'
        self.state.origin='https://team.example'
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.state))
        threading.Thread(target=self.server.serve_forever,daemon=True).start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.tmp.cleanup()
        os.environ.clear();os.environ.update(self.previous)

    def request(self,path,body=None,cookie=None,csrf=None,origin='https://team.example',host='team.example'):
        headers={'Host':host,'Origin':origin,'Content-Type':'application/json'}
        if cookie:headers['Cookie']=cookie
        if csrf:headers['X-CSRF-Token']=csrf
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        c.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=headers)
        r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read());c.close();return result

    def login(self,name='admin'):
        status,headers,_=self.request('/auth/login',{'username':name,'password':self.password})
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie'].split(';',1)[0]
        _,_,data=self.request('/auth/me',cookie=cookie)
        return cookie,json.loads(data)['csrf'],headers

    def test_all_data_require_login_and_wrong_host_rejected(self):
        for route in ['/api/runs','/api/run?id=real-run','/api/artifact?id=real-run&name=result.json','/auth/me']:
            self.assertEqual(self.request(route)[0],401)
        self.assertEqual(self.request('/download/full-export')[0],303)
        self.assertEqual(self.request('/login',host='evil.example')[0],421)
        self.store.start.assert_not_called()

    def test_login_password_hash_and_session_flags(self):
        self.assertFalse(password_ok('incorrect',password_hash(self.password)))
        self.assertEqual(self.request('/auth/login',{'username':'admin','password':'bad'})[0],401)
        cookie,csrf,headers=self.login()
        for flag in ['Secure','HttpOnly','SameSite=Lax','Path=/']:self.assertIn(flag,headers['Set-Cookie'])
        status,_,data=self.request('/api/runs',cookie=cookie)
        self.assertEqual(status,200);self.assertFalse(json.loads(data)['allow_live'])
        self.assertNotIn(self.password,(self.root/'users.json').read_text())

    def test_csrf_origin_and_admin_controls(self):
        cookie,csrf,_=self.login('member')
        self.assertEqual(self.request('/api/runs',{},cookie=cookie)[0],403)
        self.assertEqual(self.request('/api/runs',{},cookie=cookie,csrf=csrf,origin='https://evil.example')[0],403)
        self.assertEqual(self.request('/admin/provider',{'key':'test-key-not-real-12345'},cookie=cookie,csrf=csrf)[0],403)
        self.assertEqual(self.request('/api/runs',{},cookie=cookie,csrf=csrf)[0],400)
        self.store.start.assert_not_called()

    def test_all_members_use_real_start_contract_after_key_config(self):
        cookie,csrf,_=self.login()
        self.assertEqual(self.request('/admin/provider',{'key':'test-key-not-real-12345'},cookie=cookie,csrf=csrf)[0],200)
        self.assertTrue(self.state.store.allow_live)
        cookie,csrf,_=self.login('member')
        body={'topic':'test research','allow_live':True,'wall_seconds':60}
        self.assertEqual(self.request('/api/runs',body,cookie=cookie,csrf=csrf)[0],201)
        self.store.start.assert_called_once_with(body)
        self.assertIn('member',(self.root/'access-audit.jsonl').read_text())
        self.assertNotIn('test-key-not-real-12345',self.request('/auth/me',cookie=cookie)[2].decode())

    def test_exact_download_and_real_section(self):
        cookie,_,_=self.login('member')
        status,_,data=self.request('/api/artifact?id=real-run&name=result.json',cookie=cookie)
        self.assertEqual(status,200);self.assertEqual(data,b'exact source bytes')
        self.store.artifact.assert_called_once_with('real-run','result.json')
        self.assertEqual(self.request('/api/run?id=real-run&section=evidence',cookie=cookie)[0],200)
        self.store.section.assert_called_once_with('real-run','evidence')

    def test_live_planning_requires_auth_csrf_and_config_and_never_starts_research(self):
        body={'request_id':'interview_request_123','seed':'topic','turns':[],'allow_live':True}
        self.state.planner=Mock()
        self.state.planner.step.return_value={'question':{'title':'dynamic question','options':[]},'usage':{}}
        self.assertEqual(self.request('/api/planning/next',body)[0],401)
        cookie,csrf,_=self.login('member')
        self.assertEqual(self.request('/api/planning/next',body,cookie=cookie)[0],403)
        self.assertEqual(self.request('/api/planning/next',body,cookie=cookie,csrf=csrf)[0],400)
        self.state.planner.step.assert_not_called()
        self.store.allow_live=True
        status,_,data=self.request('/api/planning/next',body,cookie=cookie,csrf=csrf)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(data)['question']['title'],'dynamic question')
        self.state.planner.step.assert_called_once_with('member',body)
        self.store.start.assert_not_called()

    def test_planning_assets_and_settings_preserve_auth_and_do_not_launch(self):
        cookie,_,_=self.login('member')
        status,_,page=self.request('/',cookie=cookie)
        self.assertEqual(status,200)
        for asset in ('/planner.js','/planner-ui.js','/planner.css'):
            self.assertIn(asset.encode(),page)
            self.assertEqual(self.request(asset)[0],303)
            self.assertEqual(self.request(asset,cookie=cookie)[0],200)
        self.assertEqual(self.request('/app.js',cookie=cookie)[2],(self.state.static/'app.js').read_bytes())
        self.assertFalse(json.loads(self.request('/auth/me',cookie=cookie)[2])['bundle_available'])
        self.assertEqual(self.request('/settings',cookie=cookie)[0],200)
        self.store.start.assert_not_called()

    def test_key_change_blocked_while_research_active_and_password_type_checked(self):
        cookie,csrf,_=self.login()
        self.store.summary.return_value={'launcher_alive':True}
        self.assertEqual(self.request('/admin/provider',{'key':'test-key-not-real-12345'},cookie=cookie,csrf=csrf)[0],400)
        self.assertFalse((self.root/'provider.json').exists())
        self.assertEqual(self.request('/auth/password',{'current_password':[], 'password':'replacement-password'},cookie=cookie,csrf=csrf)[0],400)

    def test_account_create_password_change_and_logout_revocation(self):
        cookie,csrf,_=self.login()
        self.assertEqual(self.request('/admin/users',{'username':'alice','password':'a-secure-test-password'},cookie=cookie,csrf=csrf)[0],200)
        self.assertFalse(self.state.users['alice']['admin'])
        self.assertEqual(self.request('/auth/password',{'current_password':self.password,'password':'replacement-password-2026'},cookie=cookie,csrf=csrf)[0],200)
        self.assertEqual(self.request('/auth/me',cookie=cookie)[0],401)
        cookie,csrf,_=self.login('member')
        self.assertEqual(self.request('/auth/logout',{},cookie=cookie,csrf=csrf)[0],200)
        self.assertEqual(self.request('/auth/me',cookie=cookie)[0],401)

    def test_login_rate_limit_and_expiry(self):
        for _ in range(10):
            self.assertEqual(self.request('/auth/login',{'username':'absent','password':'bad'})[0],401)
        self.assertEqual(self.request('/auth/login',{'username':'absent','password':'bad'})[0],429)
        raw,session=self.state.new_session('member')
        session['expires']=0
        self.assertEqual(self.request('/auth/me',cookie='__Host-sage_session='+raw)[0],401)

if __name__=='__main__':unittest.main()
