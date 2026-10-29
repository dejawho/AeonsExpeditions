// Expedition progress is a list of actions; the state is rebuilt by replaying them.
// Undo = drop the last action. Scoring is the official Expedition one: 6/4/2/0 points for a win
// on the 1st/2nd/3rd/later attempt.
// Each battle starts with a briefing (the approach story, nemesis still hidden); "begin" reveals the
// nemesis and the setup. After a defeat, "reinforce" records the card added to the Barracks.
import type { Action, BattleNode, DefeatSource, Expedition, RouteStep } from "./types";

export type Phase = "briefing" | "battle" | "victory" | "defeat" | "completed";

export interface Result {
  node: string;
  result: "win" | "loss";
  attempt: number;
  points?: number;
  at?: string;
}

/** A card added to the Barracks after a defeat (Expedition rules: one per lost battle). */
export interface Added {
  node: string;
  attempt: number;
  source: DefeatSource;
  level?: number | null;
  card: string;
}

export interface State {
  phase: Phase;
  current: string;
  path: string[]; // battles won, in order
  attempts: Record<string, number>;
  results: Result[];
  score: number;
  maxScore: number;
  added: Added[];
  reinforced: boolean; // the card of the current defeat has been added
}

const SCORE: Record<number, number> = { 1: 6, 2: 4, 3: 2 };

/** Battle ids in play order: 1, 2a, 2b, 3 ... (never rely on object key order: JS sorts '1','3' before '2a'). */
export function orderedNodes(exp: Expedition): BattleNode[] {
  return Object.values(exp.nodes).sort((a, b) => a.battle - b.battle || (a.branch ?? "").localeCompare(b.branch ?? ""));
}

export function apply(state: State, exp: Expedition, action: Action): State {
  const s: State = {
    ...state, path: [...state.path], attempts: { ...state.attempts }, results: [...state.results], added: [...state.added],
  };
  const cur = s.current;
  const node = exp.nodes[cur];
  if (s.phase === "completed") throw new Error("The expedition is already completed.");
  // saves made before briefings existed go straight from the start to win/loss
  if (s.phase === "briefing" && (action.type === "win" || action.type === "loss")) s.phase = "battle";
  switch (action.type) {
    case "begin":
      if (s.phase !== "briefing") throw new Error("The battle has already begun.");
      s.phase = "battle";
      return s;
    case "win": {
      if (s.phase !== "battle") throw new Error("No battle in progress.");
      const attempt = s.attempts[cur];
      const points = SCORE[attempt] ?? 0;
      s.score += points;
      s.path.push(cur);
      s.results.push({ node: cur, result: "win", attempt, points, at: action.at });
      s.phase = node.final ? "completed" : "victory";
      return s;
    }
    case "loss":
      if (s.phase !== "battle") throw new Error("No battle in progress.");
      s.results.push({ node: cur, result: "loss", attempt: s.attempts[cur], at: action.at });
      s.phase = "defeat";
      s.reinforced = false;
      return s;
    case "reinforce":
      if (s.phase !== "defeat") throw new Error("Cards are added after a defeat.");
      if (s.reinforced) throw new Error("A card has already been added for this defeat.");
      s.added.push({ node: cur, attempt: s.attempts[cur], source: action.source, level: action.level, card: action.card });
      s.reinforced = true;
      return s;
    case "retry":
      if (s.phase !== "defeat") throw new Error("Nothing to retry.");
      s.attempts[cur] += 1;
      s.phase = "battle";
      s.reinforced = false;
      return s;
    case "advance": {
      if (s.phase !== "victory") throw new Error("Win the current battle first.");
      const next = action.next ?? (node.next.length === 1 ? node.next[0] : undefined);
      if (!next || !node.next.includes(next)) throw new Error("Choose a path.");
      s.current = next;
      s.phase = "briefing";
      s.attempts[next] = 1;
      return s;
    }
  }
}

/** Has the players' party seen this nemesis yet (faced, fought, or beaten it)? */
export function nemesisKnown(state: State, id: string): boolean {
  return state.path.includes(id) || (id === state.current && state.phase !== "briefing");
}

export function replay(exp: Expedition, actions: Action[]): State {
  const first = orderedNodes(exp)[0].id;
  let s: State = {
    phase: "briefing", current: first, path: [], attempts: { [first]: 1 }, results: [], score: 0,
    maxScore: 6 * exp.settings.battles, added: [], reinforced: false,
  };
  for (const a of actions) s = apply(s, exp, a);
  return s;
}

/** Barracks / suggested supply for the current battle: the route that matches the path taken so far. */
export function currentStep(exp: Expedition, state: State): RouteStep | undefined {
  const prefix = state.phase === "victory" || state.phase === "completed" ? state.path : [...state.path, state.current];
  const route = exp.routes.find((r) => prefix.every((n, i) => r.nodes[i] === n));
  return route?.steps[prefix.length - 1];
}

/** Status of each battle on the map, for the road map component. */
export type NodeStatus = "won" | "current" | "option" | "skipped" | "ahead";

export function nodeStatus(exp: Expedition, state: State, id: string): NodeStatus {
  if (state.path.includes(id) && !(id === state.current && state.phase !== "victory" && state.phase !== "completed"))
    return "won";
  if (id === state.current) return "current";
  if (state.phase === "victory" && exp.nodes[state.current].next.includes(id)) return "option";
  // reachable from the current battle?
  const reachable = new Set<string>();
  const stack = [state.current];
  while (stack.length) {
    const n = stack.pop()!;
    for (const m of exp.nodes[n].next) if (!reachable.has(m)) reachable.add(m), stack.push(m);
  }
  return reachable.has(id) ? "ahead" : "skipped";
}

export function summary(exp: Expedition, actions: Action[]) {
  const s = replay(exp, actions);
  const battle = exp.nodes[s.current].battle;
  const label =
    s.phase === "completed" ? "Completed" : `Battle ${battle} of ${exp.settings.battles}${s.phase === "defeat" ? " (lost)" : ""}`;
  return { state: s, label };
}
