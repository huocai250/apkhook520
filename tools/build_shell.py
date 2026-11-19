#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
重新编译壳 dex（libs/ShellDexDir/src/com/sakuqi/steady/*.smali -> classes.dex）。

平时不需要跑这个脚本，仓库里已经放了编好的 classes.dex。只有在你改了壳的
smali 源码（比如适配新的 Android 反射字段）之后才需要：

    python tools/build_shell.py            # 编译 + 自检
    python tools/build_shell.py --check    # 只自检现有 classes.dex

编译产物会覆盖 libs/ShellDexDir/classes.dex，并用 baksmali 反编译回来做
往返校验（能编能反 = dex 结构自洽）。
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, 'libs', 'ShellDexDir', 'src')
OUT = os.path.join(ROOT, 'libs', 'ShellDexDir', 'classes.dex')
SMALI_JAR = os.path.join(ROOT, 'libs', 'jar', 'smali.jar')
BAKSMALI_JAR = os.path.join(ROOT, 'libs', 'jar', 'baksmali.jar')

# 壳必须保留的符号：JNI 按名绑定，改名即 UnsatisfiedLinkError
REQUIRED = [
    '.class public Lcom/sakuqi/steady/SteadyApplication;',
    '.super Landroid/app/Application;',
    '.method public native decrypt([B)[B',
]


def java():
    home = os.environ.get('JAVA_HOME')
    if home:
        exe = os.path.join(home, 'bin', 'java.exe' if os.name == 'nt' else 'java')
        if os.path.isfile(exe):
            return exe
    return 'java'


def run(cmd):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout.decode('utf-8', 'replace')
    if proc.returncode != 0:
        raise SystemExit('命令失败: %s\n%s' % (' '.join(cmd), out))
    return out


def check(dex_path):
    """检查 dex 头 + 必要符号（用 baksmali 反编译到临时目录）。"""
    ok = True
    with open(dex_path, 'rb') as fp:
        magic = fp.read(8)
    if not magic.startswith(b'dex\n') or magic[7:8] != b'\x00':
        print('[-] dex magic 非法: %r' % magic)
        return False
    print('[+] dex magic OK: %r  size=%d' % (magic, os.path.getsize(dex_path)))

    tmp = tempfile.mkdtemp(prefix='shell_check_')
    try:
        run([java(), '-jar', BAKSMALI_JAR, 'd', dex_path, '-o', tmp])
        text = ''
        for base, _dirs, files in os.walk(tmp):
            for name in files:
                if name.endswith('.smali'):
                    with open(os.path.join(base, name), encoding='utf-8',
                              errors='replace') as fp:
                        text += fp.read()
        for needle in REQUIRED:
            if needle in text:
                print('[+] 符号存在: %s' % needle)
            else:
                print('[-] 缺少符号: %s' % needle)
                ok = False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


def main():
    ap = argparse.ArgumentParser(description='编译 apkhook520 壳 dex')
    ap.add_argument('--check', action='store_true', help='只检查现有 classes.dex')
    ap.add_argument('-o', '--output', default=OUT, help='输出 dex 路径')
    args = ap.parse_args()

    if not args.check:
        if not os.path.isdir(SRC):
            raise SystemExit('壳源码目录不存在: %s' % SRC)
        target = os.path.abspath(args.output)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.exists(target):
            backup = target + '.bak'
            shutil.copyfile(target, backup)
            print('[*] 已备份原 dex -> %s' % backup)
            os.remove(target)
        out = run([java(), '-jar', SMALI_JAR, 'a', SRC, '-o', target])
        # smali 2.x 在部分错误下仍然 exit 0，只往 stderr 打字，必须自己看输出+产物。
        bad = [mark for mark in ('Invalid register', 'Invalid instruction',
                                 'Could not resolve', 'cannot be resolved',
                                 'Error:', 'Exception') if mark in out]
        if bad:
            raise SystemExit('壳 smali 汇编失败（%s）:\n%s' % (', '.join(bad), out))
        if not os.path.isfile(target) or os.path.getsize(target) == 0:
            raise SystemExit('壳 smali 汇编没有产出 dex:\n%s' % out)
        print('[+] 编译完成: %s (%d bytes)' % (target, os.path.getsize(target)))

    target = os.path.abspath(OUT) if args.check else os.path.abspath(args.output)
    if not os.path.isfile(target):
        raise SystemExit('找不到 dex: %s' % target)
    if not check(target):
        raise SystemExit(1)
    print('[+] 壳 dex 自检通过')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
