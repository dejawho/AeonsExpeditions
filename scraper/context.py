"""Assemble a lore pack for one expedition, ready to feed a story generator (template or LLM).

    python scraper/context.py --random                     # 4 random mages, battles 1-4
    python scraper/context.py --random --battles 5 --seed 7
    python scraper/context.py --mages "Brama,Xaxos" --nemeses "Rageborne,Blight Lord,Gate Witch,Maelstrom: Risen"
"""
import argparse
import json
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "db" / "aeons_end.sqlite"


def rows(con, sql, *args):
    cur = con.execute(sql, args)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def decode(d):
    for k, v in d.items():
        if isinstance(v, str) and v[:1] in "[{":
            try:
                d[k] = json.loads(v)
            except ValueError:
                pass
    return d


def draw(con, n_battles, rng):
    mages = [t for (t,) in con.execute("SELECT title FROM mages WHERE box NOT IN ('Promo Pack 1 (Digital)')")]
    nemeses = []
    for b in range(1, n_battles + 1):
        pool = [t for (t,) in con.execute(
            "SELECT nemesis FROM expedition_battles WHERE battle=? AND nemesis NOT IN (SELECT title FROM nemeses WHERE box='Promo')", (b,))]
        nemeses.append(rng.choice([p for p in pool if p not in nemeses]))
    return rng.sample(mages, 4), nemeses


def character_for(con, title):
    """Map a mage/nemesis page title to its curated character profile, if any."""
    for c in rows(con, "SELECT * FROM lore_characters"):
        if title in json.loads(c["versions"]) or c["name"] == title:
            return decode(c)
    return None


def quotes_for(con, title, limit=4):
    """Mat quotes written on the page itself, then quotes that mention it (curated first)."""
    own = rows(con, "SELECT speaker, text FROM lore_texts WHERE page=? AND source IN ('story','mention','mat_quote') LIMIT 2", title)
    about = rows(con, """SELECT l.page, l.speaker, l.text FROM mentions m JOIN lore_texts l ON l.id=m.lore_id
                         WHERE m.target=? AND l.page!=? ORDER BY m.via='curated' DESC, length(l.text) DESC LIMIT ?""",
                 title, title, limit)
    return {"own": own, "about": about}


def build(con, mage_titles, nemesis_titles):
    pack = {"mages": [], "battles": [], "era": None, "era_bridges": [], "story_kit": {}}
    era_votes = Counter()
    for t in mage_titles:
        m = rows(con, "SELECT title, box, epithet, ability_name, ability_effect FROM mages WHERE title=?", t)
        prof = character_for(con, t)
        pack["mages"].append({"card": m[0] if m else {"title": t}, "profile": prof, "quotes": quotes_for(con, t, 2)})
        if prof:
            era_votes.update(prof["eras"])
    for i, t in enumerate(nemesis_titles, 1):
        n = rows(con, "SELECT title, box, life, difficulty, unleash FROM nemeses WHERE title=?", t)
        lore = rows(con, "SELECT * FROM nemesis_lore WHERE title=?", t)
        lore = decode(lore[0]) if lore else None
        if lore:
            era_votes[lore["era"]] += 2  # nemeses set the scene more than mages do
        pack["battles"].append({"battle": i, "nemesis": n[0] if n else {"title": t}, "lore": lore,
                                "quotes": quotes_for(con, t, 3)})
    if era_votes:
        era_id = era_votes.most_common(1)[0][0]
        pack["era"] = decode(rows(con, "SELECT * FROM lore_eras WHERE id=?", era_id)[0]) if era_id in {
            r for (r,) in con.execute("SELECT id FROM lore_eras")} else None
        eras = {e for e in era_votes if e not in ("all", "unknown")}
        if len(eras) > 1:
            kit = json.loads(con.execute("SELECT value FROM story_kit WHERE key='era_bridges'").fetchone()[0])
            pack["era_bridges"] = kit["bridges"]
    era_key = pack["era"]["id"] if pack["era"] else "new_gravehold"
    kit = {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM story_kit")}
    pack["story_kit"] = {
        "style": kit["style"], "arc": kit["arc"],
        "missions": [m for m in kit["missions"] if era_key in m["eras"]] or kit["missions"],
        "quest_givers": kit["quest_givers"].get(era_key, []),
        "settings": kit["settings"].get(era_key, []),
        "twists": kit["twists"], "loss_rescuers": kit["loss_rescuers"],
    }
    return pack


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mages", default="")
    ap.add_argument("--nemeses", default="")
    ap.add_argument("--random", action="store_true")
    ap.add_argument("--battles", type=int, default=4)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    con = sqlite3.connect(DB)
    if a.random:
        mages, nemeses = draw(con, a.battles, random.Random(a.seed))
    else:
        mages = [m.strip() for m in a.mages.split(",") if m.strip()]
        nemeses = [n.strip() for n in a.nemeses.split(",") if n.strip()]
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(build(con, mages, nemeses), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
