import type { Box } from "../types";

interface Props {
  boxes: Box[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
}

function waveName(wave: number | null) {
  return wave == null ? "Promos & extras" : `Wave ${wave}`;
}

export function BoxPicker({ boxes, selected, onChange }: Props) {
  const waves = new Map<string, Box[]>();
  for (const b of boxes) waves.set(waveName(b.wave), [...(waves.get(waveName(b.wave)) ?? []), b]);

  const set = (titles: string[], on: boolean) => {
    const next = new Set(selected);
    titles.forEach((t) => (on ? next.add(t) : next.delete(t)));
    onChange(next);
  };

  return (
    <div className="boxpicker">
      <div className="row gap">
        <button type="button" className="btn small" onClick={() => set(boxes.map((b) => b.title), true)}>
          Select all
        </button>
        <button type="button" className="btn small" onClick={() => onChange(new Set())}>
          Clear
        </button>
        <span className="muted">{selected.size} of {boxes.length} selected</span>
      </div>
      {[...waves.entries()].map(([wave, list]) => {
        const all = list.every((b) => selected.has(b.title));
        return (
          <fieldset key={wave} className="wave">
            <legend>
              <label>
                <input type="checkbox" checked={all} onChange={(e) => set(list.map((b) => b.title), e.target.checked)} />{" "}
                {wave}
              </label>
            </legend>
            <div className="box-grid">
              {list.map((b) => (
                <label key={b.title} className={`box ${selected.has(b.title) ? "on" : ""}`}>
                  <input
                    type="checkbox"
                    checked={selected.has(b.title)}
                    onChange={(e) => set([b.title], e.target.checked)}
                  />
                  <span className="box-title">{b.title}</span>
                  <span className="box-meta">
                    {b.type ?? "Extra"}
                    {b.contents.mages ? ` · ${b.contents.mages} mages` : ""}
                    {b.contents.nemeses ? ` · ${b.contents.nemeses} nemeses` : ""}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}
