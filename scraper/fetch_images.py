"""Download a local copy of the wiki image of every card the app can show, and make web versions.

    data/raw/images/<file>            untouched originals (cache: re-running only downloads what is missing)
    data/images/full/<slug>.webp      max 720 px on the long side (zoomed view)
    data/images/thumb/<slug>.webp     max 160 px (chips in lists)
    data/images/manifest.json         {title: {slug, kind, w, h, source}}

Image URLs come from the crawl (pages.image = the page's main image: card face, or mat front for
mages / nemeses / friends / foes). Card art is (c) Indie Boards & Cards: keep this copy private.
"""
import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
LORE_DB = ROOT / "data" / "db" / "aeons_end.sqlite"
EXP_DB = ROOT / "data" / "db" / "expedition.sqlite"
RAW = ROOT / "data" / "raw" / "images"
OUT = ROOT / "data" / "images"
UA = "AeonsExpeditionsLoreBot/0.1 (personal non-commercial fan project)"
DELAY = 0.5
SIZES = {"full": 720, "thumb": 160}
KINDS = {  # expedition.sqlite table -> kind shown in the app
    "mages": "mage", "nemeses": "nemesis", "supply_cards": "card", "treasures": "treasure",
    "banners": "card", "friends": "friend", "foes": "foe",
}


def slugify(title, taken):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "card"
    if slug in taken and taken[slug] != title:
        slug += "-" + hashlib.sha1(title.encode()).hexdigest()[:6]
    taken[slug] = title
    return slug


def download(session, url, dest):
    for attempt in range(5):
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            if not r.headers.get("content-type", "").startswith("image/"):
                raise ValueError(f"not an image: {r.headers.get('content-type')}")
            dest.write_bytes(r.content)
            return True
        except (requests.RequestException, ValueError) as e:
            print(f"  retry {attempt + 1} {url}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    return False


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        (OUT / size).mkdir(parents=True, exist_ok=True)
    images = dict(sqlite3.connect(LORE_DB).execute("SELECT title, image FROM pages WHERE image IS NOT NULL"))
    exp = sqlite3.connect(EXP_DB)
    wanted = {}
    for table, kind in KINDS.items():
        for (title,) in exp.execute(f"SELECT title FROM {table} ORDER BY title"):
            if title in images:
                wanted.setdefault(title, kind)

    session = requests.Session()
    session.headers["User-Agent"] = UA
    manifest, taken, failed = {}, {}, []
    for i, (title, kind) in enumerate(sorted(wanted.items()), 1):
        url = images[title].split("?")[0]
        raw = RAW / unquote(Path(urlparse(url).path).name)
        if not raw.exists():
            if not download(session, url, raw):
                failed.append(title)
                continue
            time.sleep(DELAY)
        slug = slugify(title, taken)
        try:
            with Image.open(raw) as im:
                im = im.convert("RGB")
                w, h = im.size
                for size, limit in SIZES.items():
                    target = OUT / size / f"{slug}.webp"
                    if not target.exists():
                        copy = im.copy()
                        copy.thumbnail((limit, limit), Image.LANCZOS)
                        copy.save(target, "WEBP", quality=80 if size == "full" else 72, method=6)
        except OSError as e:
            print(f"  cannot read {raw.name}: {e}", file=sys.stderr)
            failed.append(title)
            continue
        manifest[title] = {"slug": slug, "kind": kind, "w": w, "h": h, "source": url}
        if i % 50 == 0:
            print(f"  {i}/{len(wanted)}")

    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=0), encoding="utf-8")
    total = sum(f.stat().st_size for f in OUT.rglob("*.webp"))
    print(f"{len(manifest)} images ready ({total / 1e6:.1f} MB), {len(failed)} failed: {failed[:10]}")


if __name__ == "__main__":
    main()
