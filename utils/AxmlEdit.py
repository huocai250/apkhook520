# -*- coding: utf-8 -*-
"""AxmlEdit.py —— 纯 Python 3 (stdlib) 的 AndroidManifest.xml (AXML) 读写模块。

设计目标（替换 libs/jar/ManifestEditor.jar）：
  * 未修改的属性逐字节保留：Res_value 的 type/data 原样回写，
    resource 引用 (@drawable/xxx -> 0x7f... ) 不会被写成 0；
  * 字符串池只追加、不重排（仅在必须补 resource map 时按需重排，
    并重映射全部字符串索引）；
  * 无第三方依赖，py3.8+ 语法；不依赖 arsc。

对外 API：
    AxmlError
    AxmlAttr / AxmlElement / AxmlDocument
    parse(data) / load(path) / save(doc, path)
    get_package_name / get_application_name / set_application_name
    set_extract_native_libs / add_meta_data / add_uses_permission
    set_target_sdk / set_min_sdk / application_element
"""

import struct

__all__ = [
    "ANDROID_NS", "AxmlError", "AxmlAttr", "AxmlElement", "AxmlDocument",
    "parse", "load", "save",
    "get_package_name", "get_application_name", "set_application_name",
    "set_extract_native_libs", "add_meta_data", "add_uses_permission",
    "set_target_sdk", "set_min_sdk", "application_element",
]

ANDROID_NS = "http://schemas.android.com/apk/res/android"

# ---- chunk 类型 ----
RES_XML_TYPE = 0x0003
RES_STRING_POOL_TYPE = 0x0001
RES_XML_RESOURCE_MAP_TYPE = 0x0180
RES_XML_START_NAMESPACE_TYPE = 0x0100
RES_XML_END_NAMESPACE_TYPE = 0x0101
RES_XML_START_ELEMENT_TYPE = 0x0102
RES_XML_END_ELEMENT_TYPE = 0x0103
RES_XML_CDATA_TYPE = 0x0104

# ---- Res_value dataType ----
TYPE_NULL = 0x00
TYPE_REFERENCE = 0x01
TYPE_ATTRIBUTE = 0x02
TYPE_STRING = 0x03
TYPE_FLOAT = 0x04
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_INT_BOOLEAN = 0x12

NO_ENTRY = 0xFFFFFFFF

# 字符串池 flags
POOL_FLAG_STYLE = 0x0001
POOL_FLAG_UTF8 = 0x0100

# 属性名 -> 资源 id（resource map 缺失时的查询表）
ATTR_IDS = {
    "theme": 0x01010000,
    "label": 0x01010001,
    "icon": 0x01010002,
    "name": 0x01010003,
    "permission": 0x01010006,
    "process": 0x01010011,
    "enabled": 0x0101000E,
    "debuggable": 0x0101000F,
    "exported": 0x01010010,
    "authorities": 0x01010018,
    "screenOrientation": 0x0101001E,
    "configChanges": 0x0101001F,
    "value": 0x01010024,
    "resource": 0x01010025,
    "minSdkVersion": 0x0101020C,
    "versionCode": 0x0101021B,
    "versionName": 0x0101021C,
    "targetSdkVersion": 0x01010270,
    "extractNativeLibs": 0x010104EA,
    # API 29+ 前台服务类型；值直接取自 Settings.apk 的 resource map，
    # 少了这一条，平台会把该属性的 resId 当成 0 并忽略（2.0 踩过）。
    "foregroundServiceType": 0x01010599,
}


class AxmlError(Exception):
    """AXML 解析/写入错误（对异常输入统一抛这个，不裸奔 struct.error）。"""


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def _u32(b, off):
    return struct.unpack_from("<I", b, off)[0]


def _u16(b, off):
    return struct.unpack_from("<H", b, off)[0]


def _utf8_char_len(s):
    """UTF-8 池里记录的“字符数”是 UTF-16 code unit 数。"""
    return len(s.encode("utf-16-le")) // 2


def _enc_len8(n):
    """UTF-8 池长度前缀：>0x7F 用两字节（高字节带 0x80 标记）。"""
    if n > 0x7F:
        return bytes(((n >> 8) | 0x80, n & 0xFF))
    return bytes((n,))


def _enc_len16(n):
    """UTF-16 池长度前缀：>0x7FFF 用两个 u16（高位带 0x8000）。"""
    if n > 0x7FFF:
        return struct.pack("<HH", ((n >> 16) | 0x8000), n & 0xFFFF)
    return struct.pack("<H", n)


def _encode_string(s, utf8):
    if utf8:
        raw = s.encode("utf-8")
        return _enc_len8(_utf8_char_len(s)) + _enc_len8(len(raw)) + raw + b"\x00"
    raw = s.encode("utf-16-le")
    return _enc_len16(len(raw) // 2) + raw + b"\x00\x00"


def _decode_pool(data, off, csize):
    """解析 ResStringPool，返回 (strings, utf8, style_count, style_offsets, style_data)。"""
    hdr = off + 8
    if hdr + 20 > off + csize:
        raise AxmlError("string pool 头部被截断")
    count, style_count, flags, strings_start, styles_start = struct.unpack_from(
        "<IIIII", data, hdr)
    if count < 0 or count > 0x100000:
        raise AxmlError("string pool 字符串数量异常: %d" % count)
    utf8 = bool(flags & POOL_FLAG_UTF8)
    base = hdr + 20
    if base + count * 4 > off + csize:
        raise AxmlError("string pool 偏移表被截断")
    offsets = struct.unpack_from("<%dI" % count, data, base) if count else ()
    data_start = off + strings_start
    limit = off + csize
    strings = []
    for o in offsets:
        p = data_start + o
        try:
            if utf8:
                n1 = data[p]
                p += 1
                if n1 & 0x80:
                    n1 = ((n1 & 0x7F) << 8) | data[p]
                    p += 1
                n2 = data[p]
                p += 1
                if n2 & 0x80:
                    n2 = ((n2 & 0x7F) << 8) | data[p]
                    p += 1
                strings.append(data[p:p + n2].decode("utf-8", "replace"))
            else:
                n = _u16(data, p)
                p += 2
                if n & 0x8000:
                    n = ((n & 0x7FFF) << 16) | _u16(data, p)
                    p += 2
                strings.append(data[p:p + n * 2].decode("utf-16-le", "replace"))
        except (IndexError, struct.error):
            raise AxmlError("string pool 字符串数据越界 (offset=%d)" % o)
        if p > limit + 4:
            raise AxmlError("string pool 越界")
    style_offsets = ()
    style_data = b""
    if style_count:
        if base + (count + style_count) * 4 > off + csize:
            raise AxmlError("string pool style 偏移表被截断")
        style_offsets = struct.unpack_from("<%dI" % style_count, data,
                                           base + count * 4)
        style_data = data[off + styles_start:off + csize]
    return strings, utf8, style_count, style_offsets, style_data


def _build_pool(strings, utf8, style_count, style_offsets, style_data):
    body = bytearray()
    offsets = []
    for s in strings:
        offsets.append(len(body))
        body += _encode_string(s, utf8)
    # 4 字节对齐（aapt 也这么做）
    while len(body) % 4:
        body += b"\x00"
    hdr_size = 8 + 20
    strings_start = hdr_size + 4 * len(strings) + 4 * len(style_offsets)
    styles_start = strings_start + len(body) if style_count else 0
    out = bytearray()
    out += struct.pack("<HHI", RES_STRING_POOL_TYPE, hdr_size, 0)  # size 稍后回填
    out += struct.pack("<IIIII", len(strings), len(style_offsets),
                       (POOL_FLAG_UTF8 if utf8 else 0) | (POOL_FLAG_STYLE if style_count else 0),
                       strings_start, styles_start)
    out += struct.pack("<%dI" % len(strings), *offsets) if strings else b""
    if style_offsets:
        out += struct.pack("<%dI" % len(style_offsets), *style_offsets)
    out += body
    if style_count and style_data:
        out += style_data
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out)


# --------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------
class AxmlAttr(object):
    """单个属性。raw 为 rawValue 指向的字符串（可能为 None）。"""

    __slots__ = ("ns", "name", "raw", "type", "data", "pool", "_size", "_res0",
                 "name_idx", "ns_idx", "raw_idx")

    def __init__(self, name, ns=None, raw=None, type=TYPE_STRING, data=0, pool=None):
        self.ns = ns
        self.name = name
        self.raw = raw
        self.type = type
        self.data = data
        self.pool = pool
        self._size = 8
        self._res0 = 0
        # 原始字符串池索引：池里有重复字符串时必须原样保留，否则语义等价但字节不同
        self.name_idx = None
        self.ns_idx = None
        self.raw_idx = None

    # 便捷取值
    @property
    def value(self):
        if self.raw is not None:
            return self.raw
        if self.type == TYPE_STRING and self.pool is not None:
            if 0 <= self.data < len(self.pool):
                return self.pool[self.data]
        return None

    def __repr__(self):
        return "AxmlAttr(%r, ns=%r, type=0x%02x, data=0x%08x, raw=%r)" % (
            self.name, self.ns, self.type, self.data & 0xFFFFFFFF, self.raw)


class AxmlElement(object):
    """元素树节点。"""

    __slots__ = ("tag", "attrs", "children", "ns", "line", "comment", "pool",
                 "end_line", "end_comment", "name_idx", "ns_idx")

    def __init__(self, tag, ns=None, pool=None):
        self.tag = tag
        self.attrs = []
        self.children = []
        self.ns = ns
        self.line = 0
        self.comment = NO_ENTRY   # 原文件里 comment 字段原样保留
        self.pool = pool
        self.end_line = NO_ENTRY      # END_ELEMENT 的 line/comment 单独保存，
        self.end_comment = NO_ENTRY   # aapt 常写 0xFFFFFFFF，必须原样回写
        self.name_idx = None          # 原始字符串索引（池内可能有重复串）
        self.ns_idx = None

    # ---- 属性查找/修改 ----
    def get(self, name, ns=ANDROID_NS):
        for a in self.attrs:
            if a.name == name and a.ns == ns:
                return a
        return None

    def get_str(self, name, ns=ANDROID_NS):
        a = self.get(name, ns)
        if a is None:
            return None
        return a.value

    def set_str(self, name, value, ns=ANDROID_NS):
        a = self.get(name, ns)
        if a is None:
            a = AxmlAttr(name, ns=ns, raw=value, type=TYPE_STRING, data=0,
                         pool=self.pool)
            self.attrs.append(a)
        a.raw = value
        a.type = TYPE_STRING
        a.data = 0  # 写回时按 raw 重新 intern
        return a

    def set_int(self, name, value, ns=ANDROID_NS, hexa=False):
        a = self.get(name, ns)
        if a is None:
            a = AxmlAttr(name, ns=ns, raw=None, type=TYPE_INT_HEX if hexa else TYPE_INT_DEC,
                         data=int(value) & 0xFFFFFFFF, pool=self.pool)
            self.attrs.append(a)
        a.raw = None
        a.type = TYPE_INT_HEX if hexa else TYPE_INT_DEC
        a.data = int(value) & 0xFFFFFFFF
        return a

    def set_bool(self, name, value, ns=ANDROID_NS):
        a = self.get(name, ns)
        if a is None:
            a = AxmlAttr(name, ns=ns, pool=self.pool)
            self.attrs.append(a)
        a.raw = "true" if value else "false"
        a.type = TYPE_INT_BOOLEAN
        a.data = 0xFFFFFFFF if value else 0
        return a

    def remove(self, name, ns=ANDROID_NS):
        n = len(self.attrs)
        self.attrs[:] = [a for a in self.attrs if not (a.name == name and a.ns == ns)]
        return n != len(self.attrs)

    # ---- 子节点 ----
    def find_children(self, tag):
        return [c for c in self.children if getattr(c, "tag", None) == tag]

    def first_child(self, tag):
        for c in self.children:
            if getattr(c, "tag", None) == tag:
                return c
        return None

    def append_child(self, el):
        el.pool = self.pool
        self.children.append(el)
        return el

    def __repr__(self):
        return "<%s attrs=%d children=%d>" % (self.tag, len(self.attrs), len(self.children))


class _CData(object):
    """CDATA 节点（manifest 里基本不存在，但保留以免丢数据）。"""

    __slots__ = ("text", "line", "type", "data")

    tag = "#cdata"

    def __init__(self, text, line=0):
        self.text = text
        self.line = line
        self.type = TYPE_STRING
        self.data = 0

    def __repr__(self):
        return "CData(%r)" % (self.text,)


class AxmlDocument(object):
    def __init__(self):
        self.root = None
        self.strings = []
        self.resmap = []
        self.utf8 = False
        self.namespaces = []      # [{'kind':'start'|'end','line':..,'comment':..,'prefix':..,'uri':..}]
        self.style_count = 0
        self.style_offsets = ()
        self.style_data = b""
        self.unknown = []         # [(chunk_type, raw_bytes)] 未知 chunk，原样保留
        self._pool_raw = None     # 原始 string pool chunk 字节（未改动时原样回写，保证逐字节一致）
        self._pool_sig = None     # 该原始 chunk 对应的 (strings, utf8, style...) 快照

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------
    @classmethod
    def from_bytes(cls, data):
        if isinstance(data, memoryview):
            data = data.tobytes()
        if not isinstance(data, (bytes, bytearray)):
            raise AxmlError("from_bytes 需要 bytes，收到 %r" % type(data))
        data = bytes(data)
        if len(data) < 8:
            raise AxmlError("数据太短，不是 AXML")
        typ, hdr_size, total = struct.unpack_from("<HHI", data, 0)
        if typ != RES_XML_TYPE:
            raise AxmlError("不是 AXML：magic type=0x%04x (期望 0x0003)" % typ)
        if hdr_size < 8 or hdr_size > len(data):
            raise AxmlError("AXML 头部异常: headerSize=%d" % hdr_size)
        doc = cls()
        if total > len(data):
            total = len(data)
        off = hdr_size
        stack = []
        seen_pool = False
        while off + 8 <= total:
            ctype, chs, csize = struct.unpack_from("<HHI", data, off)
            if csize < 8 or off + csize > total:
                raise AxmlError("chunk 长度异常 @%d type=0x%04x size=%d" % (off, ctype, csize))
            if ctype == RES_STRING_POOL_TYPE:
                if seen_pool:
                    doc.unknown.append((ctype, data[off:off + csize]))
                else:
                    (doc.strings, doc.utf8, doc.style_count,
                     doc.style_offsets, doc.style_data) = _decode_pool(data, off, csize)
                    doc._pool_raw = bytes(data[off:off + csize])
                    doc._pool_sig = (tuple(doc.strings), doc.utf8, doc.style_count,
                                     tuple(doc.style_offsets), doc.style_data)
                    seen_pool = True
            elif ctype == RES_XML_RESOURCE_MAP_TYPE:
                n = (csize - 8) // 4
                doc.resmap = list(struct.unpack_from("<%dI" % n, data, off + 8)) if n else []
            elif ctype in (RES_XML_START_NAMESPACE_TYPE, RES_XML_END_NAMESPACE_TYPE):
                if off + 24 > total:
                    raise AxmlError("namespace chunk 被截断")
                line, comment, prefix, uri = struct.unpack_from("<IIII", data, off + 8)
                doc.namespaces.append({
                    "kind": "start" if ctype == RES_XML_START_NAMESPACE_TYPE else "end",
                    "line": line, "comment": comment,
                    "prefix": doc._s(prefix), "uri": doc._s(uri),
                    "prefix_idx": prefix, "uri_idx": uri,
                })
            elif ctype == RES_XML_START_ELEMENT_TYPE:
                el = doc._parse_start_element(data, off, csize)
                if stack:
                    stack[-1].append_child(el)
                else:
                    if doc.root is not None:
                        raise AxmlError("出现多个根元素")
                    doc.root = el
                    el.pool = doc.strings
                stack.append(el)
            elif ctype == RES_XML_END_ELEMENT_TYPE:
                if not stack:
                    raise AxmlError("END_ELEMENT 没有匹配的 START_ELEMENT")
                if off + 24 > total:
                    raise AxmlError("END_ELEMENT chunk 被截断")
                eline, ecomment = struct.unpack_from("<II", data, off + 8)
                el = stack.pop()
                el.end_line = eline
                el.end_comment = ecomment
            elif ctype == RES_XML_CDATA_TYPE:
                if off + 24 > total:
                    raise AxmlError("CDATA chunk 被截断")
                line, comment = struct.unpack_from("<II", data, off + 8)
                size_, res0, dtype, val = struct.unpack_from("<HBBI", data, off + 16)
                text = doc._s(val) if dtype == TYPE_STRING else None
                node = _CData(text if text is not None else "", line)
                node.type, node.data = dtype, val
                if stack:
                    stack[-1].children.append(node)
                else:
                    doc.unknown.append((ctype, data[off:off + csize]))
            else:
                doc.unknown.append((ctype, data[off:off + csize]))
            off += csize
        if doc.root is None:
            raise AxmlError("AXML 中没有根元素")
        if stack:
            raise AxmlError("元素未闭合（缺少 %d 个 END_ELEMENT）" % len(stack))
        return doc

    def _s(self, idx):
        if idx == NO_ENTRY:
            return None
        if idx >= len(self.strings):
            raise AxmlError("字符串索引越界: %d (池大小 %d)" % (idx, len(self.strings)))
        return self.strings[idx]

    def _parse_start_element(self, data, off, csize):
        if csize < 36 or off + 36 > len(data):
            raise AxmlError("START_ELEMENT 被截断 @%d" % off)
        line, comment, ns_idx, name_idx = struct.unpack_from("<IIII", data, off + 8)
        a_start, a_size, a_count, id_idx, cls_idx, sty_idx = struct.unpack_from(
            "<HHHHHH", data, off + 24)
        el = AxmlElement(self._s(name_idx), ns=self._s(ns_idx), pool=self.strings)
        el.line = line
        el.comment = comment
        el.name_idx = name_idx
        el.ns_idx = ns_idx
        if a_size < 8:
            raise AxmlError("attributeSize 异常: %d" % a_size)
        base = off + 16 + (a_start if a_start else 20)
        if base + a_count * a_size > off + csize:
            raise AxmlError("属性区越界 @%d" % off)
        for i in range(a_count):
            p = base + i * a_size
            ans, anam, araw, vsize, res0, dtype, adata = struct.unpack_from(
                "<IIIHBBI", data, p)
            at = AxmlAttr(self._s(anam), ns=self._s(ans),
                          raw=self._s(araw) if araw != NO_ENTRY else None,
                          type=dtype, data=adata, pool=self.strings)
            at._size = vsize
            at._res0 = res0
            at.name_idx = anam
            at.ns_idx = ans
            at.raw_idx = araw
            if dtype == TYPE_STRING and adata != NO_ENTRY and adata >= len(self.strings):
                raise AxmlError("属性字符串值越界: %d" % adata)
            el.attrs.append(at)
        return el

    @classmethod
    def from_file(cls, path):
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def _iter_elements(self, el=None):
        if el is None:
            el = self.root
        if el is None:
            return
        stack = [el]
        while stack:
            cur = stack.pop()
            yield cur
            kids = [c for c in cur.children if isinstance(c, AxmlElement)]
            stack.extend(reversed(kids))

    def _referenced_strings(self):
        out = []
        seen = set()

        def add(s):
            if s is not None and s not in seen:
                seen.add(s)
                out.append(s)

        for ev in self.namespaces:
            add(ev.get("prefix"))
            add(ev.get("uri"))
        for el in self._iter_elements():
            add(el.tag)
            add(el.ns)
            for a in el.attrs:
                add(a.ns)
                add(a.name)
                add(a.raw)
                if a.raw is None and a.type == TYPE_STRING:
                    add(a.value)
            for c in el.children:
                if isinstance(c, _CData):
                    add(c.text)
        return out

    def _plan_pool(self):
        """计算最终字符串池与 resource map；必要时重排以补 attr id。"""
        pool = list(self.strings)
        for s in self._referenced_strings():
            if s not in pool:
                pool.append(s)
        resmap = list(self.resmap)
        if not self.style_count:
            need = []
            for el in self._iter_elements():
                for a in el.attrs:
                    if a.ns != ANDROID_NS:
                        continue
                    rid = ATTR_IDS.get(a.name)
                    if not rid:
                        continue
                    if a.name not in pool:
                        pool.append(a.name)
                    i = pool.index(a.name)
                    if i < len(resmap):
                        if resmap[i] == rid:
                            continue
                        # 池里同名串已映射到别的 id：不动（保持原状）
                        continue
                    if a.name not in need:
                        need.append(a.name)
            if need:
                n = len(resmap)
                prefix = pool[:n]
                need_set = set(need)
                rest = [s for s in pool[n:] if s not in need_set]
                pool = prefix + need + rest
                resmap = resmap + [ATTR_IDS[s] for s in need]
        self.strings[:] = pool          # 就地更新，保持 attr.pool 引用有效
        self.resmap = resmap
        idx = {}
        for i, s in enumerate(pool):
            idx.setdefault(s, i)
        return pool, resmap, idx

    def to_bytes(self):
        if self.root is None:
            raise AxmlError("文档没有根元素")
        pool, resmap, idx = self._plan_pool()
        body = bytearray()
        sig = self._pool_sig
        if (self._pool_raw is not None and sig is not None and tuple(pool) == sig[0]
                and self.utf8 == sig[1] and self.style_count == sig[2]
                and tuple(self.style_offsets) == sig[3] and self.style_data == sig[4]):
            body += self._pool_raw      # 池未被改动：原样回写
        else:
            body += _build_pool(pool, self.utf8, self.style_count,
                                self.style_offsets, self.style_data)
        if resmap:
            body += struct.pack("<HHI", RES_XML_RESOURCE_MAP_TYPE, 8,
                                8 + 4 * len(resmap))
            body += struct.pack("<%dI" % len(resmap), *[r & 0xFFFFFFFF for r in resmap])
        for ev in self.namespaces:
            if ev.get("kind") == "start":
                body += self._ns_chunk(RES_XML_START_NAMESPACE_TYPE, ev, idx)
        body += self._write_element(self.root, idx)
        for ev in self.namespaces:
            if ev.get("kind") != "start":
                body += self._ns_chunk(RES_XML_END_NAMESPACE_TYPE, ev, idx)
        for ctype, raw in self.unknown:
            body += raw
        return struct.pack("<HHI", RES_XML_TYPE, 8, 8 + len(body)) + bytes(body)

    def _ns_chunk(self, ctype, ev, idx):
        prefix = self._pick(ev.get("prefix_idx"), ev.get("prefix"), idx)
        uri = self._pick(ev.get("uri_idx"), ev.get("uri"), idx)
        return struct.pack("<HHIIIII", ctype, 16, 24, int(ev.get("line") or 0),
                           int(ev.get("comment") or 0), prefix, uri)

    def _pick(self, orig, val, idx):
        """优先复用原始池索引（池内可能有重复字符串），否则按值查表。"""
        if val is None:
            return NO_ENTRY
        if orig is not None and orig != NO_ENTRY and 0 <= orig < len(self.strings) \
                and self.strings[orig] == val:
            return orig
        return idx.get(val, NO_ENTRY)

    def _write_element(self, el, idx):
        ns = self._pick(el.ns_idx, el.ns, idx)
        name = self._pick(el.name_idx, el.tag, idx)
        if name == NO_ENTRY:
            raise AxmlError("元素名未进入字符串池: %r" % (el.tag,))
        attrs = [a for a in el.attrs]
        chunk_size = 16 + 20 + 20 * len(attrs)
        out = bytearray()
        out += struct.pack("<HHIIIIIHHHHHH", RES_XML_START_ELEMENT_TYPE, 16,
                           chunk_size, int(el.line or 0),
                           int(el.comment if el.comment is not None else NO_ENTRY) & 0xFFFFFFFF,
                           ns, name,
                           20, 20, len(attrs), 0, 0, 0)
        for a in attrs:
            out += self._write_attr(a, idx)
        for c in el.children:
            if isinstance(c, AxmlElement):
                out += self._write_element(c, idx)
            elif isinstance(c, _CData):
                out += self._write_cdata(c, idx)
        out += struct.pack("<HHIIIII", RES_XML_END_ELEMENT_TYPE, 16, 24,
                           int(el.end_line if el.end_line is not None else NO_ENTRY) & 0xFFFFFFFF,
                           int(el.end_comment if el.end_comment is not None else NO_ENTRY) & 0xFFFFFFFF,
                           ns, name)
        return bytes(out)

    def _write_attr(self, a, idx):
        ans = self._pick(a.ns_idx, a.ns, idx)
        if a.name is None:
            raise AxmlError("属性缺少 name")
        anam = self._pick(a.name_idx, a.name, idx)
        if anam == NO_ENTRY:
            raise AxmlError("属性名未进入字符串池: %r" % (a.name,))
        raw_s = a.raw
        data = a.data & 0xFFFFFFFF
        if a.type == TYPE_STRING:
            if raw_s is None:
                # 用 data 反查池内字符串
                if 0 <= data < len(self.strings):
                    raw_s = self.strings[data]
            if raw_s is not None:
                data = idx.get(raw_s, data)
        araw = self._pick(a.raw_idx, raw_s, idx)
        return struct.pack("<IIIHBBI", ans, anam, araw,
                           a._size if a._size else 8, a._res0 or 0, a.type, data)

    def _write_cdata(self, c, idx):
        text = c.text or ""
        if text not in idx:
            raise AxmlError("CDATA 文本未进入字符串池")
        return struct.pack("<HHIIIHBBI", RES_XML_CDATA_TYPE, 16, 24,
                           int(c.line or 0), 0, 8, 0, TYPE_STRING, idx[text])

    def to_file(self, path):
        with open(path, "wb") as f:
            f.write(self.to_bytes())


# --------------------------------------------------------------------------
# 便捷函数
# --------------------------------------------------------------------------
def parse(data):
    return AxmlDocument.from_bytes(data)


def load(path):
    return AxmlDocument.from_file(path)


def save(doc, path):
    doc.to_file(path)


# --------------------------------------------------------------------------
# 高层 helper（apkhook520 主程序用）
# --------------------------------------------------------------------------
def application_element(doc):
    if doc is None or doc.root is None:
        return None
    return doc.root.first_child("application")


def get_package_name(doc):
    if doc is None or doc.root is None:
        return None
    a = doc.root.get("package", None)
    if a is None:
        return None
    return a.value


def get_application_name(doc):
    app = application_element(doc)
    if app is None:
        return None
    return app.get_str("name", ANDROID_NS)


def set_package_name(doc, package):
    """改 <manifest package="...">（无命名空间属性）。"""
    if doc is None or doc.root is None:
        raise AxmlError("文档没有根元素")
    return doc.root.set_str("package", package, None)


def set_application_label(doc, label):
    """把 <application android:label> 直接写成字符串值。

    原来的 label 通常是指向 @string/app_name 的资源引用；这里改成字面量，
    因此不再依赖 resources.arsc 里的条目，改名后无需重编资源。
    """
    app = _ensure_application(doc)
    return app.set_str("label", label, ANDROID_NS)


def _new_element(tag, pool, line=0):
    """新建元素：start/end chunk 的 line 保持一致，end comment 跟随 comment。"""
    el = AxmlElement(tag, pool=pool)
    el.line = line
    el.end_line = line
    el.end_comment = el.comment
    return el


def _ensure_application(doc):
    app = application_element(doc)
    if app is not None:
        return app
    app = _new_element("application", doc.strings,
                       doc.root.line if doc.root is not None else 0)
    doc.root.append_child(app)
    return app


def set_application_name(doc, class_name):
    app = _ensure_application(doc)
    app.set_str("name", class_name, ANDROID_NS)
    return app


def set_extract_native_libs(doc, value):
    app = _ensure_application(doc)
    return app.set_bool("extractNativeLibs", bool(value), ANDROID_NS)


def add_meta_data(doc, name, value):
    app = _ensure_application(doc)
    target = None
    for ch in app.children:
        if getattr(ch, "tag", None) == "meta-data" and \
                ch.get_str("name", ANDROID_NS) == name:
            target = ch
            break
    if target is None:
        target = _new_element("meta-data", doc.strings, app.line)
        target.attrs.append(AxmlAttr("name", ns=ANDROID_NS, raw=name,
                                     type=TYPE_STRING, data=0, pool=doc.strings))
        app.append_child(target)
    target.set_str("value", value, ANDROID_NS)
    return target


def _root_children(doc):
    return [c for c in doc.root.children if isinstance(c, AxmlElement)]


def _insert_before_application(doc, el):
    kids = doc.root.children
    for i, c in enumerate(kids):
        if getattr(c, "tag", None) == "application":
            kids.insert(i, el)
            return
    kids.append(el)


def add_uses_permission(doc, permission):
    for ch in _root_children(doc):
        if ch.tag == "uses-permission" and ch.get_str("name", ANDROID_NS) == permission:
            return ch
    el = _new_element("uses-permission", doc.strings, doc.root.line)
    el.attrs.append(AxmlAttr("name", ns=ANDROID_NS, raw=permission,
                             type=TYPE_STRING, data=0, pool=doc.strings))
    kids = doc.root.children
    last = -1
    for i, c in enumerate(kids):
        if getattr(c, "tag", None) == "uses-permission":
            last = i
    if last >= 0:
        kids.insert(last + 1, el)
    else:
        _insert_before_application(doc, el)
    return el


def _ensure_uses_sdk(doc):
    for ch in _root_children(doc):
        if ch.tag == "uses-sdk":
            return ch
    el = _new_element("uses-sdk", doc.strings, doc.root.line)
    _insert_before_application(doc, el)
    return el


def set_target_sdk(doc, api):
    return _ensure_uses_sdk(doc).set_int("targetSdkVersion", int(api), ANDROID_NS)


def set_min_sdk(doc, api):
    return _ensure_uses_sdk(doc).set_int("minSdkVersion", int(api), ANDROID_NS)


def add_service(doc, class_name, exported=False, foreground_service_type=None,
                process=None):
    """在 <application> 下加一个 <service>（保活用）。

    :param foreground_service_type: None 表示不写该属性；1=dataSync。
    """
    app = _ensure_application(doc)
    target = None
    for ch in app.children:
        if getattr(ch, "tag", None) == "service" and \
                ch.get_str("name", ANDROID_NS) == class_name:
            target = ch
            break
    if target is None:
        target = _new_element("service", doc.strings, app.line)
        target.attrs.append(AxmlAttr("name", ns=ANDROID_NS, raw=class_name,
                                     type=TYPE_STRING, data=0, pool=doc.strings))
        app.append_child(target)
    target.set_bool("exported", bool(exported), ANDROID_NS)
    if foreground_service_type is not None:
        target.set_int("foregroundServiceType", int(foreground_service_type),
                       ANDROID_NS)
    if process:
        target.set_str("process", process, None)
    else:
        target.remove("process", None)
    return target


def add_provider(doc, class_name, authorities, exported=False, process=None,
                 read_permission=None):
    """在 <application> 下加一个 <provider>。

    用于"零改 dex"注入：provider 的 onCreate 由系统在 Application.onCreate 之后
    自动调用，不需要替换 android:name，也不需要动宿主任何 dex。
    """
    app = _ensure_application(doc)
    target = None
    for ch in app.children:
        if getattr(ch, "tag", None) == "provider" and \
                ch.get_str("name", ANDROID_NS) == class_name:
            target = ch
            break
    if target is None:
        target = _new_element("provider", doc.strings, app.line)
        target.attrs.append(AxmlAttr("name", ns=ANDROID_NS, raw=class_name,
                                     type=TYPE_STRING, data=0, pool=doc.strings))
        app.append_child(target)
    target.set_str("authorities", authorities, ANDROID_NS)
    target.set_bool("exported", bool(exported), ANDROID_NS)
    if process:
        target.set_str("process", process, None)
    else:
        target.remove("process", None)
    if read_permission:
        target.set_str("readPermission", read_permission, ANDROID_NS)
    return target
