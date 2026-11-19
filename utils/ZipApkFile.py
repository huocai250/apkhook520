#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
ZipApkFile —— 兼容层（2.0）

v1.1 里的 ZipApkFile 用 `zipfile.write(..., ZIP_DEFLATED)` 无差别压缩，在
targetSdk>=30 的 APK 上会导致：

    Targeting R+ (version 30 and above) requires the resources.arsc of installed
    APKs to be stored uncompressed and aligned on a 4-byte boundary

并且 lib/**/*.so 不满足 Android 15+ 16KB 页对齐要求。

2.0 起真正的实现搬到 `utils/ApkZipper.py`（STORED + 对齐 + 剔除旧签名），
这里保留旧的 `ZipApkFile(filepath, mode, options).UnZipApk()/.ZipApk()` 调用
方式，避免外部脚本失效。
"""
import os

from utils.ApkZipper import (
    ApkZipper,
    DEFAULT_PAGE_ALIGN,
    alignment_extra,
    check_zip_integrity,
    is_signature_entry,
    verify_alignment,
)
from utils.ApkZipper import safe_extract


class ZipApkFile():
    """旧接口兼容包装；内部走 ApkZipper。"""

    def __init__(self, filepath, mode, options):
        self.FilePath = os.path.abspath(filepath)
        self.Mode = mode
        self.options = options or {}
        self.ZipExtractPath = self.options.get('ZipExtractPath')
        self.ZipCompressPath = self.options.get('ZipCompressPath')
        self.PageAlign = int(self.options.get('PageAlign', DEFAULT_PAGE_ALIGN))
        self.StoreLibs = bool(self.options.get('StoreLibs', True))

    def UnZipApk(self, **kwargs):
        """安全解包（拒绝 ../ 穿越、绝对路径、zip 加密条目）。"""
        dest = kwargs.get('zipextractpath') or self.ZipExtractPath
        if not dest:
            raise RuntimeError('未指定解包目录: ZipExtractPath')
        return safe_extract(self.FilePath, dest)

    def ZipApk(self, **kwargs):
        """zipalign 语义打包，返回 report dict。"""
        src = kwargs.get('zipcompresspath') or self.ZipCompressPath
        if not src:
            raise RuntimeError('未指定打包目录: ZipCompressPath')
        zipper = ApkZipper(src, self.FilePath,
                           page_align=self.PageAlign,
                           store_libs=self.StoreLibs)
        return zipper.Build()


__all__ = [
    'ZipApkFile',
    'ApkZipper',
    'verify_alignment',
    'check_zip_integrity',
    'is_signature_entry',
    'alignment_extra',
    'DEFAULT_PAGE_ALIGN',
]


if __name__ == '__main__':
    OPTIONS = {
        'ZipExtractPath': '../WorkDir/apkfile/app/',
        'ZipCompressPath': '../WorkDir/apkfile/app/',
    }
    # apk = ZipApkFile(r'../app.apk', 'r', OPTIONS)
    # apk.UnZipApk()

    apk = ZipApkFile(r'../WorkDir/AllFinish.apk', 'w', OPTIONS)
    print(apk.ZipApk())
