"""One-time Linux installation; subsequent research needs only a DeepSeek API key.

Install reviewed native upstream revisions outside the source tree. Never import
or modify the immutable archival snapshots under third_party/.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from urllib.request import urlopen

NODE = 'v24.22.0'
NODE_SHA256 = 'cc2f601cee82d9a5a233302fe307abc600727035fd7d2c3a3571755989e95008'
DSH = '0.2.0-rc.2'
ARIS = '15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee'
CORAL = '0123dfb939b35228cf2c1fde224cd0561e727408'


def run(argv, **kwargs):
    subprocess.run([str(x) for x in argv], check=True, timeout=1200, **kwargs)


def download(url, destination):
    with urlopen(url, timeout=120) as source, destination.open('wb') as target:
        shutil.copyfileobj(source, target)


def main():
    if sys.platform != 'linux' or sys.version_info < (3, 12) or os.geteuid() != 0:
        raise SystemExit('This adapter requires Linux x86_64, Python 3.12+ and root for CORAL OS-user isolation')
    if os.uname().machine != 'x86_64':
        raise SystemExit('This bootstrap currently pins the Linux x86_64 Node binary')
    home = Path(os.environ.get('SAGE_NATIVE_HOME', Path.home() / '.cache' / 'sage' / 'native')).absolute()
    home.mkdir(parents=True, exist_ok=True)
    # Directory traversal only: no permission to list/read the operator home.
    # Existing .ssh/private file permissions remain the host's responsibility.
    for parent in (home, *home.parents):
        parent.chmod(parent.stat().st_mode | 0o001)
    node_dir = home / f'node-{NODE}-linux-x64'
    if not node_dir.is_dir():
        archive = home / 'node.tar.xz'
        download(f'https://nodejs.org/dist/{NODE}/node-{NODE}-linux-x64.tar.xz', archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != NODE_SHA256:
            raise SystemExit('Node distribution checksum mismatch')
        with tarfile.open(archive) as bundle:
            bundle.extractall(home, filter='data')
    os.environ['PATH'] = str(node_dir / 'bin') + os.pathsep + os.environ['PATH']
    # npm's peer resolver loops on the mutually dependent DSH prerelease
    # packages. pnpm is the upstream's native package manager.
    pnpm_dir = home / 'pnpm'
    if not (pnpm_dir / 'node_modules' / '.bin' / 'pnpm').is_file():
        run(['npm', 'install', '--prefix', pnpm_dir, '--ignore-scripts', 'pnpm@10.34.7'])
    pnpm = pnpm_dir / 'node_modules' / '.bin' / 'pnpm'
    dsh_dir = home / 'dsh'
    dsh_dir.mkdir(exist_ok=True)
    if not (dsh_dir / 'node_modules' / '.bin' / 'dsh').is_file():
        run([pnpm, '--dir', dsh_dir, 'add', '@deepseek-ai/dsh@' + DSH])
    for name, url, commit in (
        ('ARIS', 'https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep.git', ARIS),
        ('CORAL', 'https://github.com/Human-Agent-Society/CORAL.git', CORAL)):
        path = home / name
        if not path.exists():
            run(['git', 'clone', '--filter=blob:none', url, path])
        run(['git', '-C', path, 'checkout', '--detach', commit])
    venv = home / 'python'
    if not (venv / 'bin' / 'python').is_file():
        run([sys.executable, '-m', 'venv', venv])
    python = venv / 'bin' / 'python'
    run([python, '-m', 'pip', 'install', 'uv', 'openai', 'pypdf', '-e', home / 'CORAL'])
    frozen = subprocess.check_output([str(python), '-c',
        'import importlib.metadata as m;print("\\n".join(sorted({d.metadata["Name"]+"=="+d.version '
        'for d in m.distributions() if d.metadata.get("Name", "").lower() != "coral"})))'], text=True)
    constraints = home / 'dependencies.txt'
    constraints.write_text(frozen + '\n', encoding='utf-8')
    # Reuse pip's just-downloaded wheels for CORAL's separately managed venvs.
    # Keep full native dependencies; do not strip its manager or grading modules.
    run([python, '-m', 'pip', 'download', '--no-deps', '-r', constraints, '-d', home / 'wheelhouse'])
    if subprocess.run(['id', 'sage-research'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        run(['useradd', '--create-home', '--shell', '/bin/bash', 'sage-research'])
    config = {'coral_python': str(python), 'aris_root': str(home / 'ARIS'),
              'dsh': str(dsh_dir / 'node_modules' / '.bin' / 'dsh'),
              'path': [str(node_dir / 'bin'), str(venv / 'bin'), str(pnpm.parent)],
              'versions': {'node': NODE, 'dsh': DSH, 'ARIS': ARIS, 'CORAL': CORAL}}
    (home / 'runtime.json').write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    print('Native runtime installed. Set DEEPSEEK_API_KEY, then run python -m sage autonomous --allow-live --output projects/new-run')


if __name__ == '__main__':
    main()
