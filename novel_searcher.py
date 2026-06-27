# -*- coding: utf-8 -*-
"""小说内容快速检索工具

支持 EPUB / TXT 格式，按章节建立索引，输入关键字即可快速定位章节位置。
"""
import json
import logging
import os
import re
import sys
import threading
import time
import tkinter as tk
import warnings
from datetime import datetime
from queue import Queue, Empty
from tkinter import filedialog, messagebox, simpledialog, ttk
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

try:
    from ebooklib import epub
    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
    _HAS_EBOOKLIB = True
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except Exception:
    _HAS_EBOOKLIB = False


APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(APP_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"novel_searcher_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
SAVE_DIR = os.path.join(APP_DIR, "saved_novels")
os.makedirs(SAVE_DIR, exist_ok=True)
INDEX_FILE = os.path.join(SAVE_DIR, "index.json")

_logger = logging.getLogger("novel_searcher")
_logger.setLevel(logging.DEBUG)
_fmt = logging.Formatter(
    "%(asctime)s | %(levelname)-7s | %(threadName)-12s | %(message)s",
    datefmt="%H:%M:%S",
)
_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
_logger.addHandler(_fh)

_ui_log_queue: "Queue[str]" = Queue()


class _UiLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            _ui_log_queue.put_nowait(msg)
        except Exception:
            pass


_uh = _UiLogHandler()
_uh.setLevel(logging.INFO)
_uh.setFormatter(_fmt)
_logger.addHandler(_uh)


def log_perf(label: str, start: float, extra: str = ""):
    elapsed = time.perf_counter() - start
    _logger.info(f"[PERF] {label} 耗时 {elapsed*1000:.1f}ms {extra}".rstrip())


@dataclass
class Chapter:
    index: int
    title: str
    text: str = ""
    offset: int = 0


@dataclass
class SavedNovel:
    id: str
    name: str
    chapters: List[Chapter]
    source_file: str = ""
    saved_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "source_file": self.source_file,
            "saved_at": self.saved_at,
            "chapters": [
                {"index": c.index, "title": c.title, "text": c.text} for c in self.chapters
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SavedNovel":
        chapters = [
            Chapter(index=c["index"], title=c["title"], text=c.get("text", ""))
            for c in data.get("chapters", [])
        ]
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            source_file=data.get("source_file", ""),
            saved_at=data.get("saved_at", ""),
            chapters=chapters,
        )

    def persist(self):
        os.makedirs(SAVE_DIR, exist_ok=True)
        data_path = os.path.join(SAVE_DIR, f"{self.id}.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        self._update_index()

    def _update_index(self):
        index = SavedNovel._load_index()
        index[self.id] = {
            "id": self.id,
            "name": self.name,
            "source_file": self.source_file,
            "saved_at": self.saved_at,
            "chapters_count": len(self.chapters),
        }
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _load_index() -> dict:
        if not os.path.exists(INDEX_FILE):
            return {}
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def list_all() -> List[dict]:
        index = SavedNovel._load_index()
        return sorted(
            index.values(),
            key=lambda x: x.get("saved_at", ""),
            reverse=True,
        )

    @staticmethod
    def load_by_id(novel_id: str) -> "SavedNovel":
        data_path = os.path.join(SAVE_DIR, f"{novel_id}.json")
        with open(data_path, "r", encoding="utf-8") as f:
            return SavedNovel.from_dict(json.load(f))

    @staticmethod
    def delete_by_id(novel_id: str) -> bool:
        index = SavedNovel._load_index()
        if novel_id not in index:
            return False
        del index[novel_id]
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        data_path = os.path.join(SAVE_DIR, f"{novel_id}.json")
        if os.path.exists(data_path):
            try:
                os.remove(data_path)
            except Exception:
                pass
        return True


class NovelLoader:
    MIN_CHAPTER_LEN = 20

    @staticmethod
    def load(path: str) -> List[Chapter]:
        _logger.info(f"开始加载文件: {path}")
        ext = os.path.splitext(path)[1].lower()
        t0 = time.perf_counter()
        try:
            if ext == ".epub":
                result = NovelLoader._load_epub(path)
            elif ext in (".txt", ".text"):
                result = NovelLoader._load_txt(path)
            else:
                raise ValueError(f"暂不支持的文件格式: {ext}")
            log_perf(f"加载 {ext} 文件成功", t0, f"共 {len(result)} 章")
            return result
        except Exception:
            log_perf(f"加载 {ext} 文件失败", t0)
            raise

    @staticmethod
    def _clean_html(html_text: str) -> str:
        soup = BeautifulSoup(html_text, "lxml")
        for tag in soup.find_all(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        text = re.sub(r"[ \t\r\u3000]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _is_toc_like(title: str, text: str) -> bool:
        if title and re.search(r"目录|目次|contents", title, re.IGNORECASE):
            return True
        chapter_marks = re.findall(r"第[一二三四五六七八九十百千零\d]{1,8}[章节回卷集篇部].{0,20}", text)
        if len(chapter_marks) >= 15 and len(text) > 5000:
            return True
        return False

    @staticmethod
    def _load_epub(path: str) -> List[Chapter]:
        if not _HAS_EBOOKLIB:
            raise RuntimeError("未安装 ebooklib，请先执行: pip install ebooklib")
        book = epub.read_epub(path)
        chapters: List[Chapter] = []
        for item in book.get_items_of_type(9):  # ITEM_DOCUMENT
            raw = item.get_content().decode("utf-8", errors="ignore")
            title = NovelLoader._extract_epub_title(raw, item.get_name())
            text = NovelLoader._clean_html(raw)
            if len(text) < NovelLoader.MIN_CHAPTER_LEN:
                continue
            if NovelLoader._is_toc_like(title, text):
                continue
            chapters.append(Chapter(index=0, title=title, text=text))
        if not chapters:
            for item in book.get_items():
                if item.get_type() == 9:
                    continue
                if hasattr(item, "get_content"):
                    raw = item.get_content().decode("utf-8", errors="ignore")
                    text = NovelLoader._clean_html(raw)
                    if len(text) >= NovelLoader.MIN_CHAPTER_LEN:
                        chapters.append(Chapter(index=0, title=item.get_name(), text=text))
        for i, ch in enumerate(chapters, 1):
            ch.index = i
        return chapters

    @staticmethod
    def _extract_epub_title(raw: str, fallback: str) -> str:
        soup = BeautifulSoup(raw, "lxml")
        h = soup.find(re.compile(r"^h[1-6]$"))
        if h and h.get_text(strip=True):
            return h.get_text(strip=True)
        title = soup.find("title")
        if title and title.get_text(strip=True):
            return title.get_text(strip=True)
        m = re.search(r"第[一二三四五六七八九十百千零\d]+[章节回卷集篇部].{0,20}", raw)
        if m:
            return m.group(0)
        return fallback or "未命名章节"

    @staticmethod
    def _load_txt(path: str) -> List[Chapter]:
        encodings = ["utf-8-sig", "utf-8", "gbk", "gb18030", "big5"]
        text = ""
        last_err = None
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc) as f:
                    text = f.read()
                break
            except UnicodeDecodeError as e:
                last_err = e
        if not text:
            raise RuntimeError(f"文件编码无法识别: {last_err}")

        pattern = re.compile(
            r"^\s*(第\s*[一二三四五六七八九十百千零\d]{1,8}\s*[章节回卷集篇部卷])"
            r"[\s：:．.\u3000]{0,4}(.{0,40})",
            re.MULTILINE,
        )
        matches = list(pattern.finditer(text))
        chapters: List[Chapter] = []
        if matches:
            for i, m in enumerate(matches):
                title = (m.group(1) + (m.group(2) or "")).strip()
                start = m.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                body = text[start:end].strip()
                if len(body) < NovelLoader.MIN_CHAPTER_LEN:
                    continue
                chapters.append(
                    Chapter(index=len(chapters) + 1, title=title or f"第{i + 1}章", text=body)
                )
        else:
            paragraphs = [p for p in text.split("\n\n") if len(p.strip()) >= NovelLoader.MIN_CHAPTER_LEN]
            for i, p in enumerate(paragraphs):
                chapters.append(Chapter(index=i + 1, title=f"第{i + 1}段", text=p.strip()))
        return chapters


@dataclass
class SearchHit:
    chapter_index: int
    chapter_title: str
    snippet: str
    position: int


class NovelSearcher:
    def __init__(self, chapters: List[Chapter]):
        self.chapters = chapters

    def search(
        self,
        keyword: str,
        case_sensitive: bool = False,
        fuzzy: bool = False,
        context: int = 30,
        max_hits: int = 500,
        cancel_event: Optional[threading.Event] = None,
        progress_callback=None,
    ) -> List[SearchHit]:
        keyword = keyword.strip()
        if not keyword:
            return []
        hits: List[SearchHit] = []
        cmp = str if case_sensitive else lambda s: s.lower()
        kw = cmp(keyword)

        total = len(self.chapters)
        t0 = time.perf_counter()
        _logger.info(f"开始搜索: 关键字='{keyword}', 总章节={total}, 最大命中={max_hits}, 模糊={fuzzy}")
        for idx, ch in enumerate(self.chapters):
            if cancel_event is not None and cancel_event.is_set():
                _logger.info(f"搜索已取消于第 {idx}/{total} 章，已收集 {len(hits)} 条命中")
                break
            body = cmp(ch.text)
            if fuzzy:
                positions = self._fuzzy_find_all(body, kw)
            else:
                positions = self._find_all(body, kw)
            for pos in positions:
                if len(hits) >= max_hits:
                    _logger.info(f"搜索达到上限 {max_hits}，在第 {idx}/{total} 章终止")
                    return hits
                raw_body = ch.text
                start = max(0, pos - context)
                end = min(len(raw_body), pos + len(keyword) + context)
                snippet = raw_body[start:end].replace("\n", " ")
                hits.append(
                    SearchHit(
                        chapter_index=ch.index,
                        chapter_title=ch.title,
                        snippet=snippet,
                        position=pos,
                    )
                )
            if progress_callback is not None and (idx % 100 == 0 or idx == total - 1):
                progress_callback(idx + 1, total)
        log_perf(f"搜索完成", t0, f"命中 {len(hits)} 条，分布于 {len({h.chapter_index for h in hits})} 章")
        return hits

    @staticmethod
    def _find_all(text: str, sub: str) -> List[int]:
        positions = []
        if not sub:
            return positions
        start = 0
        while True:
            idx = text.find(sub, start)
            if idx == -1:
                break
            positions.append(idx)
            start = idx + 1
        return positions

    @staticmethod
    def _fuzzy_find_all(text: str, sub: str, max_errors: int = 1) -> List[int]:
        positions = []
        n, m = len(text), len(sub)
        if m == 0 or m > n:
            return positions
        step = max(1, m // 2)
        i = 0
        while i <= n - m:
            window = text[i : i + m]
            dist = NovelSearcher._levenshtein(window, sub)
            if dist <= max_errors:
                positions.append(i)
                i += m
            else:
                i += step
        return positions

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        la, lb = len(a), len(b)
        if la == 0:
            return lb
        if lb == 0:
            return la
        prev = list(range(lb + 1))
        for i in range(1, la + 1):
            cur = [i] + [0] * lb
            for j in range(1, lb + 1):
                cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            prev = cur
        return prev[lb]


class NovelSearchApp(tk.Tk):
    MAX_HITS = 5000

    def __init__(self):
        super().__init__()
        self.title("小说内容快速检索工具")
        self.geometry("1180x720")
        self.minsize(920, 600)
        self._center_window(1180, 720)

        self.chapters: List[Chapter] = []
        self.chapter_index_map: dict = {}
        self.searcher: Optional[NovelSearcher] = None
        self.current_file: str = ""
        self._loading = False
        self._cancel_event: Optional[threading.Event] = None
        self._feed_after_id: Optional[str] = None
        self._feed_index = 0
        self._feed_grouped = {}
        self._feed_total = 0
        self._feed_first_cidx = None
        self._chapter_list_index = 0
        self._chapter_list_after_id = None
        self._current_preview_idx: int = -1
        self._current_preview_kw: str = ""
        self._saved_records: List[dict] = []

        self._build_ui()
        self.after(100, self._refresh_saved_list)

    def _center_window(self, width: int, height: int):
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="小说文件:").pack(side=tk.LEFT)
        self.var_file = tk.StringVar(value="(未加载)")
        ttk.Label(top, textvariable=self.var_file, foreground="#555").pack(side=tk.LEFT, padx=(4, 12))
        self.btn_open = ttk.Button(top, text="打开…", command=self.on_open)
        self.btn_open.pack(side=tk.LEFT)
        self.btn_demo = ttk.Button(top, text="加载示例(遮天.epub)", command=self.on_load_demo)
        self.btn_demo.pack(side=tk.LEFT, padx=6)

        ttk.Label(top, text="已保存:").pack(side=tk.LEFT, padx=(12, 2))
        self.var_saved = tk.StringVar()
        self.cmb_saved = ttk.Combobox(top, textvariable=self.var_saved, width=38, state="readonly")
        self.cmb_saved.pack(side=tk.LEFT)
        self.cmb_saved.bind("<<ComboboxSelected>>", lambda e: self.on_load_saved())
        self.btn_load_saved = ttk.Button(top, text="载入", command=self.on_load_saved)
        self.btn_load_saved.pack(side=tk.LEFT, padx=4)
        self.btn_save = ttk.Button(top, text="保存当前", command=self.on_save_current)
        self.btn_save.pack(side=tk.LEFT, padx=2)
        self.btn_delete_saved = ttk.Button(top, text="删除", command=self.on_delete_saved)
        self.btn_delete_saved.pack(side=tk.LEFT, padx=2)

        sep = ttk.Separator(self, orient=tk.HORIZONTAL)
        sep.pack(side=tk.TOP, fill=tk.X, pady=4)

        qbar = ttk.Frame(self, padding=(8, 4))
        qbar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(qbar, text="检索关键字:").pack(side=tk.LEFT)
        self.var_query = tk.StringVar()
        self.entry_query = ttk.Entry(qbar, textvariable=self.var_query, width=40)
        self.entry_query.pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        self.entry_query.bind("<Return>", lambda e: self.on_search())

        self.var_case = tk.BooleanVar(value=False)
        self.var_fuzzy = tk.BooleanVar(value=False)
        self.var_context = tk.IntVar(value=30)
        ttk.Checkbutton(qbar, text="区分大小写", variable=self.var_case).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(qbar, text="模糊匹配", variable=self.var_fuzzy).pack(side=tk.LEFT, padx=6)
        ttk.Label(qbar, text="上下文:").pack(side=tk.LEFT, padx=(12, 2))
        ttk.Spinbox(qbar, from_=5, to=200, width=5, textvariable=self.var_context).pack(side=tk.LEFT)
        self.btn_search = ttk.Button(qbar, text="搜索", command=self.on_search)
        self.btn_search.pack(side=tk.LEFT, padx=8)
        self.btn_cancel = ttk.Button(qbar, text="停止", command=self.on_cancel, state=tk.DISABLED)
        self.btn_cancel.pack(side=tk.LEFT)
        self.btn_clear = ttk.Button(qbar, text="清除", command=self.on_clear)
        self.btn_clear.pack(side=tk.LEFT)

        status = ttk.Frame(self)
        status.pack(side=tk.TOP, fill=tk.X)
        self.var_status = tk.StringVar(value="就绪")
        ttk.Label(status, textvariable=self.var_status, anchor="w", padding=(10, 2),
                  relief=tk.SUNKEN).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=120)
        self.progress.pack(side=tk.RIGHT, padx=6)

        body = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=6)

        left = ttk.Labelframe(body, text="章节目录 (输入过滤)")
        body.add(left, weight=1)

        filter_bar = ttk.Frame(left)
        filter_bar.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4)
        self.var_ch_filter = tk.StringVar()
        self.var_ch_filter.trace_add("write", lambda *a: self._filter_chapters())
        ttk.Label(filter_bar, text="过滤:").pack(side=tk.LEFT)
        ttk.Entry(filter_bar, textvariable=self.var_ch_filter).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self.chapter_tree = ttk.Treeview(left, columns=("title",), show="headings", height=20)
        self.chapter_tree.heading("title", text="章节标题")
        self.chapter_tree.column("title", anchor=tk.W, stretch=True)
        self.chapter_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        ch_sb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.chapter_tree.yview)
        self.chapter_tree.configure(yscrollcommand=ch_sb.set)
        ch_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.chapter_tree.bind("<<TreeviewSelect>>", lambda e: self._on_chapter_select())

        right = ttk.Frame(body)
        body.add(right, weight=4)

        right_split = ttk.Panedwindow(right, orient=tk.VERTICAL)
        right_split.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        top_panel = ttk.Labelframe(right_split, text="搜索结果 (双击查看章节原文)")
        right_split.add(top_panel, weight=3)

        cols = ("idx", "chapter", "snippet")
        self.tree = ttk.Treeview(top_panel, columns=cols, show="headings", height=12)
        self.tree.heading("idx", text="序号")
        self.tree.heading("chapter", text="章节")
        self.tree.heading("snippet", text="匹配片段")
        self.tree.column("idx", width=60, anchor=tk.CENTER, stretch=False)
        self.tree.column("chapter", width=260, anchor=tk.W)
        self.tree.column("snippet", width=700, anchor=tk.W)
        sb = ttk.Scrollbar(top_panel, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", lambda e: self._show_current_chapter())
        self.tree.bind("<Enter>", lambda e: self._bind_tree_mousewheel(True))
        self.tree.bind("<Leave>", lambda e: self._bind_tree_mousewheel(False))
        self._bind_tree_mousewheel(True)

        bottom_panel = ttk.Labelframe(right_split, text="章节原文预览 (搜索关键字会高亮)")
        right_split.add(bottom_panel, weight=2)
        self.txt_view = tk.Text(bottom_panel, wrap="word", font=("Microsoft YaHei", 10),
                                bg="#fdfdfd", relief=tk.FLAT)
        self.txt_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sv = ttk.Scrollbar(bottom_panel, orient=tk.VERTICAL, command=self.txt_view.yview)
        self.txt_view.configure(yscrollcommand=sv.set)
        sv.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_view.configure(state=tk.DISABLED)

        log_panel = ttk.Labelframe(self, text="运行日志 (可诊断卡顿原因)")
        log_panel.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(0, 6))
        self.txt_log = tk.Text(log_panel, height=8, wrap="none",
                               font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
                               insertbackground="#d4d4d4", relief=tk.FLAT)
        self.txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_sb_y = ttk.Scrollbar(log_panel, orient=tk.VERTICAL, command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=log_sb_y.set)
        log_sb_y.pack(side=tk.RIGHT, fill=tk.Y)
        log_sb_x = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.txt_log.xview)
        self.txt_log.configure(xscrollcommand=log_sb_x.set)
        log_sb_x.pack(side=tk.BOTTOM, fill=tk.X, padx=8)
        self.txt_log.configure(state=tk.DISABLED)

        self._log_pump()
        _logger.info(f"程序启动，日志文件: {LOG_FILE}")

    def _bind_tree_mousewheel(self, bind: bool):
        if bind:
            self.tree.bind("<MouseWheel>", self._on_tree_mousewheel)
            self.tree.bind("<Button-4>", lambda e: self._on_tree_mousewheel(e, -1))
            self.tree.bind("<Button-5>", lambda e: self._on_tree_mousewheel(e, 1))
        else:
            self.tree.unbind("<MouseWheel>")
            self.tree.unbind("<Button-4>")
            self.tree.unbind("<Button-5>")

    def _on_tree_mousewheel(self, event, direction=None):
        if direction is not None:
            delta = -direction * 120
        else:
            delta = event.delta
        units = int(-delta / 120) if delta else 0
        if units != 0:
            self.tree.yview_scroll(units, "units")
        return "break"

    def _log_pump(self):
        try:
            chunks = []
            for _ in range(200):
                try:
                    msg = _ui_log_queue.get_nowait()
                    chunks.append(msg)
                except Empty:
                    break
            if chunks:
                self.txt_log.configure(state=tk.NORMAL)
                self.txt_log.insert(tk.END, "\n".join(chunks) + "\n")
                self.txt_log.see(tk.END)
                line_count = int(self.txt_log.index("end-1c").split(".")[0])
                MAX_LOG_LINES = 4000
                if line_count > MAX_LOG_LINES:
                    self.txt_log.delete("1.0", f"{line_count - MAX_LOG_LINES}.0")
                self.txt_log.configure(state=tk.DISABLED)
        except Exception:
            pass
        self.after(150, self._log_pump)

    def _set_status(self, msg: str):
        self.var_status.set(msg)
        self.update_idletasks()

    def _set_busy(self, busy: bool):
        self._loading = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.btn_open.configure(state=state)
        self.btn_demo.configure(state=state)
        self.btn_search.configure(state=state)
        self.btn_clear.configure(state=state)
        self.entry_query.configure(state=state)
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()

    def _set_search_running(self, running: bool):
        if running:
            self.btn_search.configure(state=tk.DISABLED)
            self.btn_cancel.configure(state=tk.NORMAL)
            self.btn_clear.configure(state=tk.DISABLED)
            self.progress.stop()
            self.progress.start(10)
        else:
            self.btn_search.configure(state=tk.NORMAL)
            self.btn_cancel.configure(state=tk.DISABLED)
            self.btn_clear.configure(state=tk.NORMAL)
            self.progress.stop()

    def on_open(self):
        path = filedialog.askopenfilename(
            title="选择小说文件",
            filetypes=[("小说文件", "*.epub *.txt"), ("EPUB", "*.epub"), ("TXT", "*.txt"), ("全部", "*.*")],
        )
        if not path:
            return
        self._load_file(path)

    def on_load_demo(self):
        demo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "遮天.epub")
        if os.path.exists(demo):
            self._load_file(demo)
        else:
            messagebox.showinfo("提示", f"未找到示例文件:\n{demo}")

    def _refresh_saved_list(self):
        records = SavedNovel.list_all()
        self._saved_records = records
        display_values = [
            f"【{r.get('chapters_count', 0)}章】{r.get('name', '未命名')}  ({r.get('saved_at', '')})"
            for r in records
        ]
        self.cmb_saved["values"] = display_values
        _logger.info(f"已刷新保存列表，共 {len(records)} 本小说")

    def _get_selected_saved_id(self) -> Optional[str]:
        idx = self.cmb_saved.current()
        if idx < 0 or idx >= len(self._saved_records):
            return None
        return self._saved_records[idx].get("id")

    def on_save_current(self):
        if not self.chapters:
            messagebox.showinfo("提示", "当前没有已加载的小说可保存")
            return
        default_name = ""
        if self.current_file:
            default_name = os.path.splitext(os.path.basename(self.current_file))[0]
        name = simpledialog.askstring(
            "保存小说",
            "请输入小说保存名称:",
            initialvalue=default_name or f"小说_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            parent=self,
        )
        if not name:
            return
        name = name.strip()
        if not name:
            return
        novel_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = SavedNovel(
            id=novel_id,
            name=name,
            chapters=self.chapters,
            source_file=self.current_file,
            saved_at=saved_at,
        )
        try:
            record.persist()
        except Exception as e:
            _logger.exception(f"保存小说失败: {e}")
            messagebox.showerror("保存失败", str(e))
            return
        self._refresh_saved_list()
        self.var_saved.set(
            f"【{len(self.chapters)}章】{name}  ({saved_at})"
        )
        self._set_status(f"已保存小说：{name}")
        _logger.info(f"小说保存成功: {name}, id={novel_id}, 共 {len(self.chapters)} 章")
        messagebox.showinfo("保存成功", f"小说《{name}》已保存。\n共 {len(self.chapters)} 章。")

    def on_load_saved(self):
        novel_id = self._get_selected_saved_id()
        if not novel_id:
            return
        self._set_busy(True)
        self._set_status("正在从本地载入已保存小说…")
        _logger.info(f"UI 触发加载已保存小说: id={novel_id}")
        t0 = time.perf_counter()

        def worker():
            try:
                record = SavedNovel.load_by_id(novel_id)
                self.after(0, lambda: self._on_loaded_saved(record, None, time.perf_counter() - t0))
            except Exception as e:
                self.after(0, lambda: self._on_loaded_saved(None, str(e), time.perf_counter() - t0))

        threading.Thread(target=worker, daemon=True, name="loader-saved").start()

    def _on_loaded_saved(self, record: Optional[SavedNovel], error: Optional[str], elapsed: float):
        self._set_busy(False)
        if error or record is None:
            _logger.error(f"加载已保存小说失败: {error}")
            self._set_status(f"加载失败: {error}")
            messagebox.showerror("加载失败", error or "未知错误")
            return
        _logger.info(
            f"加载已保存小说成功: 《{record.name}》共 {len(record.chapters)} 章，耗时 {elapsed*1000:.0f}ms"
        )
        self.chapters = record.chapters
        self.current_file = record.source_file or f"(已保存) {record.name}"
        self.searcher = NovelSearcher(record.chapters)
        self.chapter_index_map = {c.index: c for c in record.chapters}
        self.var_file.set(f"{record.name}  |  共 {len(record.chapters)} 章  (已保存)")
        self._set_status(f"已载入：{record.name}（{len(record.chapters)} 章）")
        self.on_clear()
        self._rebuild_chapter_list()

    def on_delete_saved(self):
        novel_id = self._get_selected_saved_id()
        if not novel_id:
            messagebox.showinfo("提示", "请先从下拉框选择要删除的已保存小说")
            return
        idx = self.cmb_saved.current()
        name = self._saved_records[idx].get("name", "")
        if not messagebox.askyesno("确认删除", f"确定删除已保存的小说《{name}》吗？\n此操作不可恢复。"):
            return
        try:
            ok = SavedNovel.delete_by_id(novel_id)
        except Exception as e:
            _logger.exception(f"删除保存小说失败: {e}")
            messagebox.showerror("删除失败", str(e))
            return
        if ok:
            self._refresh_saved_list()
            self.var_saved.set("")
            self._set_status(f"已删除：{name}")
            _logger.info(f"已删除保存小说: id={novel_id}, name={name}")
        else:
            messagebox.showerror("删除失败", "未找到对应的保存记录")

    def _load_file(self, path: str):
        self._set_busy(True)
        self._set_status(f"正在加载: {os.path.basename(path)} ...")
        _logger.info(f"UI 触发加载: {path}")
        t0 = time.perf_counter()

        def worker():
            try:
                chapters = NovelLoader.load(path)
                self.after(0, lambda: self._on_loaded(path, chapters, None, time.perf_counter() - t0))
            except Exception as e:
                self.after(0, lambda: self._on_loaded(path, [], str(e), time.perf_counter() - t0))

        threading.Thread(target=worker, daemon=True, name="loader").start()

    def _on_loaded(self, path: str, chapters: List[Chapter], error: Optional[str], elapsed: float):
        self._set_busy(False)
        if error:
            _logger.error(f"加载失败: {error}，耗时 {elapsed*1000:.0f}ms")
            self._set_status(f"加载失败: {error}")
            messagebox.showerror("加载失败", error)
            return
        _logger.info(f"加载成功: {len(chapters)} 章，耗时 {elapsed*1000:.0f}ms")
        self.chapters = chapters
        self.current_file = path
        self.searcher = NovelSearcher(chapters)
        self.chapter_index_map = {c.index: c for c in chapters}
        self.var_file.set(f"{os.path.basename(path)}  |  共 {len(chapters)} 章")
        self._set_status(f"加载完成: {len(chapters)} 个章节已建立索引")
        self.on_clear()
        _logger.info("开始重建章节目录")
        list_t0 = time.perf_counter()
        self._rebuild_chapter_list()
        log_perf("重建章节目录", list_t0, f"共 {len(chapters)} 章")

    def _rebuild_chapter_list(self):
        if self._chapter_list_after_id is not None:
            self.after_cancel(self._chapter_list_after_id)
            self._chapter_list_after_id = None
        for row in self.chapter_tree.get_children():
            self.chapter_tree.delete(row)
        self._chapter_list_index = 0
        self._chapter_list_step()

    def _chapter_list_step(self, batch: int = 100):
        end = min(self._chapter_list_index + batch, len(self.chapters))
        for ch in self.chapters[self._chapter_list_index : end]:
            self.chapter_tree.insert("", tk.END, iid=str(ch.index), values=(ch.title,))
        self._chapter_list_index = end
        if self._chapter_list_index < len(self.chapters):
            self._chapter_list_after_id = self.after(1, self._chapter_list_step)
        else:
            self._chapter_list_after_id = None

    def _filter_chapters(self):
        q = self.var_ch_filter.get().strip()
        if not q:
            self._rebuild_chapter_list()
            return
        for row in self.chapter_tree.get_children():
            self.chapter_tree.delete(row)
        ql = q.lower()
        for ch in self.chapters:
            if ql in ch.title.lower():
                self.chapter_tree.insert("", tk.END, iid=str(ch.index), values=(ch.title,))

    def _on_chapter_select(self):
        sel = self.chapter_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        self._show_chapter(idx, self.var_query.get())

    def on_search(self):
        if not self.searcher:
            messagebox.showinfo("提示", "请先加载一本小说")
            return
        kw = self.var_query.get()
        if not kw.strip():
            return
        if self._feed_after_id is not None:
            self.after_cancel(self._feed_after_id)
            self._feed_after_id = None
        self._cancel_event = threading.Event()
        self._set_search_running(True)
        self._set_status("正在检索…")
        _logger.info(f"UI 触发搜索: '{kw}'")

        cancel_ev = self._cancel_event

        def progress(ch_idx, total):
            self.after(0, lambda: self._set_status(f"正在检索… ({ch_idx}/{total})"))

        def worker():
            t0 = time.perf_counter()
            try:
                hits = self.searcher.search(
                    kw,
                    case_sensitive=self.var_case.get(),
                    fuzzy=self.var_fuzzy.get(),
                    context=int(self.var_context.get()),
                    max_hits=self.MAX_HITS,
                    cancel_event=cancel_ev,
                    progress_callback=progress,
                )
                elapsed = time.perf_counter() - t0
                if cancel_ev.is_set():
                    self.after(0, lambda: self._on_search_done(kw, hits, cancelled=True, elapsed=elapsed))
                else:
                    self.after(0, lambda: self._on_search_done(kw, hits, cancelled=False, elapsed=elapsed))
            except Exception as e:
                self.after(0, lambda: self._on_search_error(str(e)))

        threading.Thread(target=worker, daemon=True, name="search").start()

    def on_cancel(self):
        if self._cancel_event is not None:
            self._cancel_event.set()
            self._set_status("请求取消中…")
            _logger.warning("用户请求取消搜索")

    def _on_search_error(self, msg: str):
        self._set_search_running(False)
        self._set_status(f"检索失败: {msg}")
        _logger.error(f"检索失败: {msg}")

    def _on_search_done(self, kw: str, hits: List[SearchHit], cancelled: bool, elapsed: float):
        self._set_search_running(False)
        status = "取消" if cancelled else "完成"
        _logger.info(f"搜索{status}: '{kw}' 命中 {len(hits)} 条，耗时 {elapsed*1000:.1f}ms")
        self._set_status("正在整理结果…")
        self.after(0, lambda: self._build_feed(kw, hits, cancelled))

    def _build_feed(self, kw: str, hits: List[SearchHit], cancelled: bool):
        t0 = time.perf_counter()
        grouped: dict = {}
        for h in hits:
            grouped.setdefault(h.chapter_index, {"title": h.chapter_title, "count": 0, "first": h.snippet})
            grouped[h.chapter_index]["count"] += 1

        chapter_indices = sorted(grouped.keys())
        total_chapters = len(chapter_indices)
        self._feed_grouped = grouped
        self._feed_chapter_indices = chapter_indices
        self._feed_total_hits = len(hits)
        self._feed_total_chapters = total_chapters
        self._feed_kw = kw
        self._feed_cancelled = cancelled
        self._feed_index = 0
        self._feed_first_cidx = chapter_indices[0] if chapter_indices else None

        for row in self.tree.get_children():
            self.tree.delete(row)

        log_perf("整理搜索结果", t0, f"{len(grouped)} 个章节分组")
        _logger.info(f"开始分批渲染 {total_chapters} 个章节到 Treeview")
        self._feed_step()

    def _tree_select_safe(self, tree, iid):
        try:
            tree.blockSignals(True)
            tree.selection_set(iid)
            tree.see(iid)
        except Exception as e:
            _logger.warning(f"Treeview 选中失败 iid={iid}: {e}")
        finally:
            try:
                tree.blockSignals(False)
            except Exception:
                pass

    def _feed_step(self):
        BATCH = 50
        if self._feed_index >= len(self._feed_chapter_indices):
            extra = "（已达上限，可能还有更多章节）" if self._feed_total_hits >= self.MAX_HITS else ""
            prefix = "已取消，部分结果" if self._feed_cancelled else "检索完成"
            self._set_status(
                f"{prefix}：关键字 “{self._feed_kw}” 共 {self._feed_total_hits} 处匹配{extra}，分布于 {self._feed_total_chapters} 章"
            )
            _logger.info(f"Treeview 渲染完成：共 {self._feed_total_chapters} 个章节")
            self.progress.stop()
            if self._feed_first_cidx is not None:
                first_iid = f"chapter_{self._feed_first_cidx}"
                self._tree_select_safe(self.tree, first_iid)
                try:
                    _logger.info(f"准备预览首个章节: index={self._feed_first_cidx}")
                    self._show_chapter(self._feed_first_cidx, self._feed_kw)
                except Exception as e:
                    _logger.exception(f"预览章节异常: {e}")
            self._feed_after_id = None
            return

        end = min(self._feed_index + BATCH, len(self._feed_chapter_indices))
        for i in range(self._feed_index, end):
            cidx = self._feed_chapter_indices[i]
            info = self._feed_grouped[cidx]
            display_title = info["title"]
            prefix = f"第{cidx}章 [{info['count']}处] "
            try:
                self.tree.insert(
                    "",
                    tk.END,
                    iid=f"chapter_{cidx}",
                    values=(i + 1, prefix + display_title, info["first"]),
                    tags=(str(cidx), "chapter"),
                )
            except tk.TclError as e:
                _logger.warning(f"插入 Treeview 行失败 iid=chapter_{cidx}: {e}")
        self._feed_index = end
        self._set_status(
            f"正在渲染结果… {self._feed_index}/{self._feed_total_chapters}"
        )
        self._feed_after_id = self.after(1, self._feed_step)

    def on_clear(self):
        if self._feed_after_id is not None:
            self.after_cancel(self._feed_after_id)
            self._feed_after_id = None
        self.progress.stop()
        try:
            for row in self.tree.get_children():
                self.tree.delete(row)
        except Exception:
            pass
        try:
            self.txt_view.configure(state=tk.NORMAL)
            self.txt_view.delete("1.0", tk.END)
            self.txt_view.configure(state=tk.DISABLED)
        except Exception:
            pass
        self._set_status("已清除搜索结果")

    def _show_current_chapter(self):
        sel = self.tree.selection()
        if not sel:
            return
        item = sel[0]
        tags = self.tree.item(item, "tags") or ()
        for t in tags:
            if t.isdigit():
                self._show_chapter(int(t), self.var_query.get())
                return
        values = self.tree.item(item, "values")
        if values:
            title = values[1] if len(values) > 1 else ""
            for ch in self.chapters:
                if ch.title == title:
                    self._show_chapter(ch.index, self.var_query.get())
                    return

    def _show_chapter(self, chapter_index: int, keyword: str):
        ch = self.chapter_index_map.get(chapter_index)
        if not ch:
            _logger.warning(f"_show_chapter: 未找到 index={chapter_index} 的章节")
            return
        if self._current_preview_idx == chapter_index and self._current_preview_kw == keyword:
            _logger.debug(f"跳过重复预览: 章节 {chapter_index}")
            return
        self._current_preview_idx = chapter_index
        self._current_preview_kw = keyword
        _logger.info(f"开始预览章节: index={chapter_index}, title='{ch.title}', 长度={len(ch.text)}")
        t0 = time.perf_counter()
        self.txt_view.configure(state=tk.NORMAL)
        self.txt_view.delete("1.0", tk.END)
        self.txt_view.tag_remove("hl", "1.0", tk.END)
        self.txt_view.tag_configure("hl", background="#fff2a8", foreground="#b8860b")
        self.txt_view.insert(tk.END, f"【{ch.title}】\n\n")
        self.txt_view.configure(state=tk.DISABLED)
        self._tree_select_safe(self.chapter_tree, str(chapter_index))

        def feed_text(text, kw, pos=0, chunk=8000):
            self.txt_view.configure(state=tk.NORMAL)
            end = min(pos + chunk, len(text))
            self.txt_view.insert(tk.END, text[pos:end])
            self.txt_view.configure(state=tk.DISABLED)
            if end < len(text):
                self.after(1, lambda: feed_text(text, kw, end, chunk))
            else:
                self.txt_view.configure(state=tk.NORMAL)
                if kw:
                    try:
                        self._highlight_full(kw)
                    except Exception as e:
                        _logger.warning(f"高亮异常: {e}")
                self.txt_view.see("1.0")
                self.txt_view.configure(state=tk.DISABLED)
                log_perf("章节预览渲染", t0, f"章节 {chapter_index}，共 {len(text)} 字")

        feed_text(ch.text, keyword)

    def _highlight_full(self, keyword: str):
        text_widget = self.txt_view
        text_widget.tag_remove("hl", "1.0", tk.END)
        if not keyword:
            return
        end_idx = text_widget.index("end-1c")
        idx = "1.0"
        count = 0
        MAX_HIGHLIGHT = 5000
        while True:
            pos = text_widget.search(keyword, idx, nocase=not self.var_case.get(), stopindex=end_idx)
            if not pos:
                break
            end = f"{pos}+{len(keyword)}c"
            text_widget.tag_add("hl", pos, end)
            idx = end
            count += 1
            if count >= MAX_HIGHLIGHT:
                break


if __name__ == "__main__":
    app = NovelSearchApp()
    app.mainloop()
