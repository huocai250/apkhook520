#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
ManifestTools —— AndroidManifest.xml 的高层编排（2.0 新增）

为什么不再用 `libs/jar/ManifestEditor.jar` + `xml2axml.jar`：
  两者都是"整份 XML 反序列化 -> 重新编码"的实现，重编码时属性值里的
  资源引用（@drawable/xxx、@style/xxx、android:theme…）因为没有
  resources.arsc 上下文，会被写成 0x00000000，装上去就是启动崩溃。
  实测：`xml2axml e` 往返一次 `@drawable/ic_launcher` 变成 `@00000000`。

本模块直接用纯 Python 的 `utils/AxmlEdit.py` 做二进制级编辑：
只改需要改的属性，其余字节原样保留。

对外：
    ReadInfo(path)            -> dict  读取清单摘要
    Patch(src, dst, **kw)     -> dict  改写清单（就地或另存）
    Describe(info)            -> str   人类可读摘要
"""
import os
import shutil

try:
    from utils import AxmlEdit
except Exception:  # noqa: BLE001  # 允许直接 python utils/ManifestTools.py
    import AxmlEdit  # type: ignore

ANDROID_NS = AxmlEdit.ANDROID_NS

COMPONENT_TAGS = ('activity', 'activity-alias', 'service', 'receiver', 'provider')

# 需要"有 intent-filter 就必须显式 exported"的组件（targetSdk>=31 强制）
EXPORTED_TAGS = ('activity', 'activity-alias', 'service', 'receiver')


class ManifestError(RuntimeError):
    pass


def _children(el):
    return [c for c in getattr(el, 'children', []) if hasattr(c, 'tag')]


def _bool_attr(el, name):
    """布尔属性：AXML 里 true=0xFFFFFFFF、false=0，缺省返回 None。"""
    value = _int_attr(el, name)
    if value is None:
        return None
    return bool(value)


def _components(app, tag):
    return [c for c in _children(app) if c.tag == tag]


def _int_attr(el, name):
    attr = el.get(name, ANDROID_NS)
    if attr is None:
        return None
    try:
        return int(getattr(attr, 'data', 0))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# 读取
# --------------------------------------------------------------------------
def ReadInfo(path):
    """解析二进制 AndroidManifest，返回结构化摘要。

    :raises ManifestError: 文件不存在 / 不是合法 AXML
    """
    if not os.path.isfile(path):
        raise ManifestError(f'AndroidManifest.xml 不存在: {path}')
    try:
        doc = AxmlEdit.load(path)
    except Exception as exc:  # noqa: BLE001
        raise ManifestError(f'解析 AndroidManifest.xml 失败: {exc}') from exc

    root = doc.root
    if root is None or root.tag != 'manifest':
        raise ManifestError('AndroidManifest.xml 根节点不是 <manifest>')

    app = AxmlEdit.application_element(doc)
    info = {
        'package': AxmlEdit.get_package_name(doc) or '',
        'application': AxmlEdit.get_application_name(doc),
        'has_application_element': app is not None,
        'launcher_activity': None,
        'activities': [],
        'services': [],
        'receivers': [],
        'providers': [],
        'permissions': [],
        'target_sdk': None,
        'min_sdk': None,
        'version_name': None,
        'version_code': None,
        'extract_native_libs': None,
        'debuggable': None,
        'uses_sdk_element': False,
        'components': [],
        'label': None,
    }

    for ch in _children(root):
        if ch.tag == 'uses-permission':
            name = ch.get_str('name', ANDROID_NS)
            if name:
                info['permissions'].append(name)
        elif ch.tag == 'uses-sdk':
            info['uses_sdk_element'] = True
            info['target_sdk'] = _int_attr(ch, 'targetSdkVersion')
            info['min_sdk'] = _int_attr(ch, 'minSdkVersion')

    attr = root.get('versionName', ANDROID_NS)
    if attr is not None:
        info['version_name'] = attr.value
    info['version_code'] = _int_attr(root, 'versionCode')

    if app is not None:
        info['extract_native_libs'] = _bool_attr(app, 'extractNativeLibs')
        info['debuggable'] = _bool_attr(app, 'debuggable')
        info['label'] = app.get_str('label', ANDROID_NS)
        for tag in ('activity', 'service', 'receiver', 'provider'):
            names = []
            for comp in _components(app, tag):
                name = comp.get_str('name', ANDROID_NS)
                if name:
                    names.append(name)
            info[f'{tag}s' if tag != 'activity' else 'activities'] = names

        # 组件明细：targetSdk>=31 后 exported 必须是显式值，自检要用
        for tag in ('activity', 'activity-alias', 'service', 'receiver', 'provider'):
            for comp in _components(app, tag):
                name = comp.get_str('name', ANDROID_NS) or ''
                exported = comp.get('exported', ANDROID_NS)
                has_filter = any(sub.tag == 'intent-filter' for sub in _children(comp))
                info['components'].append({
                    'tag': tag,
                    'name': NormalizeClassName(info['package'], name),
                    'exported': None if exported is None else bool(exported.value),
                    'has_intent_filter': has_filter,
                })

        for comp in _components(app, 'activity') + _components(app, 'activity-alias'):
            name = comp.get_str('name', ANDROID_NS) or ''
            for sub in _children(comp):
                if sub.tag != 'intent-filter':
                    continue
                actions = [a.get_str('name', ANDROID_NS) for a in _children(sub)
                           if a.tag == 'action']
                cats = [c.get_str('name', ANDROID_NS) for c in _children(sub)
                        if c.tag == 'category']
                if ('android.intent.action.MAIN' in actions
                        and 'android.intent.category.LAUNCHER' in cats):
                    info['launcher_activity'] = name
                    break
            if info['launcher_activity']:
                break

    if not info['launcher_activity'] and info['activities']:
        # 有些加固/马甲包把 MAIN 写在 activity-alias 上，退一步用第一个 activity
        info['launcher_activity'] = info['activities'][0]

    return info


def NormalizeClassName(package, name):
    if not name:
        return None
    name = name.strip()
    if name.startswith('.'):
        return f'{package}{name}'
    if '.' not in name:
        return f'{package}.{name}'
    return name


# --------------------------------------------------------------------------
# 改写
# --------------------------------------------------------------------------
def _ensure_exported(doc, app):
    """targetSdk>=31 时，带 intent-filter 的组件必须显式写 android:exported。

    老 App 没有这个属性：带 intent-filter 的组件历史上默认 exported=true，
    所以这里补 true 才不改变原有行为。
    """
    changed = []
    for tag in EXPORTED_TAGS:
        for comp in _components(app, tag):
            if comp.get('exported', ANDROID_NS) is not None:
                continue
            has_filter = any(c.tag == 'intent-filter' for c in _children(comp))
            if not has_filter:
                # 没有 intent-filter 的组件默认就是 false，显式写出来更保险
                comp.set_bool('exported', False, ANDROID_NS)
                changed.append((comp.get_str('name', ANDROID_NS), False))
            else:
                comp.set_bool('exported', True, ANDROID_NS)
                changed.append((comp.get_str('name', ANDROID_NS), True))
    return changed


def Patch(src, dst=None, application_name=None, meta_data=None,
          permissions=(), target_sdk=None, min_sdk=None,
          extract_native_libs=None, ensure_exported=False, debuggable=None,
          package_name=None, label=None, provider=None, service=None):
    """改写 AndroidManifest.xml。

    :param src: 输入（二进制 AXML）
    :param dst: 输出；None 表示就地覆盖
    :param application_name: 设置 <application android:name>，None 表示不动
    :param meta_data: dict，写 <meta-data android:name=... android:value=...>
    :param permissions: 需要补齐的 uses-permission 列表
    :param target_sdk/min_sdk: 整数，None 表示不动
    :param extract_native_libs: True/False/None
    :param ensure_exported: 给缺失 exported 的组件补显式值
    :param debuggable: True/False/None
    :param package_name: 把包名改成新值（同时重写 authorities / 组件全名等）
    :param label: 把 <application android:label> 写成字面量字符串
    :param provider: dict(name=类全名, authorities=字符串, exported=bool)，
                     用于"零改 dex"注入（provider.onCreate 里起 payload）
    :return: 变更摘要 dict
    """
    dst = dst or src
    if not os.path.isfile(src):
        raise ManifestError(f'AndroidManifest.xml 不存在: {src}')

    try:
        doc = AxmlEdit.load(src)
    except Exception as exc:  # noqa: BLE001
        raise ManifestError(f'解析 AndroidManifest.xml 失败: {exc}') from exc

    if doc.root is None or doc.root.tag != 'manifest':
        raise ManifestError('AndroidManifest.xml 根节点不是 <manifest>')

    changes = {
        'src': os.path.abspath(src),
        'dst': os.path.abspath(dst),
        'application_name': None,
        'meta_data': [],
        'permissions_added': [],
        'target_sdk': None,
        'min_sdk': None,
        'extract_native_libs': None,
        'exported_fixed': [],
        'debuggable': None,
        'package_name': None,
        'label': None,
        'renamed_attributes': [],
        'provider': None,
    }

    before = ReadInfo(src)

    # 先改名：后面 application_name / meta_data 都基于新包名书写
    if package_name and package_name != before['package']:
        renamed = RenamePackage(doc, before['package'], package_name)
        changes['package_name'] = {'from': before['package'], 'to': package_name,
                                   'attributes': renamed}
        changes['renamed_attributes'] = renamed

    if label:
        AxmlEdit.set_application_label(doc, label)
        changes['label'] = {'to': label}

    if application_name:
        old = before['application']
        if not before['has_application_element']:
            AxmlEdit.set_application_name(doc, application_name)
            changes['application_name'] = {'from': None, 'to': application_name,
                                           'created_application': True}
        elif old != application_name:
            AxmlEdit.set_application_name(doc, application_name)
            changes['application_name'] = {'from': old, 'to': application_name}
        else:
            changes['application_name'] = {'from': old, 'to': old, 'unchanged': True}

    for key, value in (meta_data or {}).items():
        AxmlEdit.add_meta_data(doc, key, value)
        changes['meta_data'].append({'name': key, 'value': value})

    if provider:
        klass = provider.get('name')
        authorities = provider.get('authorities') or ''
        if not klass:
            raise ManifestError('provider 缺少 name')
        if not authorities:
            authorities = f"{before['package']}.apkhook"
        AxmlEdit.add_provider(doc, klass, authorities,
                              exported=bool(provider.get('exported', False)),
                              process=provider.get('process'))
        changes['provider'] = {'name': klass, 'authorities': authorities,
                               'exported': bool(provider.get('exported', False))}

    if service:
        name = service.get('name')
        if not name:
            raise ManifestError('service 缺少 name')
        AxmlEdit.add_service(
            doc, name,
            exported=bool(service.get('exported', False)),
            foreground_service_type=service.get('foreground_service_type'))
        changes['service'] = {
            'name': name,
            'exported': bool(service.get('exported', False)),
            'foreground_service_type': service.get('foreground_service_type'),
        }

    if permissions:
        existing = set(before['permissions'])
        for perm in permissions:
            perm = perm.strip()
            if not perm:
                continue
            if not perm.startswith('android.permission.'):
                perm = 'android.permission.' + perm.split('.')[-1]
            if perm in existing:
                continue
            AxmlEdit.add_uses_permission(doc, perm)
            changes['permissions_added'].append(perm)

    if target_sdk is not None and int(target_sdk) != before['target_sdk']:
        AxmlEdit.set_target_sdk(doc, int(target_sdk))
        changes['target_sdk'] = {'from': before['target_sdk'], 'to': int(target_sdk)}

    if min_sdk is not None and int(min_sdk) != before['min_sdk']:
        AxmlEdit.set_min_sdk(doc, int(min_sdk))
        changes['min_sdk'] = {'from': before['min_sdk'], 'to': int(min_sdk)}

    if extract_native_libs is not None:
        current = before['extract_native_libs']
        want = 1 if extract_native_libs else 0
        AxmlEdit.set_extract_native_libs(doc, bool(extract_native_libs))
        if current != want:
            changes['extract_native_libs'] = {'from': current, 'to': want}

    if debuggable is not None:
        app = AxmlEdit.application_element(doc)
        if app is not None:
            app.set_bool('debuggable', bool(debuggable), ANDROID_NS)
            changes['debuggable'] = {'from': before['debuggable'],
                                     'to': 1 if debuggable else 0}

    if ensure_exported:
        app = AxmlEdit.application_element(doc)
        if app is not None:
            changes['exported_fixed'] = _ensure_exported(doc, app)

    if os.path.abspath(dst) != os.path.abspath(src):
        shutil.copyfile(src, dst)
    AxmlEdit.save(doc, dst)

    after = ReadInfo(dst)
    changes['after'] = {
        'package': after['package'],
        'application': after['application'],
        'target_sdk': after['target_sdk'],
        'min_sdk': after['min_sdk'],
        'extract_native_libs': after['extract_native_libs'],
        'label': after['label'],
        'permissions': len(after['permissions']),
    }
    return changes


# 包名重命名时要同步替换的属性（值里含旧包名的都改）
RENAME_ATTRS = (
    'authorities', 'targetPackage', 'process', 'taskAffinity',
    'permission', 'value', 'resource',
)

# 这些标签的 android:name 是"类名"，dex 里的类路径不会随包名变化，
# 因此只能把相对名补全成旧包名的绝对名，绝不能跟着改前缀。
CLASS_TAGS = (
    'application', 'activity', 'activity-alias', 'service', 'receiver',
    'provider', 'instrumentation',
)
CLASS_ATTRS = ('name', 'targetActivity', 'parentActivityName',
               'backupAgent', 'manageSpaceActivity')


def _absolutize_class(old_pkg, value):
    """'.Main' / 'Main' -> 'old.pkg.Main'；已经是绝对名则原样返回。"""
    if not value:
        return value
    value = value.strip()
    if value.startswith('.'):
        return old_pkg + value
    if '.' not in value:
        return old_pkg + '.' + value
    return value


def RenamePackage(doc, old, new):
    """把清单里的旧包名换成新包名（马甲包），保持类名指向 dex 里的真实类。

    规则：
      * `<manifest package>` 直接改成新包名；
      * 组件的类名属性（android:name / targetActivity …）先把相对名补全成
        旧包名的绝对名，**不改前缀**（dex 里的类路径不变，改了就 ClassNotFound）；
      * authorities / targetPackage / permission / taskAffinity / meta-data 值
        等字符串属性按 token 边界替换成新包名；
      * 旧包名必须以完整 token 出现（前后不是字母/数字/下划线），
        避免 `com.a.b` 误伤 `com.a.bc`。
    """
    if not old or not new or old == new:
        return []
    import re
    pattern = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(old) + r'(?![A-Za-z0-9_])')
    changes = []
    for el in doc._iter_elements():
        tag = getattr(el, 'tag', None)
        for attr in list(getattr(el, 'attrs', [])):
            if attr.ns != ANDROID_NS:
                continue
            try:
                value = attr.value
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(value, str) or not value:
                continue

            # 1) 类名属性：补全相对名，前缀不动
            if tag in CLASS_TAGS and attr.name in CLASS_ATTRS:
                fixed = _absolutize_class(old, value)
                if fixed != value:
                    el.set_str(attr.name, fixed, ANDROID_NS)
                    changes.append({'tag': tag, 'attr': attr.name,
                                    'from': value, 'to': fixed,
                                    'kind': 'absolutized'})
                continue

            # 2) 字符串属性：token 级替换
            if attr.name not in RENAME_ATTRS or old not in value:
                continue
            replaced = pattern.sub(new, value)
            if replaced == value:
                continue
            el.set_str(attr.name, replaced, ANDROID_NS)
            changes.append({'tag': tag, 'attr': attr.name,
                            'from': value, 'to': replaced,
                            'kind': 'renamed'})
    if AxmlEdit.get_package_name(doc) == old:
        AxmlEdit.set_package_name(doc, new)
        changes.append({'tag': 'manifest', 'attr': 'package',
                        'from': old, 'to': new, 'kind': 'renamed'})
    return changes


def Describe(info):
    lines = [
        f"包名          : {info['package']}",
        f"版本          : {info['version_name']} ({info['version_code']})",
        f"显示名        : {info.get('label') or '(资源引用)'}",
        f"Application   : {info['application'] or 'android.app.Application (默认)'}",
        f"启动 Activity : {info['launcher_activity'] or '(未找到)'}",
        f"组件数量      : activity={len(info['activities'])} "
        f"service={len(info['services'])} receiver={len(info['receivers'])}",
        f"targetSdk     : {info['target_sdk']}   minSdk: {info['min_sdk']}",
        f"extractNativeLibs: {info['extract_native_libs']}",
        f"权限数量      : {len(info['permissions'])}",
    ]
    return '\n'.join(lines)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('usage: ManifestTools.py <AndroidManifest.xml> [out.xml]')
        raise SystemExit(0)
    source = sys.argv[1]
    parsed = ReadInfo(source)
    print(Describe(parsed))
    if len(sys.argv) > 2:
        print(Patch(source, sys.argv[2], permissions=['INTERNET']))
