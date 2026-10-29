import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { AiRewrite } from "../components/AiRewrite";
import { RoadMap } from "../components/RoadMap";
import { newId, putSave, requestPersistence } from "../storage";
import type { Generated, Settings, Story } from "../types";
import { savePrefs } from "./NewExpedition";

/**
 * Generates and shows an expedition before it is started.
 * Reached from the form (settings in the navigation state) or from a share code (?code=AEX-...).
 * Once generated, the URL carries the share code, so a reload or a shared link shows the same expedition.
 */
export function Preview() {
  const location = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const code = params.get("code");
  const incoming = (location.state as { settings?: Settings } | null)?.settings;
  const [preview, setPreview] = useState<Generated | null>(null);
  const [original, setOriginal] = useState<Story | null>(null); // the template story, before any AI rewrite
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [dataChanged, setDataChanged] = useState(false);
  const [reveal, setReveal] = useState(false);
  const shown = useRef<string | null>(null); // share code currently displayed (avoids regenerating it)

  async function generate(settings: Settings) {
    setBusy(true);
    setError("");
    try {
      const { ai_story, ...g } = await api.generate(settings);
      shown.current = g.expedition.share_code;
      // a code with a stored AI story opens with it: the same code shows the same story everywhere
      const story = ai_story ?? g.story;
      setPreview({ ...g, story });
      setOriginal(g.story);
      setName(story.title);
      setParams({ code: g.expedition.share_code }, { replace: true, state: null });
    } catch (e) {
      setPreview(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (code && code === shown.current) return;
    if (code) {
      api
        .readCode(code)
        .then(({ settings, data_changed }) => {
          setDataChanged(data_changed);
          return generate(settings);
        })
        .catch((e) => {
          setError(e instanceof Error ? e.message : String(e));
          setBusy(false);
        });
    } else if (incoming) {
      generate(incoming);
    } else {
      navigate("/new", { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  const reroll = () => {
    if (!preview) return;
    const s = { ...preview.expedition.settings, forks: null, seed: null };
    savePrefs(s);
    generate(s);
  };

  const changeStory = (story: Story) => {
    if (!preview) return;
    if (name === preview.story.title) setName(story.title); // keep a name the user typed
    setPreview({ ...preview, story });
  };

  const start = async () => {
    if (!preview) return;
    const now = new Date().toISOString();
    const id = newId();
    await putSave({ id, name: name.trim() || preview.story.title, createdAt: now, updatedAt: now, actions: [], notes: "", ...preview });
    requestPersistence();
    navigate(`/play/${id}`);
  };

  return (
    <div className="page">
      <p>
        <Link to="/new" className="btn small">
          ← Change settings
        </Link>
      </p>

      {busy && (
        <section className="card preview loading" aria-busy="true">
          <p className="eyebrow">Please wait</p>
          <h2>Drawing your expedition…</h2>
          <p className="muted">Shuffling the randomizers, consulting the archives of Gravehold.</p>
        </section>
      )}

      {error && !busy && (
        <section className="card">
          <p className="error">{error}</p>
          <Link to="/new" className="btn">
            Back to the settings
          </Link>
        </section>
      )}

      {preview && !busy && (
        <section className="card preview">
          {dataChanged && (
            <p className="callout">
              This share code was made with an older version of the card data, so the expedition may differ from the
              original.
            </p>
          )}
          <p className="eyebrow">
            {preview.story.mission} · {preview.story.era}
          </p>
          <h1>{preview.story.title}</h1>
          <p className="mono small">Share code: {preview.expedition.share_code}</p>
          <label className="check small">
            <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} /> Reveal the map
            (spoilers)
          </label>
          <RoadMap exp={preview.expedition} reveal={reveal} />
          <div className="story">
            {preview.story.prologue.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
          {original && (
            <AiRewrite
              code={preview.expedition.share_code}
              story={preview.story}
              original={original}
              onStory={changeStory}
            />
          )}
          {preview.expedition.warnings.length > 0 && (
            <ul className="warnings">
              {preview.expedition.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          <div className="row gap wrap">
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} aria-label="Expedition name" />
            <button className="btn primary" onClick={start}>
              Start expedition
            </button>
            <button className="btn" onClick={reroll}>
              Generate another
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
