# -*- mode: python ; coding: utf-8 -*-
# 小说内容快速检索 - Buildozer 配置（APK 打包）
#
# ==============================================
# 构建前准备（一次性） —— 建议在 Linux / WSL2 下执行
# ==============================================
#
#   sudo apt-get update
#   sudo apt-get install -y python3-pip python3-venv python3-dev zip unzip openjdk-17-jdk \
#       autoconf libtool pkg-config zlib1g-dev libncurses5-dev libsdl2-dev libssl-dev libffi-dev
#   python3 -m venv .venv && source .venv/bin/activate
#   pip install --upgrade pip setuptools wheel buildozer cython
#
#   # 首次构建时 buildozer 会自动下载 Android SDK / NDK
#   buildozer android sdk
#
# ==============================================
# 打包命令
# ==============================================
#
#   # Debug 版
#   buildozer android debug
#   # 产物默认位于 bin/<title>-<arch>-debug.apk
#
#   # Release 版（需签名，配置 ~/.android/debug.keystore 或 release 证书）
#   buildozer android release
#
#   # 安装到已连接的手机
#   adb install -r bin/NovelSearcher-arm64-v8a-debug.apk
#
# ==============================================
# 说明
# ==============================================
# 1. 入口为 main.py：后台线程启动 Flask，WebView 加载 http://127.0.0.1:{port}/
# 2. templates/ 目录将作为 assets 随 APK 一起打包，Flask 能正常 serve 模板
# 3. 保存目录（saved_novels/）默认使用应用私有目录：
#      /data/org.mynovel.novelsearcher/files/saved_novels/
#    若 Android 11+ 的分区存储限制导致写入失败，main.py 已请求存储权限
# 4. 未把 lxml 放入 requirements：它需要 C 编译，在 Android 上编译复杂；
#    core.py 已在缺失 lxml 时自动降级到 html.parser，解析效果无明显差异
# 5. werkzeug 的 debug reloader 在 Android 上会 fork 失败，main.py 已 use_reloader=False 规避

package.name = novelsearcher
package.domain = org.mynovel
package.source = 0
package.version = 1.0
package.version_code = 1

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,ogg,mp3,wav,html,htm,js,css,json,txt
source.exclude_dirs = tests,__pycache__,saved_novels,logs,.git

# 权限
android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, \
    READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, FOREGROUND_SERVICE

android.api = 33
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a

android.fullscreen = 0
android.immersive = 1
android.orientation = sensor

# 使用 python-for-android 的 WebviewBootstrap
# 主 Activity 自动变为 WebViewActivity，会加载 bootstrap 中指定的 URL
bootstrap = webview

# 依赖（注意：不包含 lxml）
requirements = python3,flask,itsdangerous,jinja2,click,werkzeug,markupsafe,jinxed,colorama,\
    beautifulsoup4,ebooklib

log_level = 2

# 应用图标（可选，若存在则自动打包）
# presplash.filename = %(source.dir)s/logo.png
