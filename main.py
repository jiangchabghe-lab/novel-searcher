# -*- coding: utf-8 -*-
"""APK 入口（python-for-android / Buildozer）。

在安卓 WebView 中加载本地 Flask 服务。Flask 作为后台线程启动，
WebView 加载 http://127.0.0.1:{port}/
"""
import os
import socket
import sys
import threading
import time


HOST = "127.0.0.1"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _start_flask(port: int):
    os.environ["WERKZEUG_RUN_MAIN"] = "true"  # 防止 Flask 重载子进程
    try:
        import web_app  # noqa: WPS433
        # 直接调用 app.run 但禁用 reloader，避免 fork 出问题
        web_app.app.run(host=HOST, port=port, debug=False, use_reloader=False, threaded=True)
    except Exception as exc:
        import traceback
        try:
            from plyer import notification  # type: ignore
            try:
                notification.notify(
                    title="小说检索启动失败",
                    message=str(exc)[:250],
                )
            except Exception:
                pass
        except Exception:
            pass
        traceback.print_exc()


def _wait_for_flask(port: int, timeout_s: float = 15.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def run():
    # 兼容 python-for-android 的 webview bootstrap
    try:
        from android import activity  # type: ignore  # noqa: F401
        from android.webview import WebView  # type: ignore
        from jnius import autoclass, cast  # type: ignore
        from plyer import notification  # type: ignore
    except Exception:
        # 在桌面开发环境下退化为纯 HTTP 服务（用于本地调试）
        print("[main] 未检测到 android 环境，退化为桌面模式")
        port = _find_free_port()
        t = threading.Thread(target=_start_flask, args=(port,), daemon=True)
        t.start()
        print(f"[main] Flask 在 http://{HOST}:{port}/ 启动")
        print(f"[main] 按 Ctrl+C 退出")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return

    port = _find_free_port()
    flask_thread = threading.Thread(target=_start_flask, args=(port,), daemon=True)
    flask_thread.start()

    if not _wait_for_flask(port, timeout_s=20.0):
        try:
            notification.notify(
                title="小说检索",
                message="服务启动超时，请重启 App",
            )
        except Exception:
            pass
        # 即使超时也尝试打开 WebView，让用户看到实际错误

    url = f"http://{HOST}:{port}/"

    WebView(
        url=url,
        allow_zoom=False,
        enable_javascript=True,
        enable_local_file_url=True,
    )

    activity.bind(on_activity_result=lambda *a, **kw: None)
    try:
        from android.permissions import request_permissions, Permission  # type: ignore
        request_permissions([
            Permission.INTERNET,
            Permission.ACCESS_NETWORK_STATE,
            Permission.READ_EXTERNAL_STORAGE,
            Permission.WRITE_EXTERNAL_STORAGE,
        ])
    except Exception:
        pass

    try:
        activity.wait_for_android_event()
    except Exception:
        # 某些版本 python-for-android 没有 wait_for_android_event
        while True:
            time.sleep(0.5)


if __name__ == "__main__":
    run()
