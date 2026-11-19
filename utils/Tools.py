#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Tools —— 统一的 java / jar 子进程调用层（2.0 新增）

为什么要单独一层：
  * 老 `JarCommand.py` 用 `Popen(..., shell=True)` 且只返回 (stdout, stderr)，
    拿不到 returncode，命令失败时上层根本不知道，只能靠"下一步崩了"反推；
  * shell=True 在路径含空格/中文时会被二次解析，Windows 上尤其危险；
  * apksigner 需要 --min-sdk-version/--v1/--v2/--v3 这些参数，老的写死调用满足不了。

本模块只做三件事：定位 java、拼参数、执行并返回 (returncode, output)。
"""
import os
import shutil
import subprocess
import sys

JAR_DIR = 'libs/jar'

BAKSMALI_JAR = 'baksmali.jar'
SMALI_JAR = 'smali.jar'
APKSIGNER_JAR = 'apksigner.jar'
MANIFEST_EDITOR_JAR = 'ManifestEditor.jar'
XML2AXML_JAR = 'xml2axml.jar'


class ToolError(RuntimeError):
    """外部工具执行失败。message 里带返回码与截断后的输出。"""


def which_java(explicit=None):
    """按 JAVA_HOME -> explicit -> PATH 找 java 可执行文件。"""
    candidates = []
    if explicit:
        candidates.append(explicit)
    home = os.environ.get('JAVA_HOME')
    if home:
        candidates.append(os.path.join(home, 'bin', 'java.exe'))
        candidates.append(os.path.join(home, 'bin', 'java'))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    found = shutil.which('java')
    if found:
        return found
    raise ToolError('找不到 java，请安装 JDK 8+ 并加入 PATH，或用 --java 指定路径')


def resolve(*parts):
    """把相对路径按"项目根目录"解析，绝对路径原样返回。

    项目根目录 = 本文件所在目录的上一级（utils/ 的父目录），
    这样无论从哪个 cwd 启动 main.py 都能找到 libs/jar。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for part in parts:
        if part and os.path.isabs(part):
            return part
    return os.path.abspath(os.path.join(root, *[p for p in parts if p]))


def jar(name):
    path = resolve(JAR_DIR, name)
    if not os.path.isfile(path):
        raise ToolError(f'缺少工具包: {path}')
    return path


def run(cmd, timeout=1800, cwd=None):
    """执行命令，返回 (returncode, 合并后的输出文本)。

    list/tuple 走 shell=False（路径带空格/中文最稳），str 走 shell=True。
    """
    shell = isinstance(cmd, str)
    try:
        proc = subprocess.run(
            cmd, shell=shell, cwd=cwd, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=dict(os.environ, PYTHONIOENCODING='utf-8'),
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f'命令超时({timeout}s): {cmd}')
    out = (proc.stdout or b'').decode('utf-8', 'replace')
    return proc.returncode, out


def run_checked(cmd, what='', timeout=1800, tail=1600):
    rc, out = run(cmd, timeout=timeout)
    if rc != 0:
        text = out.strip()
        if len(text) > tail:
            text = '...' + text[-tail:]
        raise ToolError(f'{what or "命令"} 失败 (rc={rc})\n{text}')
    return out


# ---------------------------------------------------------------- baksmali
def dex2smali(dexpath, outdir, java=None, api=0, timeout=1800):
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir, exist_ok=True)
    args = [which_java(java), '-jar', jar(BAKSMALI_JAR), 'd', resolve(dexpath),
            '-o', resolve(outdir)]
    if api:
        args += ['--api', str(api)]
    return run_checked(args, f'baksmali {os.path.basename(dexpath)}', timeout=timeout)


# ------------------------------------------------------------------ smali
def smali2dex(srcdir, outdex, java=None, api=0, timeout=1800):
    out = resolve(outdex)
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    if os.path.exists(out):
        os.remove(out)
    args = [which_java(java), '-jar', jar(SMALI_JAR), 'a', resolve(srcdir), '-o', out]
    if api:
        args += ['--api', str(api)]
    rc, text = run(args, timeout=timeout)
    # smali.jar 出错时**仍然返回 0**，只往 stderr 打字，所以必须自己判错，
    # 否则会拿上一次的旧 dex 当成功（历史上真的踩过这个坑）。
    bad = [m for m in ('Invalid register', 'Invalid instruction', 'Could not resolve',
                       'cannot be resolved', 'Unable to find', 'Error:', 'Exception')
           if m in text]
    if rc != 0 or bad or not os.path.isfile(out) or os.path.getsize(out) == 0:
        detail = text.strip()
        if len(detail) > 1600:
            detail = '...' + detail[-1600:]
        raise ToolError(f'smali 汇编失败 ({os.path.basename(srcdir)}): '
                        f'rc={rc}, 命中={bad}\n{detail}')
    return out


# ------------------------------------------------------------------ 签名
def apksigner_sign(apkpath, keystore, ks_pass, key_pass=None,
                   min_sdk=21, v1=True, v2=True, v3=True, java=None, timeout=1800):
    apk = resolve(apkpath)
    args = [which_java(java), '-jar', jar(APKSIGNER_JAR), 'sign',
            '--ks', resolve(keystore),
            '--ks-pass', f'pass:{ks_pass}']
    if key_pass and key_pass != ks_pass:
        args += ['--key-pass', f'pass:{key_pass}']
    args += [
        f'--v1-signing-enabled', 'true' if v1 else 'false',
        f'--v2-signing-enabled', 'true' if v2 else 'false',
        f'--v3-signing-enabled', 'true' if v3 else 'false',
        '--min-sdk-version', str(int(min_sdk)),
        apk,
    ]
    return run_checked(args, 'apksigner sign', timeout=timeout)


def apksigner_verify(apkpath, java=None, timeout=600):
    apk = resolve(apkpath)
    args = [which_java(java), '-jar', jar(APKSIGNER_JAR), 'verify',
            '--verbose', '--print-certs', apk]
    rc, out = run(args, timeout=timeout)
    return rc, out


# ------------------------------------------------------------------- 其他
def sha256_file(path, chunk=1 << 20):
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as fp:
        while True:
            block = fp.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def md5_file(path, chunk=1 << 20):
    import hashlib
    h = hashlib.md5()
    with open(path, 'rb') as fp:
        while True:
            block = fp.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def human_size(num):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if num < 1024 or unit == 'GB':
            return f'{num:.2f} {unit}' if unit != 'B' else f'{num} B'
        num /= 1024.0
    return f'{num:.2f} GB'


if __name__ == '__main__':
    try:
        print('java =', which_java())
    except ToolError as exc:
        print('ERROR:', exc)
        sys.exit(1)
