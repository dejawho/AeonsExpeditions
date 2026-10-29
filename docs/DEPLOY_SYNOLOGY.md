# Running Aeon's Expeditions on a Synology DS218+

The app is a single Docker container: a small Python server that generates expeditions, plus the React
web page. It keeps **no data**: every saved expedition lives in the browser of the person playing it.
So the container needs no shared folder or volume, and you can delete or update it without losing games.

Requirements: DSM 7.2 with **Container Manager** (Package Center). The DS218+ is x86-64, which this image
is built for. The container uses about 40 MB of RAM.

## Option A — build on your PC, import the image (recommended)

1. On the PC (Docker Desktop running), in the project folder:
   ```powershell
   .\deploy\build-image.ps1
   ```
   This creates `deploy\aeons-expeditions-1.0.0.tar` (about 220 MB).
2. On the NAS: **Container Manager → Image → Add → Add from file**, choose the `.tar`.
3. **Container Manager → Container → Create**:
   - Image: `aeons-expeditions:1.0.0`, name `aeons-expeditions`
   - Enable **auto-restart**
   - **Port settings**: local port `8080` → container port `8080` (TCP). Use another local port if 8080 is taken.
   - No volumes or environment variables are needed.
4. Open `http://<nas-address>:8080` from any device on your network.

## Option B — build directly on the NAS

1. Copy the project folder to the NAS, e.g. `/volume1/docker/aeons-expeditions` (the `.venv`, `data/raw`
   and `frontend/node_modules` folders are not needed).
2. **Container Manager → Project → Create**, path = that folder. It finds `docker-compose.yml`.
   Choose "Build" and start. The first build takes several minutes on the DS218+.

## Using it

- **New expedition**: pick your boxes, players, battles (4, or 5 with wave 9+), branching points and options,
  generate, reroll until you like it, then *Start expedition*.
- **Playing**: each battle shows its story, the mages and suggested supply for your path, treasures to choose,
  the nemesis deck, friend/foe and modifiers. Tap *We won* / *We lost*. After a defeat, choose what to add to
  your Barracks (a random mage, a gem, a relic, a spell, or a treasure of a level already found): the app draws
  the card and lists it in every later battle. At a fork choose path A or B.
  *Undo last step* fixes a wrong tap.
- **Resume**: the home page lists the expeditions saved in this browser.
- **Share**: the share code (e.g. `AEX-05T83-...`) recreates the same expedition on any device: *Open code*.
- **Move or back up a game**: *Export save* downloads a file; *Import save file* restores it, on any device.

## Optional: AI-written stories (Claude or DeepSeek)

Every expedition comes with a story written from templates and canon lore. On the preview page you can
ask an AI to rework it: the server sends the AI the expedition and a lore bundle cut down to its nemeses,
mages, places and canon texts, then checks every chapter it gets back (no invented dialogue, no nemesis named
before you face it, the same treasures and allies). A chapter that fails a check keeps its template text.

The buttons appear only when the server has an API key. Keys stay on the NAS, never in the browser:

1. Create an API key: Claude at <https://platform.claude.com> (Settings → API keys), DeepSeek at
   <https://platform.deepseek.com/api_keys>. Both are prepaid / pay-as-you-go.
2. Next to `docker-compose.yml`, create a file named `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   DEEPSEEK_API_KEY=sk-...
   ```
   (one of them is enough). With Option A, add the same variables in Container Manager → the container →
   *Settings → Environment* instead.
3. Restart the project. The preview page now shows *Rewrite with DeepSeek V4 Pro* (the default, highlighted)
   and, if its key is set, *Rewrite with Claude Sonnet 5.5*.

What a rewrite costs, roughly (about 10–15k tokens in, 6–10k out, prices as of October 2026):

| Model | Price per million tokens (in / out) | One expedition |
|---|---|---|
| Claude Sonnet 5.5 | $2 / $10 | about $0.10–0.13 |
| DeepSeek V4 Pro (`AI_DEEPSEEK_MODEL=deepseek-v4-pro`, default) | $1.32 / $3.96 peak, half off-peak | about $0.05 off-peak, $0.10 peak (measured: 11–12k in, 15–22k out including its reasoning) |
| DeepSeek Flash (`AI_DEEPSEEK_MODEL=deepseek-flash`) | $0.30 / $1.20 peak, half off-peak | about $0.01–0.02 |

The page shows the estimated cost after each rewrite. `AI_DAILY_LIMIT` (default 30) caps paid rewrites per
day for the whole server, since anyone who can open the app can press the button. The AI story is saved
with the game in the browser like the rest of it.

**AI stories are stored on the NAS, by share code** (the one thing the server keeps, in the `ai-stories`
volume, file `ai_stories.sqlite`). A share code then always opens with the same AI story, on any device,
and asking again for it costs nothing. The first story written for a code stays; *Use the original story*
still shows the template one. With Option A (image imported in Container Manager), add a volume: the
container → *Settings → Volume Settings → Add folder*, e.g. `docker/aeons-expeditions` mounted at
`/app/data/state`, and give the folder write access to everyone (the container runs as user 10001).
Without a writable volume the app still works; the AI stories are just not kept after a restart. For Claude, refusal fallbacks are switched on: if Claude Sonnet
declines a request, the API retries it on the model Anthropic recommends, within the same call.

A rewrite takes one to three minutes. The server streams its progress, so DSM's reverse proxy does not time
out (no setting to change). Other variables: `AI_CLAUDE_MODEL` (default `claude-sonnet-5-5`),
`AI_CLAUDE_EFFORT` (`low` / `medium` (default) / `high`: more effort is slower and costs more).

## Card images

The image includes local copies of the card pictures from the wiki (about 900 cards, mats and treasures),
so the app works without internet access. They are made by `scraper/fetch_images.py` before building.
The card art is © Indie Boards & Cards: unlike the wiki text it is not under an open licence, so keep an
image built with the pictures on your own NAS for your group, and do not publish it (e.g. on Docker Hub).

## Things to know

- **Saves are per browser and per address.** `http://diskstation:8080` and `http://192.168.1.10:8080` count as
  different sites for the browser, so always use the same address, or move games with Export / Import.
  Clearing the browser's site data deletes the saves: export the ones you care about.
- **Copy code** needs HTTPS (a browser rule for the clipboard). Over plain `http://` the code is still shown
  on screen. To get HTTPS, use DSM's reverse proxy: **Control Panel → Login Portal → Advanced → Reverse Proxy**,
  source `https://aeons.<your-domain>:443` → destination `http://localhost:8080`. (Saves made on the old
  address will not appear on the new one: export/import them once.)
- **Updating**: build/import the new image, then recreate the container from it. Saves are untouched.
  Share codes made before a card-data update still work, but the page warns that the expedition may differ.
- **Health**: `http://<nas-address>:8080/api/health` returns `{"status":"ok"}`; the API is documented at
  `/api/docs`.
