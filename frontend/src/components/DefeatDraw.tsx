import { useState } from "react";
import { api } from "../api";
import type { State } from "../progress";
import type { Action, DefeatSource, RouteStep, Save } from "../types";
import { CardChip } from "./CardViewer";

interface Props {
  save: Save;
  state: State;
  step?: RouteStep;
  onAdd: (action: Action) => void;
}

const SOURCES: { source: DefeatSource; label: string }[] = [
  { source: "mage", label: "A random mage" },
  { source: "gem", label: "A gem" },
  { source: "relic", label: "A relic" },
  { source: "spell", label: "A spell" },
];

/**
 * Expedition rule after a lost battle: the players add one card to their Barracks, from the source they choose
 * (a random mage, a gem / relic / spell randomizer, or a treasure deck already drawn from), then fight again.
 */
export function DefeatDraw({ save, state, step, onAdd }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const exp = save.expedition;
  const added = state.added[state.added.length - 1];

  if (state.reinforced && added) {
    return (
      <div className="callout defeat-draw">
        <strong>Added to your Barracks</strong>
        <ul className="chips">
          <li>
            <CardChip title={added.card} />
          </li>
        </ul>
        <p className="small muted">Undo last step to choose another kind of card.</p>
      </div>
    );
  }

  // treasure decks already drawn from on this route (none before the first victory)
  const levels = Object.keys(step?.treasures_available ?? {})
    .map(Number)
    .sort((a, b) => a - b);

  const draw = async (source: DefeatSource, level: number | null = null) => {
    setBusy(true);
    setError("");
    try {
      const path = [...state.path, state.current];
      const r = await api.defeatDraw(exp.share_code, path, source, level, state.added.map((a) => a.card));
      onAdd({ type: "reinforce", source: r.source, level: r.level, card: r.card });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="callout defeat-draw">
      <strong>After a defeat, add one card to your Barracks.</strong> Which kind do you draw?
      <div className="row gap wrap">
        {SOURCES.map((s) => (
          <button key={s.source} className="btn small" disabled={busy} onClick={() => draw(s.source)}>
            {s.label}
          </button>
        ))}
        {levels.map((l) => (
          <button key={l} className="btn small" disabled={busy} onClick={() => draw("treasure", l)}>
            A level {l} treasure
          </button>
        ))}
      </div>
      {levels.length === 0 && <p className="small muted">No treasure deck has been drawn from yet.</p>}
      {error && <p className="error small">{error}</p>}
    </div>
  );
}
