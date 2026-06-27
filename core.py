# -*- coding: utf-8 -*-
"""小说检索核心逻辑（无 Tkinter 依赖，可用于桌面版与 Web 版）。"""
import json
import logging
import os
import re
import time
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

try:
    from ebooklib import epub
    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
    _HAS_EBOOKLIB = True
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except Exception:
    _HAS_EBOOKLIB = False


APP_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = os.path.join(APP_DIR, "saved_novels")
os.makedirs(SAVE_DIR, exist_ok=True)
INDEX_FILE = os.path.join(SAVE_DIR, "index.json")

logger = logging.getLogger("novel_core")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    logger.addHandler(_sh)


def log_perf(label: str, start: float, extra: str = ""):
    elapsed = time.perf_counter() - start
    logger.info(f"[PERF] {label} 耗时 {elapsed*1000:.1f}ms {extra}".rstrip())


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

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "source_file": self.source_file,
            "saved_at": self.saved_at,
            "chapters_count": len(self.chapters),
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
        logger.info(f"开始加载文件: {path}")
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
    def load_text(text: str) -> List[Chapter]:
        """从内存文本解析章节（Web 端上传后使用）。"""
        chapters: List[Chapter] = []
        pattern = re.compile(
            r"^\s*(第\s*[一二三四五六七八九十百千零\d]{1,8}\s*[章节回卷集篇部卷])"
            r"[\s：:．.\u3000]{0,4}(.{0,40})",
            re.MULTILINE,
        )
        matches = list(pattern.finditer(text))
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

    @staticmethod
    def _clean_html(html_text: str) -> str:
        try:
            soup = BeautifulSoup(html_text, "lxml")
        except Exception:
            soup = BeautifulSoup(html_text, "html.parser")
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
        for item in book.get_items_of_type(9):
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
        try:
            soup = BeautifulSoup(raw, "lxml")
        except Exception:
            soup = BeautifulSoup(raw, "html.parser")
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
        return NovelLoader.load_text(text)


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
        cancel_event=None,
        progress_callback=None,
    ) -> List[SearchHit]:
        keyword = keyword.strip()
        if not keyword:
            return []
        hits: List[SearchHit] = []
        cmp = str if case_sensitive else lambda s: s.lower()
        kw = cmp(keyword)

        total = len(self.chapters)
        for idx, ch in enumerate(self.chapters):
            if cancel_event is not None and cancel_event.is_set():
                break
            body = cmp(ch.text)
            if fuzzy:
                positions = self._fuzzy_find_all(body, kw)
            else:
                positions = self._find_all(body, kw)
            for pos in positions:
                if len(hits) >= max_hits:
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
