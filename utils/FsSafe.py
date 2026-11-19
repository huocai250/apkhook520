# -*- coding: utf-8 -*-
"""抗干扰的文件读写。

Windows 上杀毒软件（尤其是 Defender 的实时防护 + 云提交）在文件刚写完或刚解压时
会短暂拦截打开动作，`open()` 抛的是 `OSError: [Errno 22] Invalid argument` 这种
看着像「路径写错了」的错，实际重试几十毫秒就好。这个模块把所有碰 dex/二进制大文件的
读写都包一层退避重试，失败时给出可操作的提示（把项目目录加进杀软白名单）。

只用标准库。
"""

import errno
import os
import shutil
import time

# 值得重试的 errno：EINVAL(22) 是 Windows 杀软拦截的典型表现，
# EACCES(13)/EBUSY(16)/EPERM(1) 是文件仍被别处占用。
RETRY_ERRNOS = {
    errno.EINVAL: '文件被安全软件临时拦截',
    errno.EACCES: '文件正被其它进程占用',
    errno.EBUSY: '文件正被其它进程占用',
    errno.EPERM: '文件权限被临时拒绝',
}
RETRIES = 8
DELAY = 0.04          # 起始退避时间，逐次翻倍
HINT = ('若反复失败：把项目目录加入杀毒软件（Windows Defender → 病毒和威胁防护 → '
        '排除项）白名单后重试，Android payload 的 .dex 常被实时防护短暂锁定。')


class FileBusyError(OSError):
    """重试若干次后仍然读不到文件。"""

    def __init__(self, path, last):
        super().__init__(f'{path} 无法读取：{last}。{HINT}')
        self.path = path
        self.last = last


def _retry(func, path, retries=RETRIES):
    delay = DELAY
    last = None
    for attempt in range(retries):
        try:
            return func()
        except FileNotFoundError:
            raise
        except OSError as exc:
            last = exc
            if exc.errno not in RETRY_ERRNOS:
                raise
            if attempt == retries - 1:
                break
            time.sleep(delay)
            delay *= 1.7
    raise FileBusyError(path, last) from last


def read_bytes(path, retries=RETRIES):
    """读整个文件为 bytes（带重试）。"""
    def go():
        with open(path, 'rb') as fp:
            return fp.read()
    return _retry(go, path, retries)


def write_bytes(path, data, retries=RETRIES):
    """整文件写入（带重试）；先写临时文件再原子替换，避免半截文件。"""
    tmp = f'{path}.tmp{os.getpid()}'

    def go():
        with open(tmp, 'wb') as fp:
            fp.write(data)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, path)
    try:
        _retry(go, path, retries)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return path


def copyfile(src, dst, retries=RETRIES):
    """等价 shutil.copyfile，但源文件被临时锁住时会退避重试。"""
    def go():
        shutil.copyfile(src, dst)
    _retry(go, src, retries)
    return dst


def copy2(src, dst, retries=RETRIES):
    def go():
        shutil.copy2(src, dst)
    _retry(go, src, retries)
    return dst


def replace(src, dst, retries=RETRIES):
    def go():
        os.replace(src, dst)
    _retry(go, src, retries)
    return dst


def read_text(path, encoding='utf-8', retries=RETRIES):
    def go():
        with open(path, 'r', encoding=encoding) as fp:
            return fp.read()
    return _retry(go, path, retries)


def head(path, count, retries=RETRIES):
    """只读开头 count 字节（dex 头校验用）。"""
    def go():
        with open(path, 'rb') as fp:
            return fp.read(count)
    return _retry(go, path, retries)
