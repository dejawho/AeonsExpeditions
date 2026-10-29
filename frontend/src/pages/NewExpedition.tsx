import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { BoxPicker } from "../components/BoxPicker";
import type { Catalog, Settings } from "../types";

const PREFS_KEY = "aeons-expeditions:last-settings";

const DEFAULTS: Settings = {
  players: 2, battles: 4, forks: null, boxes: [], xaxos_outcast: false, friends_foes: false,
  campaign_mechanics: false, seed: null,
};

function loadPrefs(): Partial<Settings> {
  try {
    return JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}");
  } catch {
    return {};
  }
}

export function savePrefs(s: Settings) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify({ ...s, seed: null }));
  } catch {
    /* convenience only */
  }
}

/** The settings form. Generating happens on the preview page, so the button navigates at once. */
export function NewExpedition() {
  const navigate = useNavigate();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [settings, setSettings] = useState<Settings>({ ...DEFAULTS, ...loadPrefs() });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .catalog()
      .then((c) => {
        setCatalog(c);
        // an empty box list means "every box"
        setSelected(new Set(settings.boxes.length ? settings.boxes : c.boxes.map((b) => b.title)));
      })
      .catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const update = <K extends keyof Settings>(key: K, value: Settings[K]) => setSettings((s) => ({ ...s, [key]: value }));

  const generate = () => {
    const all = catalog && selected.size === catalog.boxes.length;
    // forks are always left to the seed: the branching is a surprise
    const s: Settings = { ...settings, forks: null, boxes: all ? [] : [...selected], seed: null };
    savePrefs(s);
    navigate("/preview", { state: { settings: s } });
  };

  if (!catalog) return <div className="page">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</div>;

  return (
    <div className="page">
      <h1>New expedition</h1>

      <section className="card">
        <h2>Game</h2>
        <div className="form-grid">
          <label>
            Players
            <select className="input" value={settings.players} onChange={(e) => update("players", +e.target.value)}>
              {[1, 2, 3, 4].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label>
            Battles
            <select className="input" value={settings.battles} onChange={(e) => update("battles", +e.target.value)}>
              <option value={4}>4 (standard)</option>
              <option value={5}>5 (with Battle 5, wave 9+)</option>
            </select>
          </label>
        </div>
        <p className="small muted">The road will branch along the way. Where, and how often, is a surprise.</p>
        <div className="row gap wrap">
          <label className="check">
            <input type="checkbox" checked={settings.friends_foes} onChange={(e) => update("friends_foes", e.target.checked)} />
            Friends &amp; Foes
          </label>
          <label className="check">
            <input type="checkbox" checked={settings.xaxos_outcast} onChange={(e) => update("xaxos_outcast", e.target.checked)} />
            Xaxos: Outcast instead of Gravehold
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={settings.campaign_mechanics}
              onChange={(e) => update("campaign_mechanics", e.target.checked)}
            />
            Allow boost / overheat cards
          </label>
        </div>
      </section>

      <section className="card">
        <h2>Your collection</h2>
        <BoxPicker boxes={catalog.boxes} selected={selected} onChange={setSelected} />
      </section>

      <div className="row gap wrap sticky-actions">
        <button className="btn primary" disabled={selected.size === 0} onClick={generate}>
          Generate expedition
        </button>
        {selected.size === 0 && <p className="muted small">Select at least one box.</p>}
      </div>
    </div>
  );
}
