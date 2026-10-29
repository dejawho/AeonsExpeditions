"""Generate a complete expedition — every branch, its game setup and its story — in one go.

    python scraper/make_expedition.py --players 2 --seed 42                  # markdown to stdout
    python scraper/make_expedition.py --players 3 --battles 5 --forks 2 --friends-foes --out tale.md
    python scraper/make_expedition.py --code AEX-06T83-MG5ZZ-ZZZZR-30000-0AG  # the exact same expedition
    python scraper/make_expedition.py --seed 42 --format json
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from generate_expedition import DB, add_arguments, generate, settings_from_args
from shareable import PRNG
from storyteller import Storyteller, to_markdown


def make(settings, con=None):
    con = con or sqlite3.connect(DB)
    exp = generate(con, settings)
    story = Storyteller(PRNG.stream(settings["seed"], "story")).tell(exp)
    return exp, story


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    add_arguments(ap)
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--out")
    a = ap.parse_args()
    con = sqlite3.connect(DB)
    exp, story = make(settings_from_args(a, con), con)
    text = (to_markdown(exp, story) if a.format == "md"
            else json.dumps({"expedition": exp, "story": story}, ensure_ascii=False, indent=2))
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {a.out}  (share code {exp['share_code']})")
    else:
        print(text)


if __name__ == "__main__":
    main()
