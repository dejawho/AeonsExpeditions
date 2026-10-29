# Aeon's Expeditions

Generator of custom and random **expeditions** (mini-campaigns) for the board game *Aeon's End*, each wrapped in a light story grounded in the game's canon lore.

This repository currently contains the **lore database** the generator will be built on.

## Pipeline

```
scraper/crawl.py      wiki API  ->  data/raw/pages.jsonl          (all 2,962 articles, resumable)
scraper/build_db.py   raw       ->  data/db/aeons_end.sqlite      (parsed game data + lore texts)
                      lore/*.json -> lore_* tables + docs/LORE.md (curated reconstruction, validated)
scraper/context.py    DB        ->  JSON "lore pack" for one expedition
scraper/build_expedition.py  DB + expedition/rules.json -> data/db/expedition.sqlite + data/expedition/*.json
scraper/fetch_images.py      wiki -> data/images/{full,thumb}/*.webp + manifest.json (local card images)
scraper/generate_expedition.py  expedition.sqlite -> a full branching expedition map (+ share code)
scraper/storyteller.py          expedition + lore DB + lore/narrative_templates.json -> its story
scraper/make_expedition.py      both together -> markdown or JSON  (example: docs/sample_expedition.md)
```

```powershell
python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python scraper\crawl.py       # only to refresh from the wiki
.\.venv\Scripts\python scraper\build_db.py    # rebuilds the whole DB, then loads lore/
.\.venv\Scripts\python scraper\context.py --random --battles 4 --seed 1
.\.venv\Scripts\python scraper\build_expedition.py
.\.venv\Scripts\python scraper\fetch_images.py      # local card images (about 10 min the first time)
.\.venv\Scripts\python scraper\generate_expedition.py --players 2 --battles 5 --friends-foes --seed 4
.\.venv\Scripts\python scraper\make_expedition.py --players 3 --battles 5 --forks 2 --friends-foes --seed 21 --out tale.md
.\.venv\Scripts\python scraper\make_expedition.py --code AEX-06T83-MG5ZZ-ZZZZR-30000-058
```

## Web app (Docker / Synology)

```
backend/main.py     stateless FastAPI: /api/catalog, /api/generate, /api/codes/{code}, /api/rewrite; serves the React build
backend/llm.py      optional AI story rewrite providers: Claude (anthropic SDK) and DeepSeek (OpenAI-compatible API)
frontend/           React + Vite + TypeScript: new expedition, play, journal, resume, share codes, export/import
Dockerfile          one container (node build stage → python:3.12-slim runtime), non-root, ~40 MB RAM
docker-compose.yml  for Synology Container Manager "Project"
deploy/build-image.ps1   builds and exports the image .tar for Container Manager
deploy/docker-compose.nas.yml   the compose file on the NAS (/volume1/docker/aeons-expeditions, port 3005 behind DSM's reverse proxy)
```

No accounts and no server-side storage: saved expeditions live in the player's browser (IndexedDB), as the
full generated expedition plus a list of actions (win / loss / retry / advance), so undo is exact and a later
card-data update never changes a game in progress. Export / import moves a save between devices.
The server stores only the AI-written stories, by share code (`backend/store.py`, volume `/app/data/state`),
so a code always opens with the same AI story.
Deployment guide: [docs/DEPLOY_SYNOLOGY.md](docs/DEPLOY_SYNOLOGY.md).

Development: `uvicorn backend.main:app --port 8000` and, in `frontend/`, `npm run dev` (proxies `/api`).
Progress logic tests: `node --experimental-strip-types frontend/tests/progress.test.mjs <expedition.json>...`
AI rewrite tests (offline, no API key needed): `python backend/test_rewrite.py`
(generate the files with `scraper/make_expedition.py --format json --out ...`).

## Expedition generation

An expedition is generated **entirely up front**: every battle on every path, with its nemesis, nemesis deck,
friend/foe, treasure setup, rewards and story, before anyone plays.

- **Branching:** 1 or 2 forks (`--forks`, otherwise chosen by the seed). A *detour* offers two different
  versions of the next battle, then the paths rejoin; a *finale* fork splits the expedition into two
  different last battles and epilogues. Each branch has its own nemesis, rewards and story. Battle numbers,
  treasure levels and upgraded-basic counts always follow the official Expedition rules.
- **Map:** `nodes` (battles, e.g. `1`, `2a`, `2b`, `3`), `edges`, `forks`, and `routes` (each complete path with
  its Barracks / suggested supply, since those depend on the rewards collected along the way).
- **One character, one appearance:** a character never shows up twice on a route: not as two versions of a mage
  (Razra and Razra (Legacy of Gravehold)), not as a mage and a friend (Qu / Qu, the Rift Walker), not as a mage
  and a nemesis (Thraxir / Knight of Shackles, Xaxos / Xaxos: Ascended), not as two forms of one nemesis
  (Bishop of Scrolls / Bishop: Returned). The quest giver is never one of them either. Identities come from
  `versions` in [lore/characters.json](lore/characters.json) (table `characters`). If the collection is too
  small to avoid a repeat, the expedition says so in its warnings.
- **Share codes:** e.g. `AEX-06T83-MG5ZZ-ZZZZR-30000-058` stores the seed with the players, battles, forks,
  options and owned boxes. `--code` regenerates exactly the same expedition and story. Codes embed a fingerprint
  of the card database and warn if it has changed since.
- **Portable randomness:** a mulberry32 PRNG ([scraper/shareable.py](scraper/shareable.py)) with its own
  `choice`/`sample`, and separate streams for layout, draws, supply and story, so a JavaScript port can
  reproduce the same codes and editing the prose never changes the cards.
- [expedition/box_order.json](expedition/box_order.json) fixes the bit order of boxes in codes: only append to it.

## Stories

`make_expedition.py` draws an expedition by the official rules and tells it as a short campaign:
prologue, an introduction / victory / defeat text for every battle, and an epilogue with a twist.

- The **era** comes from the drawn nemeses, the **mission** (missing expedition, spreading blight, the traitor...) from their themes,
  the **quest giver** from the era (never one of the party).
- Battles foreshadow each other: every victory ends with the warning signs of the next nemesis.
- No invented dialogue: the only quoted words are canon texts (nemesis mat stories, card flavor). Treasures
  and recruited mages are introduced with their own lore.
- No spoilers: a battle's approach and the fork choices never name the nemesis; forks hint at what waits.
- No sentence repeats along a route; every battle has its own place (lore/settings.json).
- Mages or nemeses from another era are bridged with canon explanations (time in the Void, the spiral of worlds, Nook's anomaly...).
- All prose lives in [lore/narrative_templates.json](lore/narrative_templates.json) and can be edited without touching code.
- Every wiki page quoted is listed at the end for CC BY-SA attribution.
- **Optional AI rewrite** ([scraper/ai_story.py](scraper/ai_story.py), [backend/llm.py](backend/llm.py)): the
  template story plus a lore bundle for this expedition only are sent to Claude Sonnet 5.5 or DeepSeek, with a
  fixed JSON schema. Every chapter returned is checked (quotes must be canon, no nemesis named before it is
  faced, the same treasures / recruits / friend and foe, fork options matching the map, no sentence repeated on
  a route); a chapter that fails keeps the template text. Setup and costs: [docs/DEPLOY_SYNOLOGY.md](docs/DEPLOY_SYNOLOGY.md).

## Expedition database (`data/db/expedition.sqlite`, JSON copy in `data/expedition/`)

Everything a generator needs, cleaned for Expedition mode. Titles match the lore DB, so the two can be `ATTACH`ed.

| table | content |
|---|---|
| `rules` | the Expedition rules as structured JSON (from [expedition/rules.json](expedition/rules.json)): setup, supply 3/2/4, treasure setup per battle, upgraded-basic chart, basic cards by player count, rewards on win/loss, scoring, variants, difficulty levels, turn order, Friends & Foes, Xaxos: Outcast, exclusions |
| `mages` | 102 randomizer mages, parsed starting hand/deck with Crystal and Spark counts (for level 1 treasures) |
| `supply_cards` | 419 randomizer gems/relics/spells; `requires` (swap zone, trinket deck, Xaxos: Outcast), `campaign_mechanic` (LoG boost/overheat), `legacy_power` (weak/standard/strong) |
| `treasures` | 270 treasures: level 1 (99), level 2 (67), level 3 (83), level 4 (21); level-1 `replaces` Crystal or Spark |
| `nemeses` | 67 randomizer nemeses with `battles`, Battle 4/5 `expedition_modifiers`, increased difficulty, `deck_source` |
| `nemesis_cards` | each nemesis' cards with `role`: `deck` (tiers 1-3), `setup` (tier 0), `special` |
| `basic_nemesis_cards` | 278 basic and upgraded basic cards (campaign versions removed), `player_count` variants |
| `friends`, `foes`, `friend_foe_cards`, `banners` | Friends & Foes module |
| `linked_cards` | non-supply cards a setup pulls in: mage uniques, side decks, swap zone, trinkets, Xaxos: Outcast abilities |
| `characters` | who each mage / nemesis / friend / foe is (`thraxir` for Thraxir, Thraxir (The Descent), Knight of Shackles...) |
| `exclusions` | content not usable in an expedition, with the reason |
| `data_fixes` | wiki inconsistencies corrected during the build |

Every item carries `box` (first printing) and `boxes` (every box it was printed in, as JSON). The generator treats an item as
owned if *any* of its boxes is in your collection, so reprints count. In the main DB, `player_cards`, `nemesis_cards` and
`friend_foe_cards` also have `printings`: each box with that printing's card numbers. Box details (wave, standalone or
expansion, release year) are in `boxes`.

## Database (`data/db/aeons_end.sqlite`)

**Extracted from the wiki**

| table | content |
|---|---|
| `pages` | every article: kind, box, categories, plain text, raw wikitext, infobox |
| `boxes` | 34 boxes/expansions with wave, release, back-of-box blurb |
| `mages` | 104 mage versions: ability, breaches, starting cards, complexity |
| `nemeses` | 73 nemeses: life, difficulty, expedition battles, unleash/setup/rules |
| `expedition_battles` | which nemesis can appear in Expedition battle 1–5 |
| `nemesis_cards`, `player_cards` | 1,282 nemesis cards, 957 player cards/treasures (with treasure level) |
| `friends_foes`, `friend_foe_cards` | The Descent's Friends & Foes module |
| `narrative_cards` | Legacy/expedition story cards, events, campaign cards (both faces) |
| `lore_texts` | 1,410 narrative texts: mat stories, flavor text, campaign text, blurbs (deduplicated) |
| `character_quotes` | the wiki's curated *Character Quote* index: whose mat quote, said by, mentioned in |
| `mentions` | lore text → page links (`curated`, `speaker`, `link`, `name`) |
| `characters` | identities grouped across versions (e.g. 7 versions of Xaxos) |
| `character_lore` (view) | every lore text tied to a character |
| `lore_fts` | full-text search over lore texts |

**Curated reconstruction** (source of truth in `lore/`, every claim cited to wiki pages)

| table | content |
|---|---|
| `lore_eras`, `lore_events` | in-universe timeline: 9 eras from the phoenixes to Cindercrown, 31 key events |
| `lore_places`, `lore_factions`, `lore_concepts`, `lore_secrets` | world building, hidden card-text messages |
| `lore_characters`, `lore_relationships` | 87 profiles with traits, hooks, relationships |
| `nemesis_lore` | every nemesis: archetype, origin, foreshadowing signs, aftermath, hook |
| `friend_foe_lore` | narrative role of each friend and foe |
| `story_kit` | expedition story grammar: beats, missions, quest givers, settings, era bridges, twists |
| `lore_citations` | entity → wiki page; join to `lore_texts.page` to retrieve the source text |
| `compendium_fts` | full-text search over the curated lore |

Readable version: [docs/LORE.md](docs/LORE.md).

## Licence and attribution

Text extracted from the [Aeon's End Wiki](https://aeonsend.wiki.gg/) is © its contributors, licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0). Every page keeps its source URL (`pages.url`);
the webapp must credit the wiki and share derived lore under the same licence. Aeon's End is © Indie Boards & Cards / Action Phase Games.
