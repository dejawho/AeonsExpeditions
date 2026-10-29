"""Optional AI rewrite of an expedition's story, on top of the template story (storyteller.py).

The template story stays the source of truth: it already has every fact right (places, rewards,
which battle hides which nemesis). The model only rewrites the prose, from a lore bundle cut down
to this one expedition (not the whole DB). Everything it returns is checked chapter by chapter,
and any chapter that breaks a rule falls back to the template text:

  - no invented dialogue: quoted words must be canon texts given in the bundle;
  - spoilers: the title, prologue, approaches and fork texts never name a nemesis of the expedition;
    a chapter's encounter / victory / defeat names only its own nemesis;
  - facts: the treasures, recruits and friend / foe named by the template are still named;
  - branches: no sentence repeats along any route.

This module makes no network call: backend/llm.py sends the prompt to the provider.
"""
import copy
import json
import re
import sqlite3
from pathlib import Path

from storyteller import (LORE_DB, PLACE_NAMES, SETTINGS, SKIPPED_NARRATORS, canon_excerpt, name_index, names_any,
                         nemesis_names, outsider_names, short)

PROMPT_VERSION = 6
SECTIONS = ("approach", "encounter", "victory", "defeat")
MAX_PARAGRAPH = 1400  # characters
MAX_PARAGRAPHS = 6

_strs = {"type": "array", "items": {"type": "string"}}
# One fixed schema for every expedition (the API caches a compiled schema for 24 hours).
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outline", "title", "prologue", "chapters", "epilogues"],
    "properties": {
        # written first: the plan that ties the battles together (kept in the report, never shown)
        "outline": {
            "type": "object", "additionalProperties": False, "required": ["question", "steps", "threads", "endings"],
            "properties": {
                "question": {"type": "string"},
                "steps": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["battle", "learned"],
                    "properties": {"battle": {"type": "integer"}, "learned": {"type": "string"}}}},
                "threads": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["thread", "opened_in", "closed_in"],
                    "properties": {"thread": {"type": "string"}, "opened_in": {"type": "string"},
                                   "closed_in": {"type": "array", "items": {"type": "string"}}}}},
                "endings": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["node", "answer"],
                    "properties": {"node": {"type": "string"}, "answer": {"type": "string"}}}},
            }},
        "title": {"type": "string"},
        "prologue": _strs,
        "chapters": {"type": "array", "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["node", *SECTIONS, "fork_intro", "fork_options", "fork_note"],
            "properties": {
                "node": {"type": "string"},
                **{s: _strs for s in SECTIONS},
                "fork_intro": {"type": "string"},
                "fork_options": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["node", "text"],
                    "properties": {"node": {"type": "string"}, "text": {"type": "string"}}}},
                "fork_note": {"type": "string"},
            }}},
        "epilogues": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["node", "paragraphs"],
            "properties": {"node": {"type": "string"}, "paragraphs": _strs}}},
    },
}

SYSTEM = """You are the narrator of an Aeon's End expedition: a short branching campaign of the cooperative \
deck-building board game, where the players' breach mages defend Gravehold from the Nameless. You rewrite the \
narration of one expedition so it reads like a coherent, atmospheric tale grounded in the canon lore you are given.

You receive a JSON bundle with:
- "expedition": era, the mission (its premise and beats), quest giver, the party of mages;
- "thread": which mission beat each battle number should carry, and the twist each ending must land;
- "map": every battle (node), which battles can come before it ("after") and the complete routes a group can play;
- "chapters": for each battle its place, its nemesis and that nemesis' canon lore ("quotable" excerpts and \
"background"), the rewards and the one-battle allies;
- "template": the current text of the story, written from fixed templates. It has every fact right but reads \
like separate episodes. Your job is to rewrite it as one story.

First write the "outline": the mission's question (what the party must find out or stop), then for each battle \
number what the party learns or loses there that moves the mission forward, then the "threads": every hint, \
mystery, suspect or character arc you open (a foe that echoes the mission, a cloaked figure, a recruit's past...), \
the node where it opens ("prologue" or a node id) and the nodes that close it (battles, or final nodes for their \
epilogue). Check them against "map.routes": every route that passes where a thread opens must pass one of the \
nodes that close it. Then, for each final node, how its epilogue answers the question (using that ending's \
twist). Then write the story from the outline:
- The mission is the spine. The prologue asks its question; every victory ends on what was learned and where it \
points; every approach picks that up, so the party travels for a reason; the final battle confronts the source; \
each epilogue answers the question. Nothing the story hints at may be left hanging.
- Plan by battle number, not by branch: both battles of a fork carry the same step of the thread (in their own \
way), so the battle after a fork can follow up on it whichever branch was played.
- The party are the protagonists. In every chapter at least one party mage acts in a way true to their lore \
(skills, temper, history), and the party's mood carries from one battle to the next. A recruited mage, once \
they join (in the victory where the template names them), travels with the party from then on: mention them \
in later chapters of the routes that pass through that battle, never in chapters that can come before it.

Rules. Breaking one makes the app throw your chapter away, so follow them exactly:
1. No dialogue. Nobody speaks in quotation marks. The only quoted words allowed are a chapter's own "quotable" \
excerpts, copied verbatim and attributed to their speaker: at most ONE quote per chapter, and none at all in the \
title, prologue, approaches, forks and epilogues. Quotes weaken a story when there are many: often the best \
chapter has none, and tells the lore in your own words ("background" is for that, never to be quoted). Describe the situation \
instead: what the mages see, hear and do. Brief reported speech is fine. Canon narrators (Indira, Xaxos, \
Yan Magda...) are people with their own limited view, not all-knowing chroniclers: quote at most one canon text \
per chapter, as a short verbatim excerpt (a sentence or two), never present it as truth or prophecy, and never \
bring the narrator into the story unless they are in the party or the allies. Never mention a nemesis that \
is not in this expedition, even one the lore compares it to.
2. Secrets. The players must not learn a nemesis before they face it. The title, the prologue, every "approach" \
and every fork text (fork_intro, fork_options, fork_note) must never name any nemesis listed in \
"expedition.nemeses", nor quote their canon texts. Hint at what waits through its signs, its hook and its teaser. \
A chapter's "encounter", "victory" and "defeat" may name that chapter's own nemesis and no other. An epilogue \
may name only the nemesis of its own final battle.
3. Branches. A battle can be reached from different battles ("after"), so its approach must read well after any \
of them: refer to the thread step reached at the previous battle number, never to a place, nemesis, ally or \
event that only one of those branches contains. Fork options describe the road and hint at what waits there; \
keep each option's place.
4. Facts. Keep the places, the party, the quest giver, the era. In each victory, name every treasure and every \
recruited mage the template names, with their exact names. If a chapter has a friend and a foe, name them in its \
encounter. They belong to that one battle (see "allies"): the friend is met at that place, fights beside you and \
is given a farewell in the victory (stays behind, goes their own way); the foe is a danger of that battle only \
and ends with it. Do not bring them back in another chapter, unless the same card is drawn again on that route \
(then it is the same person returning: say so). Never leave a foe as a loose hint: a foe whose name echoes the \
mission (a foe called "The Traitor" in a traitor mission) is either resolved in the outline on every route that \
meets it, or kept a danger of that battle only. Never invent named characters, places, factions or events; you may only use the lore in the bundle. \
Do not contradict it. Do not mention game mechanics (cards, life points, turns). Use each character's "pronouns"; when they are "unknown" or a character has no lore, use the name or "they".
5. Voice. Second person plural ("you"), present tense, as in the template. Grounded, concrete, sensory, with the \
era's tone; quiet dread before a fight, exhaustion and cost after it. No purple prose, no clichés ("tapestry", \
"testament to", "a sense of"), no exclamation marks, no headings or markdown.
6. Variety. No sentence, and no paragraph opening, may appear twice along any route. Battles on different branches \
of the same fork may share nothing either: write each one fresh.
7. Length. prologue 2-3 paragraphs; approach 2-4; encounter 2-3; victory 2-4; defeat 1-2; each epilogue 2-3. \
Paragraphs of 2-5 sentences. A fork_intro is one sentence, each fork option one or two, the fork_note one.

Output JSON only, following the schema: one entry in "chapters" for every node of the map (same node ids), one \
entry in "epilogues" for every final node. For a battle with no fork, set fork_intro and fork_note to "" and \
fork_options to []. For a battle with a fork, give the options in the template's order with the same node ids."""


def _rows(con, sql, *args):
    cur = con.execute(sql, args)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _json(v, default):
    try:
        return json.loads(v) if v else default
    except ValueError:
        return default


def _character(con, title):
    for c in _rows(con, "SELECT name, pronouns, epithets, versions, summary, traits FROM lore_characters ORDER BY rowid"):
        if title in _json(c["versions"], []) or c["name"] == short(title):
            return {"name": c["name"], "pronouns": c["pronouns"] or "unknown", "epithets": _json(c["epithets"], []),
                    "summary": c["summary"], "traits": _json(c["traits"], [])}
    return None


def _place_details():
    places = json.loads(Path(SETTINGS).read_text(encoding="utf-8"))
    return {p["name"]: p["detail"] for era, pool in places.items() if not era.startswith("_") for p in pool}


def _canon_texts(con, nemesis, index):
    """What may be quoted about a nemesis (short excerpts, never naming another one), and its mat story as
    background, minus the sentences about other nemeses."""
    texts = _rows(con, "SELECT speaker, text FROM lore_texts WHERE page=? AND source IN ('story','mention') ORDER BY id",
                  nemesis)
    flavor = _rows(con, """SELECT l.text FROM lore_texts l JOIN nemesis_cards n ON n.title = l.page
                           WHERE n.nemesis=? AND l.source='flavor' AND length(l.text) < 220 ORDER BY l.id LIMIT 4""",
                   nemesis)
    own, others = index[0].get(nemesis, nemesis_names(nemesis)), outsider_names(index, {nemesis})
    quotable, background = [], []
    for t in texts:
        if t["speaker"] in SKIPPED_NARRATORS:
            continue
        if excerpt := canon_excerpt(t["text"], own, others):
            quotable.append({"speaker": t["speaker"] or "", "text": excerpt})
        sentences = re.split(r"(?<=[.!?…])\s+", t["text"].replace(" / ", " ").replace("\n", " "))
        background.append(" ".join(s for s in sentences if not names_any(s, others)))
    for f in flavor:
        line = f["text"].replace("\n", " ").strip().strip('"')
        if not names_any(line, others):
            quotable.append({"speaker": "card flavor", "text": line})
    return quotable, background


def _mission(con, story):
    kit = {k: _json(v, None) for k, v in con.execute("SELECT key, value FROM story_kit WHERE key IN ('missions', 'twists')")}
    mission = next((m for m in kit["missions"] if m["name"].lower() == story["mission"].lower()), None) \
        or {"name": story["mission"], "premise": "", "beats": []}
    twists = {nid: next((t for t in kit["twists"] if t in " ".join(paras)), "") for nid, paras in story["epilogues"].items()}
    return {"name": story["mission"], "premise": mission.get("premise", ""), "beats": mission.get("beats", [])}, twists


def _thread(exp, mission, twists):
    """Which mission beat each battle number carries: the first, the middle ones, the finale."""
    beats, last = mission["beats"], max(n["battle"] for n in exp["nodes"].values())
    steps = []
    for b in range(1, last + 1):
        if not beats:
            beat = ""
        elif b == 1:
            beat = beats[0]
        elif b == last:
            beat = beats[-1]
        else:
            beat = beats[min(len(beats) - 2, 1 + (b - 2) * max(1, len(beats) - 2) // max(1, last - 2))] \
                if len(beats) > 2 else beats[0]
        steps.append({"battle": b, "beat": beat})
    return {"steps": steps, "endings": [{"node": nid, "twist": t} for nid, t in twists.items()]}


def secret_names(exp):
    """Name variants of every nemesis of the expedition: 'Maelstrom: Risen' -> {'Maelstrom: Risen', 'Maelstrom'}."""
    mages = {short(m) for m in exp["starting_barracks"]["mages"]}
    mages |= {short(m) for n in exp["nodes"].values() for m in n["rewards"].get("mages", [])}
    out = {}
    for n in exp["nodes"].values():
        name = re.sub(r"^The ", "", short(n["nemesis"]))
        # 'Xaxos: Ascended' must not ban the mage Xaxos
        variants = {name, re.split(r":|,", name)[0].strip()} - mages - PLACE_NAMES
        out[n["nemesis"]] = {v for v in variants if len(v) > 3}
    return out


def build_bundle(exp, story, con=None):
    """Everything the model needs about this expedition, and nothing else (con: the lore DB)."""
    con = con or sqlite3.connect(f"file:{LORE_DB}?mode=ro", uri=True)
    index = name_index(con)
    outsiders = outsider_names(index, {n["nemesis"] for n in exp["nodes"].values()})
    nodes = exp["nodes"]
    details = _place_details()
    era = _rows(con, "SELECT id, name, when_text, summary, tone FROM lore_eras WHERE name=?", story["era"])
    era = era[0] if era else {"name": story["era"]}
    mission, twists = _mission(con, story)
    after = {nid: sorted({r["nodes"][i - 1] for r in exp["routes"] for i, x in enumerate(r["nodes"]) if x == nid and i})
             for nid in nodes}
    party = []
    for m in exp["starting_barracks"]["mages"]:
        c = _character(con, m)
        party.append({"name": short(m), **({"lore": c} if c else {})})
    chapters = []
    for nid, n in nodes.items():
        ch = story["chapters"][nid]
        lore = _rows(con, "SELECT archetype, origin, signs, aftermath, hook, themes, teaser FROM nemesis_lore WHERE title=?",
                     n["nemesis"])
        lore = lore[0] if lore else {}
        for k in ("signs", "themes"):
            if k in lore:
                lore[k] = _json(lore[k], [])
        # like the template: no curated line about a nemesis the players never meet
        lore = {k: ([x for x in v if not names_any(x, outsiders)] if isinstance(v, list)
                    else "" if isinstance(v, str) and names_any(v, outsiders) else v) for k, v in lore.items()}
        rewards = n["rewards"]
        entry = {
            "node": nid, "battle": n["battle"], "final": n["final"], "after": after[nid],
            "place": ch["setting"], "place_detail": details.get(ch["setting"], ""),
            "nemesis": {"name": short(n["nemesis"]), **lore,
                        **dict(zip(("quotable", "background"), _canon_texts(con, n["nemesis"], index)))},
            "rewards": {"treasures_named": rewards.get("treasures", [])[:3],
                        "recruits": [{"name": short(m), **({"lore": c} if (c := _character(con, m)) else {})}
                                     for m in rewards.get("mages", [])]},
        }
        if n.get("friend"):
            entry["allies"] = {"note": "Friends & Foes cards: they exist for this battle only"}
            for role in ("friend", "foe"):
                note = _rows(con, "SELECT note FROM friend_foe_lore WHERE title=?", n[role])
                entry["allies"][role] = {"name": n[role], "note": note[0]["note"] if note else ""}
        if ch.get("choice"):
            entry["fork"] = {"kind": ch["choice"]["kind"],
                             "meaning": "the two roads rejoin later" if ch["choice"]["kind"] == "detour"
                             else "the two roads lead to different final battles",
                             "options": [{"node": o["node"], "place": o["setting"]} for o in ch["choice"]["options"]]}
        chapters.append(entry)
    template = {
        "title": story["title"], "prologue": story["prologue"],
        "chapters": [{"node": nid, **{s: c[s] for s in SECTIONS},
                      **({"fork": {"intro": c["choice"]["intro"], "note": c["choice"]["note"],
                                   "options": [{"node": o["node"], "text": o["text"]} for o in c["choice"]["options"]]}}
                         if c.get("choice") else {})}
                     for nid, c in story["chapters"].items()],
        "epilogues": [{"node": nid, "paragraphs": p} for nid, p in story["epilogues"].items()],
    }
    return {
        "expedition": {"era": era, "mission": mission, "quest_giver": story["quest_giver"],
                       **({"quest_giver_lore": g} if (g := _character(con, story["quest_giver"])) else {}),
                       "players": exp["settings"]["players"], "party": party,
                       "nemeses": sorted({short(n["nemesis"]) for n in nodes.values()})},
        "thread": _thread(exp, mission, twists),
        "map": {"nodes": [{"node": nid, "battle": n["battle"], "final": n["final"], "after": after[nid],
                           "next": n["next"]} for nid, n in nodes.items()],
                "routes": [r["nodes"] for r in exp["routes"]]},
        "chapters": chapters,
        "template": template,
        "_other_nemeses": sorted(outsiders),
    }


def user_prompt(bundle):
    return ("Rewrite the narration of this expedition, following the rules.\n\n"
            + json.dumps(bundle, ensure_ascii=False, indent=1))


# --- checking and merging -------------------------------------------------------------------
# a quote is “...” (which may hold a "nested" one), "..." or «...»
QUOTE = re.compile(r'“([^”]{12,})”|"([^"]{12,})"|«([^»]{12,})»')


def quotes(text):
    return ["".join(m) for m in QUOTE.findall(text)]


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _paragraphs(value, lo=1, hi=MAX_PARAGRAPHS):
    if not isinstance(value, list) or not lo <= len(value) <= hi:
        return None
    out = [re.sub(r"\s+", " ", p).strip() for p in value if isinstance(p, str)]
    if len(out) != len(value) or any(not p or len(p) > MAX_PARAGRAPH for p in out):
        return None
    return out


class Checker:
    def __init__(self, exp, story, bundle):
        self.exp, self.story = exp, story
        self.secrets = secret_names(exp)
        corpus = [json.dumps(bundle["template"], ensure_ascii=False)]
        corpus += [t["text"] for c in bundle["chapters"] for t in c["nemesis"]["quotable"]]
        self.canon = _norm(" ".join(corpus))
        self.outsiders = bundle.get("_other_nemeses", [])
        # proper names allowed anywhere: they may contain a nemesis' name ('Eye of the Maelstrom')
        names = set()
        for n in exp["nodes"].values():
            names.update(n["rewards"].get("treasures", []))
            names.update(n.get(k) for k in ("friend", "foe") if n.get(k))
        names.update(c["setting"] for c in story["chapters"].values())
        names.update([story["mission"], story["quest_giver"]])  # 'The Spreading Blight' is a mission, not a spoiler
        self.harmless = sorted((x for x in names if x), key=len, reverse=True)

    def names_in(self, text, allowed=()):
        own = [re.sub(r"^The ", "", short(a)) for a in allowed]  # full names only: 'Bishop' alone stays checked
        for h in self.harmless + own:
            text = text.replace(h, " ").replace(h[:1].lower() + h[1:], " ")
        return [title for title, variants in self.secrets.items() if title not in allowed
                and any(re.search(rf"(?<![\w-]){re.escape(v)}(?![\w-])", text) for v in variants)]

    def bad_quotes(self, text):
        return [q for q in quotes(text) if _norm(q) not in self.canon]

    def problems(self, paragraphs, allowed=None):
        """allowed=None: a text read before the fight (no nemesis at all, not even in a canon quote).
        Otherwise the nemeses it may name; canon quotes (checked separately) may name any."""
        text = " ".join(paragraphs)
        named = self.names_in(text) if allowed is None else self.names_in(QUOTE.sub(" ", text), allowed)
        out = [f"names {n}" for n in named]
        bare = text
        for h in self.harmless:
            bare = bare.replace(h, " ")
        out += [f"names {n}, who is not in this expedition" for n in self.outsiders if names_any(bare, [n])]
        out += [f"invented quote: {q[:40]}…" for q in self.bad_quotes(text)]
        return out


def _sentences(paragraphs):
    return {_norm(s) for p in paragraphs for s in re.split(r"(?<=[.!?…])\s+", p) if len(_norm(s)) > 30}


def merge(exp, story, bundle, ai):
    """Template story + model output -> (story, report). Keeps the template wherever the output fails a check."""
    out = copy.deepcopy(story)
    check = Checker(exp, story, bundle)
    report = {"chapters": {}, "kept_template": [], "notes": [],
              "outline": ai.get("outline") if isinstance(ai, dict) else None}
    if not isinstance(ai, dict):
        report["notes"].append("the reply is not a JSON object")
        report["kept_template"] = ["title", "prologue", *story["chapters"], *(f"epilogue {e}" for e in story["epilogues"])]
        return out, report

    title = ai.get("title")
    if isinstance(title, str) and 3 <= len(title) <= 90 and not check.problems([title]):
        out["title"] = title.strip()
    else:
        report["kept_template"].append("title")
    prologue = _paragraphs(ai.get("prologue"), 1, 4)
    if prologue and not (p := check.problems(prologue)):
        out["prologue"] = prologue
    else:
        report["kept_template"].append("prologue")
        report["notes"].append(f"prologue: {p if prologue else 'missing or malformed'}")

    given = {c.get("node"): c for c in ai.get("chapters") or [] if isinstance(c, dict)}
    for nid, ch in story["chapters"].items():
        why = _chapter_problems(check, exp["nodes"][nid], ch, given.get(nid))
        if why:
            report["kept_template"].append(nid)
            report["chapters"][nid] = why
            continue
        new = out["chapters"][nid]
        for s in SECTIONS:
            new[s] = _paragraphs(given[nid][s])
        if ch.get("choice"):
            texts = {o["node"]: o["text"] for o in given[nid]["fork_options"]}
            new["choice"]["intro"] = given[nid]["fork_intro"].strip()
            new["choice"]["note"] = given[nid]["fork_note"].strip() or ch["choice"]["note"]
            for o in new["choice"]["options"]:
                o["text"] = texts[o["node"]].strip()
        report["chapters"][nid] = "rewritten"

    epilogues = {e.get("node"): e.get("paragraphs") for e in ai.get("epilogues") or [] if isinstance(e, dict)}
    for nid in story["epilogues"]:
        paras = _paragraphs(epilogues.get(nid), 1, 4)
        allowed = {exp["nodes"][nid]["nemesis"], *check.names_in(" ".join(story["epilogues"][nid]))}
        if paras and not check.problems(paras, allowed=allowed):
            out["epilogues"][nid] = paras
        else:
            report["kept_template"].append(f"epilogue {nid}")

    _drop_repeats(exp, story, out, report)
    report["notes"] += _loose_threads(exp, report.get("outline"))
    return out, report


def _chapter_problems(check, node, ch, new):
    if not new:
        return "missing"
    sections = {s: _paragraphs(new.get(s)) for s in SECTIONS}
    bad = [s for s, v in sections.items() if v is None]
    if bad:
        return f"malformed {', '.join(bad)}"
    problems = [f"approach {p}" for p in check.problems(sections["approach"])]
    count = len(quotes(" ".join(p for s in SECTIONS for p in sections[s])))
    if count > 1:
        problems.append(f"{count} quotes (one at most)")
    for s in ("encounter", "victory", "defeat"):
        # its own nemesis, and any the template already names there (a canon narrator, a recruit's history)
        allowed = {ch["nemesis"], *check.names_in(" ".join(ch[s]))}
        problems += [f"{s} {p}" for p in check.problems(sections[s], allowed=allowed)]
    victory = " ".join(sections["victory"])
    for name in node["rewards"].get("treasures", [])[:3] + [short(m) for m in node["rewards"].get("mages", [])]:
        if name not in victory:
            problems.append(f"victory lost {name}")
    encounter = " ".join(sections["encounter"])
    for role in ("friend", "foe"):
        if node.get(role) and re.sub(r"^The ", "", node[role].split(",")[0]).lower() not in encounter.lower():
            problems.append(f"encounter lost the {role}")
    if ch.get("choice"):
        opts = new.get("fork_options") or []
        texts = [o.get("text") for o in opts if isinstance(o, dict)]
        if [o.get("node") for o in opts if isinstance(o, dict)] != [o["node"] for o in ch["choice"]["options"]] \
                or not all(isinstance(t, str) and 10 < len(t) < 500 for t in texts):
            problems.append("fork options do not match the map")
        else:
            fork_text = [new.get("fork_intro") or "", new.get("fork_note") or "", *texts]
            if not (new.get("fork_intro") or "").strip():
                problems.append("fork intro missing")
            problems += [f"fork {p}" for p in check.problems([t for t in fork_text if t])]
    return "; ".join(problems)


def _drop_repeats(exp, story, out, report):
    """A sentence met twice on one route: put the later rewritten chapter back to its template text."""
    for _ in range(len(story["chapters"])):
        fixed = False
        for route in exp["routes"]:
            seen = _sentences(out["prologue"])
            for nid in route["nodes"]:
                ch = out["chapters"][nid]
                mine = _sentences([p for s in SECTIONS for p in ch[s]])
                if seen & mine and report["chapters"].get(nid) == "rewritten":
                    out["chapters"][nid] = copy.deepcopy(story["chapters"][nid])
                    report["chapters"][nid] = "repeats an earlier sentence of the route"
                    report["kept_template"].append(nid)
                    fixed = True
                    break
                seen |= mine
            if fixed:
                break
        if not fixed:
            return


def _loose_threads(exp, outline):
    """The model's own plan, checked against the map: a thread opened on a route must be closed on it."""
    if not isinstance(outline, dict) or not isinstance(outline.get("threads"), list):
        return ["no thread plan in the outline"]
    notes = []
    for t in outline["threads"]:
        if not isinstance(t, dict):
            continue
        opened, closed = t.get("opened_in"), set(t.get("closed_in") or [])
        for r in exp["routes"]:
            if (opened == "prologue" or opened in r["nodes"]) and not closed & set(r["nodes"]):
                notes.append(f"thread left open on route {r['id']}: {str(t.get('thread'))[:80]}")
    return notes


def summary(report):
    rewritten = sum(1 for v in report["chapters"].values() if v == "rewritten")
    return {"rewritten_chapters": rewritten, "total_chapters": len(report["chapters"]),
            "kept_template": report["kept_template"],
            "problems": {k: v for k, v in report["chapters"].items() if v != "rewritten"},
            "notes": report["notes"], "outline": report.get("outline")}
