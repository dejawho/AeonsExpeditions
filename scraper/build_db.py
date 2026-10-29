"""Build data/db/aeons_end.sqlite from the raw crawl in data/raw/pages.jsonl.

Layers:
  pages            every wiki article (kind, box, categories, plain text)
  boxes / mages / nemeses / nemesis_cards / player_cards /
  friends_foes / friend_foe_cards / narrative_cards   typed game data
  lore_texts       every piece of narrative text (flavor, story quotes, campaign cards...)
  mentions         lore_text -> page links (explicit wiki links + name matches)
  characters       mage / nemesis / friend / foe / NPC identities grouped across versions
  character_quotes the wiki's curated "Character Quote" index of mat lore
  lore_fts         FTS5 index over lore_texts
  lore_* / nemesis_lore / story_kit   curated reconstruction from lore/*.json (see load_lore.py)
"""
import hashlib
import json
import re
import sqlite3
from pathlib import Path

import mwparserfromhell as mw

import load_lore
from wikitext import links, normalize_title, sections, template_params, to_text

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "db" / "aeons_end.sqlite"
WIKI = "https://aeonsend.wiki.gg/wiki/"

KIND_BY_TEMPLATE = {
    "Mage": "mage", "Nemesis": "nemesis", "NemesisCard": "nemesis_card",
    "PlayerCard": "player_card", "StoryCard": "story_card", "LegacyCard": "legacy_card",
    "Friend": "friend", "Foe": "foe", "Friend&FoeCard": "friend_foe_card", "Box": "box",
    "AbilityCardXaxos": "ability_card", "AbilityCardOna": "ability_card", "Upgrade": "upgrade",
}
LORE_SECTIONS = {
    "Flavor Text": "flavor", "Old Flavor Text": "old_flavor", "Story": "story",
    "Lore": "story", "Mentions": "mention", "Mentioned": "mention", "By": "mention",
}
# Box/expansion names double as categories; used to tag a page with its box.
SCHEMA = """
CREATE TABLE pages (
  title TEXT PRIMARY KEY, pageid INTEGER, kind TEXT, box TEXT, base_name TEXT,
  url TEXT, image TEXT, categories TEXT, revid INTEGER, timestamp TEXT,
  spoiler TEXT, text TEXT, wikitext TEXT, infobox TEXT);
CREATE TABLE redirects (alias TEXT PRIMARY KEY, target TEXT);
CREATE TABLE boxes (
  title TEXT PRIMARY KEY, wave INTEGER, first_release TEXT, type TEXT,
  mages INTEGER, nemeses INTEGER, blurb TEXT, description TEXT);
CREATE TABLE mages (
  title TEXT PRIMARY KEY, base_name TEXT, box TEXT, epithet TEXT, complexity INTEGER,
  affiliation TEXT, ability_name TEXT, ability_effect TEXT, charge_spaces INTEGER,
  breaches TEXT, starting_hand TEXT, starting_deck TEXT, unique_cards TEXT, rules TEXT);
CREATE TABLE nemeses (
  title TEXT PRIMARY KEY, base_name TEXT, box TEXT, life INTEGER, difficulty INTEGER,
  expedition_battles TEXT, unleash TEXT, setup TEXT, rules TEXT, increased_difficulty TEXT,
  expedition_b5_modifiers TEXT, unique_cards TEXT, overview TEXT);
CREATE TABLE nemesis_cards (
  title TEXT PRIMARY KEY, box TEXT, type TEXT, tier INTEGER, nemesis TEXT, basic INTEGER,
  upgraded INTEGER, life TEXT, shield TEXT, effect TEXT, card_ids TEXT, boxes TEXT, printings TEXT);
CREATE TABLE player_cards (
  title TEXT PRIMARY KEY, box TEXT, type TEXT, cost INTEGER, unique_to TEXT,
  treasure_level INTEGER, rules TEXT, mechanics TEXT, card_ids TEXT, boxes TEXT, printings TEXT);
CREATE TABLE friends_foes (
  title TEXT PRIMARY KEY, role TEXT, base_name TEXT, box TEXT, ability_name TEXT,
  effect TEXT, charge_spaces INTEGER, setup TEXT, rules TEXT, deck TEXT, unique_cards TEXT);
CREATE TABLE friend_foe_cards (
  title TEXT PRIMARY KEY, friend TEXT, foe TEXT, type TEXT, box TEXT, effect TEXT, card_ids TEXT,
  boxes TEXT, printings TEXT);
CREATE TABLE narrative_cards (
  id INTEGER PRIMARY KEY, page TEXT, kind TEXT, box TEXT, card_id TEXT, face INTEGER,
  title TEXT, lore TEXT, rules TEXT, nemesis TEXT);
CREATE TABLE lore_texts (
  id INTEGER PRIMARY KEY, page TEXT, page_kind TEXT, box TEXT, source TEXT,
  speaker TEXT, card_id TEXT, heading TEXT, text TEXT, wikitext TEXT, hash TEXT UNIQUE);
CREATE TABLE mentions (
  lore_id INTEGER, target TEXT, via TEXT, PRIMARY KEY (lore_id, target));
CREATE TABLE characters (
  name TEXT PRIMARY KEY, roles TEXT, versions TEXT, boxes TEXT, lore_count INTEGER);
-- Curated by the wiki's "Character Quote" page: which mat quotes belong to / are by / mention a character.
CREATE TABLE character_quotes (
  character TEXT, section_pages TEXT, relation TEXT, lore_id INTEGER, speaker TEXT,
  PRIMARY KEY (character, relation, lore_id));
CREATE TABLE expedition_battles (nemesis TEXT, battle INTEGER, PRIMARY KEY (nemesis, battle));
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
-- Every lore text tied to a character, either written on one of its pages or mentioning it.
CREATE VIEW character_lore AS
  SELECT c.name AS character, l.id AS lore_id, 'self' AS via, l.*
    FROM characters c JOIN json_each(c.versions) v JOIN lore_texts l ON l.page = v.value
  UNION
  SELECT c.name, l.id, m.via, l.*
    FROM characters c JOIN json_each(c.versions) v JOIN mentions m ON m.target = v.value
    JOIN lore_texts l ON l.id = m.lore_id;
CREATE VIRTUAL TABLE lore_fts USING fts5(text, page, speaker, source, box,
  content='lore_texts', content_rowid='id');
"""


def load_pages():
    pages = {}
    for line in (RAW / "pages.jsonl").read_text(encoding="utf-8").splitlines():
        p = json.loads(line)
        pages[p["title"]] = p
    redirects = json.loads((RAW / "redirects.json").read_text(encoding="utf-8"))
    return pages, redirects


def first_infobox(code):
    for t in code.filter_templates(recursive=False):
        name = str(t.name).strip()
        if name in KIND_BY_TEMPLATE:
            return name, t
    return None, None


def base_name(title):
    """'Brama (Legacy of Gravehold)' / 'Xaxos: Outcast' / 'Adelheim, the Blacksmith' -> base."""
    b = re.sub(r"\s*\(.*?\)\s*$", "", title)
    b = re.split(r":\s|,\s", b)[0]
    return b.strip()


def to_int(s):
    m = re.search(r"-?\d+", s or "")
    return int(m.group()) if m else None


def card_list(wikitext):
    out = []
    for t in mw.parse(wikitext or "").filter_templates():
        if str(t.name).strip().lower() in ("card", "cardimage") and t.has(1):
            out.append(normalize_title(str(t.get(1).value)))
    return out


def printing_cols(boxes, ids, fallback):
    """(boxes JSON, printings JSON): every box the card was printed in, with that printing's card numbers."""
    printings = [{"box": b, "ids": i} for b, i in zip(boxes, ids)] or [{"box": fallback, "ids": ""}]
    unique = list(dict.fromkeys(p["box"] for p in printings))
    return json.dumps(unique), json.dumps(printings, ensure_ascii=False)


def multi_box(params):
    boxes, ids = [], []
    for i in range(1, 12):
        if f"Box {i}" in params and to_text(params[f"Box {i}"]):
            boxes.append(to_text(params[f"Box {i}"]))
            ids.append(to_text(params.get(f"ID {i}", "")))
    return boxes, ids


def classify(p, box_titles):
    code = mw.parse(p["wikitext"])
    tname, tpl = first_infobox(code)
    cats = set(p["categories"])
    if tname:
        kind = KIND_BY_TEMPLATE[tname]
    elif "Text-Only Character" in cats:
        kind = "npc"
    elif "Game Term" in cats or "Game Mechanics" in cats or "Card Type" in cats:
        kind = "rules"
    elif "disambiguation" in p["title"].lower():
        kind = "disambiguation"
    elif p["title"] in box_titles or "Game Box" in cats:
        kind = "box"
    elif "Reminder" in cats or "Player Aid" in p["title"]:
        kind = "reminder"
    else:
        kind = "other"
    params = template_params(tpl) if tpl is not None else {}
    box = None
    for key in ("Box", "Box 1"):
        if params.get(key):
            box = to_text(params[key])
            break
    if not box:
        hits = [c for c in p["categories"] if c in box_titles]
        box = hits[0] if hits else None
    if kind == "box":
        box = p["title"]
    spoiler = None
    m = re.search(r"\{\{Spoiler warning\|subject=([^|}]+)", p["wikitext"])
    if m:
        spoiler = m.group(1).strip()
    return kind, params, box, spoiler, code


def extract_quotes(body, pagename):
    """Yield (speaker, card_id, text, wikitext) for each Quote in a section, or the raw body."""
    code = mw.parse(body)
    quotes = [t for t in code.filter_templates(recursive=False) if str(t.name).strip().lower() == "quote"]
    if not quotes:
        txt = to_text(body, pagename)
        if txt:
            yield None, None, txt, body.strip()
        return
    for q in quotes:
        prm = template_params(q)
        raw = prm.get("quote") or prm.get("1") or ""
        txt = to_text(raw, pagename)
        if txt:
            yield (to_text(prm.get("speaker", ""), pagename) or None,
                   to_text(prm.get("ID", "")) or None, txt, raw)


def text_hash(text):
    return hashlib.sha1(re.sub(r"\W+", "", text.lower()).encode()).hexdigest()


def load_character_quotes(con, pages, resolve):
    """Parse the 'Character Quote' page: == [[Character]] == then optional === By === / === Mentioned ===.

    Quotes are matched to existing lore_texts (exact normalized text, else same 120-char prefix);
    unmatched ones are inserted as new lore. Each becomes a curated mention of the section's pages.
    """
    page = pages.get("Character Quote")
    if not page:
        return
    by_prefix = {}
    for lid, txt in con.execute("SELECT id, text FROM lore_texts"):
        by_prefix.setdefault(re.sub(r"\W+", "", txt.lower())[:120], lid)
    character, targets, relation = None, [], "self"
    for heading, level, body in sections(page["wikitext"]):
        if level == 2:
            targets = [resolve(l) for l in links(heading)]
            character = base_name(targets[0]) if targets else to_text(heading)
            relation = "self"
        elif level == 3:
            relation = {"by": "by", "mentioned": "mentioned"}.get(heading.lower(), heading.lower())
        if not character:
            continue
        for speaker, cid, txt, raw in extract_quotes(body, "Character Quote"):
            if len(txt) < 40:
                continue
            h = text_hash(txt)
            row = con.execute("SELECT id FROM lore_texts WHERE hash=?", (h,)).fetchone()
            lid = row[0] if row else by_prefix.get(re.sub(r"\W+", "", txt.lower())[:120])
            if lid is None:
                lid = con.execute(
                    "INSERT INTO lore_texts (page,page_kind,box,source,speaker,card_id,heading,text,wikitext,hash) "
                    "VALUES ('Character Quote','other',NULL,'mat_quote',?,?,?,?,?,?)",
                    (speaker, cid, character, txt, raw, h)).lastrowid
            con.execute("INSERT OR IGNORE INTO character_quotes VALUES (?,?,?,?,?)",
                        (character, json.dumps(targets), relation, lid, speaker))
            for t in targets:
                if t in pages:
                    con.execute("INSERT OR IGNORE INTO mentions VALUES (?,?,?)", (lid, t, "curated"))


def main():
    pages, redirects = load_pages()
    box_titles = {t for t, p in pages.items() if "Game Box" in p["categories"]
                  or p["wikitext"].lstrip("{ ").startswith("Box")}
    box_titles |= {t for t, p in pages.items()
                   if re.search(r"\{\{Box\s*\n?\|", p["wikitext"])}

    def resolve(t):
        t = normalize_title(t)
        seen = 0
        while t in redirects and seen < 5:
            t = redirects[t]
            seen += 1
        return t

    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO redirects VALUES (?,?)", redirects.items())

    lore_rows = []  # (page, kind, box, source, speaker, card_id, heading, text, wikitext)
    page_kind = {}

    for title, p in sorted(pages.items()):
        kind, params, box, spoiler, code = classify(p, box_titles)
        page_kind[title] = kind
        text = to_text(p["wikitext"], title)
        con.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            title, p["pageid"], kind, box, base_name(title), WIKI + title.replace(" ", "_"),
            p.get("image"), json.dumps(p["categories"]), p["revid"], p["timestamp"], spoiler,
            text, p["wikitext"], json.dumps({k: to_text(v, title) for k, v in params.items()})))
        T = lambda k: to_text(params.get(k, ""), title) or None  # noqa: E731
        cats = p["categories"]
        secs = sections(p["wikitext"])
        sec = {h: b for h, _, b in secs}

        if kind == "mage":
            cx = params.get("Complexity") or next((c.split()[1] for c in cats if c.startswith("Complexity ")), None)
            con.execute("INSERT INTO mages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                title, base_name(title), box, T("title"), to_int(cx), T("Affiliation"),
                T("Name"), T("Effect"), to_int(params.get("Charge Spaces")),
                json.dumps([params.get(f"Breach{i}", "").strip() for i in range(1, 5)]),
                T("Starting Hand"), T("Starting Deck"),
                json.dumps(card_list(params.get("Unique Cards"))), T("Rules")))
        elif kind == "nemesis":
            eb = [int(x) for x in re.findall(r"\d+", params.get("Expedition Battle", ""))]
            for b in eb:
                con.execute("INSERT OR IGNORE INTO expedition_battles VALUES (?,?)", (title, b))
            uniq = []
            in_uniq = False
            for h, lv, b in secs:
                if lv == 2:
                    in_uniq = h == "Unique Cards"
                if in_uniq:
                    uniq += card_list(b)
            con.execute("INSERT INTO nemeses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                title, base_name(title), box, to_int(params.get("Life")),
                to_int(params.get("Difficulty Level")), json.dumps(eb), T("Unleash"), T("Setup"),
                T("Rules"), T("Increased Difficulty"),
                to_text(sec.get("Expedition Battle 5 Modifiers", ""), title) or None,
                json.dumps(uniq), to_text(sec.get("Overview", ""), title) or None))
        elif kind == "nemesis_card":
            boxes, ids = multi_box(params)
            con.execute("INSERT INTO nemesis_cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                title, boxes[0] if boxes else box, T("Type"), to_int(params.get("Tier")),
                T("Nemesis"), int("Basic" in cats), int("Upgraded" in cats or bool(params.get("Upgraded"))),
                T("Life"), T("Shield"), T("Effect"), json.dumps(ids), *printing_cols(boxes, ids, box)))
        elif kind in ("player_card", "ability_card", "upgrade"):
            boxes, ids = multi_box(params)
            lvl = next((to_int(c) for c in cats if c.startswith("Treasure Level")), None)
            con.execute("INSERT INTO player_cards VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                title, boxes[0] if boxes else box, T("Type") or kind.replace("_", " ").title(),
                to_int(params.get("Cost")), T("Unique To"), lvl, T("Rules"),
                T("Mechanics") or T("Mechanic"), json.dumps(ids), *printing_cols(boxes, ids, box)))
        elif kind in ("friend", "foe"):
            con.execute("INSERT INTO friends_foes VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                title, kind, base_name(title), box, T("Name"), T("Effect"),
                to_int(params.get("Charge Spaces")), T("Setup"), T("Rules"),
                json.dumps(card_list(params.get("Deck"))), json.dumps(card_list(params.get("Unique Cards")))))
        elif kind == "friend_foe_card":
            boxes, ids = multi_box(params)
            con.execute("INSERT INTO friend_foe_cards VALUES (?,?,?,?,?,?,?,?,?)", (
                title, T("Friend"), T("Foe"), T("Type"), boxes[0] if boxes else box, T("Effect"), json.dumps(ids),
                *printing_cols(boxes, ids, box)))
        elif kind == "box":
            m = re.search(r"<blockquote>(.*?)</blockquote>", p["wikitext"], re.S)
            blurb = to_text(m.group(1), title) if m else None
            lead = to_text(secs[0][2], title)
            con.execute("INSERT INTO boxes VALUES (?,?,?,?,?,?,?,?)", (
                title, to_int(params.get("Wave")), T("First Release") or T("Release"), T("Type"),
                to_int(params.get("Mages")), to_int(params.get("Nemeses")), blurb, lead or None))
            if blurb:
                lore_rows.append((title, kind, title, "box_blurb", None, None, "Back of box", blurb, m.group(1)))
            if lead:
                lore_rows.append((title, kind, title, "box_description", None, None, "", lead, secs[0][2]))

        # Narrative cards (campaign / story / event)
        if kind == "legacy_card":
            for face in (1, 2):
                lore = params.get(f"Lore{face}", "")
                con.execute("INSERT INTO narrative_cards (page,kind,box,card_id,face,title,lore,rules) VALUES (?,?,?,?,?,?,?,?)", (
                    title, "legacy", box, T("ID"), face, T(f"Title{face}"), to_text(lore, title) or None, T(f"Rules{face}")))
                if lore.strip():
                    lore_rows.append((title, kind, box, "campaign", None, T("ID"), T(f"Title{face}"), to_text(lore, title), lore))
        elif kind == "story_card":
            ntype = "event" if "Event" in cats else "story"
            for face, suffix in ((1, ""), (2, "2")):
                lore = params.get(f"Lore{suffix}", "") or (params.get("Lores", "") if face == 1 else "")
                rules = params.get(f"Rules{suffix}", "")
                if face == 2 and not (lore or rules):
                    continue
                con.execute("INSERT INTO narrative_cards (page,kind,box,card_id,face,title,lore,rules,nemesis) VALUES (?,?,?,?,?,?,?,?,?)", (
                    title, ntype, box, T("ID"), face, title, to_text(lore, title) or None,
                    to_text(rules, title) or None, T("Nemesis")))
                if lore.strip():
                    lore_rows.append((title, kind, box, ntype, None, T("ID"), title, to_text(lore, title), lore))

        # Section-based lore (flavor texts, story quotes, mentions)
        for h, lv, b in secs:
            src = LORE_SECTIONS.get(h)
            if not src:
                continue
            for speaker, cid, txt, raw in extract_quotes(b, title):
                lore_rows.append((title, kind, box, src, speaker, cid, h, txt, raw))

    # Insert lore, deduplicating identical texts (aggregator pages repeat quotes).
    priority = {"campaign": 0, "story": 1, "event": 1, "flavor": 2, "old_flavor": 3,
                "mention": 4, "box_blurb": 5, "box_description": 6}
    lore_rows.sort(key=lambda r: (r[0] == "Character Quote", priority.get(r[3], 9)))
    seen = {}
    for r in lore_rows:
        h = hashlib.sha1(re.sub(r"\W+", "", r[7].lower()).encode()).hexdigest()
        if h in seen:
            continue
        cur = con.execute("INSERT INTO lore_texts (page,page_kind,box,source,speaker,card_id,heading,text,wikitext,hash) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?)", (*r, h))
        seen[h] = cur.lastrowid

    load_character_quotes(con, pages, resolve)

    # Mentions: explicit links in the lore wikitext, then plain-text name matches.
    all_titles = set(pages)
    named = {}  # surface name -> target page, for characters only
    for t, k in page_kind.items():
        if k in ("mage", "nemesis", "friend", "foe", "npc"):
            b = base_name(t)
            if len(b) >= 3:
                # prefer the original (un-parenthesised) page as the canonical target
                if b not in named or t == b:
                    named[b] = t
    name_re = re.compile(r"\b(" + "|".join(sorted(map(re.escape, named), key=len, reverse=True)) + r")\b")
    for lid, page, wt, txt, speaker in con.execute("SELECT id, page, wikitext, text, speaker FROM lore_texts").fetchall():
        targets = {}
        m = name_re.search(speaker or "")
        if m and named[m.group(1)] != page:
            targets[named[m.group(1)]] = "speaker"
        for l in links(wt):
            r = resolve(l)
            if r in all_titles and r != page:
                targets[r] = "link"
        for m in name_re.finditer(txt):
            r = named[m.group(1)]
            if r != page and r not in targets and base_name(r) not in {base_name(x) for x in targets}:
                targets[r] = "name"
        con.executemany("INSERT OR IGNORE INTO mentions VALUES (?,?,?)", [(lid, t, v) for t, v in targets.items()])

    # Characters: group mage/nemesis/friend/foe/npc pages by base name.
    chars = {}
    for t, k in page_kind.items():
        if k in ("mage", "nemesis", "friend", "foe", "npc"):
            c = chars.setdefault(base_name(t), {"roles": set(), "versions": [], "boxes": set()})
            c["roles"].add(k)
            c["versions"].append(t)
            bx = con.execute("SELECT box FROM pages WHERE title=?", (t,)).fetchone()[0]
            if bx:
                c["boxes"].add(bx)
    for name, c in chars.items():
        vers = c["versions"]
        q = ",".join("?" * len(vers))
        n = con.execute(f"SELECT COUNT(DISTINCT id) FROM lore_texts l LEFT JOIN mentions m ON m.lore_id=l.id "
                        f"WHERE l.page IN ({q}) OR m.target IN ({q})", vers + vers).fetchone()[0]
        con.execute("INSERT INTO characters VALUES (?,?,?,?,?)", (
            name, json.dumps(sorted(c["roles"])), json.dumps(sorted(vers)), json.dumps(sorted(c["boxes"])), n))

    # Link nemesis cards to their nemesis where the template didn't say.
    for nem, uniq in con.execute("SELECT title, unique_cards FROM nemeses").fetchall():
        for card in json.loads(uniq):
            con.execute("UPDATE nemesis_cards SET nemesis=? WHERE title=? AND nemesis IS NULL", (nem, card))

    con.execute("INSERT INTO lore_fts(lore_fts) VALUES ('rebuild')")
    info = json.loads((RAW / "siteinfo.json").read_text(encoding="utf-8"))
    con.executemany("INSERT INTO meta VALUES (?,?)", [
        ("source", "https://aeonsend.wiki.gg/"),
        ("license", info["rightsinfo"]["text"] + " — " + info["rightsinfo"]["url"]),
        ("crawled_at", info["general"]["time"]),
    ])
    load_lore.load(con)
    con.commit()

    for tbl in ("pages", "boxes", "mages", "nemeses", "nemesis_cards", "player_cards", "friends_foes",
                "friend_foe_cards", "narrative_cards", "lore_texts", "mentions", "characters", "expedition_battles"):
        print(f"{tbl:20s} {con.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]}")
    con.close()


if __name__ == "__main__":
    main()
