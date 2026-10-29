import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AiProvider, Story } from "../types";

interface Props {
  code: string;
  story: Story;
  /** the template story, to switch back to */
  original: Story;
  onStory: (story: Story) => void;
}

interface Progress {
  label: string;
  expected: number;
  chars: number;
  status: string;
}

/**
 * Optional: ask the server to rework the story with an LLM. Shown only when the server has an AI
 * provider configured (its API key lives on the server, never in the browser).
 */
export function AiRewrite({ code, story, original, onStory }: Props) {
  const [providers, setProviders] = useState<AiProvider[]>([]);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    api
      .catalog()
      .then((c) => setProviders(c.ai ?? []))
      .catch(() => setProviders([]));
    return () => abort.current?.abort();
  }, []);

  // a new expedition (reroll): forget the previous rewrite
  useEffect(() => {
    abort.current?.abort();
    setProgress(null);
    setError("");
    setNote("");
  }, [code]);

  if (!providers.length) return null;

  const rewrite = async (p: AiProvider, newVersion = false) => {
    const controller = new AbortController();
    abort.current = controller;
    setError("");
    setNote("");
    setProgress({ label: p.label, expected: 1, chars: 0, status: "Waiting for the writer…" });
    try {
      await api.rewrite(
        code,
        p.id,
        (e) => {
          if (e.type === "queued") setProgress((s) => s && { ...s, expected: e.expected_chars });
          else if (e.type === "started") setProgress((s) => s && { ...s, status: "Reading the lore of this expedition…" });
          else if (e.type === "progress" || (e.type === "waiting" && e.chars > 0))
            setProgress((s) => s && { ...s, chars: e.chars, status: "Writing…" });
          else if (e.type === "done") {
            if (e.story.share_code !== code) throw new Error("the server rewrote a different expedition");
            onStory(e.story);
            const { rewritten_chapters: done, total_chapters: total } = e.report;
            if (done < total) setNote(`${total - done} of ${total} chapters kept their original text (they failed a check).`);
          } else if (e.type === "error") throw new Error(e.message);
        },
        { signal: controller.signal, newVersion },
      );
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (abort.current === controller) setProgress(null);
    }
  };

  const cancel = () => {
    abort.current?.abort();
    setProgress(null);
    setNote("Cancelled. The server still finishes the request: asking again soon returns that story at no extra cost.");
  };

  const author = story.author;
  // a new version comes from the same writer if it is still enabled, else from the default one
  const newVersionOf = (id: string) => providers.find((p) => p.id === id) ?? providers[0]; // providers is not empty here
  const pct = progress ? Math.min(99, Math.round((100 * progress.chars) / progress.expected)) : 0;

  return (
    <div className="ai-box">
      {author ? (
        <p className="small">
          ✦ Story rewritten by <strong>{author.label}</strong> ({author.rewritten}/{author.chapters} chapters
          {author.cost_usd != null ? `, about $${author.cost_usd.toFixed(3)}` : ""}). Stored with the share code:
          anyone opening it gets this story.{" "}
          <button className="btn small" onClick={() => onStory(original)}>
            Use the original story
          </button>{" "}
          {!progress && (
            <button
              className="btn small"
              onClick={() => {
                const p = newVersionOf(author.provider);
                if (confirm(`Write a new version with ${p.label}? It replaces the stored story for this code and costs another rewrite.`))
                  rewrite(p, true);
              }}
            >
              Write a new version
            </button>
          )}
        </p>
      ) : (
        !progress && (
          <>
            <p className="small muted">
              Let an AI rework the story from the lore of this expedition. It takes a minute or two; spoilers stay
              hidden.
            </p>
            <div className="row gap wrap">
              {providers.map((p, i) => (
                // the server lists its default provider first
                <button key={p.id} className={i === 0 ? "btn primary" : "btn"} onClick={() => rewrite(p)}>
                  ✦ Rewrite with {p.label}
                </button>
              ))}
            </div>
          </>
        )
      )}
      {progress && (
        <div className="ai-progress" role="status">
          <span className="small">
            {progress.label}: {progress.status}
            {progress.chars > 0 ? ` ${pct}%` : ""}
          </span>
          <progress max={100} value={progress.chars > 0 ? pct : undefined} />
          <button className="btn small" onClick={cancel}>
            Cancel
          </button>
        </div>
      )}
      {note && <p className="small muted">{note}</p>}
      {error && <p className="error small">{error}</p>}
    </div>
  );
}
