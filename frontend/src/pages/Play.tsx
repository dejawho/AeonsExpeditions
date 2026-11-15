import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { BattleSetup, RewardsList } from "../components/BattleSetup";
import { DefeatDraw } from "../components/DefeatDraw";
import { RoadMap } from "../components/RoadMap";
import { SceneBanner, useEraBackdrop } from "../art";
import { currentStep, orderedNodes, replay } from "../progress";
import { exportSave, getSave, putSave } from "../storage";
import type { Action, Chapter, Save } from "../types";

function stamp(a: Action): Action {
  return { ...a, at: new Date().toISOString() };
}

const short = (title: string) => title.replace(/ \(.*\)$/, "");
const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
/** Story fields are lists of paragraphs (saves from the first version used single strings). */
const paras = (x: string[] | string | undefined | null): string[] => (x == null ? [] : Array.isArray(x) ? x : [x]);

function Story({ paragraphs, className = "" }: { paragraphs: string[]; className?: string }) {
  return (
    <div className={`story ${className}`}>
      {paragraphs.map((p, i) => (
        <p key={i}>{p}</p>
      ))}
    </div>
  );
}

const approachOf = (ch: Chapter) => (ch.approach ? ch.approach : paras(ch.introduction));

export function Play() {
  const { id } = useParams();
  const [save, setSave] = useState<Save | null | undefined>(undefined);
  const [tab, setTab] = useState<"battle" | "journal">("battle");
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (id) getSave(id).then(setSave);
  }, [id]);

  const state = useMemo(() => (save ? replay(save.expedition, save.actions) : null), [save]);
  useEraBackdrop(save?.story.era);

  if (save === undefined) return <div className="page muted">Loading…</div>;
  if (save === null || !state)
    return (
      <div className="page">
        <p>This expedition is not saved in this browser.</p>
        <Link to="/" className="btn">
          Back
        </Link>
      </div>
    );

  const { expedition: exp, story } = save;
  const node = exp.nodes[state.current];
  const chapter = story.chapters[state.current];
  const step = currentStep(exp, state);
  const isStart = save.actions.length === 0;
  const attempt = state.attempts[state.current];
  const fork = exp.forks.find((f) => f.from === state.current);
  // first-version saves have no choice texts: rebuild a plain choice from the map
  const choice =
    chapter.choice ??
    (fork
      ? {
          kind: fork.kind,
          intro: "The trail splits before you.",
          note: "",
          options: fork.options.map((o) => ({
            node: o, label: exp.nodes[o].branch?.toUpperCase() ?? o, setting: story.chapters[o].setting,
            text: capitalize(story.chapters[o].setting) + ".", harder: false, note: "",
          })),
        }
      : null);

  const act = async (action: Action) => {
    setError("");
    try {
      replay(exp, [...save.actions, action]); // validate before saving
      const next = { ...save, actions: [...save.actions, stamp(action)] };
      await putSave(next);
      setSave(next);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const undo = async () => {
    const next = { ...save, actions: save.actions.slice(0, -1) };
    await putSave(next);
    setSave(next);
  };

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(exp.share_code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard not available (e.g. plain http): the code is visible anyway */
    }
  };

  const heading = state.phase === "briefing" ? chapter.place ?? capitalize(chapter.setting) : short(node.nemesis);

  return (
    <div className="page">
      <header className="play-head">
        <div>
          <p className="eyebrow">
            {story.mission} · {story.era}
          </p>
          <h1>{save.name}</h1>
          <p className="small">
            <span className="mono">{exp.share_code}</span>{" "}
            <button className="btn small" onClick={copyCode}>
              {copied ? "Copied" : "Copy code"}
            </button>
          </p>
        </div>
        <div className="score">
          <span className="score-num">{state.score}</span>
          <span className="muted small">/ {state.maxScore} points</span>
        </div>
      </header>

      <label className="check small">
        <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} /> Reveal the whole map
        (spoilers)
      </label>
      <RoadMap exp={exp} state={state} reveal={reveal} />

      <nav className="tabs">
        <button className={tab === "battle" ? "active" : ""} onClick={() => setTab("battle")}>
          {state.phase === "completed" ? "Ending" : "Current battle"}
        </button>
        <button className={tab === "journal" ? "active" : ""} onClick={() => setTab("journal")}>
          Journal
        </button>
      </nav>

      {error && <p className="error">{error}</p>}

      {tab === "battle" && (
        <article className="card">
          {state.phase !== "briefing" && (
            <SceneBanner scene={state.phase === "completed" ? "ending" : state.phase} />
          )}
          {isStart && (
            <div className="prologue">
              <h2>Prologue</h2>
              <Story paragraphs={story.prologue} />
              {story.author && <p className="small muted">✦ Story rewritten by {story.author.label}.</p>}
            </div>
          )}

          <p className="eyebrow">
            Battle {node.battle} of {exp.settings.battles}
            {node.branch ? ` · Path ${node.branch.toUpperCase()}` : ""}
            {attempt > 1 && state.phase !== "completed" ? ` · attempt ${attempt}` : ""}
          </p>
          <h2>{heading}</h2>

          {state.phase === "briefing" && (
            <>
              <Story paragraphs={approachOf(chapter)} />
              <div className="row gap wrap actions briefing-cta">
                <button className="btn primary" onClick={() => act({ type: "begin" })}>
                  Face the nemesis
                </button>
              </div>
            </>
          )}

          {state.phase === "battle" && (
            <>
              {attempt === 1 && <Story paragraphs={paras(chapter.encounter)} />}
              {attempt > 1 && (
                <Story paragraphs={[`You return to ${chapter.setting}. This time you know what is waiting for you.`]} />
              )}
              <BattleSetup node={node} step={step} added={state.added.map((a) => a.card)} />
              <div className="row gap wrap actions">
                <button className="btn primary" onClick={() => act({ type: "win" })}>
                  We won
                </button>
                <button className="btn danger" onClick={() => act({ type: "loss" })}>
                  We lost
                </button>
              </div>
            </>
          )}

          {state.phase === "defeat" && (
            <>
              <Story paragraphs={paras(chapter.defeat)} />
              <DefeatDraw save={save} state={state} step={step} onAdd={act} />
              <div className="row gap wrap actions">
                <button className={state.reinforced ? "btn primary" : "btn"} onClick={() => act({ type: "retry" })}>
                  {state.reinforced ? `Fight again (attempt ${attempt + 1})` : "Fight again without a new card"}
                </button>
              </div>
            </>
          )}

          {state.phase === "victory" && (
            <>
              <Story paragraphs={paras(chapter.victory)} />
              <RewardsList node={node} />
              {choice ? (
                <div className="choices">
                  <h3>{choice.kind === "finale" ? "Choose how the expedition ends" : "Choose your path"}</h3>
                  <p className="choices-intro">
                    {choice.intro} {choice.note}
                  </p>
                  {choice.options.map((o) => {
                    const n = exp.nodes[o.node];
                    return (
                      <button key={o.node} className="card choice" onClick={() => act({ type: "advance", next: o.node })}>
                        <span className="eyebrow">Path {o.label}</span>
                        <span className="choice-text">{o.text}</span>
                        {o.note && <span className="small gold">{o.note}</span>}
                        {reveal && <span className="muted small">{short(n.nemesis)} · difficulty {n.difficulty}</span>}
                      </button>
                    );
                  })}
                </div>
              ) : (
                !node.final && (
                  <div className="row gap wrap actions">
                    <button className="btn primary" onClick={() => act({ type: "advance" })}>
                      Continue to Battle {node.battle + 1}
                    </button>
                  </div>
                )
              )}
            </>
          )}

          {state.phase === "completed" && (
            <>
              <Story paragraphs={paras(chapter.victory)} />
              <h3>Epilogue</h3>
              <Story paragraphs={paras(story.epilogues[state.current])} />
              <div className="callout">
                <strong>Expedition complete.</strong> Final score {state.score} / {state.maxScore}.
                <ul>
                  {state.results
                    .filter((r) => r.result === "win")
                    .map((r) => (
                      <li key={r.node}>
                        Battle {exp.nodes[r.node].battle} — {short(exp.nodes[r.node].nemesis)}: won on attempt {r.attempt} (
                        {r.points} points)
                      </li>
                    ))}
                </ul>
              </div>
            </>
          )}
        </article>
      )}

      {tab === "journal" && <Journal save={save} path={state.path} />}

      <div className="row gap wrap footer-actions">
        <button className="btn small" disabled={save.actions.length === 0} onClick={undo}>
          Undo last step
        </button>
        <button className="btn small" onClick={() => exportSave(save)}>
          Export save
        </button>
        <Link className="btn small" to="/">
          All expeditions
        </Link>
      </div>

      <p className="credits small muted">
        Lore and card text from the{" "}
        <a href="https://aeonsend.wiki.gg/" target="_blank" rel="noreferrer">
          Aeon's End Wiki
        </a>{" "}
        (CC BY-SA 4.0). Aeon's End © Indie Boards &amp; Cards / Action Phase Games.
      </p>
    </div>
  );
}

function Journal({ save, path }: { save: Save; path: string[] }) {
  const { expedition: exp, story } = save;
  const played = orderedNodes(exp).filter((n) => path.includes(n.id));
  const last = path[path.length - 1];
  return (
    <article className="card journal">
      <h2>Prologue</h2>
      <Story paragraphs={story.prologue} />
      {played.map((n) => {
        const ch = story.chapters[n.id];
        return (
          <section key={n.id}>
            <h3>
              Battle {n.battle}
              {n.branch ? ` · Path ${n.branch.toUpperCase()}` : ""}: {short(n.nemesis)}
            </h3>
            <Story paragraphs={[...approachOf(ch), ...paras(ch.encounter), ...paras(ch.victory)]} />
            {story.epilogues[n.id] && last === n.id && (
              <>
                <h3>Epilogue</h3>
                <Story paragraphs={paras(story.epilogues[n.id])} />
              </>
            )}
          </section>
        );
      })}
      {played.length === 0 && <p className="muted">No battle won yet.</p>}
    </article>
  );
}
