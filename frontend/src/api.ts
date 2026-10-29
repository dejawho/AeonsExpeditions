import type { Catalog, DefeatSource, GenerateResponse, RewriteEvent, Settings } from "./types";

async function failure(res: Response): Promise<Error> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch {
    /* keep statusText */
  }
  return new Error(detail);
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) throw await failure(res);
  return res.json() as Promise<T>;
}

export const api = {
  catalog: () => call<Catalog>("/api/catalog"),
  generate: (settings: Settings) => call<GenerateResponse>("/api/generate", { method: "POST", body: JSON.stringify(settings) }),
  /** The card added to the Barracks after a defeat (drawn on the server: it knows the card pools). */
  defeatDraw: (code: string, path: string[], source: DefeatSource, level: number | null, taken: string[]) =>
    call<{ card: string; source: DefeatSource; level: number | null }>("/api/defeat-draw", {
      method: "POST",
      body: JSON.stringify({ code, path, source, level, taken }),
    }),
  readCode: (code: string) =>
    call<{ settings: Settings; data_changed: boolean }>(`/api/codes/${encodeURIComponent(code.trim())}`),
  /** Streams the AI rewrite of an expedition's story (newline-delimited JSON events). */
  async rewrite(
    code: string,
    provider: string,
    onEvent: (e: RewriteEvent) => void,
    { signal, newVersion = false }: { signal?: AbortSignal; newVersion?: boolean } = {},
  ) {
    const res = await fetch("/api/rewrite", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, provider, new_version: newVersion }),
      signal,
    });
    if (!res.ok || !res.body) throw await failure(res);
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) if (line.trim()) onEvent(JSON.parse(line) as RewriteEvent);
    }
    if (buffer.trim()) onEvent(JSON.parse(buffer) as RewriteEvent);
  },
};
