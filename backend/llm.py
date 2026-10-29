"""LLM providers for the optional story rewrite (scraper/ai_story.py builds the prompt and checks the reply).

A provider is enabled by its API key in the server's environment; keys never reach the browser.

    DEEPSEEK_API_KEY    DeepSeek, the default provider (model deepseek-v4-pro, AI_DEEPSEEK_MODEL to change it, e.g. deepseek-flash)
    ANTHROPIC_API_KEY   Claude (default model claude-sonnet-5-5, AI_CLAUDE_MODEL to change it, AI_CLAUDE_EFFORT)
    AI_FAKE=1           a fake provider that returns the template story, for tests (no network, no cost)

Each provider streams, so the browser sees progress and the connection never sits idle behind a proxy.
"""
import json
import os
from datetime import datetime, timezone

import ai_story

CLAUDE_MODEL = os.environ.get("AI_CLAUDE_MODEL", "claude-sonnet-5-5")
CLAUDE_EFFORT = os.environ.get("AI_CLAUDE_EFFORT", "medium")
DEEPSEEK_MODEL = os.environ.get("AI_DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_URL = os.environ.get("AI_DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LABELS = {"claude-sonnet-5-5": "Claude Sonnet 5.5", "deepseek-v4-pro": "DeepSeek V4 Pro", "deepseek-flash": "DeepSeek Flash"}
# USD per million tokens (input, output), to show an estimate of what a rewrite cost. DeepSeek: peak-hour
# prices (off-peak is half). Checked 2026-10: platform.claude.com pricing, api-docs.deepseek.com/quick_start/pricing
PRICES = {"claude-sonnet-5-5": (2.0, 10.0), "deepseek-v4-pro": (1.32, 3.96), "deepseek-flash": (0.30, 1.20)}
MAX_TOKENS = 32000
TIMEOUT = 600  # seconds


class ProviderError(Exception):
    pass


class Claude:
    id = "claude"

    def __init__(self):
        import anthropic

        self.client = anthropic.Anthropic(timeout=TIMEOUT, max_retries=2)
        self.model = CLAUDE_MODEL
        self.label = LABELS.get(self.model, self.model)

    def complete(self, system, prompt, on_progress):
        import anthropic

        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=MAX_TOKENS,
                # on a policy decline the API re-runs the request on Anthropic's recommended fallback model
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system,
                output_config={"effort": CLAUDE_EFFORT,
                               "format": {"type": "json_schema", "schema": ai_story.SCHEMA}},
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    on_progress(len(text))
                message = stream.get_final_message()
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"cannot reach the Claude API: {e}") from e
        if message.stop_reason == "refusal":
            raise ProviderError("Claude declined to write this story")
        if message.stop_reason == "max_tokens":
            raise ProviderError("the story was cut off (max_tokens)")
        parts = []
        for block in message.content:
            if block.type == "fallback":  # a model declined mid-answer: keep only what the next one wrote
                parts = []
            elif block.type == "text":
                parts.append(block.text)
        text = "".join(parts)
        usage = {"input_tokens": message.usage.input_tokens, "output_tokens": message.usage.output_tokens}
        return text, {"model": message.model, "usage": usage}


class DeepSeek:
    id = "deepseek"

    def __init__(self):
        from openai import OpenAI

        self.client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=DEEPSEEK_URL,
                             timeout=TIMEOUT, max_retries=2)
        self.model = DEEPSEEK_MODEL
        self.label = LABELS.get(self.model, self.model)

    def complete(self, system, prompt, on_progress):
        import openai

        # JSON mode does not enforce a schema: show it, and ai_story.merge() checks the shape
        system = system + "\n\nThe JSON schema of your reply:\n" + json.dumps(ai_story.SCHEMA)
        parts, usage = [], {}
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                stream=True,
                stream_options={"include_usage": True},
            )
            for chunk in stream:
                if chunk.usage:
                    usage = {"input_tokens": chunk.usage.prompt_tokens, "output_tokens": chunk.usage.completion_tokens}
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    parts.append(delta.content)
                    on_progress(len(delta.content))
                elif getattr(delta, "reasoning_content", None):
                    on_progress(0)  # thinking: alive, but no story text yet
                if chunk.choices[0].finish_reason == "length":
                    raise ProviderError("the story was cut off (max_tokens)")
        except openai.APIStatusError as e:
            raise ProviderError(f"DeepSeek API error {e.status_code}: {e.message}") from e
        except openai.APIConnectionError as e:
            raise ProviderError(f"cannot reach the DeepSeek API: {e}") from e
        text = "".join(parts)
        if not text.strip():  # documented: JSON mode may occasionally return empty content
            raise ProviderError("DeepSeek returned an empty reply, try again")
        return text, {"model": self.model, "usage": usage}


class Fake:
    """Echoes the template story through the whole pipeline: for tests and demos, free."""
    id = "fake"
    label = "Test writer (no AI)"
    model = "fake"

    def complete(self, system, prompt, on_progress):
        bundle = json.loads(prompt[prompt.index("{"):])
        t = bundle["template"]
        reply = {"title": t["title"], "prologue": t["prologue"], "epilogues": t["epilogues"], "chapters": [
            {"node": c["node"], **{s: c[s] for s in ai_story.SECTIONS},
             "fork_intro": c.get("fork", {}).get("intro", ""), "fork_note": c.get("fork", {}).get("note", ""),
             "fork_options": c.get("fork", {}).get("options", [])} for c in t["chapters"]]}
        text = json.dumps(reply, ensure_ascii=False)
        for i in range(0, len(text), 2000):
            on_progress(len(text[i:i + 2000]))
        return text, {"model": "fake", "usage": {}}


_providers = None


def providers():
    """Enabled providers, by id, the default first (built once: the SDK clients are reused)."""
    global _providers
    if _providers is None:
        found = {}
        if os.environ.get("DEEPSEEK_API_KEY"):  # the default: DeepSeek V4 Pro
            found["deepseek"] = DeepSeek()
        if os.environ.get("ANTHROPIC_API_KEY"):
            found["claude"] = Claude()
        if os.environ.get("AI_FAKE") == "1":
            found["fake"] = Fake()
        _providers = found
    return _providers


def deepseek_peak(now=None):
    """DeepSeek's peak hours (full price): weekdays 01:00-04:00 and 06:00-10:00 UTC; otherwise half price."""
    now = now or datetime.now(timezone.utc)
    return now.weekday() < 5 and (1 <= now.hour < 4 or 6 <= now.hour < 10)


def cost(model, usage, now=None):
    """Estimated USD cost of a reply, or None if the model's price is unknown."""
    price = next((p for m, p in PRICES.items() if model.startswith(m)), None)
    if not price or not usage:
        return None
    usd = (usage["input_tokens"] * price[0] + usage["output_tokens"] * price[1]) / 1e6
    if model.startswith("deepseek") and not deepseek_peak(now):
        usd /= 2
    return round(usd, 4)
