# -*- mode: python ; coding: utf-8 -*-
# 小说内容快速检索 - Buildozer 配置（APK 打包）
#
# ==============================================
# 说明
# ==============================================
# 1. 入口为 main.py：后台线程启动 Flask，WebView 加载 http://127.0.0.1:{port}/
# 2. templates/ 目录将作为 assets 随 APK 一起打包
# 3. saved_novels/ 使用应用私有目录
# 4. 未把 lxml 放入 requirements：Android 编译复杂，core.py 已降级到 html.parser
# 5. werkzeug use_reloader=False 规避 fork 问题

package.name = novelsearcher
package.domain = org.mynovel
package.source = 0
package.version = 1.0
package.version_code = 1

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,ogg,mp3,wav,html,htm,js,css,json,txt
source.exclude_dirs = tests,__pycache__,saved_novels,logs,.git,.venv,dist,bin

# 权限
android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, \
    READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, FOREGROUND_SERVICE

android.api = 33
android.minapi = 24
android.archs = arm64-v8a

android.fullscreen = 0
android.immersive = 1
android.orientation = sensor

# 使用 python-for-android 的 WebviewBootstrap
bootstrap = webview

# 依赖（注意：不包含 lxml）
requirements = python3,flask,itsdangerous,jinja2,click,werkzeug,markupsafe,jinxed,colorama,\
    beautifulsoup4,ebooklib,pyjwt

log_level = 2

# 应用图标（可选）
# presplash.filename = %(source.dir)s/logo.png

# 禁止 SSL 验证（针对 GitHub Actions 环境的网络问题）
# 可通过环境变量覆盖
