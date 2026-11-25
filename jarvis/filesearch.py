"""Ask my files: "what does my lease say about pets?", "find my notes on the history essay".

Jarvis keeps a private search index of your documents (JARVIS_FILE_FOLDERS, default Documents and Desktop) in
data/files.db on this PC: plain text, notes, code, CSV, PDFs and Word files. A question finds the best passages
in the index, and only those few passages (with secrets hidden) go to the AI for the answer.
Files that live only in the cloud (OneDrive "online-only") are skipped, so indexing never downloads anything.
The index updates itself when Jarvis starts and every few hours; "index my files" does it now.
"""
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import config, privacy
from .tools import S, tool

DB_FILE = config.DATA_DIR / "files.db"
TEXT_TYPES = {".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".csv", ".log", ".ini", ".yaml", ".yml",
              ".bat", ".ps1", ".java", ".c", ".cpp", ".cs", ".sql", ".xml", ".rtf", ".tex"}
DOC_TYPES = {".pdf", ".docx"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "AppData", "$RECYCLE.BIN", ".cache"}
MAX_BYTES = 8 * 2**20
MAX_FILES = 20000
CHUNK_WORDS = 180
CLOUD_ONLY = 0x00400000 | 0x00001000  # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | FILE_ATTRIBUTE_OFFLINE
ANSWER_PROMPT = ("Answer {owner}'s question from these passages of his own files. Say which file the answer comes "
                 "from (by its name). If the passages don't answer it, say so plainly. Short and spoken, plain text.")
_lock = threading.Lock()
_indexing = threading.Event()


def _db():
    db = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    db.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, mtime REAL, size INTEGER)")
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(path UNINDEXED, name, text, tokenize='porter')")
    return db


def _read(path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:300])
    if ext == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    return path.read_text(encoding="utf-8", errors="ignore")


def _chunks(text):
    words = text.split()
    for i in range(0, len(words), CHUNK_WORDS - 30):  # a little overlap so answers aren't cut in half
        piece = " ".join(words[i:i + CHUNK_WORDS])
        if piece.strip():
            yield piece
        if i + CHUNK_WORDS >= len(words):
            break


def _wanted(entry):
    try:
        st = entry.stat()
    except OSError:
        return None
    attrs = getattr(st, "st_file_attributes", 0)
    if attrs & CLOUD_ONLY or st.st_size > MAX_BYTES or st.st_size == 0:
        return None
    return st


def _walk(folders):
    count = 0
    for folder in folders:
        root = Path(os.path.expandvars(os.path.expanduser(folder)))
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                p = Path(dirpath) / name
                if p.suffix.lower() in TEXT_TYPES | DOC_TYPES:
                    count += 1
                    if count > MAX_FILES:
                        return
                    yield p


def index(folders=None, progress=None):
    """Bring the index up to date. Returns (files added or updated, files removed)."""
    folders = folders or config.FILE_FOLDERS
    if _indexing.is_set():
        return (0, 0)
    _indexing.set()
    try:
        with _lock:
            db = _db()
            known = {p: (m, s) for p, m, s in db.execute("SELECT path, mtime, size FROM files")}
            seen, changed = set(), 0
            for p in _walk(folders):
                st = _wanted(p)
                if not st:
                    continue
                key = str(p)
                seen.add(key)
                if known.get(key) == (st.st_mtime, st.st_size):
                    continue
                try:
                    text = privacy.redact(_read(p))
                except Exception:
                    continue
                db.execute("DELETE FROM chunks WHERE path = ?", (key,))
                db.executemany("INSERT INTO chunks (path, name, text) VALUES (?, ?, ?)",
                               [(key, p.stem, c) for c in _chunks(text)])
                db.execute("INSERT OR REPLACE INTO files VALUES (?, ?, ?)", (key, st.st_mtime, st.st_size))
                changed += 1
                if changed % 50 == 0:
                    db.commit()
                    if progress:
                        progress(changed)
            gone = [p for p in known if p not in seen]
            for p in gone:
                db.execute("DELETE FROM chunks WHERE path = ?", (p,))
                db.execute("DELETE FROM files WHERE path = ?", (p,))
            db.commit()
            db.close()
            return changed, len(gone)
    finally:
        _indexing.clear()


def _query(question):
    """An FTS query from the meaningful words of a question."""
    stop = {"what", "does", "did", "the", "my", "about", "say", "says", "find", "where", "when", "which", "who", "how",
            "is", "are", "was", "were", "a", "an", "of", "in", "on", "for", "to", "and", "or", "do", "i", "me", "it",
            "that", "this", "there", "any", "file", "files", "document", "documents", "notes", "note", "with", "from"}
    words = [w for w in re.findall(r"[a-z0-9]{2,}", question.lower()) if w not in stop]
    return " OR ".join(f'"{w}"*' for w in words[:12])


def search(question, limit=6):
    q = _query(question)
    if not q or not DB_FILE.exists():
        return []
    with _lock:
        db = _db()
        try:
            rows = db.execute("SELECT path, name, snippet(chunks, 2, '', '', ' ... ', 60), bm25(chunks, 0.0, 4.0, 1.0) "
                              "FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks, 0.0, 4.0, 1.0) LIMIT ?",
                              (q, limit)).fetchall()
        finally:
            db.close()
    return [{"path": r[0], "name": r[1], "text": r[2]} for r in rows]


def _answer(question, hits):
    passages = "\n\n".join(f"[{Path(h['path']).name}]\n{h['text']}" for h in hits)
    content = privacy.redact(f"Question: {question}\n\nPassages:\n{passages}")
    system = ANSWER_PROMPT.format(owner=config.OWNER_NAME)
    import anthropic
    from . import local_brain, spend
    local = config.BRAIN == "local" or (config.BRAIN == "auto" and (local_brain.claude_resting() or spend.over_budget()))
    if not local:
        try:
            r = anthropic.Anthropic().messages.create(model=config.HELPER_MODEL, max_tokens=800,
                                                      output_config={"effort": "low"}, system=system,
                                                      messages=[{"role": "user", "content": content}])
            spend.record(r.model or config.HELPER_MODEL, r.usage, "ask my files")
            return next((b.text for b in r.content if b.type == "text"), "").strip()
        except anthropic.APIError as e:
            if config.BRAIN != "auto" or not local_brain.available():
                raise
            if isinstance(e, (anthropic.BadRequestError, anthropic.AuthenticationError, anthropic.APIConnectionError)):
                local_brain.rest_claude()
    body = {"model": config.LOCAL_MODEL, "stream": False, "options": {"num_predict": 200, "temperature": 0.2},
            "keep_alive": f"{local_brain.KEEP_LOADED_MINUTES}m",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content[:6000]}]}
    req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + "/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)["message"]["content"].strip()
    finally:
        local_brain.prompt_disturbed()


def ask(question):
    if not DB_FILE.exists():
        threading.Thread(target=index, daemon=True).start()
        return "I'm indexing your files for the first time, sir. Ask me again in a few minutes."
    hits = search(question)
    if not hits:
        return "I couldn't find anything about that in your files, sir."
    try:
        text = _answer(question, hits)
        return re.sub(r"^(?:File|Source):\s*(.+?)\s*\n+", r"From \1: ", text)  # small models put the file first
    except Exception:
        names = ", ".join(dict.fromkeys(Path(h["path"]).name for h in hits))
        return f"I found matches in {names}, but couldn't put an answer together right now."


def index_now():
    from .vitals import Progress
    p = Progress("INDEXING FILES", ["Scanning folders", "Reading documents", "Done"])
    p.step(0, ", ".join(config.FILE_FOLDERS))
    added, removed = index(progress=lambda n: p.step(1, f"{n} files read"))
    with _lock:
        db = _db()
        total = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        db.close()
    p.done(f"{total} files indexed")
    return f"Your files are indexed, sir: {total} documents, {added} new or changed since last time."


@tool("Search and answer questions from his own documents (Documents and Desktop: notes, PDFs, Word files, text, "
      "code). Use for 'what does my lease say about...', 'find my notes on...', 'which file has...'.",
      {"question": S("His question")}, ["question"])
def ask_my_files(question):
    return ask(question)


@tool("Update the index of his documents now (it also updates by itself every few hours).")
def index_my_files():
    return index_now()


def start():
    def loop():
        time.sleep(120)  # let Jarvis start up first
        while True:
            try:
                index()
            except Exception:
                pass
            time.sleep(4 * 3600)
    threading.Thread(target=loop, daemon=True, name="file-index").start()
