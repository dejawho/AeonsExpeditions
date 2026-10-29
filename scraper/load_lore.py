"""Validate the curated lore in lore/*.json and load it into the SQLite DB.

Tables: lore_eras, lore_events, lore_places, lore_factions, lore_concepts, lore_secrets,
        lore_characters, lore_relationships, nemesis_lore, friend_foe_lore, story_kit,
        lore_citations (entity -> wiki page), compendium_fts.
Also writes docs/LORE.md, a readable compendium generated from the same data.

Run standalone (python scraper/load_lore.py) or via build_db.py.
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LORE = ROOT / "lore"
DB = ROOT / "data" / "db" / "aeons_end.sqlite"
DOC = ROOT / "docs" / "LORE.md"
WIKI = "https://aeonsend.wiki.gg/wiki/"

SCHEMA = """
DROP TABLE IF EXISTS lore_eras; DROP TABLE IF EXISTS lore_events; DROP TABLE IF EXISTS lore_places;
DROP TABLE IF EXISTS lore_factions; DROP TABLE IF EXISTS lore_concepts; DROP TABLE IF EXISTS lore_secrets;
DROP TABLE IF EXISTS lore_characters; DROP TABLE IF EXISTS lore_relationships; DROP TABLE IF EXISTS nemesis_lore;
DROP TABLE IF EXISTS friend_foe_lore; DROP TABLE IF EXISTS story_kit; DROP TABLE IF EXISTS lore_citations;
DROP TABLE IF EXISTS compendium_fts;
CREATE TABLE lore_eras (id TEXT PRIMARY KEY, ord INTEGER, name TEXT, when_text TEXT, summary TEXT,
  boxes TEXT, tone TEXT);
CREATE TABLE lore_events (id INTEGER PRIMARY KEY, era TEXT, ord INTEGER, title TEXT, summary TEXT,
  characters TEXT, places TEXT, nemeses TEXT);
CREATE TABLE lore_places (id TEXT PRIMARY KEY, name TEXT, type TEXT, eras TEXT, summary TEXT,
  features TEXT, confidence TEXT);
CREATE TABLE lore_factions (id TEXT PRIMARY KEY, name TEXT, eras TEXT, summary TEXT, members TEXT);
CREATE TABLE lore_concepts (id TEXT PRIMARY KEY, name TEXT, summary TEXT);
CREATE TABLE lore_secrets (id TEXT PRIMARY KEY, title TEXT, how TEXT, text TEXT);
CREATE TABLE lore_characters (id TEXT PRIMARY KEY, name TEXT, kind TEXT, pronouns TEXT, epithets TEXT,
  versions TEXT, eras TEXT, affiliations TEXT, summary TEXT, traits TEXT, hooks TEXT);
CREATE TABLE lore_relationships (a TEXT, b TEXT, type TEXT, note TEXT);
CREATE TABLE nemesis_lore (title TEXT PRIMARY KEY, era TEXT, archetype TEXT, origin TEXT, signs TEXT,
  aftermath TEXT, hook TEXT, themes TEXT, teaser TEXT);
CREATE TABLE friend_foe_lore (title TEXT PRIMARY KEY, role TEXT, era TEXT, note TEXT);
CREATE TABLE story_kit (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE lore_citations (entity TEXT, entity_id TEXT, page TEXT, PRIMARY KEY (entity, entity_id, page));
CREATE VIRTUAL TABLE compendium_fts USING fts5(entity, entity_id, name, text);
"""


def load_json(name):
    return json.loads((LORE / name).read_text(encoding="utf-8"))


def j(v):
    return json.dumps(v, ensure_ascii=False)


def load(con):
    timeline, world = load_json("timeline.json"), load_json("world.json")
    chars, nems, kit = load_json("characters.json"), load_json("nemeses.json"), load_json("story_kit.json")

    titles = {t for (t,) in con.execute("SELECT title FROM pages")}
    redirects = dict(con.execute("SELECT alias, target FROM redirects"))
    nemesis_titles = {t for (t,) in con.execute("SELECT title FROM nemeses")}
    errors, warnings = [], []

    def page(t, where):
        t = redirects.get(t, t)
        if t not in titles:
            errors.append(f"{where}: unknown wiki page '{t}'")
            return None
        return t

    con.executescript(SCHEMA)

    def cite(entity, eid, sources):
        for s in sources:
            p = page(s, f"{entity}:{eid}")
            if p:
                con.execute("INSERT OR IGNORE INTO lore_citations VALUES (?,?,?)", (entity, eid, p))

    def fts(entity, eid, name, *texts):
        con.execute("INSERT INTO compendium_fts VALUES (?,?,?,?)",
                    (entity, eid, name, "\n".join(t for t in texts if t)))

    era_ids = {e["id"] for e in timeline["eras"]} | {"all", "unknown", "crossover"}
    for e in timeline["eras"]:
        con.execute("INSERT INTO lore_eras VALUES (?,?,?,?,?,?,?)", (
            e["id"], e["order"], e["name"], e["when"], e["summary"], j(e["boxes"]), j(e["tone"])))
        cite("era", e["id"], e["sources"])
        fts("era", e["id"], e["name"], e["summary"])
    for ev in timeline["events"]:
        if ev["era"] not in era_ids:
            errors.append(f"event '{ev['title']}': unknown era {ev['era']}")
        cur = con.execute("INSERT INTO lore_events (era,ord,title,summary,characters,places,nemeses) VALUES (?,?,?,?,?,?,?)", (
            ev["era"], ev["order"], ev["title"], ev["summary"], j(ev["characters"]), j(ev["places"]), j(ev["nemeses"])))
        cite("event", str(cur.lastrowid), ev["sources"])
        fts("event", str(cur.lastrowid), ev["title"], ev["summary"])
        for n in ev["nemeses"]:
            if n not in nemesis_titles:
                warnings.append(f"event '{ev['title']}': '{n}' is not a nemesis title")

    for p in world["places"]:
        con.execute("INSERT INTO lore_places VALUES (?,?,?,?,?,?,?)", (
            p["id"], p["name"], p["type"], j(p["eras"]), p["summary"], j(p.get("features", [])), p["confidence"]))
        cite("place", p["id"], p["sources"])
        fts("place", p["id"], p["name"], p["summary"], " ".join(p.get("features", [])))
    for f in world["factions"]:
        con.execute("INSERT INTO lore_factions VALUES (?,?,?,?,?)", (f["id"], f["name"], j(f["eras"]), f["summary"], j(f["members"])))
        cite("faction", f["id"], f["sources"])
        fts("faction", f["id"], f["name"], f["summary"])
    for c in world["concepts"]:
        con.execute("INSERT INTO lore_concepts VALUES (?,?,?)", (c["id"], c["name"], c["summary"]))
        cite("concept", c["id"], c["sources"])
        fts("concept", c["id"], c["name"], c["summary"])
    for s in world["secrets"]:
        con.execute("INSERT INTO lore_secrets VALUES (?,?,?,?)", (s["id"], s["title"], s["how"], s["text"]))
        cite("secret", s["id"], s["sources"])
        fts("secret", s["id"], s["title"], s["text"])
    con.execute("INSERT INTO story_kit VALUES ('open_questions', ?)", (j(world["open_questions"]),))

    char_ids = {c["id"] for c in chars["characters"]}
    for c in chars["characters"]:
        for v in c["versions"]:
            page(v, f"character:{c['id']} version")
        con.execute("INSERT INTO lore_characters VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            c["id"], c["name"], c["kind"], c.get("pronouns"), j(c.get("epithets", [])), j(c["versions"]),
            j(c["eras"]), j(c["affiliations"]), c["summary"], j(c["traits"]), j(c["hooks"])))
        for r in c["relationships"]:
            if r["with"] not in char_ids:
                warnings.append(f"character:{c['id']}: relationship target '{r['with']}' has no profile")
            con.execute("INSERT INTO lore_relationships VALUES (?,?,?,?)", (c["id"], r["with"], r["type"], r.get("note")))
        cite("character", c["id"], c["sources"] + c["versions"])
        fts("character", c["id"], c["name"], " ".join(c.get("epithets", [])), c["summary"], " ".join(c["hooks"]))

    seen = set()
    for n in nems["nemeses"]:
        if n["title"] not in nemesis_titles:
            errors.append(f"nemesis_lore: '{n['title']}' is not in the nemeses table")
        seen.add(n["title"])
        con.execute("INSERT INTO nemesis_lore VALUES (?,?,?,?,?,?,?,?,?)", (
            n["title"], n["era"], n["archetype"], n["origin"], j(n["signs"]), n["aftermath"], n["hook"], j(n["themes"]),
            n.get("teaser")))
        cite("nemesis", n["title"], n["sources"])
        fts("nemesis", n["title"], n["title"], n["archetype"], n["origin"], n["hook"], " ".join(n["signs"]))
    for missing in sorted(nemesis_titles - seen):
        warnings.append(f"nemesis '{missing}' has no nemesis_lore entry")
    for ff in nems["friends"] + nems["foes"]:
        page(ff["title"], f"friend_foe:{ff['title']}")
        con.execute("INSERT INTO friend_foe_lore VALUES (?,?,?,?)", (ff["title"], ff["role"], ff["era"], ff["note"]))
        cite(ff["role"], ff["title"], ff["sources"])

    for k, v in kit.items():
        if not k.startswith("_"):
            con.execute("INSERT INTO story_kit VALUES (?,?)", (k, j(v)))
    for b in kit["era_bridges"]["bridges"]:
        cite("era_bridge", b["id"], b["sources"])

    for w in warnings:
        print("warning:", w)
    if errors:
        for e in errors:
            print("ERROR:", e, file=sys.stderr)
        raise SystemExit(f"{len(errors)} lore validation error(s)")
    n_cit = con.execute("SELECT COUNT(*) FROM lore_citations").fetchone()[0]
    print(f"lore: {len(timeline['eras'])} eras, {len(timeline['events'])} events, {len(world['places'])} places, "
          f"{len(world['factions'])} factions, {len(chars['characters'])} characters, "
          f"{len(nems['nemeses'])} nemeses, {n_cit} citations")
    write_doc(timeline, world, chars, nems)


def link(t):
    return f"[{t}]({WIKI}{t.replace(' ', '_')})"


def write_doc(timeline, world, chars, nems):
    eras = {e["id"]: e for e in timeline["eras"]}
    out = ["# Aeon's End — Reconstructed Lore", "",
           "_Generated from `lore/*.json` by `scraper/load_lore.py`. Sources: [Aeon's End Wiki](https://aeonsend.wiki.gg/) (CC BY-SA 4.0)._", ""]
    out += ["## Timeline", ""]
    for e in sorted(timeline["eras"], key=lambda e: e["order"]):
        out += [f"### {e['order']}. {e['name']}", f"*{e['when']}* — boxes: {', '.join(e['boxes'])}", "", e["summary"], ""]
        for ev in sorted((x for x in timeline["events"] if x["era"] == e["id"]), key=lambda x: x["order"]):
            out.append(f"- **{ev['title']}** — {ev['summary']}")
        out.append("")
    out += ["## Places", ""] + [f"- **{p['name']}** ({p['type']}) — {p['summary']}" for p in world["places"]] + [""]
    out += ["## Factions", ""] + [f"- **{f['name']}** — {f['summary']}" for f in world["factions"]] + [""]
    out += ["## Concepts", ""] + [f"- **{c['name']}** — {c['summary']}" for c in world["concepts"]] + [""]
    out += ["## Characters", ""]
    for c in chars["characters"]:
        ep = f" — *{', '.join(c['epithets'])}*" if c.get("epithets") else ""
        out += [f"### {c['name']}{ep}", c["summary"], "",
                f"Eras: {', '.join(eras[x]['name'] if x in eras else x for x in c['eras'])}. "
                f"Versions: {', '.join(link(v) for v in c['versions']) or '—'}", ""]
    out += ["## Nemeses", ""]
    for n in nems["nemeses"]:
        out.append(f"- **{link(n['title'])}** ({n['archetype']}, {eras.get(n['era'], {}).get('name', n['era'])}) — "
                   f"{n['origin']} *Hook:* {n['hook']}")
    out += ["", "## Hidden texts", ""] + [f"- **{s['title']}** ({s['how']}): “{s['text']}”" for s in world["secrets"]]
    out += ["", "## Open questions", ""] + [f"- {q}" for q in world["open_questions"]] + [""]
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {DOC.relative_to(ROOT)}")


if __name__ == "__main__":
    con = sqlite3.connect(DB)
    load(con)
    con.commit()
    con.close()
