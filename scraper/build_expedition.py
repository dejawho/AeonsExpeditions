"""Build data/db/expedition.sqlite (+ data/expedition/*.json): everything needed to generate
an Aeon's End expedition, derived from data/db/aeons_end.sqlite and expedition/rules.json.

Tables
  boxes              collection filter (wave, type, release)
  mages              randomizer-eligible mages with starting cards (Crystal/Spark counts for treasures)
  supply_cards       gem / relic / spell randomizer pool, with module & power flags
  treasures          level 1-4 treasures
  nemeses            nemesis randomizers by battle, modifiers, deck source
  nemesis_cards      each nemesis' own cards (role: deck | setup | special)
  basic_nemesis_cards basic and upgraded basic cards
  friends, foes, friend_foe_cards, banners
  linked_cards       side cards a setup must include (swap zone, side decks, trinkets, ability decks)
  characters         who each mage / nemesis / friend / foe is: one character never appears twice in an expedition
  exclusions         content not usable in an expedition, with the reason
  rules              expedition/rules.json, one row per section
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

import mwparserfromhell as mw

from shareable import BOX_ORDER, fnv1a
from wikitext import links, sections, to_text

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "db" / "aeons_end.sqlite"
DST = ROOT / "data" / "db" / "expedition.sqlite"
JSON_DIR = ROOT / "data" / "expedition"
RULES = ROOT / "expedition" / "rules.json"
CHARACTERS = ROOT / "lore" / "characters.json"

SCHEMA = """
CREATE TABLE boxes (title TEXT PRIMARY KEY, wave INTEGER, type TEXT, first_release TEXT);
CREATE TABLE mages (title TEXT PRIMARY KEY, base_name TEXT, box TEXT, epithet TEXT, complexity INTEGER,
  ability_name TEXT, ability_effect TEXT, charge_spaces INTEGER, breaches TEXT, starting_hand TEXT,
  starting_deck TEXT, crystals INTEGER, sparks INTEGER, unique_cards TEXT, rules TEXT, url TEXT, boxes TEXT);
CREATE TABLE supply_cards (title TEXT PRIMARY KEY, type TEXT, cost INTEGER, box TEXT, rules TEXT,
  mechanics TEXT, card_ids TEXT, requires TEXT, campaign_mechanic INTEGER, legacy_power TEXT,
  develop_cost INTEGER, url TEXT, boxes TEXT);
CREATE TABLE treasures (title TEXT PRIMARY KEY, level INTEGER, type TEXT, cost INTEGER, box TEXT,
  rules TEXT, replaces TEXT, mage TEXT, url TEXT, boxes TEXT);
CREATE TABLE nemeses (title TEXT PRIMARY KEY, box TEXT, life INTEGER, difficulty INTEGER, battles TEXT,
  unleash TEXT, setup TEXT, rules TEXT, increased_difficulty TEXT, expedition_modifiers TEXT,
  deck_source TEXT, url TEXT, boxes TEXT);
CREATE TABLE nemesis_cards (title TEXT PRIMARY KEY, nemesis TEXT, role TEXT, tier INTEGER, type TEXT,
  life TEXT, shield TEXT, effect TEXT, box TEXT, boxes TEXT);
CREATE TABLE basic_nemesis_cards (title TEXT PRIMARY KEY, box TEXT, tier INTEGER, type TEXT,
  upgraded INTEGER, player_count TEXT, pool TEXT, life TEXT, shield TEXT, effect TEXT, card_ids TEXT, boxes TEXT);
CREATE TABLE friends (title TEXT PRIMARY KEY, box TEXT, ability_name TEXT, effect TEXT, charge_spaces INTEGER,
  setup TEXT, rules TEXT, deck TEXT, unique_cards TEXT, url TEXT, boxes TEXT);
CREATE TABLE foes (title TEXT PRIMARY KEY, box TEXT, ability_name TEXT, effect TEXT, charge_spaces INTEGER,
  setup TEXT, rules TEXT, deck TEXT, unique_cards TEXT, url TEXT, boxes TEXT);
CREATE TABLE friend_foe_cards (title TEXT PRIMARY KEY, owner TEXT, role TEXT, type TEXT, effect TEXT, boxes TEXT);
CREATE TABLE banners (title TEXT PRIMARY KEY, type TEXT, cost INTEGER, box TEXT, rules TEXT, boxes TEXT);
CREATE TABLE linked_cards (title TEXT PRIMARY KEY, kind TEXT, linked_to TEXT, type TEXT, cost INTEGER,
  box TEXT, rules TEXT, boxes TEXT);
CREATE TABLE characters (title TEXT, kind TEXT, character TEXT, PRIMARY KEY (title, kind));
CREATE TABLE exclusions (title TEXT, kind TEXT, reason TEXT, PRIMARY KEY (title, kind));
CREATE TABLE rules (section TEXT PRIMARY KEY, value TEXT);
CREATE TABLE data_fixes (title TEXT, field TEXT, wiki_value TEXT, used_value TEXT);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

# Nemeses whose randomizer deck reuses another nemesis' cards.
DECK_SOURCE = {"Crooked Mask (Beyond the Breach)": "Crooked Mask"}
# End-of-campaign replacements (rules.json content_exclusions.nemesis_cards).
EXCLUDED_NEMESIS_CARDS = {"Bladius Attacks", "Grasp"}
# Nemeses that are one being met in another form (lore/characters.json covers mages who are also nemeses).
SAME_NEMESIS = {"crooked_mask": ["Crooked Mask", "Crooked Mask (Beyond the Breach)"],
                "bishop_of_scrolls": ["Bishop of Scrolls", "Bishop: Returned"],
                "the_prophet": ["Twice-Dead Prophet", "Thrice-Dead Prophet"],
                "paradox": ["Paradox of Myth", "Paradox of Bone", "Paradox of Myth and Bone"]}
LEGACY_POWER = [("VIII", "strong"), ("VII", "standard"), ("VI", "strong"), ("IV", "standard"),
                ("V", "strong"), ("III", "standard"), ("II", "weak"), ("Ia", "weak"), ("Id", "weak"),
                ("Ib", "standard"), ("Ic", "standard")]


def intro_params(wikitext, name):
    for t in mw.parse(wikitext).filter_templates(recursive=False):
        if str(t.name).strip() == name:
            return {str(p.name).strip(): str(p.value).strip() for p in t.params}
    return {}


def parse_cards(text):
    """'1x Amethyst Shard\\n2x Crystal' -> [{'card': 'Amethyst Shard', 'qty': 1}, ...]"""
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"\s*(\d+)\s*x\s*(.+?)\s*$", line)
        if m:
            out.append({"card": m.group(2), "qty": int(m.group(1))})
        elif line.strip():
            out.append({"card": line.strip(), "qty": 1})
    return out


def count(cards, name):
    return sum(c["qty"] for c in cards if re.fullmatch(rf"(Enhanced |Flawed )?{name}", c["card"]))


def legacy_power(card_ids):
    for cid in card_ids:
        for prefix, power in LEGACY_POWER:
            if re.match(rf"{prefix}\d", cid):
                return power
    return None


def main():
    src = sqlite3.connect(SRC)
    src.row_factory = sqlite3.Row
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    if DST.exists():
        DST.unlink()
    db = sqlite3.connect(DST)
    db.executescript(SCHEMA)
    q = lambda sql, *a: src.execute(sql, a).fetchall()  # noqa: E731
    page = {r["title"]: r for r in q("SELECT title, wikitext, categories, url, kind, box FROM pages")}
    cats = lambda t: set(json.loads(page[t]["categories"])) if t in page else set()  # noqa: E731

    excl = rules["content_exclusions"]
    excluded_nem = {e["title"]: e["reason"] for e in excl["nemeses"]}
    excluded_mage = {e["title"]: e["reason"] for e in excl["mages"]}
    for t, r in excluded_nem.items():
        db.execute("INSERT INTO exclusions VALUES (?,?,?)", (t, "nemesis", r))
    for t, r in excluded_mage.items():
        db.execute("INSERT INTO exclusions VALUES (?,?,?)", (t, "mage", r))

    for r in q("SELECT title, wave, type, first_release FROM boxes"):
        db.execute("INSERT INTO boxes VALUES (?,?,?,?)", tuple(r))

    # --- Mages -------------------------------------------------------------
    for m in q("SELECT * FROM mages"):
        if m["title"] in excluded_mage:
            continue
        hand, deck = parse_cards(m["starting_hand"]), parse_cards(m["starting_deck"])
        db.execute("INSERT INTO mages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            m["title"], m["base_name"], m["box"], m["epithet"], m["complexity"], m["ability_name"],
            m["ability_effect"], m["charge_spaces"], m["breaches"], json.dumps(hand), json.dumps(deck),
            count(hand + deck, "Crystal"), count(hand + deck, "Spark"), m["unique_cards"], m["rules"],
            page[m["title"]]["url"], json.dumps([m["box"]])))

    # --- Player cards: classify by the PlayerCardIntro 'Non-Supply Type' -----
    mage_titles = {r["title"] for r in q("SELECT title FROM mages")}
    for c in q("SELECT * FROM player_cards"):
        t = c["title"]
        p = page[t]
        intro = intro_params(p["wikitext"], "PlayerCardIntro")
        info = json.loads(src.execute("SELECT infobox FROM pages WHERE title=?", (t,)).fetchone()[0])
        nst = intro.get("Non-Supply Type", "")
        cs = cats(t)
        ids = [i for i in json.loads(c["card_ids"] or "[]") if i]
        typ = c["type"] or ""
        rules_txt = c["rules"] or ""
        treasure_level = c["treasure_level"]
        m = re.match(r"treasure(\d)", nst)
        if m:
            treasure_level = int(m.group(1))
        if treasure_level is None and ("Treasure" in cs or typ.startswith("Treasured")):
            treasure_level = 1 if (c["cost"] or 0) == 0 else 4  # level 1 treasures all cost 0
        subject = to_text(intro.get("Subject", "")) or None

        if treasure_level:
            kind = typ if typ.startswith("Treasured") else f"Treasure Level {treasure_level}"
            mage = next((mt for mt in mage_titles if t.startswith(re.sub(r" \(.*", "", mt) + "'")), None)
            replaces = None
            if treasure_level == 1:
                replaces = "Crystal" if "Gem" in typ else "Spark" if "Spell" in typ else None
            db.execute("INSERT INTO treasures VALUES (?,?,?,?,?,?,?,?,?,?)", (
                t, treasure_level, kind, c["cost"], c["box"], rules_txt, replaces, mage, p["url"], c["boxes"]))
        elif nst == "banner":
            db.execute("INSERT INTO banners VALUES (?,?,?,?,?,?)", (t, typ, c["cost"], c["box"], rules_txt, c["boxes"]))
        elif nst in ("starter", "sideDeck", "swap", "supplySwap", "trinket") or c["unique_to"] \
                or typ in ("Ability Card", "Upgrade") or "Unique" in cs:
            kind = {"starter": "starting/unique", "sideDeck": "side deck", "swap": "swap zone",
                    "supplySwap": "swap zone", "trinket": "trinket"}.get(nst, "unique")
            if typ == "Ability Card":
                kind = "ability deck"
            linked = c["unique_to"] or subject
            if typ == "Ability Card" and "Xaxos Outcast Ability" in cs:
                linked = "Xaxos: Outcast"
            db.execute("INSERT INTO linked_cards VALUES (?,?,?,?,?,?,?,?)", (
                t, kind, linked, typ, c["cost"], c["box"], rules_txt, c["boxes"]))
        else:
            if typ not in ("Gem", "Relic", "Spell"):
                print(f"warning: unclassified player card {t} ({typ})")
                continue
            requires = []
            if "Xaxos: Outcast" in rules_txt:
                requires.append("xaxos_outcast")
            if re.search(r"\btrinket", rules_txt, re.I):
                requires.append("trinket_deck")
            if re.search(r"\b(friend|foe)\b", rules_txt, re.I):
                requires.append("friends_and_foes")
            swaps = [l for l in links(p["wikitext"].split("==")[0]) if l in page and l != t and
                     intro_params(page[l]["wikitext"], "PlayerCardIntro").get("Non-Supply Type") in ("swap", "supplySwap")]
            if swaps:
                requires.append("swap_zone:" + ";".join(sorted(set(swaps))))
            campaign = int(c["box"] == "Legacy of Gravehold" and bool(cs & {"Boost", "Overheat"}))
            power = legacy_power(ids) if c["box"] == "Legacy" else None
            db.execute("INSERT INTO supply_cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                t, typ, c["cost"], c["box"], rules_txt, c["mechanics"], json.dumps(ids), json.dumps(requires),
                campaign, power, int(info["Develop Cost"]) if info.get("Develop Cost", "").isdigit() else None,
                p["url"], c["boxes"]))
            if campaign:
                db.execute("INSERT OR IGNORE INTO exclusions VALUES (?,?,?)",
                           (t, "supply_card", "boost/overheat: Legacy of Gravehold campaign mechanic (optional)"))

    # --- Nemeses -------------------------------------------------------------
    for n in q("SELECT * FROM nemeses"):
        if n["title"] in excluded_nem:
            continue
        mods = {}
        for h, lv, body in sections(page[n["title"]]["wikitext"]):
            m = re.match(r"Expedition Battle (\d) Modifiers", h)
            if m:
                mods[m.group(1)] = [l.lstrip("* ").strip() for l in to_text(body).splitlines() if l.strip()]
        db.execute("INSERT INTO nemeses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            n["title"], n["box"], n["life"], n["difficulty"], n["expedition_battles"], n["unleash"], n["setup"],
            n["rules"], n["increased_difficulty"], json.dumps(mods), DECK_SOURCE.get(n["title"], n["title"]),
            page[n["title"]]["url"], json.dumps([n["box"]])))

    # The nemesis page's "Tier N" sections win over a card page's own Tier field (the wiki has a few typos).
    section_tier = {}
    for (nem,) in q("SELECT title FROM nemeses"):
        for h, lv, body in sections(page[nem]["wikitext"]):
            m = re.fullmatch(r"Tier (\d)", h)
            if m:
                for card in links(body):
                    section_tier[(nem, card)] = int(m.group(1))

    for c in q("SELECT * FROM nemesis_cards"):
        t = c["title"]
        info = json.loads(src.execute("SELECT infobox FROM pages WHERE title=?", (t,)).fetchone()[0])
        campaign = "Campaign" in t
        fixed = section_tier.get((c["nemesis"], t))
        if fixed and c["tier"] and fixed != c["tier"]:
            db.execute("INSERT INTO data_fixes VALUES (?,?,?,?)", (
                t, "tier", str(c["tier"]), f"{fixed} (as listed on the {c['nemesis']} page)"))
            c = {**dict(c), "tier": fixed}
        if c["basic"]:
            if campaign or t in EXCLUDED_NEMESIS_CARDS:
                db.execute("INSERT OR IGNORE INTO exclusions VALUES (?,?,?)", (t, "basic_nemesis_card", "campaign version"))
                continue
            ids = json.loads(c["card_ids"] or "[]")
            joined = " ".join(ids)
            pool = ("legacy_end" if c["box"] == "Legacy" else
                    "log_bishop_or_fate_shepherd" if re.search(r"L2-(BS|FS)", joined) else "standard")
            if c["box"] == "Legacy" and not re.search(r"END\d", joined):
                db.execute("INSERT OR IGNORE INTO exclusions VALUES (?,?,?)", (t, "basic_nemesis_card", "Legacy Evolve campaign basic"))
                continue
            db.execute("INSERT INTO basic_nemesis_cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                t, c["box"], c["tier"], c["type"], c["upgraded"], info.get("Player Count") or None, pool,
                c["life"], c["shield"], c["effect"], c["card_ids"], c["boxes"]))
            continue
        if c["nemesis"] not in {r["title"] for r in q("SELECT title FROM nemeses")}:
            continue  # mage attacks, final battle, events: not part of an expedition
        if campaign or t in EXCLUDED_NEMESIS_CARDS:
            db.execute("INSERT OR IGNORE INTO exclusions VALUES (?,?,?)", (t, "nemesis_card", "campaign version / replaced"))
            continue
        role = "deck" if 1 <= (c["tier"] or 0) <= 3 else "setup" if c["tier"] == 0 else "special"
        if c["nemesis"] == "Arachnos" and t.startswith("World Devourer"):
            role = "special"
        db.execute("INSERT INTO nemesis_cards VALUES (?,?,?,?,?,?,?,?,?,?)", (
            t, c["nemesis"], role, c["tier"], c["type"], c["life"], c["shield"], c["effect"], c["box"], c["boxes"]))

    # --- Friends, foes ------------------------------------------------------
    for f in q("SELECT * FROM friends_foes"):
        db.execute(f"INSERT INTO {f['role']}s VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            f["title"], f["box"], f["ability_name"], f["effect"], f["charge_spaces"], f["setup"], f["rules"],
            f["deck"], f["unique_cards"], page[f["title"]]["url"], json.dumps([f["box"]])))
    for c in q("SELECT * FROM friend_foe_cards"):
        db.execute("INSERT INTO friend_foe_cards VALUES (?,?,?,?,?,?)", (
            c["title"], c["friend"] or c["foe"], "friend" if c["friend"] else "foe", c["type"], c["effect"], c["boxes"]))

    build_characters(db)

    # --- Rules + meta --------------------------------------------------------
    for k, v in rules.items():
        if not k.startswith("_"):
            db.execute("INSERT INTO rules VALUES (?,?)", (k, json.dumps(v, ensure_ascii=False)))
    for k, v in src.execute("SELECT key, value FROM meta"):
        db.execute("INSERT INTO meta VALUES (?,?)", (k, v))

    validate(db, rules)
    db.execute("INSERT INTO meta VALUES ('data_version', ?)", (str(data_version(db)),))
    extend_box_order(db)
    db.commit()
    export_json(db)
    for t in ("mages", "supply_cards", "treasures", "nemeses", "nemesis_cards", "basic_nemesis_cards",
              "friends", "foes", "friend_foe_cards", "banners", "linked_cards", "exclusions"):
        print(f"{t:20s} {db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")


def build_characters(db):
    """Every version of a character (Thraxir, Thraxir (The Descent), Knight of Shackles) gets one id, so the
    generator never shows the same person twice: as two mages, as a mage and a friend, or as a mage and a nemesis."""
    by_version = {}
    for c in json.loads(CHARACTERS.read_text(encoding="utf-8"))["characters"]:
        for v in c["versions"]:
            by_version.setdefault(v, c["id"])  # 'Kiri and Phoenix' is in two profiles: the first wins
    for cid, titles in SAME_NEMESIS.items():
        by_version.update({t: cid for t in titles})
    slug = lambda name: re.sub(r"\W+", "_", name.lower()).strip("_")  # noqa: E731
    for kind, sql in (("mage", "SELECT title, base_name FROM mages"), ("nemesis", "SELECT title, title FROM nemeses"),
                      ("friend", "SELECT title, title FROM friends"), ("foe", "SELECT title, title FROM foes")):
        for title, name in db.execute(sql).fetchall():
            if kind == "friend":
                name = title.split(",")[0]  # 'Qu, the Rift Walker' -> Qu
            db.execute("INSERT INTO characters VALUES (?,?,?)", (title, kind, by_version.get(title) or slug(name)))
    shared = db.execute("""SELECT character, group_concat(title, ' / ') FROM characters GROUP BY character
                           HAVING COUNT(DISTINCT kind) > 1 ORDER BY character""").fetchall()
    print(f"characters in more than one role: {len(shared)}")
    for cid, titles in shared:
        print(f"  {cid}: {titles}")


def validate(db, rules):
    problems = []
    for typ, need in (("Gem", 3), ("Relic", 2), ("Spell", 4)):
        n = db.execute("SELECT COUNT(*) FROM supply_cards WHERE type=?", (typ,)).fetchone()[0]
        if n < need * 4:
            problems.append(f"too few {typ} supply cards ({n})")
    for lvl in (1, 2, 3, 4):
        if not db.execute("SELECT COUNT(*) FROM treasures WHERE level=?", (lvl,)).fetchone()[0]:
            problems.append(f"no level {lvl} treasures")
    for b in range(1, rules["battles"]["with_battle_5"] + 1):
        n = db.execute("SELECT COUNT(*) FROM nemeses, json_each(nemeses.battles) WHERE value=?", (b,)).fetchone()[0]
        if n < 2:
            problems.append(f"battle {b} has only {n} nemeses")
    for (nem, src_deck) in db.execute("SELECT title, deck_source FROM nemeses"):
        tiers = dict(db.execute("SELECT tier, COUNT(*) FROM nemesis_cards WHERE nemesis=? AND role='deck' GROUP BY tier",
                                (src_deck,)).fetchall())
        if any(tiers.get(t, 0) < 3 for t in (1, 2, 3)):
            problems.append(f"{nem}: deck tiers {tiers}")
        elif any(tiers[t] != 3 for t in (1, 2, 3)):
            print(f"note: {nem} has a non-standard deck {tiers} (see its setup/rules)")
    for tier, need in ((1, 8), (2, 7), (3, 7)):
        n = db.execute("SELECT COUNT(*) FROM basic_nemesis_cards WHERE tier=? AND upgraded=0", (tier,)).fetchone()[0]
        u = db.execute("SELECT COUNT(*) FROM basic_nemesis_cards WHERE tier=? AND upgraded=1", (tier,)).fetchone()[0]
        if n < need or u < rules["nemesis_setup_per_battle"]["upgraded_basic_replacement"]["4"][f"tier_{tier}"]:
            problems.append(f"basic tier {tier}: {n} basic / {u} upgraded")
    for p in problems:
        print("VALIDATION:", p, file=sys.stderr)
    if problems:
        raise SystemExit(f"{len(problems)} validation problem(s)")


def data_version(db):
    """16-bit fingerprint of everything a generator draws from; stored in share codes."""
    parts = []
    for sql in ("SELECT title, type, boxes FROM supply_cards", "SELECT title, level, boxes FROM treasures",
                "SELECT title, battles, boxes FROM nemeses", "SELECT title, nemesis, role, tier FROM nemesis_cards",
                "SELECT title, tier, upgraded, boxes FROM basic_nemesis_cards", "SELECT title, boxes FROM mages",
                "SELECT title FROM friends", "SELECT title FROM foes", "SELECT title, kind, character FROM characters",
                "SELECT section, value FROM rules"):
        parts += ["|".join(map(str, r)) for r in db.execute(sql + " ORDER BY 1")]
    return fnv1a("\n".join(parts)) & 0xFFFF


def extend_box_order(db):
    """Append boxes missing from expedition/box_order.json (never reorder: share codes depend on it)."""
    data = json.loads(BOX_ORDER.read_text(encoding="utf-8"))
    new = [b for (b,) in db.execute("SELECT title FROM boxes ORDER BY wave, first_release, title")
           if b not in data["order"]]
    if new:
        data["order"] += new
        BOX_ORDER.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print("box_order.json: appended", new)


def export_json(db):
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        cur = db.execute(f"SELECT * FROM {t}")
        cols = [c[0] for c in cur.description]
        out = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            for k, v in d.items():
                if isinstance(v, str) and v[:1] in "[{":
                    try:
                        d[k] = json.loads(v)
                    except ValueError:
                        pass
            out.append(d)
        if t == "rules":
            out = {d["section"]: d["value"] for d in out}
        (JSON_DIR / f"{t}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
