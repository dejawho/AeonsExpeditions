"""Aeon's Expeditions web server: the generator API plus the React frontend.

No accounts, no sessions, no saved games on the server: expeditions are generated on request
(deterministically from their settings / share code) and the browser keeps the saves. The one thing the
server stores is the AI-written stories, by share code (backend/store.py, AI_STORE), so a code always
opens with the same AI story.

    GET  /api/health
    GET  /api/catalog          boxes (with wave, type, what they contain), option limits, data version
    POST /api/generate         settings -> {expedition, story, ai_story (the stored AI story of this code, or null)}
    POST /api/defeat-draw      {code, path, source, level, taken} -> the card added to the Barracks after a defeat
    POST /api/rewrite          {code, provider} -> NDJSON stream: progress, then the story rewritten by an LLM
    GET  /api/codes/{code}     share code -> settings (+ whether the card data changed since)
    GET  /api/images           card title -> [slug, kind, width, height] for the local card images
    GET  /images/{full|thumb}/<slug>.webp   local copies of the wiki card images (scraper/fetch_images.py)
    GET  /*                    the built React app (frontend/dist)
"""
import json
import logging
import mimetypes
import os
import queue
import sqlite3
import sys
import threading
import time
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))

import ai_story  # noqa: E402
from generate_expedition import DB, DEFEAT_SOURCES, defeat_draw, resolve_settings  # noqa: E402
from make_expedition import make  # noqa: E402
from shareable import box_order, decode  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
from store import StoryStore  # noqa: E402

DIST = Path(os.environ.get("FRONTEND_DIST", ROOT / "frontend" / "dist"))
IMAGES = Path(os.environ.get("IMAGES_DIR", ROOT / "data" / "images"))
# python:3.12-slim has no /etc/mime.types and Python 3.12 does not know .webp: without this the
# card images would be served as text/plain
mimetypes.add_type("image/webp", ".webp")
AI_DAILY_LIMIT = int(os.environ.get("AI_DAILY_LIMIT", "30"))  # paid rewrites per day, for the whole server
stories = StoryStore(os.environ.get("AI_STORE", ROOT / "data" / "state" / "ai_stories.sqlite"))
log = logging.getLogger("aeons")
app = FastAPI(title="Aeon's Expeditions", docs_url="/api/docs", openapi_url="/api/openapi.json")


def db():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def data_version(con):
    return int(con.execute("SELECT value FROM meta WHERE key='data_version'").fetchone()[0])


class Settings(BaseModel):
    players: int = Field(2, ge=1, le=4)
    battles: int = Field(4, ge=4, le=5)
    forks: Optional[int] = Field(None, ge=1, le=2)
    boxes: list[str] = []
    xaxos_outcast: bool = False
    friends_foes: bool = False
    campaign_mechanics: bool = False
    seed: Optional[int] = Field(None, ge=0, le=0xFFFFFFFF)


@app.get("/api/health")
def health():
    with db() as con:
        return {"status": "ok", "data_version": data_version(con)}


@app.get("/api/catalog")
def catalog():
    with db() as con:
        con.row_factory = sqlite3.Row
        counts = {}
        for table, key in (("mages", "mages"), ("nemeses", "nemeses"), ("supply_cards", "player_cards"),
                           ("treasures", "treasures"), ("friends", "friends"), ("foes", "foes")):
            for row in con.execute(f"SELECT value AS box, COUNT(*) AS n FROM {table}, json_each({table}.boxes) GROUP BY value"):
                counts.setdefault(row["box"], {})[key] = row["n"]
        boxes = {r["title"]: dict(r) for r in con.execute("SELECT title, wave, type, first_release FROM boxes")}
        ordered = [{**boxes[t], "contents": counts.get(t, {})} for t in box_order() if t in boxes]
        return {"boxes": [b for b in ordered if b["contents"]], "data_version": data_version(con),
                "limits": {"players": [1, 4], "battles": [4, 5], "forks": [1, 2]},
                "ai": [{"id": p.id, "label": p.label, "model": p.model} for p in llm.providers().values()]}


@app.post("/api/generate")
def generate(settings: Settings):
    known = set(box_order())
    unknown = [b for b in settings.boxes if b not in known]
    if unknown:
        raise HTTPException(422, f"unknown boxes: {unknown}")
    s = resolve_settings(**settings.model_dump())
    try:
        with db() as con:
            expedition, story = make(s, con)
    except SystemExit as e:  # the generator's "not enough content" exit
        raise HTTPException(422, str(e))
    stored = stories.first(expedition["share_code"])
    return {"expedition": expedition, "story": story, "ai_story": stored["story"] if stored else None}


class DefeatDraw(BaseModel):
    code: str = Field(max_length=64)
    path: list[str] = Field(min_length=1, max_length=8)  # battles of the route so far, ending with the lost one
    source: str
    level: Optional[int] = Field(None, ge=1, le=4)  # for source "treasure"
    taken: list[str] = Field([], max_length=64)  # cards already added after earlier defeats


@app.post("/api/defeat-draw")
def draw_after_defeat(req: DefeatDraw):
    if req.source not in DEFEAT_SOURCES:
        raise HTTPException(422, f"source must be one of {', '.join(DEFEAT_SOURCES)}")
    try:
        settings, _ = decode(req.code)
    except (ValueError, IndexError) as e:
        raise HTTPException(400, f"invalid share code: {e}")
    try:
        with db() as con:
            return defeat_draw(con, resolve_settings(**settings), req.path, req.source, req.level, set(req.taken))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except LookupError as e:
        raise HTTPException(409, str(e))
    except SystemExit as e:
        raise HTTPException(422, str(e))


class RewriteRequest(BaseModel):
    code: str = Field(max_length=64)
    provider: str
    new_version: bool = False  # write a new story even if one is stored, and replace it


class Rewrites:
    """The daily quota of paid rewrites (in memory: it restarts with the server) and a lock so the
    NAS runs one rewrite at a time."""

    def __init__(self):
        self.day, self.count = date.today(), 0
        self.lock, self.run_lock = threading.Lock(), threading.Lock()

    def take_quota(self):
        with self.lock:
            if self.day != date.today():
                self.day, self.count = date.today(), 0
            if self.count >= AI_DAILY_LIMIT:
                return False
            self.count += 1
            return True


rewrites = Rewrites()


def ndjson(obj):
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def rewrite_job(provider, exp, story, events, new_version=False):
    """Runs in a thread: the call, the checks, the merge. Reports through the `events` queue."""
    try:
        bundle = ai_story.build_bundle(exp, story)
        with rewrites.run_lock:
            done = stories.get(exp["share_code"], provider.id)  # written while this request waited its turn
            if done and not new_version:
                events.put(("done", done))
                return
            events.put(("started", None))
            text, meta = provider.complete(ai_story.SYSTEM, ai_story.user_prompt(bundle),
                                           lambda n: events.put(("progress", n)))
        try:
            reply = json.loads(text)
        except ValueError:
            raise llm.ProviderError("the reply was not valid JSON")
        new, report = ai_story.merge(exp, story, bundle, reply)
        summary = ai_story.summary(report)
        log.info("rewrite %s by %s: %s", exp["share_code"], meta["model"], summary)
        if not summary["rewritten_chapters"]:
            raise llm.ProviderError("no chapter passed the checks, the original story is kept")
        new["author"] = {"provider": provider.id, "label": provider.label, "model": meta["model"],
                         "rewritten": summary["rewritten_chapters"], "chapters": summary["total_chapters"],
                         "usage": meta["usage"], "cost_usd": llm.cost(meta["model"], meta["usage"])}
        result = {"type": "done", "story": new, "report": summary}
        stories.put(exp["share_code"], provider.id, meta["model"], ai_story.PROMPT_VERSION, result,
                    replace=new_version)
        events.put(("done", stories.get(exp["share_code"], provider.id) or result))
    except llm.ProviderError as e:
        events.put(("error", str(e)))
    except Exception:  # noqa: BLE001 - report it, never leave the stream hanging
        log.exception("rewrite failed")
        events.put(("error", "the rewrite failed on the server"))


@app.post("/api/rewrite")
def rewrite(req: RewriteRequest):
    provider = llm.providers().get(req.provider)
    if not provider:
        raise HTTPException(404, f"AI provider not enabled on this server: {req.provider}")
    try:
        settings, _ = decode(req.code)
    except (ValueError, IndexError) as e:
        raise HTTPException(400, f"invalid share code: {e}")
    try:
        with db() as con:  # the story is rebuilt here from the code: the browser's copy is never trusted
            exp, story = make(resolve_settings(**settings), con)
    except SystemExit as e:
        raise HTTPException(422, str(e))
    cached = stories.get(exp["share_code"], provider.id)
    if cached and not req.new_version:
        return StreamingResponse(iter([ndjson(cached)]), media_type="application/x-ndjson")
    if provider.id != "fake" and not rewrites.take_quota():
        raise HTTPException(429, f"the daily limit of {AI_DAILY_LIMIT} AI rewrites is reached")

    events = queue.Queue()
    # the thread finishes even if the browser goes away: the result is stored, the call is not wasted
    threading.Thread(target=rewrite_job, args=(provider, exp, story, events, req.new_version), daemon=True).start()
    expected = len(json.dumps({k: story[k] for k in ("prologue", "chapters", "epilogues")}, ensure_ascii=False))

    def stream():
        yield ndjson({"type": "queued", "provider": provider.label, "expected_chars": expected})
        received, last = 0, 0.0
        while True:
            try:
                kind, value = events.get(timeout=5)
            except queue.Empty:
                yield ndjson({"type": "waiting", "chars": received})  # keeps proxies from closing the connection
                continue
            if kind == "started":
                yield ndjson({"type": "started"})
            elif kind == "progress":
                received += value
                if time.monotonic() - last > 0.5:
                    last = time.monotonic()
                    yield ndjson({"type": "progress", "chars": received})
            elif kind == "done":
                yield ndjson(value)
                return
            else:
                yield ndjson({"type": "error", "message": value})
                return

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.get("/api/codes/{code}")
def read_code(code: str):
    try:
        settings, version = decode(code)
    except (ValueError, IndexError) as e:
        raise HTTPException(400, f"invalid share code: {e}")
    with db() as con:
        current = data_version(con)
    return {"settings": settings, "data_version": version, "current_data_version": current,
            "data_changed": version != current}


@lru_cache(maxsize=1)
def image_manifest():
    path = IMAGES / "manifest.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {t: [m["slug"], m["kind"], m["w"], m["h"]] for t, m in data.items()}


@app.get("/api/images")
def images():
    return image_manifest()


class CachedImages(StaticFiles):
    """Card images never change for a given slug: let browsers keep them for a week."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=604800"
        return response


if IMAGES.exists():
    app.mount("/images", CachedImages(directory=IMAGES), name="images")


# --- frontend (single-page app) -------------------------------------------------
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith(("api/", "images/")):
        raise HTTPException(404)
    file = DIST / path
    if path and file.is_file() and DIST in file.resolve().parents:
        return FileResponse(file)
    index = DIST / "index.html"
    if not index.exists():
        raise HTTPException(503, "frontend not built: run `npm run build` in frontend/")
    return FileResponse(index)
