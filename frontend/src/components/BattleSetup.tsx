import type { BattleNode, RouteStep } from "../types";
import { CardChip, CardImage } from "./CardViewer";

const TREASURE_LABEL: Record<string, string> = {
  level_1: "Level 1", level_2: "Level 2", level_3: "Level 3", level_4: "Level 4",
};

/** Card names as chips with thumbnails; tap one to see the card. */
function List({ items }: { items: string[] }) {
  return items.length ? (
    <ul className="chips">
      {items.map((i, k) => (
        <li key={`${i}-${k}`}>
          <CardChip title={i} />
        </li>
      ))}
    </ul>
  ) : (
    <p className="muted">—</p>
  );
}

/** Everything needed to set up the table for one battle. */
export function BattleSetup({ node, step, added = [] }: { node: BattleNode; step?: RouteStep; added?: string[] }) {
  const deck = node.nemesis_deck;
  return (
    <div className="setup">
      <details open>
        <summary>Mages and supply</summary>
        <h4>Mages in your Barracks</h4>
        <List items={step?.mages ?? []} />
        {added.length > 0 && (
          <>
            <h4>Added to your Barracks after defeats</h4>
            <List items={added} />
          </>
        )}
        <h4>Suggested supply (3 gems, 2 relics, 4 spells)</h4>
        <List items={step?.supply ?? []} />
        {step && step.banished.length > 0 && (
          <p className="muted small">
            Choosing this supply banishes: {step.banished.join(", ")}. You may build a different supply from your
            Barracks.
          </p>
        )}
      </details>

      {Object.keys(node.treasure_setup).length > 0 && (
        <details open>
          <summary>Treasures</summary>
          {Object.entries(node.treasure_setup).map(([level, who]) => (
            <div key={level}>
              <h4>
                {TREASURE_LABEL[level] ?? level} — {who}
              </h4>
              <List items={step?.treasures_available[level.replace("level_", "")] ?? []} />
            </div>
          ))}
        </details>
      )}

      <details>
        <summary>
          Nemesis: {node.nemesis} {node.life != null && <span className="muted">· {node.life} life</span>}
        </summary>
        <CardImage title={node.nemesis} />
        {node.expedition_modifiers.length > 0 && (
          <div className="callout">
            <strong>Expedition modifiers</strong>
            <ul>
              {node.expedition_modifiers.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </div>
        )}
        <h4>Build the nemesis deck</h4>
        <p className="small muted">
          For each tier, shuffle the nemesis' own cards with basic cards drawn at random from your collection, then
          stack tier 3 at the bottom, tier 2 on top of it and tier 1 on top. Follow the nemesis mat for its setup.
        </p>
        <table className="deck-recipe">
          <thead>
            <tr>
              <th></th>
              <th>Nemesis cards</th>
              <th>Basic</th>
              <th>Upgraded basic</th>
            </tr>
          </thead>
          <tbody>
            {(["tier_1", "tier_2", "tier_3"] as const).map((t, i) => (
              <tr key={t}>
                <th>Tier {i + 1}</th>
                <td>{deck[t].nemesis.length}</td>
                <td>{deck[t].basic.length}</td>
                <td>{deck[t].upgraded_basic.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      {node.friend && (
        <details>
          <summary>Friend & foe</summary>
          <h4>Friend</h4>
          <List items={[node.friend]} />
          <h4>Foe</h4>
          <List items={node.foe ? [node.foe] : []} />
        </details>
      )}
    </div>
  );
}

export function RewardsList({ node }: { node: BattleNode }) {
  const r = node.rewards;
  const extra = [...(r.extra_level_1 ?? []), ...(r.extra_level_2 ?? []), ...(r.extra_level_3 ?? [])];
  if (!r.treasures && !r.player_cards) return null;
  return (
    <div className="rewards">
      <h4>Add to your Barracks</h4>
      {r.treasures && (
        <>
          <p className="small muted">Level {r.treasure_level} treasures</p>
          <List items={r.treasures} />
        </>
      )}
      {r.mages && (
        <>
          <p className="small muted">New mage</p>
          <List items={r.mages} />
        </>
      )}
      {extra.length > 0 && (
        <>
          <p className="small muted">Extra treasures</p>
          <List items={extra} />
        </>
      )}
      <p className="small muted">Player cards</p>
      <List items={[...(r.player_cards ?? []), ...(r.extra_player_cards ?? [])]} />
    </div>
  );
}
