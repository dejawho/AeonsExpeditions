"""Expedition generator: builds the WHOLE expedition at once, as a map of battles with 1-2 forks.

Uses only data/db/expedition.sqlite and its rules. Output:
  nodes   every battle on every path (nemesis, full nemesis deck, friend/foe, treasure setup, rewards)
  edges   which battle leads to which
  forks   where the players choose a path ('detour' rejoins later, 'finale' leads to different endings)
  routes  each complete path with its Barracks / supply sheet (it depends on the rewards collected)
The same share code (or seed + settings) always gives the same expedition.

    python scraper/generate_expedition.py --players 2 --forks 2 --seed 42
    python scraper/generate_expedition.py --code AEX-...
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from shareable import PRNG, decode, encode

DB = Path(__file__).resolve().parent.parent / "data" / "db" / "expedition.sqlite"
DEFAULTS = {"players": 2, "battles": 4, "forks": None, "boxes": [], "xaxos_outcast": False,
            "friends_foes": False, "campaign_mechanics": False, "seed": None}


def resolve_settings(**overrides):
    """Fill seed and fork count deterministically so they can be put in a share code."""
    s = {**DEFAULTS, **{k: v for k, v in overrides.items() if v is not None}}
    if s["seed"] is None:
        s["seed"] = int.from_bytes(os.urandom(4), "big")
    if s["forks"] is None:
        s["forks"] = 1 + PRNG.stream(s["seed"], "forks").randint(2)
    return s


def plan_layout(battles, forks, rng):
    """Choose fork positions. 'after' = the battle after which players choose.
    detour: battle after+1 has two versions, paths rejoin at after+2.
    finale: paths split for good (different last battle(s) and epilogue); placed late in the expedition."""
    if forks == 1:
        options = [[("detour", k)] for k in range(1, battles - 1)] + \
                  [[("finale", k)] for k in range(battles - 2, battles)]
    else:
        options = []
        for k1 in range(1, battles - 2):
            options += [[("detour", k1), ("detour", k2)] for k2 in range(k1 + 2, battles - 1)]
            options += [[("detour", k1), ("finale", k2)] for k2 in range(max(k1 + 2, battles - 2), battles)]
    return [{"kind": kind, "after": k} for kind, k in rng.choice(options)]


def build_graph(battles, layout):
    labels = {}
    for b in range(1, battles + 1):
        split = any(f["kind"] == "detour" and f["after"] == b - 1 for f in layout) or \
                any(f["kind"] == "finale" and f["after"] < b for f in layout)
        labels[b] = ["a", "b"] if split else [""]
    nodes = [f"{b}{l}" for b in range(1, battles + 1) for l in labels[b]]
    edges = []
    for b in range(1, battles):
        cur, nxt = labels[b], labels[b + 1]
        if len(cur) == len(nxt):
            edges += [(f"{b}{c}", f"{b + 1}{n}") for c, n in zip(cur, nxt)]
        else:
            edges += [(f"{b}{c}", f"{b + 1}{n}") for c in cur for n in nxt]
    forks = [{**f, "from": f"{f['after']}", "options": [f"{f['after'] + 1}a", f"{f['after'] + 1}b"]} for f in layout]
    return nodes, edges, forks


class Expedition:
    def __init__(self, con, settings):
        self.con, self.s = con, settings
        self.rules = {k: json.loads(v) for k, v in con.execute("SELECT section, value FROM rules")}
        self.data_version = int(con.execute("SELECT value FROM meta WHERE key='data_version'").fetchone()[0])
        self.boxes = set(settings["boxes"]) or {b for (b,) in con.execute("SELECT title FROM boxes")}
        self.used = set()
        # One character never appears twice on a route: two versions of a mage, a mage as a friend or a
        # nemesis. met: character -> battles where they appear (None: the starting Barracks, every route).
        self.who = {(k, t): c for t, k, c in con.execute("SELECT title, kind, character FROM characters")}
        self.met = {}
        self.node, self.routes = None, []  # the battle being drawn for; node sets of every route
        self.warnings = []
        self.rng = PRNG.stream(settings["seed"], "draws")

    # --- data access -------------------------------------------------------------
    def rows(self, sql, *args):
        cur = self.con.execute(sql, args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def is_owned(self, item):
        boxes = json.loads(item["boxes"]) if item.get("boxes") else [item.get("box")]
        return any(b in self.boxes for b in boxes)

    def on_route(self, a, b):
        """Two battles one party can both meet (None: the starting Barracks, on every route)."""
        return a is None or b is None or a == b or any(a in r and b in r for r in self.routes)

    def blocked(self, character):
        return character is not None and any(self.on_route(self.node, n) for n in self.met.get(character, ()))

    def draw(self, items, n, rng=None, kind=None, any_box=False):
        """kind: mage / nemesis / friend / foe, to skip characters met on the routes through this battle (and two
        versions of one character in the same draw). any_box: ignore the collection (optional cards nobody owns).
        Mage and nemesis cards are never used twice in an expedition; friends and foes only once per route."""
        rng = rng or self.rng
        pool = [i for i in items if (any_box or self.is_owned(i)) and i["title"] not in self.used
                and not self.blocked(self.who.get((kind, i["title"])))]
        if kind is None:
            picked = rng.sample(pool, n)
        else:  # shuffle, then keep the first n distinct characters
            picked, seen = [], set()
            for i in rng.sample(pool, len(pool)):
                c = self.who.get((kind, i["title"]), i["title"])
                if c not in seen and len(picked) < n:
                    picked.append(i)
                    seen.add(c)
        if kind not in ("friend", "foe"):
            self.used.update(p["title"] for p in picked)
        for p in picked:
            if c := self.who.get((kind, p["title"])):
                self.met.setdefault(c, set()).add(self.node)
        return picked

    def draw_one(self, items, kind, any_box=False):
        """One nemesis / friend / foe. When the collection runs short: first another version of a character
        already met, then a repeat. Returns (item, None | 'version' | 'repeat')."""
        picked = self.draw(items, 1, kind=kind, any_box=any_box)
        if picked:
            return picked[0], None
        owned = [i for i in items if any_box or self.is_owned(i)]
        fresh = [i for i in owned if i["title"] not in self.used and kind not in ("friend", "foe")]
        if fresh:
            item = self.rng.choice(fresh)
            self.used.add(item["title"])
            return item, "version"
        return (self.rng.choice(owned), "repeat") if owned else (None, None)

    def supply_pool(self, typ):
        out = []
        for c in self.rows("SELECT title, type, boxes, requires, campaign_mechanic FROM supply_cards "
                           "WHERE type=? ORDER BY title", typ):
            req = json.loads(c["requires"])
            if ("xaxos_outcast" in req and not self.s["xaxos_outcast"]) or \
               ("friends_and_foes" in req and not self.s["friends_foes"]) or \
               (c["campaign_mechanic"] and not self.s["campaign_mechanics"]):
                continue
            out.append(c)
        return out

    def draw_supply(self, gems, relics, spells):
        return [c["title"] for c in self.draw(self.supply_pool("Gem"), gems) + self.draw(self.supply_pool("Relic"), relics)
                + self.draw(self.supply_pool("Spell"), spells)]

    def draw_treasures(self, level, n):
        return [t["title"] for t in self.draw(self.rows(
            "SELECT title, boxes FROM treasures WHERE level=? ORDER BY title", level), n)]

    def draw_mages(self, n):
        return [m["title"] for m in self.draw(self.rows("SELECT title, boxes FROM mages ORDER BY title"), n,
                                              kind="mage")]

    def draw_nemesis(self, battle):
        pool = self.rows("""SELECT n.title, n.box, n.boxes, n.life, n.difficulty, n.deck_source, n.expedition_modifiers
                            FROM nemeses n, json_each(n.battles) b WHERE b.value=? ORDER BY n.title""", battle)
        nem, short = self.draw_one(pool, "nemesis")
        if not nem:
            raise SystemExit(f"No owned nemesis for Battle {battle}: add boxes or play fewer battles.")
        # no names here: the warning is shown before the expedition starts
        if short == "version":
            self.warnings.append(f"battle {battle}: you own too few Battle {battle} nemeses, so its nemesis is "
                                 f"a character already in this expedition (another version of them)")
        elif short == "repeat":
            self.warnings.append(f"battle {battle}: you own too few Battle {battle} nemeses, "
                                 f"so one of them appears twice in this expedition")
        return nem

    def draw_ally(self, items, kind):
        """A friend or foe for one battle (any of them if the collection has none: they are optional cards)."""
        item, short = self.draw_one(items, kind, any_box=not any(self.is_owned(i) for i in items))
        if short and f"too few {kind}s" not in " ".join(self.warnings):
            self.warnings.append(f"you own too few {kind}s, so a character appears twice in this expedition")
        return item["title"]

    def nemesis_deck(self, nemesis, battle):
        chart = self.rules["nemesis_deck"]["basic_cards_by_players"][str(self.s["players"])]
        upgrade = self.rules["nemesis_setup_per_battle"]["upgraded_basic_replacement"][str(battle)]
        deck = {}
        for tier in (1, 2, 3):
            own = [c["title"] for c in self.rows(
                "SELECT title FROM nemesis_cards WHERE nemesis=? AND role='deck' AND tier=? ORDER BY title",
                nemesis["deck_source"], tier)]
            basics = [b for b in self.rows("SELECT title, box, boxes, upgraded, player_count FROM basic_nemesis_cards "
                                           "WHERE tier=? ORDER BY title", tier)
                      if self.is_owned(b) and b["player_count"] in (None, str(self.s["players"]))]
            n_basic, n_up = chart[f"tier_{tier}"], min(upgrade[f"tier_{tier}"], chart[f"tier_{tier}"])
            up_pool = [b["title"] for b in basics if b["upgraded"]]
            if len(up_pool) < n_up:
                self.warnings.append(f"battle {battle} tier {tier}: only {len(up_pool)} upgraded basic cards owned "
                                     f"({n_up} wanted); filled with basic cards")
            ups = self.rng.sample(up_pool, n_up)
            regular = self.rng.sample([b["title"] for b in basics if not b["upgraded"]], n_basic - len(ups))
            deck[f"tier_{tier}"] = {"nemesis": own, "basic": regular, "upgraded_basic": ups}
        deck["setup_cards"] = [c["title"] for c in self.rows(
            "SELECT title FROM nemesis_cards WHERE nemesis IN (?,?) AND role IN ('setup','special') ORDER BY title",
            nemesis["title"], nemesis["deck_source"])]
        return deck

    # --- generation -------------------------------------------------------------------
    def run(self):
        s = self.s
        layout = plan_layout(s["battles"], s["forks"], PRNG.stream(s["seed"], "layout"))
        node_ids, edges, forks = build_graph(s["battles"], layout)
        successors = {n: [b for a, b in edges if a == n] for n in node_ids}
        self.routes = [set(p) for p in self.paths(node_ids[0], successors)]

        setup = {st["id"]: st for st in self.rules["expedition_setup"]["steps"]}
        start_cards = setup["starting_supply"]["draw"]
        start = {"mages": self.draw_mages(setup["starting_mages"]["draw"]["mage"]),
                 "player_cards": self.draw_supply(start_cards["gem"], start_cards["relic"], start_cards["spell"])}
        friends = self.rows("SELECT title, boxes FROM friends ORDER BY title")
        foes = self.rows("SELECT title, boxes FROM foes ORDER BY title")
        find = self.rules["post_battle"]["win"]["find_treasure"]

        nodes = {}
        for nid in node_ids:  # battle order, then branch a / b
            self.node = nid
            battle = int(nid.rstrip("ab"))
            nem = self.draw_nemesis(battle)
            node = {
                "id": nid, "battle": battle, "branch": nid[len(str(battle)):] or None,
                "final": not successors[nid],
                "nemesis": nem["title"], "nemesis_box": nem["box"], "life": nem["life"], "difficulty": nem["difficulty"],
                "expedition_modifiers": json.loads(nem["expedition_modifiers"]).get(str(battle), []),
                "nemesis_deck": self.nemesis_deck(nem, battle),
                "treasure_setup": {k: v for k, v in self.rules["treasure_setup"]["by_battle"][str(battle)].items() if v},
                "rewards": {},
                "next": successors[nid],
            }
            if s["friends_foes"]:
                node["friend"] = self.draw_ally(friends, "friend")
                node["foe"] = self.draw_ally(foes, "foe")
            if not node["final"]:  # nothing is gained after the last battle
                r, gained = find.get(str(battle)), {}
                if r:
                    gained["treasure_level"] = r["level"]
                    gained["treasures"] = self.draw_treasures(r["level"], r["count"])
                    extra = r.get("extra", {})
                    if extra:
                        gained["mages"] = self.draw_mages(extra["mage"])
                        for lvl in (1, 2, 3):
                            gained[f"extra_level_{lvl}"] = self.draw_treasures(lvl, extra.get(f"level_{lvl}", 0))
                        gained["extra_player_cards"] = self.draw_supply(extra["gem"], extra["relic"], extra["spell"])
                gained["player_cards"] = self.draw_supply(1, 1, 1)
                node["rewards"] = gained
            nodes[nid] = node
        self.node = None

        routes =[self.simulate_route(path, start, nodes) for path in self.paths(node_ids[0], successors)]
        return {
            "share_code": encode(s, self.data_version), "settings": s, "data_version": self.data_version,
            "starting_barracks": start, "forks": forks, "edges": edges, "nodes": nodes, "routes": routes,
            "warnings": self.warnings,
        }

    def paths(self, node, successors):
        if not successors[node]:
            return [[node]]
        return [[node] + rest for nxt in successors[node] for rest in self.paths(nxt, successors)]

    def simulate_route(self, path, start, nodes):
        """Barracks along one route; supply choice is randomised as a stand-in for the players' picks."""
        rid = "-".join(path)
        types = dict(self.con.execute("SELECT title, type FROM supply_cards"))
        need = self.rules["player_setup_per_battle"]["supply"]
        mages, cards = list(start["mages"]), list(start["player_cards"])
        treasures = {1: [], 2: [], 3: [], 4: []}
        steps = []
        for i, nid in enumerate(path):
            # seeded by the route so far: routes sharing a beginning get identical sheets up to the fork
            rng = PRNG.stream(self.s["seed"], "supply:" + "-".join(path[:i + 1]))
            supply = []
            for typ, key in (("Gem", "gems"), ("Relic", "relics"), ("Spell", "spells")):
                supply += rng.sample([c for c in cards if types[c] == typ], need[key])
            steps.append({"node": nid, "mages": list(mages), "supply": supply,
                          "banished": [c for c in cards if c not in supply],
                          "treasures_available": {lvl: list(t) for lvl, t in treasures.items() if t}})
            g = nodes[nid]["rewards"]
            if g.get("treasures"):
                treasures[g["treasure_level"]] += g["treasures"]
            for lvl in (1, 2, 3):
                treasures[lvl] += g.get(f"extra_level_{lvl}", [])
            mages += g.get("mages", [])
            cards = supply + g.get("player_cards", []) + g.get("extra_player_cards", [])
        return {"id": rid, "nodes": path, "steps": steps}


def generate(con, settings):
    return Expedition(con, settings).run()


DEFEAT_SOURCES = ("mage", "gem", "relic", "spell", "treasure")


def defeat_draw(con, settings, path, source, level=None, taken=()):
    """After a lost battle the players add one card to the Barracks, from the source they choose: a random
    mage, a gem / relic / spell randomizer, or a treasure deck already drawn from on this route.
    path: the battles of the route so far, ending with the lost one; taken: cards added after earlier defeats.
    The draw never repeats a card of this expedition (any branch) and is deterministic, so undoing and
    choosing the same source again gives the same card."""
    ex = Expedition(con, settings)
    exp = ex.run()
    route = next((r for r in exp["routes"] if r["nodes"][:len(path)] == list(path)), None) if path else None
    if not route:
        raise ValueError("this path is not part of the expedition")
    step = route["steps"][len(path) - 1]
    if source == "treasure":
        levels = sorted(int(lvl) for lvl in step["treasures_available"])
        if level not in levels:
            raise ValueError(f"no level {level} treasure deck drawn from yet (drawn: {levels or 'none'})")
        items = ex.rows("SELECT title, boxes FROM treasures WHERE level=? ORDER BY title", level)
    elif source == "mage":
        items = ex.rows("SELECT title, boxes FROM mages ORDER BY title")
    elif source in ("gem", "relic", "spell"):
        items = ex.supply_pool(source.capitalize())
    else:
        raise ValueError(f"unknown source: {source}")
    # a mage is never someone met on this route, or a version of a mage added after a defeat
    ex.node = path[-1]
    for t in taken:
        if c := ex.who.get(("mage", t)):
            ex.met.setdefault(c, set()).add(None)
    kind = "mage" if source == "mage" else None
    pool = [i["title"] for i in items if ex.is_owned(i) and i["title"] not in ex.used and i["title"] not in taken
            and not ex.blocked(ex.who.get((kind, i["title"])))]
    if not pool:
        raise LookupError(f"no {source} left to draw in your collection")
    rng = PRNG.stream(settings["seed"], f"defeat:{'-'.join(path)}:{len(taken)}:{source}:{level or ''}")
    return {"card": rng.choice(pool), "source": source, "level": level if source == "treasure" else None}


def settings_from_args(a, con):
    if a.code:
        settings, version = decode(a.code)
        current = int(con.execute("SELECT value FROM meta WHERE key='data_version'").fetchone()[0])
        if version != current:
            print(f"warning: this code was made with card data version {version}, the database is now {current}; "
                  "the expedition may differ from the original.", file=sys.stderr)
        return settings
    return resolve_settings(players=a.players, battles=a.battles, forks=a.forks, seed=a.seed,
                            boxes=[b.strip() for b in a.boxes.split(",") if b.strip()],
                            xaxos_outcast=a.xaxos_outcast, friends_foes=a.friends_foes,
                            campaign_mechanics=a.campaign_mechanics)


def add_arguments(ap):
    ap.add_argument("--code", help="share code: regenerates exactly that expedition")
    ap.add_argument("--players", type=int, choices=[1, 2, 3, 4])
    ap.add_argument("--battles", type=int, choices=[4, 5])
    ap.add_argument("--forks", type=int, choices=[1, 2], help="branch points (default: chosen by the seed)")
    ap.add_argument("--boxes", default="", help="comma-separated owned boxes (default: all)")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--xaxos-outcast", action="store_true", default=None)
    ap.add_argument("--friends-foes", action="store_true", default=None)
    ap.add_argument("--campaign-mechanics", action="store_true", default=None)


def print_sheet(exp):
    s = exp["settings"]
    print(f"EXPEDITION {exp['share_code']}  ({s['players']} players, {s['battles']} battles, {s['forks']} fork(s))")
    for f in exp["forks"]:
        print(f"  fork after battle {f['after']} ({f['kind']}): {' / '.join(f['options'])}")
    print("  starting Barracks:", ", ".join(exp["starting_barracks"]["mages"]))
    for nid, n in exp["nodes"].items():
        print(f"\n[{nid}] Battle {n['battle']}{' path ' + n['branch'].upper() if n['branch'] else ''}: "
              f"{n['nemesis']} (difficulty {n['difficulty']}) -> {', '.join(n['next']) or 'END'}")
        if "friend" in n:
            print(f"    friend: {n['friend']}  foe: {n['foe']}")
        for m in n["expedition_modifiers"]:
            print("    modifier:", m)
        print("    rewards:", {k: v for k, v in n["rewards"].items() if v} or "—")
    for r in exp["routes"]:
        print(f"\nroute {r['id']}")
        for st in r["steps"]:
            print(f"    {st['node']}: supply {', '.join(st['supply'])}")
    for w in exp["warnings"]:
        print("warning:", w)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    add_arguments(ap)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect(DB)
    exp = generate(con, settings_from_args(a, con))
    print(json.dumps(exp, ensure_ascii=False, indent=2) if a.json else "", end="")
    if not a.json:
        print_sheet(exp)


if __name__ == "__main__":
    main()
