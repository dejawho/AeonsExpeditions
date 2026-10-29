"""Offline tests of the AI rewrite: the checks in scraper/ai_story.py and the /api/rewrite stream.
No network, no cost: the 'fake' provider echoes the template story, and the tests tamper with it.

    python -m pytest backend/test_rewrite.py      (or: python backend/test_rewrite.py)
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["AI_FAKE"] = "1"
STORE = Path(tempfile.mkdtemp()) / "ai_stories.sqlite"
os.environ["AI_STORE"] = str(STORE)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402  (puts scraper/ on the path)
import ai_story  # noqa: E402
import llm  # noqa: E402
from generate_expedition import resolve_settings  # noqa: E402
from make_expedition import make  # noqa: E402

client = TestClient(main.app)


def expedition(seed=21, **kw):
    s = resolve_settings(**{"players": 2, "battles": 5, "friends_foes": True, "seed": seed, **kw})
    with main.db() as con:
        return make(s, con)


def echo(exp, story):
    """What a perfect model would answer: the template itself, in the reply schema."""
    bundle = ai_story.build_bundle(exp, story)
    text, _ = llm.Fake().complete(ai_story.SYSTEM, ai_story.user_prompt(bundle), lambda n: None)
    return bundle, json.loads(text)


def chapter(reply, nid):
    return next(c for c in reply["chapters"] if c["node"] == nid)


def test_template_passes_every_check():
    for seed in range(1, 60):
        exp, story = expedition(seed, players=1 + seed % 4, battles=4 + seed % 2, friends_foes=bool(seed % 2))
        bundle, reply = echo(exp, story)
        _, report = ai_story.merge(exp, story, bundle, reply)
        assert not report["kept_template"], (seed, report)


def test_bad_chapters_fall_back_to_the_template():
    exp, story = expedition()
    bundle, reply = echo(exp, story)
    first, final = "1", next(n for n, x in exp["nodes"].items() if x["final"])
    later = next(n for n, x in exp["nodes"].items() if x["battle"] == 3)
    secret = ai_story.short(exp["nodes"][final]["nemesis"])
    bad = copy.deepcopy(reply)
    chapter(bad, first)["approach"][0] += f" Everyone knows the {secret} waits at the end."  # spoiler
    chapter(bad, later)["encounter"][0] += " “We should never have come here,” says Brama."  # invented dialogue
    treasure = exp["nodes"][later]["rewards"].get("treasures", [])[:1]
    bad["title"] = f"The Road to the {secret}"
    _, report = ai_story.merge(exp, story, bundle, bad)
    assert "approach names" in report["chapters"][first]
    assert "invented quote" in report["chapters"][later]
    assert "title" in report["kept_template"]
    if treasure:
        lost = copy.deepcopy(reply)
        v = chapter(lost, later)["victory"]
        chapter(lost, later)["victory"] = [p.replace(treasure[0], "a trinket") for p in v]
        _, report = ai_story.merge(exp, story, bundle, lost)
        assert "victory lost" in report["chapters"][later]


def test_fork_options_must_match_the_map():
    exp, story = expedition()
    fork = next(n for n, c in story["chapters"].items() if c.get("choice"))
    bundle, reply = echo(exp, story)
    chapter(reply, fork)["fork_options"].reverse()
    _, report = ai_story.merge(exp, story, bundle, reply)
    assert "fork options" in report["chapters"][fork]


def test_repeated_sentence_on_a_route_is_dropped():
    exp, story = expedition()
    bundle, reply = echo(exp, story)
    route = exp["routes"][0]["nodes"]
    a, b = route[0], route[2]
    line = "The wind carries the smell of old smoke over the broken stones of the road."
    chapter(reply, a)["approach"][0] += " " + line
    chapter(reply, b)["approach"][0] += " " + line
    merged, report = ai_story.merge(exp, story, bundle, reply)
    assert report["chapters"][a] == "rewritten" and "repeats" in report["chapters"][b]
    assert merged["chapters"][b] == story["chapters"][b]


def test_malformed_reply_keeps_the_template():
    exp, story = expedition()
    bundle, _ = echo(exp, story)
    merged, report = ai_story.merge(exp, story, bundle, {"title": 3, "chapters": "nope"})
    assert merged["chapters"] == story["chapters"]
    assert set(story["chapters"]) <= set(report["kept_template"])


def test_rewrite_stream_and_cache():
    catalog = client.get("/api/catalog").json()
    assert {"id": "fake", "label": llm.Fake.label, "model": "fake"} in catalog["ai"]
    exp, story = expedition()
    with client.stream("POST", "/api/rewrite", json={"code": exp["share_code"], "provider": "fake"}) as r:
        assert r.status_code == 200
        events = [json.loads(line) for line in r.iter_lines() if line]
    assert events[0]["type"] == "queued" and events[-1]["type"] == "done"
    done = events[-1]
    assert done["story"]["share_code"] == exp["share_code"]
    assert done["story"]["author"]["provider"] == "fake"
    assert done["report"]["rewritten_chapters"] == len(story["chapters"])
    # the second request is answered from the cache, in one line
    with client.stream("POST", "/api/rewrite", json={"code": exp["share_code"], "provider": "fake"}) as r:
        again = [json.loads(line) for line in r.iter_lines() if line]
    assert len(again) == 1 and again[0]["story"] == done["story"]
    # stored by share code: generating the same code again opens with the AI story
    settings = client.get(f"/api/codes/{exp['share_code']}").json()["settings"]
    generated = client.post("/api/generate", json=settings).json()
    assert generated["ai_story"] == done["story"] and generated["story"] == story
    assert main.stories.count() == 1


def test_store_keeps_the_first_story():
    exp, story = expedition(seed=99)
    first = {"type": "done", "story": {**story, "title": "First"}, "report": {}}
    main.stories.put(exp["share_code"], "fake", "fake", 1, first)
    main.stories.put(exp["share_code"], "fake", "fake", 1, {**first, "story": {**story, "title": "Second"}})
    assert main.stories.get(exp["share_code"], "fake")["story"]["title"] == "First"
    assert main.stories.first(exp["share_code"])["story"]["title"] == "First"
    assert main.stories.first("AEX-UNKNOWN") is None
    main.stories.put(exp["share_code"], "fake", "fake", 1, {**first, "story": {**story, "title": "Third"}}, replace=True)
    assert main.stories.get(exp["share_code"], "fake")["story"]["title"] == "Third"


def test_new_version_rewrites_a_stored_story():
    exp, story = expedition(seed=7)
    body = {"code": exp["share_code"], "provider": "fake"}
    for new_version in (False, False, True):
        with client.stream("POST", "/api/rewrite", json={**body, "new_version": new_version}) as r:
            events = [json.loads(line)["type"] for line in r.iter_lines() if line]
        # the second request is served from the store (one line); a new version is written again
        assert events == (["done"] if events[0] == "done" else ["queued", "started", "progress", "done"]), events
        if new_version:
            assert events[0] == "queued"


def test_rewrite_errors():
    assert client.post("/api/rewrite", json={"code": "AEX-NOPE", "provider": "fake"}).status_code == 400
    exp, _ = expedition()
    assert client.post("/api/rewrite", json={"code": exp["share_code"], "provider": "gpt"}).status_code == 404


def test_defeat_draw():
    exp, _ = expedition(seed=21)
    route = exp["routes"][0]["nodes"]
    body = {"code": exp["share_code"], "path": route[:2]}
    in_expedition = set(exp["starting_barracks"]["mages"]) | set(exp["starting_barracks"]["player_cards"])
    in_expedition |= {c for n in exp["nodes"].values() for v in n["rewards"].values() if isinstance(v, list) for c in v}
    for source in ("mage", "gem", "relic", "spell"):
        card = client.post("/api/defeat-draw", json={**body, "source": source}).json()["card"]
        assert card not in in_expedition
        again = client.post("/api/defeat-draw", json={**body, "source": source}).json()["card"]
        assert again == card, "the same choice draws the same card (no reroll by undo)"
        other = client.post("/api/defeat-draw", json={**body, "source": source, "taken": [card]}).json()["card"]
        assert other != card
    r = client.post("/api/defeat-draw", json={**body, "source": "treasure", "level": 1}).json()
    assert r["level"] == 1 and r["card"] not in in_expedition
    # before the first victory no treasure deck has been drawn from
    first = {"code": exp["share_code"], "path": ["1"]}
    assert client.post("/api/defeat-draw", json={**first, "source": "treasure", "level": 1}).status_code == 422
    assert client.post("/api/defeat-draw", json={**body, "source": "treasure", "level": 4}).status_code == 422
    assert client.post("/api/defeat-draw", json={**body, "source": "nemesis"}).status_code == 422
    assert client.post("/api/defeat-draw", json={**first, "path": ["1", "9"], "source": "gem"}).status_code == 422


def test_no_character_twice_on_a_route():
    """Two versions of a mage, a mage as friend (Qu, the Rift Walker) or as nemesis (Thraxir / Knight of Shackles):
    never on one route, unless a warning says the collection is too small."""
    with main.db() as con:
        who = {(k, t): c for t, k, c in con.execute("SELECT title, kind, character FROM characters")}
    assert who[("nemesis", "Knight of Shackles")] == who[("mage", "Thraxir (The Descent)")]
    assert who[("friend", "Qu, the Rift Walker")] == who[("mage", "Qu (Outcasts)")]
    for seed in range(1, 80):
        exp, _ = expedition(seed, players=1 + seed % 4, battles=4 + seed % 2, forks=1 + seed % 2)
        if exp["warnings"]:
            continue
        on_route = {}
        for route in exp["routes"]:
            people = [who[("mage", m)] for m in exp["starting_barracks"]["mages"]]
            for nid in route["nodes"]:
                n = exp["nodes"][nid]
                people += [who[("nemesis", n["nemesis"])], who[("friend", n["friend"])], who[("foe", n["foe"])]]
                people += [who[("mage", m)] for m in n["rewards"].get("mages", [])]
            assert len(people) == len(set(people)), (seed, route["id"], people)
            on_route[route["id"]] = set(people)
        # a mage drawn after a defeat is nobody met on that route either (a route through the lost battle)
        first = exp["routes"][0]
        drawn = client.post("/api/defeat-draw", json={"code": exp["share_code"], "path": first["nodes"], "source": "mage"})
        if drawn.status_code == 200:
            assert who[("mage", drawn.json()["card"])] not in on_route[first["id"]], seed


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
