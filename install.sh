#!/bin/sh
# 520apkhook 一键安装（Linux / macOS / WSL / Git-Bash）
#
#   bash install.sh                  # 装齐依赖
#   bash install.sh --check          # 只体检
#   bash install.sh --venv --mirror aliyun
#
# 真正干活的是 install.py（Windows 用 install.bat 走同一份逻辑）。

set -eu

cd "$(dirname "$0")" || exit 1

PY=""
for candidate in python3 python3.13 python3.12 python3.11 python3.10 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)' 2>/dev/null; then
            PY="$candidate"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "[-] 没找到 Python 3.8+，请先安装：" >&2
    echo "      Debian/Ubuntu : sudo apt update && sudo apt install -y python3 python3-pip python3-venv" >&2
    echo "      CentOS/RHEL   : sudo yum install -y python3 python3-pip" >&2
    echo "      Fedora        : sudo dnf install -y python3 python3-pip" >&2
    echo "      Arch          : sudo pacman -S python python-pip" >&2
    echo "      macOS         : brew install python@3.12" >&2
    exit 2
fi

echo "[*] 使用 $("$PY" -c 'import sys;print(sys.executable, sys.version.split()[0])')"
if [ "$#" -eq 0 ]; then
    exec "$PY" install.py
fi
exec "$PY" install.py "$@"
