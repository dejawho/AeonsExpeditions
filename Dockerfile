# Aeon's Expeditions — one container: FastAPI generator API + the built React app.
# Saved games live in the players' browsers. The only server data is the AI-written stories (by share
# code), in the volume /app/data/state.
# Optional AI story rewrite: pass ANTHROPIC_API_KEY and/or DEEPSEEK_API_KEY at run time (never bake them in).

# --- 1. build the React frontend ---------------------------------------------------
FROM node:22.14.0-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. runtime ------------------------------------------------------------------
FROM python:3.12.10-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Only what the generator needs at runtime (the crawler / DB builders stay out of the image).
COPY scraper/generate_expedition.py scraper/make_expedition.py scraper/storyteller.py scraper/shareable.py \
     scraper/ai_story.py scraper/
COPY lore/narrative_templates.json lore/settings.json lore/
COPY expedition/box_order.json expedition/
COPY data/db/aeons_end.sqlite data/db/expedition.sqlite data/db/
# Local copies of the wiki card images (scraper/fetch_images.py). Card art is (c) Indie Boards & Cards:
# keep images built with them private (your own NAS), do not publish them.
COPY data/images/ data/images/
COPY backend/main.py backend/llm.py backend/store.py backend/
COPY --from=web /web/dist frontend/dist

RUN useradd --system --uid 10001 --no-create-home app \
 && mkdir -p data/state && chown app data/state
ENV AI_STORE=/app/data/state/ai_stories.sqlite
VOLUME /app/data/state
USER app

EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)"
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
