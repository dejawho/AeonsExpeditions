// Shapes returned by the Python API (scraper/generate_expedition.py + storyteller.py).

export interface Settings {
  players: number;
  battles: number;
  forks: number | null;
  boxes: string[];
  xaxos_outcast: boolean;
  friends_foes: boolean;
  campaign_mechanics: boolean;
  seed: number | null;
}

export interface Box {
  title: string;
  wave: number | null;
  type: string | null;
  first_release: string | null;
  contents: Partial<Record<"mages" | "nemeses" | "player_cards" | "treasures" | "friends" | "foes", number>>;
}

export interface AiProvider {
  id: string;
  label: string;
  model: string;
}

export interface Catalog {
  boxes: Box[];
  data_version: number;
  ai?: AiProvider[];
}

export interface Tier {
  nemesis: string[];
  basic: string[];
  upgraded_basic: string[];
}

export interface NemesisDeck {
  tier_1: Tier;
  tier_2: Tier;
  tier_3: Tier;
  setup_cards: string[];
}

export interface Rewards {
  treasure_level?: number;
  treasures?: string[];
  mages?: string[];
  extra_level_1?: string[];
  extra_level_2?: string[];
  extra_level_3?: string[];
  extra_player_cards?: string[];
  player_cards?: string[];
}

export interface BattleNode {
  id: string;
  battle: number;
  branch: string | null;
  final: boolean;
  nemesis: string;
  nemesis_box: string;
  life: number | null;
  difficulty: number | null;
  expedition_modifiers: string[];
  nemesis_deck: NemesisDeck;
  treasure_setup: Record<string, string>;
  rewards: Rewards;
  next: string[];
  friend?: string;
  foe?: string;
}

export interface Fork {
  kind: "detour" | "finale";
  after: number;
  from: string;
  options: string[];
}

export interface RouteStep {
  node: string;
  mages: string[];
  supply: string[];
  banished: string[];
  treasures_available: Record<string, string[]>;
}

export interface Route {
  id: string;
  nodes: string[];
  steps: RouteStep[];
}

export interface Expedition {
  share_code: string;
  settings: Settings;
  data_version: number;
  starting_barracks: { mages: string[]; player_cards: string[] };
  forks: Fork[];
  edges: [string, string][];
  nodes: Record<string, BattleNode>;
  routes: Route[];
  warnings: string[];
}

export interface ChoiceOption {
  node: string;
  label: string;
  setting: string;
  text: string;
  harder: boolean;
  note: string;
}

export interface Choice {
  kind: "detour" | "finale";
  intro: string;
  options: ChoiceOption[];
  note: string;
}

export interface Chapter {
  battle: number;
  branch: string | null;
  nemesis: string;
  setting: string;
  place?: string; // the setting as a title, used as the briefing heading
  approach: string[]; // before the fight: never names the nemesis
  encounter: string[]; // the nemesis appears
  victory: string[];
  defeat: string[];
  choice: Choice | null;
  // saves from the first version had single strings instead
  introduction?: string;
}

export interface Story {
  title: string;
  era: string;
  mission: string;
  quest_giver: string;
  share_code: string;
  prologue: string[];
  chapters: Record<string, Chapter>;
  epilogues: Record<string, string[] | string>;
  sources: string[];
  /** set when an AI rewrote the template story */
  author?: StoryAuthor;
}

export interface StoryAuthor {
  provider: string;
  label: string;
  model: string;
  rewritten: number;
  chapters: number;
  usage?: { input_tokens: number; output_tokens: number };
  cost_usd?: number | null;
}

export type RewriteEvent =
  | { type: "queued"; provider: string; expected_chars: number }
  | { type: "started" }
  | { type: "waiting"; chars: number }
  | { type: "progress"; chars: number }
  | { type: "done"; story: Story; report: { rewritten_chapters: number; total_chapters: number; problems: Record<string, string> } }
  | { type: "error"; message: string };

export interface Generated {
  expedition: Expedition;
  story: Story;
}

/** /api/generate: also the AI story stored on the server for this share code, if any */
export interface GenerateResponse extends Generated {
  ai_story?: Story | null;
}

export type DefeatSource = "mage" | "gem" | "relic" | "spell" | "treasure";

export type Action =
  | { type: "begin"; at?: string }
  | { type: "win"; at?: string }
  | { type: "loss"; at?: string }
  | { type: "retry"; at?: string }
  /** after a defeat: the card added to the Barracks, from the source the players chose */
  | { type: "reinforce"; source: DefeatSource; level?: number | null; card: string; at?: string }
  | { type: "advance"; next?: string; at?: string };

export interface Save {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  expedition: Expedition;
  story: Story;
  actions: Action[];
  notes: string;
}
