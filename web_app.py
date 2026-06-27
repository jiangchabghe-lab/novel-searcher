# -*- coding: utf-8 -*-
"""小说检索 Web 服务端（支持安卓浏览器直接访问）。

功能：
- 上传 txt/epub 文件后，在服务端解析、建立索引
- 搜索关键字，返回章节匹配列表
- 保存当前小说到本地（便于下次在任意设备上直接载入）
- 多本保存小说管理（载入 / 删除 / 列出）

启动：
    pip install flask ebooklib beautifulsoup4 lxml
    python web_app.py

安卓设备使用：
- 同局域网：在手机浏览器访问 http://<电脑IP>:5000
- Termux：在安卓上安装 Termux 后，运行 python web_app.py 即可本机访问 http://localhost:5000
"""
import io
import os
import sys
import tempfile
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory, abort

from core import (
    APP_DIR,
    Chapter,
    NovelLoader,
    NovelSearcher,
    SavedNovel,
    log_perf,
)


app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 单文件最大 200MB


_state_lock = threading.RLock()
_state = {
    "chapters": [],
    "searcher": None,
    "source_name": "",
    "novel_id": None,
}


def _get_public_hosts():
    """返回监听的地址提示信息。"""
    hints = ["127.0.0.1"]
    try:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            hints.append(ip)
            s.close()
        except Exception:
            pass
    except Exception:
        pass
    return list(dict.fromkeys(hints))


def _chapter_to_dict(c: Chapter, include_text: bool = False) -> dict:
    d = {"index": c.index, "title": c.title}
    if include_text:
        d["text"] = c.text
    return d


def _set_current(chapters, source_name: str, novel_id: str | None = None):
    with _state_lock:
        _state["chapters"] = list(chapters)
        _state["searcher"] = NovelSearcher(chapters) if chapters else None
        _state["source_name"] = source_name
        _state["novel_id"] = novel_id


def _get_current():
    with _state_lock:
        return (
            list(_state["chapters"]),
            _state["searcher"],
            _state["source_name"],
            _state["novel_id"],
        )


def _highlight(text: str, keyword: str, case_sensitive: bool) -> str:
    if not keyword:
        return text
    kw = keyword if case_sensitive else keyword.lower()
    cmp_text = text if case_sensitive else text.lower()
    start = 0
    out = []
    kl = len(keyword)
    while True:
        idx = cmp_text.find(kw, start)
        if idx < 0:
            out.append(text[start:])
            break
        out.append(text[start:idx])
        out.append(f"<mark>{text[idx:idx + kl]}</mark>")
        start = idx + kl
    return "".join(out)


@app.route("/")
def index():
    return send_from_directory(os.path.join(APP_DIR, "templates"), "index.html")


@app.route("/api/status")
def api_status():
    chapters, _, source_name, novel_id = _get_current()
    return jsonify(
        {
            "loaded": bool(chapters),
            "source_name": source_name,
            "chapters_count": len(chapters),
            "novel_id": novel_id,
            "saved_list": SavedNovel.list_all(),
        }
    )


@app.route("/api/upload", methods=["POST"])
def api_upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "未选择文件"}), 400
    filename = os.path.basename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    try:
        if ext == ".txt":
            raw = file.read()
            # 尝试常见编码
            encodings = ["utf-8-sig", "utf-8", "gbk", "gb18030", "big5"]
            text = None
            last_err = None
            for enc in encodings:
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError as e:
                    last_err = e
            if text is None:
                return jsonify({"ok": False, "error": f"文件编码无法识别: {last_err}"}), 400
            chapters = NovelLoader.load_text(text)
        elif ext == ".epub":
            with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
                tmp.write(file.read())
                tmp_path = tmp.name
            try:
                chapters = NovelLoader.load(tmp_path)
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
        else:
            return jsonify({"ok": False, "error": "仅支持 .txt / .epub 文件"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"加载失败: {e}"}), 500

    if not chapters:
        return jsonify({"ok": False, "error": "未能解析出任何章节"}), 400

    t0 = time.perf_counter()
    _set_current(chapters, source_name=filename, novel_id=None)
    log_perf("Web 端加载", t0, f"{filename} 共 {len(chapters)} 章")

    chapters_preview = [_chapter_to_dict(c) for c in chapters[:200]]
    return jsonify(
        {
            "ok": True,
            "filename": filename,
            "chapters_count": len(chapters),
            "chapters": chapters_preview,
            "truncated": len(chapters) > 200,
        }
    )


@app.route("/api/chapters")
def api_chapters():
    chapters, _, source_name, _ = _get_current()
    q = (request.args.get("q") or "").strip().lower()
    if q:
        filtered = [_chapter_to_dict(c) for c in chapters if q in c.title.lower()]
    else:
        filtered = [_chapter_to_dict(c) for c in chapters]
    return jsonify(
        {
            "ok": True,
            "source_name": source_name,
            "chapters_count": len(chapters),
            "chapters": filtered,
        }
    )


@app.route("/api/chapters/<int:chapter_index>")
def api_chapter(chapter_index: int):
    chapters, _, source_name, _ = _get_current()
    for c in chapters:
        if c.index == chapter_index:
            kw = (request.args.get("keyword") or "").strip()
            case_sensitive = request.args.get("case_sensitive") == "1"
            hl = _highlight(c.text, kw, case_sensitive) if kw else c.text
            return jsonify(
                {
                    "ok": True,
                    "chapter": {
                        "index": c.index,
                        "title": c.title,
                        "text": c.text,
                        "html": hl,
                    },
                    "source_name": source_name,
                }
            )
    return jsonify({"ok": False, "error": "未找到该章节"}), 404


@app.route("/api/search")
def api_search():
    keyword = (request.args.get("keyword") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "缺少关键字"}), 400
    case_sensitive = request.args.get("case_sensitive") == "1"
    fuzzy = request.args.get("fuzzy") == "1"
    try:
        context = int(request.args.get("context", 30))
    except ValueError:
        context = 30
    try:
        max_hits = int(request.args.get("max_hits", 500))
    except ValueError:
        max_hits = 500

    chapters, searcher, _, _ = _get_current()
    if not searcher:
        return jsonify({"ok": False, "error": "请先加载小说"}), 400

    t0 = time.perf_counter()
    try:
        hits = searcher.search(
            keyword,
            case_sensitive=case_sensitive,
            fuzzy=fuzzy,
            context=context,
            max_hits=max_hits,
        )
    except Exception as e:
        return jsonify({"ok": False, "error": f"搜索失败: {e}"}), 500
    elapsed = time.perf_counter() - t0

    grouped = {}
    for h in hits:
        grouped.setdefault(h.chapter_index, {"title": h.chapter_title, "count": 0, "snippet": h.snippet})
        grouped[h.chapter_index]["count"] += 1

    groups = []
    for cidx in sorted(grouped.keys()):
        info = grouped[cidx]
        snippet_html = _highlight(info["snippet"], keyword, case_sensitive)
        groups.append(
            {
                "chapter_index": cidx,
                "chapter_title": info["title"],
                "count": info["count"],
                "snippet": info["snippet"],
                "snippet_html": snippet_html,
            }
        )

    return jsonify(
        {
            "ok": True,
            "keyword": keyword,
            "case_sensitive": case_sensitive,
            "fuzzy": fuzzy,
            "context": context,
            "total_hits": len(hits),
            "total_chapters": len(groups),
            "elapsed_ms": round(elapsed * 1000, 1),
            "groups": groups,
        }
    )


@app.route("/api/saved", methods=["GET"])
def api_saved_list():
    return jsonify({"ok": True, "list": SavedNovel.list_all()})


@app.route("/api/saved/save", methods=["POST"])
def api_saved_save():
    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "缺少保存名称"}), 400
    chapters, _, source_name, _ = _get_current()
    if not chapters:
        return jsonify({"ok": False, "error": "没有可保存的小说"}), 400
    novel_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record = SavedNovel(
        id=novel_id,
        name=name,
        chapters=chapters,
        source_file=source_name,
        saved_at=saved_at,
    )
    try:
        record.persist()
    except Exception as e:
        return jsonify({"ok": False, "error": f"保存失败: {e}"}), 500
    return jsonify({"ok": True, "id": novel_id, "name": name})


@app.route("/api/saved/load/<novel_id>", methods=["POST"])
def api_saved_load(novel_id: str):
    try:
        record = SavedNovel.load_by_id(novel_id)
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "未找到该保存"}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": f"载入失败: {e}"}), 500
    _set_current(record.chapters, source_name=f"(已保存) {record.name}", novel_id=record.id)
    chapters_preview = [_chapter_to_dict(c) for c in record.chapters[:200]]
    return jsonify(
        {
            "ok": True,
            "novel": {
                "id": record.id,
                "name": record.name,
                "source_file": record.source_file,
                "chapters_count": len(record.chapters),
            },
            "chapters": chapters_preview,
            "truncated": len(record.chapters) > 200,
        }
    )


@app.route("/api/saved/delete/<novel_id>", methods=["POST"])
def api_saved_delete(novel_id: str):
    ok = SavedNovel.delete_by_id(novel_id)
    return jsonify({"ok": ok})


@app.route("/api/saved/<novel_id>/chapters-list")
def api_saved_chapters_list(novel_id: str):
    """仅返回章节索引与标题列表（轻量）。"""
    try:
        record = SavedNovel.load_by_id(novel_id)
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "未找到该保存"}), 404
    chapters_preview = [_chapter_to_dict(c) for c in record.chapters]
    return jsonify(
        {
            "ok": True,
            "novel": {
                "id": record.id,
                "name": record.name,
                "source_file": record.source_file,
                "chapters_count": len(record.chapters),
            },
            "chapters": chapters_preview,
        }
    )


@app.route("/api/saved/<novel_id>/chapters/<int:chapter_index>")
def api_saved_chapter(novel_id: str, chapter_index: int):
    try:
        record = SavedNovel.load_by_id(novel_id)
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "未找到该保存"}), 404
    for c in record.chapters:
        if c.index == chapter_index:
            kw = (request.args.get("keyword") or "").strip()
            case_sensitive = request.args.get("case_sensitive") == "1"
            hl = _highlight(c.text, kw, case_sensitive) if kw else c.text
            return jsonify(
                {
                    "ok": True,
                    "chapter": {
                        "index": c.index,
                        "title": c.title,
                        "text": c.text,
                        "html": hl,
                    },
                    "novel_id": novel_id,
                    "novel_name": record.name,
                }
            )
    return jsonify({"ok": False, "error": "未找到该章节"}), 404


@app.route("/api/saved/<novel_id>/search")
def api_saved_search(novel_id: str):
    keyword = (request.args.get("keyword") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "缺少关键字"}), 400
    case_sensitive = request.args.get("case_sensitive") == "1"
    fuzzy = request.args.get("fuzzy") == "1"
    try:
        context = int(request.args.get("context", 30))
    except ValueError:
        context = 30
    try:
        max_hits = int(request.args.get("max_hits", 500))
    except ValueError:
        max_hits = 500

    try:
        record = SavedNovel.load_by_id(novel_id)
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "未找到该保存"}), 404

    searcher = NovelSearcher(record.chapters)
    try:
        hits = searcher.search(
            keyword,
            case_sensitive=case_sensitive,
            fuzzy=fuzzy,
            context=context,
            max_hits=max_hits,
        )
    except Exception as e:
        return jsonify({"ok": False, "error": f"搜索失败: {e}"}), 500

    grouped = {}
    for h in hits:
        grouped.setdefault(h.chapter_index, {"title": h.chapter_title, "count": 0, "snippet": h.snippet})
        grouped[h.chapter_index]["count"] += 1

    groups = []
    for cidx in sorted(grouped.keys()):
        info = grouped[cidx]
        snippet_html = _highlight(info["snippet"], keyword, case_sensitive)
        groups.append(
            {
                "chapter_index": cidx,
                "chapter_title": info["title"],
                "count": info["count"],
                "snippet": info["snippet"],
                "snippet_html": snippet_html,
            }
        )

    return jsonify(
        {
            "ok": True,
            "keyword": keyword,
            "novel_id": novel_id,
            "novel_name": record.name,
            "total_hits": len(hits),
            "total_chapters": len(groups),
            "groups": groups,
        }
    )


@app.errorhandler(413)
def too_large(e):
    return jsonify({"ok": False, "error": "文件过大（最大 200MB）"}), 413


@app.errorhandler(500)
def server_error(e):
    return jsonify({"ok": False, "error": f"服务错误: {e}"}), 500


if __name__ == "__main__":
    hosts = _get_public_hosts()
    port = int(os.environ.get("PORT", "5000"))
    print("=" * 60)
    print("小说检索 Web 版启动")
    print("请在浏览器中访问:")
    for h in hosts:
        print(f"  http://{h}:{port}/")
    print("=" * 60)
    sys.stdout.flush()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
