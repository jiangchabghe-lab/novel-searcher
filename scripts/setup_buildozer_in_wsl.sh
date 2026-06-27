#!/usr/bin/env bash
# 在 WSL 的 Ubuntu 中执行一次即可：安装 Buildozer 所需依赖
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "======================================"
echo " 1. 检测 Ubuntu 版本"
echo "======================================"
if command -v lsb_release >/dev/null 2>&1; then
    CODENAME=$(lsb_release -cs)
else
    CODENAME=$(grep -oP '(?<=VERSION_CODENAME=).*' /etc/os-release 2>/dev/null || grep CODENAME /etc/os-release | cut -d= -f2)
fi
echo "检测到 Ubuntu 版本代号：$CODENAME"

if [ -z "$CODENAME" ]; then
    echo "无法检测 Ubuntu 版本，请手动指定 jammy(22.04) 或 noble(24.04)"
    exit 1
fi

# 根据版本选择镜像源
if [ "$CODENAME" = "jammy" ] || [ "$CODENAME" = "noble" ] || [ "$CODENAME" = "focal" ]; then
    SRC_FILE="/etc/apt/sources.list"
    BACKUP_FILE="/etc/apt/sources.list.bak.$(date +%s)"
    echo "======================================"
    echo " 2. 备份并重置软件源到清华镜像"
    echo "======================================"
    sudo cp "$SRC_FILE" "$BACKUP_FILE" 2>/dev/null || true
    echo "已备份到 $BACKUP_FILE"
    sudo tee "$SRC_FILE" > /dev/null <<EOF
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ $CODENAME main restricted universe multiverse
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ $CODENAME-updates main restricted universe multiverse
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ $CODENAME-backports main restricted universe multiverse
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ $CODENAME-security main restricted universe multiverse
EOF
    echo "已写入清华镜像源 ($CODENAME)"
fi

echo "======================================"
echo " 3. 更新软件列表 + 修复可能的依赖冲突"
echo "======================================"
sudo apt-get clean
sudo rm -rf /var/lib/apt/lists/*
sudo apt-get update -y
sudo apt-get -f install -y || true

echo "======================================"
echo " 4. 安装系统依赖"
echo "======================================"
sudo apt-get install -y \
    python3-pip python3-venv python3-dev zip unzip \
    openjdk-17-jdk-headless openjdk-17-jre-headless \
    autoconf libtool pkg-config zlib1g-dev libncurses5-dev \
    libsdl2-dev libssl-dev libffi-dev liblzma-dev libbz2-dev libreadline-dev

echo "======================================"
echo " 5. 创建虚拟环境 .venv 并安装 Buildozer"
echo "======================================"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install --upgrade buildozer cython

echo "======================================"
echo " 6. 初始化 Buildozer 并下载 Android SDK/NDK（首次）"
echo "======================================"
buildozer android sdk

echo ""
echo "======================================"
echo " 就绪！现在可以用："
echo "    ./scripts/build_apk_in_wsl.sh    # 生成 APK"
echo "======================================"
