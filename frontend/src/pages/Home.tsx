import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { summary } from "../progress";
import { deleteSave, exportSave, importSave, listSaves, storageIsPersistent } from "../storage";
import type { Save } from "../types";

export function Home() {
  const [saves, setSaves] = useState<Save[] | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const refresh = () => listSaves().then(setSaves).catch((e) => setError(String(e)));
  useEffect(() => {
    refresh();
  }, []);

  const fromCode = (e: React.FormEvent) => {
    e.preventDefault();
    navigate(`/preview?code=${encodeURIComponent(code.trim().toUpperCase())}`);
  };

  const onImport = async (file?: File) => {
    if (!file) return;
    setError("");
    try {
      const save = await importSave(file);
      navigate(`/play/${save.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const remove = async (s: Save) => {
    if (!confirm(`Delete "${s.name}"? This cannot be undone (export it first if you want a backup).`)) return;
    await deleteSave(s.id);
    refresh();
  };

  return (
    <div className="page">
      <section className="hero">
        <h1>Aeon's Expeditions</h1>
        <p>Branching expeditions for Aeon's End, with a story drawn from the lore of Gravehold.</p>
        <div className="row gap wrap">
          <Link to="/new" className="btn primary">
            New expedition
          </Link>
          <button className="btn" onClick={() => fileInput.current?.click()}>
            Import save file
          </button>
          <input ref={fileInput} type="file" accept=".json,application/json" hidden onChange={(e) => onImport(e.target.files?.[0])} />
        </div>
        <form className="row gap wrap code-form" onSubmit={fromCode}>
          <input
            className="input mono"
            placeholder="Share code, e.g. AEX-06T83-MG5ZZ-..."
            value={code}
            onChange={(e) => setCode(e.target.value)}
            aria-label="Share code"
          />
          <button className="btn" disabled={!code.trim()}>
            Open code
          </button>
        </form>
        {error && <p className="error">{error}</p>}
      </section>

      <section>
        <h2>Your expeditions</h2>
        <p className="muted small">
          Saved in this browser only. Export a save to keep a backup or to continue on another device.
          {!storageIsPersistent() && " Storage is unavailable here: saves will be lost when the page closes."}
        </p>
        {saves === null ? (
          <p className="muted">Loading…</p>
        ) : saves.length === 0 ? (
          <p className="muted">No expeditions yet.</p>
        ) : (
          <ul className="saves">
            {saves.map((s) => {
              const { state, label } = summary(s.expedition, s.actions);
              return (
                <li key={s.id} className="card save">
                  <div>
                    <h3>{s.name}</h3>
                    <p className="muted small">
                      {s.story.mission} · {s.expedition.settings.players} players · {label} · score {state.score}/
                      {state.maxScore}
                    </p>
                    <p className="muted small">Last played {new Date(s.updatedAt).toLocaleString()}</p>
                  </div>
                  <div className="row gap wrap">
                    <Link className="btn primary" to={`/play/${s.id}`}>
                      {state.phase === "completed" ? "View" : "Resume"}
                    </Link>
                    <button className="btn" onClick={() => exportSave(s)}>
                      Export
                    </button>
                    <button className="btn danger" onClick={() => remove(s)}>
                      Delete
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
