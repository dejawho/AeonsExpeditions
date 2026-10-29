"""Turn a generated expedition into a light story, using only canon lore.

Reads the expedition produced by generate_expedition.Expedition.run(), the lore DB
(aeons_end.sqlite: nemesis_lore, lore_characters, story_kit, lore_texts), the prose templates in
lore/narrative_templates.json and the places in lore/settings.json.

Rules of the story:
  - no invented dialogue: the only quoted words are canon texts (nemesis mat stories, card flavor), at most
    one short excerpt per battle, about that nemesis and naming no other;
  - a battle's approach and the fork choices never name the nemesis (it is revealed when faced);
  - no template variant is used twice in one expedition, and every battle has its own place.
"""
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LORE_DB = ROOT / "data" / "db" / "aeons_end.sqlite"
TEMPLATES = ROOT / "lore" / "narrative_templates.json"
SETTINGS = ROOT / "lore" / "settings.json"

# Theme words (from nemesis_lore.themes / archetype) that point to each mission.
MISSION_THEMES = {
    "rescue_expedition": ["experiment", "transformed", "mad science", "rescue", "pet monster", "hubris"],
    "spreading_blight": ["nature", "plague", "corruption", "environment", "decay", "sickness", "petrification"],
    "harvest": ["harvest", "resources", "memory", "mental anchor", "breeder"],
    "the_hunt": ["hunt", "predator", "duel", "destiny", "cold", "beast", "feral"],
    "pilgrimage": ["pilgrimage", "escape", "threshold", "promised land", "grief"],
    "ruins_delve": ["lost home", "underwater", "archives", "lost history", "ancestors"],
    "outpost_defense": ["consequences", "fire", "swarm", "siege", "attrition", "tremors", "ambush"],
    "into_the_void": ["alien", "afterlife", "mirror", "entropy", "between worlds", "dimensions"],
    "the_traitor": ["betrayal", "cult", "manipulation", "civil war", "fallen friend", "temptation"],
    "time_fracture": ["time", "time travel", "inevitability", "false victory"],
}
# Canon narrators whose mat stories are not quoted: the Bishop of Scrolls tells his tales as a collector of
# Nameless for his army, a minor voice in the saga, and quoting him made every expedition read as his story.
# Those battles use the nemesis' origin and card flavor instead.
SKIPPED_NARRATORS = {"The Bishop of Scrolls"}
BREACH_SIGN = "the burnt-air smell of an opening breach"  # for a nemesis with too few curated signs
PROPER_FIRST_WORDS = {"Brama", "Xaxos", "Mist", "Quilius", "Gravehold", "Azer", "Rip", "Arachnos"}


QUOTE_LIMIT = 260  # characters of a canon excerpt: a sentence or two
COMMON_WORDS = {"Blight", "Coven", "Wrath", "Timeless", "Wanderer", "Fortress", "Reliquary", "Infecter"}
PLACE_NAMES = {"Erythiza"}  # a nemesis name that is also a place of the lore ('Erythiza, Consumed')


def nemesis_names(title):
    """How a text names a nemesis: 'Maelstrom: Risen' -> {'Maelstrom: Risen', 'Maelstrom'}, 'The Wailing' -> {'Wailing'}."""
    name = re.sub(r"^The ", "", short(title))
    return {name, re.split(r":|,", name)[0].strip()}


def name_index(con):
    """Every nemesis' names, and the names that are people or places too ('Xaxos: Ascended' -> Xaxos)."""
    names = {t: nemesis_names(t) for (t,) in con.execute("SELECT title FROM nemeses")}
    people = {n for (n,) in con.execute("SELECT name FROM lore_characters")} | PLACE_NAMES
    return names, people


def outsider_names(index, titles):
    """How a text would name a nemesis other than `titles` (people and places excluded)."""
    names, people = index
    own = {n for t in titles for n in names.get(t, nemesis_names(t))}
    return {n for t, ns in names.items() if t not in titles for n in ns
            if n not in COMMON_WORDS and n not in people and not any(n in o for o in own)}


def names_any(text, names):
    return any(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text) for n in names)


def canon_excerpt(text, own, others, limit=QUOTE_LIMIT):
    """The best short excerpt (1-3 whole sentences) of a canon text about one nemesis: it names that nemesis,
    never names another one, and does not open on a dangling pronoun. '' if nothing fits: no quote then."""
    sentences = [s for s in re.split(r"(?<=[.!?…])\s+", text.replace(" / ", " ").replace("\n", " ").strip()) if s]
    best = None
    for i in range(len(sentences)):
        for n in (1, 2, 3):
            window = sentences[i:i + n]
            excerpt = " ".join(window)
            if len(window) < n or len(excerpt) > limit:
                continue
            bare = excerpt
            for o in sorted(own, key=len, reverse=True):  # 'Blight Lord' must not count as 'Blight'
                bare = bare.replace(o, " ")
            if names_any(bare, others):
                continue
            score = (names_any(excerpt, own), not re.match(r"(It|Its|They|Their|This|These|He|She|His|Her)\b", window[0]),
                     len(excerpt), -i)
            if best is None or score > best[0]:
                best = (score, excerpt)
    return best[1] if best and best[0][0] else ""


def short(title):
    """'Brama (Legacy of Gravehold)' -> 'Brama'."""
    return re.sub(r"\s*\(.*?\)\s*$", "", title)


def cap(s):
    return s[:1].upper() + s[1:]


def lower_article(name):
    return "the " + name[4:] if name.startswith("The ") else name


def end_punct(s):
    s = s.strip()
    return s if re.search(r"[.!?…]['\"”’)]?$", s) else s.rstrip(";:,") + "."


def as_sentence(fragment):
    return end_punct(cap(fragment.strip()))


def as_clause(fragment):
    """Lower-case the first letter unless it starts a proper name (two capitalised words, a possessive...)."""
    s = fragment.strip().rstrip(".")
    proper = re.match(r"[A-Z][\w']+ [A-Z]|[A-Z][\w]*'s\b|[A-Z][a-z]+, ", s) or s.split(" ")[0] in PROPER_FIRST_WORDS
    return s if proper else s[:1].lower() + s[1:]


def join_names(names):
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def tidy(text):
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,!?])", r"\1", text)
    return re.sub(r'(^|[.!?]\s+)(["“]?)([a-z])', lambda m: m.group(1) + m.group(2) + m.group(3).upper(), text)


def title_case(phrase):
    small = {"of", "the", "a", "an", "in", "to", "where", "with", "under", "and", "beside", "over", "on", "by"}
    return " ".join(w if (i and w in small) or w[:1].isupper() else cap(w) for i, w in enumerate(phrase.split()))


class Storyteller:
    def __init__(self, rng, lore_db=LORE_DB):
        self.rng = rng
        self.con = sqlite3.connect(lore_db)
        self.t = json.loads(TEMPLATES.read_text(encoding="utf-8"))
        self.places = json.loads(SETTINGS.read_text(encoding="utf-8"))
        self.kit = {k: json.loads(v) for k, v in self.con.execute("SELECT key, value FROM story_kit")}
        self.sources = set()
        self.used_by = {}  # template variant / place -> battles (node ids; None = prologue) that used it
        self.routes = []  # node sets of every route, to know which texts one reader can meet
        self.node = None  # battle currently being written (None = prologue, title)
        # every nemesis' names, to keep a quote about one from naming another
        self.index = name_index(self.con)
        self.all_names = self.index[0]
        self.outsiders = set()  # names of nemeses not in this expedition: curated lore naming them is skipped
        self.secret_names = set()  # this expedition's nemeses: never in approach texts / choices

    # --- picking without repeats ----------------------------------------------------
    def conflicts(self, a, b):
        """Two texts conflict if one reader can meet both: same battle, the prologue/title (node None),
        or two battles that lie on a common route. Alternative branches (2a / 2b) never conflict."""
        return a is None or b is None or a == b or any(a in r and b in r for r in self.routes)

    def fresh(self, pool, optional=False):
        """A variant nobody on the same route has read yet. Optional pools return None once used up;
        required pools fall back to a repeat only if every variant has been used on this route."""
        unused = [p for p in pool if not any(self.conflicts(self.node, n) for n in self.used_by.get(p, ()))]
        # prefer variants already used on another branch (no reader meets both): this saves the
        # untouched ones for battles that lie on every route
        reusable = [p for p in unused if p in self.used_by]
        if reusable and self.node is not None:
            unused = reusable
        if not unused:
            if optional:
                return None
            unused = list(pool)
        choice = self.rng.choice(unused)
        self.used_by.setdefault(choice, set()).add(self.node)
        return choice

    def pick(self, pool, **values):
        return self.fresh(pool).format(**values)

    # --- lookups ------------------------------------------------------------------
    def q(self, sql, *args):
        cur = self.con.execute(sql, args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def nemesis(self, title):
        r = self.q("SELECT * FROM nemesis_lore WHERE title=?", title)
        if not r:
            return {"title": title, "era": None, "signs": [], "hook": "", "aftermath": "", "themes": [],
                    "archetype": "", "origin": "", "teaser": ""}
        r = r[0]
        for k in ("signs", "themes"):
            r[k] = json.loads(r[k])
        r["signs"] = [s for s in r["signs"] if self.about_here(s)]
        for k in ("hook", "aftermath", "origin", "teaser"):
            r[k] = self.about_here(r[k])
        self.sources.add(title)
        return r

    def character(self, mage_title):
        for c in self.q("SELECT * FROM lore_characters ORDER BY rowid"):
            if mage_title in json.loads(c["versions"]) or c["name"] == short(mage_title):
                c["eras"] = json.loads(c["eras"])
                c["epithets"] = json.loads(c["epithets"])
                return c
        return None

    def display(self, title):
        """Name as used mid-sentence: 'the Bishop of Scrolls', 'Rageborne', 'the Wailing'."""
        name = short(title)
        if name.startswith("The "):
            return "the " + name[4:]
        return name if name in self.t["nemeses_without_article"] else "the " + name

    def epithet(self, mage_title):
        """Official card title ('The Shield' -> 'the Shield'), else the curated epithet."""
        row = self.q("SELECT epithet FROM mages WHERE title=?", mage_title)
        if row and row[0]["epithet"]:
            return re.sub(r"^The ", "the ", row[0]["epithet"])
        c = self.character(mage_title)
        return c["epithets"][0] if c and c["epithets"] else None

    def setting(self, era_id):
        """A place of the story's era, never used before in this expedition."""
        pool = self.places.get(era_id) or self.places["new_gravehold"]
        free = [p for p in pool if p["name"] not in self.used_by] \
            or [p for p in pool if not any(self.conflicts(self.node, n) for n in self.used_by[p["name"]])] or pool
        place = self.rng.choice(free)
        self.used_by.setdefault(place["name"], set()).add(self.node)
        return place

    def atmosphere(self, era_id):
        return self.fresh(self.t["atmosphere"].get(era_id) or self.t["atmosphere"]["default"], optional=True)

    def other_names(self, title):
        return outsider_names(self.index, {title})

    def about_here(self, text):
        """A curated lore line, unless it names a nemesis that is not in this expedition."""
        return "" if text and names_any(text, self.outsiders) else text

    def chronicle(self, title):
        """A short excerpt of the nemesis' own mat story, with its narrator (see canon_excerpt)."""
        rows = self.q("SELECT speaker, text FROM lore_texts WHERE page=? AND source IN ('story','mention') ORDER BY id", title)
        if not rows:
            return ""
        if rows[0]["speaker"] in SKIPPED_NARRATORS:
            return ""
        speaker = rows[0]["speaker"]
        excerpt = canon_excerpt(rows[0]["text"], self.all_names.get(title, nemesis_names(title)), self.other_names(title))
        if not excerpt:
            return ""
        self.sources.add(title)
        if not speaker:
            return self.pick(self.t["chronicle_anonymous"], excerpt=excerpt)
        if re.match(r"(Excerpt from|A poem|From|The journal)", speaker, re.I):
            source = re.sub(r"^Excerpt from ", "From ", speaker).rstrip(".")
            key = "source:" + source  # the same journal quoted twice on a route: say so
            if any(self.conflicts(self.node, n) for n in self.used_by.get(key, ())):
                return self.pick(self.t["chronicle_source_again"], excerpt=excerpt)
            self.used_by.setdefault(key, set()).add(self.node)
            return self.pick(self.t["chronicle_source"], source=cap(source), excerpt=excerpt)
        return self.pick(self.t["chronicle_named"], speaker=speaker.split(",")[0].strip(), excerpt=excerpt)

    def old_warning(self, title):
        rows = self.q("""SELECT l.page, l.text FROM lore_texts l JOIN nemesis_cards n ON n.title = l.page
                         WHERE n.nemesis=? AND l.source='flavor' AND length(l.text) < 200 ORDER BY l.id""", title)
        if not rows:
            return ""
        others = self.other_names(title)
        rows = [r for r in rows if not names_any(r["text"], others)]
        if not rows:
            return ""
        r = self.rng.choice(rows)
        self.sources.add(r["page"])
        return self.pick(self.t["old_warning"], flavor=end_punct(r["text"].replace("\n", " ").strip().strip('"')))

    # --- planning -------------------------------------------------------------
    def choose_era(self, nemeses):
        votes = {}
        for i, n in enumerate(nemeses):
            if n["era"] and n["era"] not in ("all", "unknown"):
                votes[n["era"]] = votes.get(n["era"], 0) + 1 + (i == len(nemeses) - 1)  # the finale counts double
        era = max(votes, key=votes.get) if votes else "new_gravehold"
        return self.q("SELECT * FROM lore_eras WHERE id=?", era)[0]

    def choose_mission(self, nemeses, era_id):
        scores = {}
        for m in self.kit["missions"]:
            words = MISSION_THEMES.get(m["id"], [])
            s = sum(1 for n in nemeses for th in n["themes"] + [n["archetype"]] if any(w in th for w in words))
            scores[m["id"]] = s + (2 if era_id in m["eras"] else 0)
        best = sorted(scores, key=scores.get, reverse=True)[:2]
        mid = self.rng.choice(best)
        return next(m for m in self.kit["missions"] if m["id"] == mid)

    def choose_quest_giver(self, era_id, party, people=()):
        """people: every character met in the expedition (recruits, friends, foes, a mage who is a nemesis)."""
        pool = [g for g in self.kit["quest_givers"].get(era_id, ["the Council of Elders"])
                if not any(short(p) in g for p in party) and not any(s in g for s in self.secret_names)
                and not names_any(g, people)] \
            or ["the Council of Elders"]
        giver = self.rng.choice(pool)
        chunk = re.split(r",| at | of | in | returned ", giver)[0].strip()
        if chunk.lower().startswith("the "):
            giver_short = "the " + chunk.split()[1]
        else:
            for title in self.t["quest_giver_titles"]:
                chunk = chunk.removeprefix(title + " ")
            giver_short = chunk
        return giver, giver_short

    # --- the parts of a battle ---------------------------------------------------------
    def plan_node(self, node, era_id):
        n = self.nemesis(node["nemesis"])
        signs = n["signs"] or ["a sudden silence"]
        return {"lore": n, "name": self.display(node["nemesis"]), "place": self.setting(era_id), "signs": signs,
                "sign1": signs[0], "sign2": signs[1] if len(signs) > 1 else BREACH_SIGN}

    def approach(self, plan, era_id, position, heralded=False):
        """Before the fight: the journey, the place, the signs. Never names the nemesis.
        heralded: the first sign was already told (the last victory's news, or a fork option), so the
        arrival shows what the news did not say instead of repeating it."""
        place, n = plan["place"], plan["lore"]
        p1 = " ".join(x for x in [self.fresh(self.t["travel"][position]), self.atmosphere(era_id)] if x)
        p2 = " ".join([self.pick(self.t["arrive"], setting=place["name"]), place["detail"]])
        clause = lambda s: as_clause(s).rstrip("!?.'")  # noqa: E731
        new = plan["signs"][1:3] if heralded else [plan["sign1"], plan["sign2"]]
        if len(new) == 2:
            signs = self.pick(self.t["signs"], s1=clause(new[0]), s2=clause(new[1]))
        else:
            signs = self.pick(self.t["signs_more"], s1=clause(new[0] if new else BREACH_SIGN))
        p3 = " ".join(x for x in [signs, n["hook"]] if x)
        p4 = self.fresh(self.t["tension"])
        return [tidy(p) for p in (p1, p2, p3, p4) if p]

    def encounter(self, node, plan, displaced):
        n, name = plan["lore"], plan["name"]
        p1 = [self.pick(self.t["encounter"], nemesis=name, nemesis_cap=cap(name))]
        if n["archetype"]:
            p1.append(self.pick(self.t["archetype"], archetype=n["archetype"].replace(" / ", " and ")))
        if displaced:  # optional: once every variant is used, say nothing rather than repeat
            p1.append(self.fresh(self.t["displaced"], optional=True) or "")
        chronicle = self.chronicle(node["nemesis"])
        paragraphs = [" ".join(p1), chronicle]
        # one quote per battle at most: card flavor only for a nemesis with no mat story at all
        has_story = self.q("SELECT 1 FROM lore_texts WHERE page=? AND source IN ('story','mention') LIMIT 1", node["nemesis"])
        p3 = [] if chronicle or has_story else [x for x in [self.old_warning(node["nemesis"])] if x]
        if node.get("friend"):
            p3.append(self.pick(self.t["friend_foe"], friend=node["friend"].split(",")[0], foe=lower_article(node["foe"])))
        p3.append(self.fresh(self.t["to_battle"]))
        paragraphs.append(" ".join(p3))
        return [tidy(p) for p in paragraphs if p]

    def treasure_text(self, rewards):
        if not rewards.get("treasures"):
            return ""
        shown = rewards["treasures"][:3]
        self.sources.update(shown)
        return self.pick(self.t["treasure_sentence"][str(rewards["treasure_level"])], treasures=join_names(shown))

    def recruit_text(self, rewards):
        out = ""
        for m in rewards.get("mages", []):
            c = self.character(m)
            # the first two sentences of their lore that name no nemesis the players never meet
            kept = [s for s in c["summary"].split(". ") if not names_any(s, self.outsiders)] if c else []
            intro = " ".join(kept[:2]).rstrip(".") + "." if kept else ""
            out = self.pick(self.t["recruit"], ally=short(m), ally_intro=intro)
            self.sources.add(m)
        return out

    def victory(self, node, plan, plans, forks):
        n, name = plan["lore"], plan["name"]
        p1 = " ".join(x for x in [self.pick(self.t["victory"], nemesis=name, nemesis_cap=cap(name)),
                                  as_sentence(n["aftermath"]) if n["aftermath"] else ""] if x)
        p2 = " ".join(x for x in [self.treasure_text(node["rewards"]), self.recruit_text(node["rewards"])] if x)
        p3 = self.pick(self.t["reflection_origin"], origin=n["origin"]) if n["origin"] else ""
        if node["final"]:
            p4 = self.fresh(self.t["final_victory"])
        elif node["id"] in forks:
            p4 = ""
        else:
            p4 = self.pick(self.t["next_clue"], next_sign=as_clause(plans[node["next"][0]]["sign1"]).rstrip("!?."))
        return [tidy(p) for p in (p1, p2, p3, p4) if p]

    def choice(self, fork, plans, nodes):
        """The fork: each road shows its place and a vague hint of what waits there (never a name)."""
        a, b = fork["options"]
        diff = {o: nodes[o]["difficulty"] or 0 for o in (a, b)}
        options = []
        for label, o, other in (("A", a, b), ("B", b, a)):
            place, n = plans[o]["place"], plans[o]["lore"]
            teaser = n.get("teaser") or f"The scouts report {as_clause(plans[o]['sign1']).rstrip('!?.')}."
            harder = diff[o] >= diff[other] + 2
            options.append({"node": o, "label": label, "setting": place["name"],
                            "text": tidy(self.pick(self.t["fork_option"], setting_cap=cap(place["name"]), teaser=teaser)),
                            "harder": harder, "note": self.t["harder_note"] if harder else ""})
        note = self.fresh(self.t["finale_note" if fork["kind"] == "finale" else "detour_note"])
        return {"kind": fork["kind"], "intro": self.fresh(self.t["fork_intro"]), "options": options, "note": note}

    def defeat(self, plan, rescuers):
        name = plan["name"]
        p1 = self.pick(self.t["defeat"], rescuer=self.rng.choice(rescuers), nemesis=name, nemesis_cap=cap(name))
        # the last sign: the first one has already been told before the battle, often twice
        p2 = " ".join([self.pick(self.t["regroup"], setting=plan["place"]["name"]),
                       self.pick(self.t["escalation"], sign=as_clause(plan["signs"][-1]).rstrip("!?."), nemesis_cap=cap(name))])
        return [tidy(p1), tidy(p2)]

    def epilogue(self, party, giver_short, twist):
        p1 = self.pick(self.t["epilogue_return"], party=join_names(short(p) for p in party))
        p2 = self.pick(self.t["epilogue_report"], quest_giver_short=giver_short, twist=twist)
        p3 = " ".join([self.fresh(self.t["epilogue_rest"]), self.fresh(self.t["final_hook"])])
        return [tidy(p) for p in (p1, p2, p3)]

    # --- the whole expedition -----------------------------------------------------------
    def tell(self, exp):
        nodes, forks = exp["nodes"], {f["from"]: f for f in exp["forks"]}
        self.routes = [set(r["nodes"]) for r in exp["routes"]]
        self.outsiders = outsider_names(self.index, {n["nemesis"] for n in nodes.values()})
        for n in nodes.values():  # 'The Wailing' -> 'Wailing', 'Maelstrom: Risen' -> 'Maelstrom', 'Erythiza, Consumed' -> 'Erythiza'
            name = re.sub(r"^The ", "", short(n["nemesis"]))
            self.secret_names.update({name, re.split(r":|,", name)[0].strip()})
        nem = [self.nemesis(n["nemesis"]) for n in nodes.values()]
        finals = [self.nemesis(n["nemesis"]) for n in nodes.values() if n["final"]]
        era = self.choose_era(nem + finals)  # endings count double
        mission = self.choose_mission(nem, era["id"])
        mt = self.t["missions"][mission["id"]]
        party = exp["starting_barracks"]["mages"]
        met = party + [m for n in nodes.values() for m in n["rewards"].get("mages", [])] \
            + [n[k] for n in nodes.values() for k in ("nemesis", "friend", "foe") if n.get(k)]
        people = {c["name"] for t in met if (c := self.character(t))}  # Knight of Shackles -> Thraxir
        giver, giver_short = self.choose_quest_giver(era["id"], party, people)

        # The title never names a nemesis or hints at forks. It borrows a place of the era not used in battle.
        title_place = title_case(self.rng.choice(self.places.get(era["id"]) or self.places["new_gravehold"])["name"])
        title = self.pick(self.t["titles"], mission_name=mt["name"], place_title=title_place,
                          place_title_mid=re.sub(r"^(The|A|An) ", lambda m: m.group(1).lower() + " ", title_place),
                          place_title_short=re.sub(r"^(The|A|An) ", "", title_place))
        story = {"title": tidy(title), "era": era["name"], "mission": mt["name"], "quest_giver": giver,
                 "share_code": exp["share_code"], "chapters": {}, "epilogues": {}}

        # an epithet can spoil a nemesis: Nook, Timeless while The Timeless waits ahead
        intros = [f"{short(p)}, {e}" if (e := self.epithet(p)) and not names_any(e, self.secret_names) else short(p)
                  for p in party]
        party_intro = "; ".join(intros[:-1]) + " and " + intros[-1] if len(intros) > 1 else intros[0]
        prologue = [self.pick(mt["prologue"], quest_giver=giver, quest_giver_short=giver_short,
                              omen=self.fresh(self.t["omens"])),
                    " ".join(x for x in [self.atmosphere(era["id"]),
                                         self.pick(self.t["party"], quest_giver_short=cap(giver_short), party_intro=party_intro),
                                         self.fresh(self.t["departure"])] if x)]
        outsiders = [short(p) for p in party
                     if (c := self.character(p)) and era["id"] not in c["eras"] and "all" not in c["eras"]]
        if outsiders:
            bridges = [b for b in self.kit["era_bridges"]["bridges"] if b["explains"] in ("people", "both")]
            bridge = self.rng.choice([b for b in bridges if not any(s in b["text"] for s in self.secret_names)
                                      and not names_any(b["text"], self.outsiders)] or bridges)
            self.sources.update(bridge["sources"])
            prologue.append(self.pick(self.t["era_bridge"], bridge=bridge["text"], outsiders=join_names(outsiders)))
        story["prologue"] = [tidy(p) for p in prologue]

        plans = {}
        for nid, n in nodes.items():
            self.node = nid
            plans[nid] = self.plan_node(n, era["id"])
        # a battle is heralded when its first sign was told before: in the news after the previous victory,
        # or in the fork option leading to it (when its lore has no teaser of its own)
        preds = {nid: [a for a, b in exp["edges"] if b == nid] for nid in nodes}
        heralded = {nid: any(p not in forks or not plans[nid]["lore"].get("teaser") for p in preds[nid]) for nid in nodes}
        rescuers = [r for r in self.kit["loss_rescuers"] if not any(short(p) == r for p in party)] or ["a patrol"]
        final_nodes = [nid for nid, n in nodes.items() if n["final"]]
        twists = self.rng.sample(self.kit["twists"], len(final_nodes))
        for nid, node in nodes.items():
            self.node = nid
            plan, lore = plans[nid], plans[nid]["lore"]
            position = "first" if node["battle"] == 1 else "final" if node["final"] else "middle"
            displaced = bool(lore["era"] and lore["era"] not in (era["id"], "all", "unknown"))
            story["chapters"][nid] = {
                "battle": node["battle"], "branch": node["branch"], "nemesis": node["nemesis"],
                "setting": plan["place"]["name"], "place": title_case(plan["place"]["name"]),
                "approach": self.approach(plan, era["id"], position, heralded[nid]),
                "encounter": self.encounter(node, plan, displaced),
                "victory": self.victory(node, plan, plans, forks),
                "defeat": self.defeat(plan, rescuers),
                "choice": self.choice(forks[nid], plans, nodes) if nid in forks else None,
            }
            if node["final"]:
                story["epilogues"][nid] = self.epilogue(party, giver_short, twists.pop())
        story["sources"] = sorted(self.sources)
        return story


def route_map(exp, reveal=False):
    """Markdown road map. Unless revealed, future forks stay hidden: one '?' per battle."""
    by_battle = {}
    for n in exp["nodes"].values():
        by_battle.setdefault(n["battle"], []).append(n)
    parts = []
    for b, ns in sorted(by_battle.items()):
        if not reveal:
            parts.append(f"**{b}.** ?")
        elif len(ns) == 1:
            parts.append(f"**{b}.** {short(ns[0]['nemesis'])}")
        else:
            parts.append(f"**{b}.** " + " | ".join(f"*{n['branch'].upper()}:* {short(n['nemesis'])}" for n in ns))
    return " → ".join(parts)


def deck_recipe(node):
    deck = node["nemesis_deck"]
    return " · ".join(f"T{t}: {len(deck[f'tier_{t}']['nemesis'])} nemesis + {len(deck[f'tier_{t}']['basic'])} basic"
                      f" + {len(deck[f'tier_{t}']['upgraded_basic'])} upgraded basic" for t in (1, 2, 3))


def to_markdown(exp, story, reveal=True):
    s = exp["settings"]
    out = [f"# {story['title']}",
           f"*{story['mission']} — {story['era']} — {s['players']} players, {s['battles']} battles*", "",
           f"**Share code:** `{exp['share_code']}`", "", "**The road ahead:** " + route_map(exp, reveal), ""]
    out += story["prologue"] + [""]
    for nid, ch in story["chapters"].items():
        node = exp["nodes"][nid]
        path = f" — Path {ch['branch'].upper()}" if ch["branch"] else ""
        out += [f"## Battle {ch['battle']}{path}: {ch['place']}", ""] + ch["approach"]
        out += ["", f"### {short(ch['nemesis'])}", ""] + ch["encounter"] + [""]
        setup = []
        if node.get("friend"):
            setup.append(f"**Friend / foe:** {node['friend']} / {node['foe']}")
        if node["treasure_setup"]:
            setup.append("**Treasures:** " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in node["treasure_setup"].items()))
        for m in node["expedition_modifiers"]:
            setup.append(f"**Expedition modifier:** {m}")
        setup.append("**Nemesis deck (random basics from your collection):** " + deck_recipe(node))
        r = node["rewards"]
        if r:
            gained = [f"level {r['treasure_level']} treasures: {', '.join(r['treasures'])}"] if r.get("treasures") else []
            gained += [f"mage: {', '.join(r['mages'])}"] if r.get("mages") else []
            gained += [f"player cards: {', '.join(r['player_cards'] + r.get('extra_player_cards', []))}"]
            setup.append("**Rewards:** " + "; ".join(gained))
        out += ["> " + "  \n> ".join(setup), "", "**If you win.**", ""] + ch["victory"] + [""]
        if ch["choice"]:
            c = ch["choice"]
            out += [f"{c['intro']} {c['note']}"]
            out += [f"- **Path {o['label']}** — {o['text']} {o['note']}".rstrip() for o in c["options"]] + [""]
        out += ["**If you lose.**", ""] + ch["defeat"] + [""]
        if nid in story["epilogues"]:
            out += [f"### Epilogue{path}", ""] + story["epilogues"][nid] + [""]
    out += ["## Route sheets", "", "Suggested supply for each battle along each route (players may choose differently).", ""]
    for route in exp["routes"]:
        out += [f"**Route {route['id']}**", ""]
        out += [f"- Battle {st['node']}: {', '.join(st['supply'])}" for st in route["steps"]] + [""]
    out += ["---", "*Lore and card text from the [Aeon's End Wiki](https://aeonsend.wiki.gg/) (CC BY-SA 4.0): "
            + ", ".join(story["sources"]) + ".*"]
    return "\n".join(out)
