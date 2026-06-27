#!/usr/bin/env bash
# 在 WSL Ubuntu 中执行：正式打包 APK，并将产物复制到项目根目录
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [ -d ".venv" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

export ANDROIDAPI=33

echo "当前目录: $(pwd)"
echo "开始打包 debug APK ..."
buildozer android debug

echo ""
echo "完成！APK 在 bin/ 目录，正在复制到项目根目录 ..."
APK_COUNT=$(find bin -maxdepth 1 -name "*.apk" | wc -l)
if [ "$APK_COUNT" -eq 0 ]; then
    echo "错误：未找到 APK，请查看上面的 buildozer 日志排查原因"
    exit 1
fi

for f in bin/*.apk; do
    cp -f "$f" .
    echo "已复制: $(basename "$f")  ->  $(basename "$f")"
done

echo ""
echo "APK 已生成在当前目录（项目根目录）："
ls -lh ./*.apk 2>/dev/null || true
