"""The only thing the server keeps: AI-written stories, by share code.

A share code always regenerates the same expedition and template story; storing the AI rewrite next to it
makes the code open with the same AI story too, on any device, and asking again costs nothing.
Saved games are not here: they stay in the players' browsers.

A code opens with its newest AI story. A second request for the same (code, provider) returns the stored story
instead of writing another, unless someone explicitly asks for a new version, which replaces it.
"""
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("aeons")

SCHEMA = """CREATE TABLE IF NOT EXISTS ai_stories (
    share_code TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version INTEGER NOT NULL,
    story TEXT NOT NULL,      -- the merged story JSON, as sent to the browser
    report TEXT NOT NULL,     -- ai_story.summary(): which chapters were rewritten / kept
    created_at TEXT NOT NULL,
    PRIMARY KEY (share_code, provider)
)"""


class StoryStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.ok = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as con:
                con.execute(SCHEMA)
        except (OSError, sqlite3.Error):
            # e.g. a volume the container user cannot write: AI stories still work, they are just not kept
            log.exception("cannot open the AI story store at %s", self.path)
            self.ok = False

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def _result(self, row):
        story, report = json.loads(row[0]), json.loads(row[1])
        return {"type": "done", "story": story, "report": report}

    def get(self, share_code, provider):
        if not self.ok:
            return None
        with self.connect() as con:
            row = con.execute("SELECT story, report FROM ai_stories WHERE share_code=? AND provider=?",
                              (share_code, provider)).fetchone()
        return self._result(row) if row else None

    def first(self, share_code):
        """The AI story a code opens with: the newest one written for it."""
        if not self.ok:
            return None
        with self.connect() as con:
            row = con.execute("SELECT story, report FROM ai_stories WHERE share_code=? ORDER BY created_at DESC LIMIT 1",
                              (share_code,)).fetchone()
        return self._result(row) if row else None

    def put(self, share_code, provider, model, prompt_version, result, replace=False):
        """replace=True: a new version asked for explicitly ("Write a new version") replaces the stored one."""
        if not self.ok:
            return
        try:
            with self.lock, self.connect() as con:
                con.execute(f"INSERT OR {'REPLACE' if replace else 'IGNORE'} INTO ai_stories VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (share_code, provider, model, prompt_version,
                             json.dumps(result["story"], ensure_ascii=False),
                             json.dumps(result["report"], ensure_ascii=False),
                             datetime.now(timezone.utc).isoformat(timespec="seconds")))
        except sqlite3.Error:
            log.exception("cannot store the AI story for %s", share_code)

    def count(self):
        if not self.ok:
            return None
        with self.connect() as con:
            return con.execute("SELECT COUNT(*) FROM ai_stories").fetchone()[0]
