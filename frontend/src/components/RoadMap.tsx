import type { BattleNode, Expedition } from "../types";
import { nemesisKnown, nodeStatus, orderedNodes, type State } from "../progress";

interface Props {
  exp: Expedition;
  state?: State; // absent = preview (nothing played yet)
  reveal: boolean; // show every branch and every nemesis
}

const short = (title: string) => title.replace(/ \(.*\)$/, "");

/** The map keeps its secrets: unless revealed, it shows one box per battle (no forks) and only
 *  the nemeses the party has already faced. */
export function RoadMap({ exp, state, reveal }: Props) {
  const byBattle = new Map<number, BattleNode[]>();
  for (const n of orderedNodes(exp)) byBattle.set(n.battle, [...(byBattle.get(n.battle) ?? []), n]);

  return (
    <ol className="roadmap" aria-label="Expedition map">
      {[...byBattle.entries()].map(([battle, nodes]) => {
        let shown: { key: string; status: string; branch: string | null; name: string | null; diff: number | null }[];
        if (reveal) {
          shown = nodes.map((n) => ({
            key: n.id,
            status: state ? nodeStatus(exp, state, n.id) : "ahead",
            branch: n.branch,
            name: short(n.nemesis),
            diff: n.difficulty,
          }));
        } else {
          // the battle on the party's path (if reached), otherwise an anonymous step
          const onPath = state ? nodes.find((n) => state.path.includes(n.id) || n.id === state.current) : undefined;
          const status = onPath && state ? nodeStatus(exp, state, onPath.id) : "ahead";
          const known = onPath && state ? nemesisKnown(state, onPath.id) : false;
          shown = [{
            key: onPath?.id ?? `b${battle}`,
            status: status === "option" ? "ahead" : status,
            branch: null,
            name: known && onPath ? short(onPath.nemesis) : null,
            diff: known && onPath ? onPath.difficulty : null,
          }];
        }
        return (
          <li key={battle} className="roadmap-step">
            <span className="roadmap-num">Battle {battle}</span>
            <div className="roadmap-nodes">
              {shown.map((n) => (
                <div key={n.key} className={`node node-${n.status}`}>
                  {n.branch && <span className="node-branch">Path {n.branch.toUpperCase()}</span>}
                  <span className="node-name">{n.name ?? "?"}</span>
                  {n.diff != null && <span className="node-diff">difficulty {n.diff}</span>}
                </div>
              ))}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
