"""Download every main-namespace page of the Aeon's End wiki via the MediaWiki API.

Output: data/raw/pages.jsonl  (one JSON object per page: title, pageid, wikitext, categories)
        data/raw/redirects.json  (redirect title -> target title)
        data/raw/siteinfo.json

Re-running is cheap: the crawl is resumable and skips pages already stored with
the same revision id.
"""
import json
import sys
import time
from pathlib import Path

import requests

API = "https://aeonsend.wiki.gg/api.php"
UA = "AeonsExpeditionsLoreBot/0.1 (personal non-commercial fan project)"
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
BATCH = 50  # API maximum of titles per content request for normal users
DELAY = 1.0  # seconds between requests, to be polite

session = requests.Session()
session.headers["User-Agent"] = UA


def api(params):
    params = {**params, "format": "json", "formatversion": "2"}
    for attempt in range(5):
        try:
            r = session.get(API, params=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            return data
        except (requests.RequestException, ValueError) as e:
            wait = 5 * (attempt + 1)
            print(f"  retry in {wait}s: {e}", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"API failed repeatedly for {params}")


def list_titles():
    """All non-redirect titles in namespace 0, plus the redirect map."""
    titles, redirects = [], {}
    cont = {}
    while True:
        d = api({"action": "query", "list": "allpages", "apnamespace": 0,
                 "apfilterredir": "nonredirects", "aplimit": "max", **cont})
        titles += [p["title"] for p in d["query"]["allpages"]]
        if "continue" not in d:
            break
        cont = d["continue"]
        time.sleep(DELAY)
    cont = {}
    while True:
        d = api({"action": "query", "generator": "allredirects", "garnamespace": 0,
                 "garlimit": "max", "redirects": 1, **cont})
        for r in d["query"].get("redirects", []):
            redirects[r["from"]] = r["to"]
        if "continue" not in d:
            break
        cont = d["continue"]
        time.sleep(DELAY)
    return titles, redirects


def fetch_batch(titles):
    d = api({"action": "query", "titles": "|".join(titles),
             "prop": "revisions|categories|pageimages",
             "rvprop": "ids|timestamp|content", "rvslots": "main",
             "cllimit": "max", "clshow": "!hidden",
             "piprop": "original"})
    out = []
    for p in d["query"]["pages"]:
        if p.get("missing"):
            continue
        rev = p["revisions"][0]
        out.append({
            "pageid": p["pageid"],
            "title": p["title"],
            "revid": rev["revid"],
            "timestamp": rev["timestamp"],
            "wikitext": rev["slots"]["main"]["content"],
            "categories": [c["title"].removeprefix("Category:") for c in p.get("categories", [])],
            "image": p.get("original", {}).get("source"),
        })
    # categories can be split across continuation for big batches; fill gaps
    if "continue" in d:
        missing_cats = {o["title"] for o in out if not o["categories"]}
        for t in missing_cats:
            dd = api({"action": "query", "titles": t, "prop": "categories",
                      "cllimit": "max", "clshow": "!hidden"})
            cats = dd["query"]["pages"][0].get("categories", [])
            for o in out:
                if o["title"] == t:
                    o["categories"] = [c["title"].removeprefix("Category:") for c in cats]
            time.sleep(DELAY / 2)
    return out


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    info = api({"action": "query", "meta": "siteinfo", "siprop": "general|rightsinfo|statistics"})
    (RAW / "siteinfo.json").write_text(json.dumps(info["query"], indent=2), encoding="utf-8")

    print("Listing titles...")
    titles, redirects = list_titles()
    (RAW / "redirects.json").write_text(json.dumps(redirects, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(titles)} pages, {len(redirects)} redirects")

    pages_file = RAW / "pages.jsonl"
    have = {}
    if pages_file.exists():
        for line in pages_file.read_text(encoding="utf-8").splitlines():
            p = json.loads(line)
            have[p["title"]] = p
    todo = [t for t in titles if t not in have]
    print(f"{len(have)} cached, {len(todo)} to fetch")

    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        for p in fetch_batch(chunk):
            have[p["title"]] = p
        print(f"  {min(i + BATCH, len(todo))}/{len(todo)}")
        # checkpoint so an interrupted crawl can resume
        with pages_file.open("w", encoding="utf-8") as f:
            for p in have.values():
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        time.sleep(DELAY)

    keep = set(titles)
    with pages_file.open("w", encoding="utf-8") as f:
        for t in sorted(have):
            if t in keep:
                f.write(json.dumps(have[t], ensure_ascii=False) + "\n")
    print("done")


if __name__ == "__main__":
    main()
