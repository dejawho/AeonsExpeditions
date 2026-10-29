// Run: node --experimental-strip-types tests/progress.test.mjs <expedition.json>...
// Plays real generated expeditions through the progress state machine.
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { replay, currentStep, orderedNodes, nodeStatus, nemesisKnown } from "../src/progress.ts";

for (const file of process.argv.slice(2)) {
  const { expedition: exp } = JSON.parse(readFileSync(file, "utf8"));
  const order = orderedNodes(exp).map((n) => n.id);
  assert.equal(order[0], "1", "battle 1 first");
  assert.deepEqual(order, [...order].sort((a, b) => parseInt(a) - parseInt(b) || a.localeCompare(b)));

  for (const route of exp.routes) {
    const actions = [];
    let s = replay(exp, actions);
    route.nodes.forEach((nid, i) => {
      assert.equal(s.current, nid);
      assert.equal(s.phase, "briefing");
      assert.equal(nemesisKnown(s, nid), false, "nemesis hidden during the briefing");
      assert.deepEqual(currentStep(exp, s), route.steps[i], `sheet for ${nid} on ${route.id}`);
      assert.throws(() => replay(exp, [...actions, { type: "retry" }]), "nothing to retry in a briefing");
      actions.push({ type: "begin" });
      s = replay(exp, actions);
      assert.equal(s.phase, "battle");
      assert.equal(nemesisKnown(s, nid), true);
      assert.throws(() => replay(exp, [...actions, { type: "begin" }]), "begin only once");
      assert.deepEqual(currentStep(exp, s), route.steps[i]);
      if (i === 1) {
        // lose once, check invalid actions, retry
        actions.push({ type: "loss" });
        s = replay(exp, actions);
        assert.equal(s.phase, "defeat");
        assert.deepEqual(currentStep(exp, s), route.steps[i]);
        assert.throws(() => replay(exp, [...actions, { type: "win" }]));
        assert.equal(s.reinforced, false);
        // add the card drawn after the defeat, once
        const card = { type: "reinforce", source: "gem", level: null, card: "Test Gem" };
        actions.push(card);
        s = replay(exp, actions);
        assert.equal(s.reinforced, true);
        assert.deepEqual(s.added, [{ node: nid, attempt: 1, source: "gem", level: null, card: "Test Gem" }]);
        assert.throws(() => replay(exp, [...actions, card]), "one card per defeat");
        actions.push({ type: "retry" });
        s = replay(exp, actions);
        assert.equal(s.reinforced, false);
        assert.throws(() => replay(exp, [...actions, card]), "no card outside a defeat");
        assert.equal(s.added.length, 1, "the card stays for the rest of the expedition");
      }
      actions.push({ type: "win" });
      s = replay(exp, actions);
      if (i < route.nodes.length - 1) {
        assert.equal(s.phase, "victory");
        const next = route.nodes[i + 1];
        assert.equal(nodeStatus(exp, s, nid), "won");
        if (exp.nodes[nid].next.length > 1) {
          assert.throws(() => replay(exp, [...actions, { type: "advance" }]), "fork needs a choice");
          assert.equal(nodeStatus(exp, s, next), "option");
        }
        actions.push({ type: "advance", next });
        s = replay(exp, actions);
      }
    });
    assert.equal(s.phase, "completed");
    const expected = 6 * route.nodes.length - 2; // one battle won on the 2nd attempt
    assert.equal(s.score, expected, `score on ${route.id}`);
    assert.equal(s.maxScore, 6 * exp.settings.battles);
    // skipped branches are marked as such
    for (const id of order) if (!route.nodes.includes(id)) assert.equal(nodeStatus(exp, s, id), "skipped");
    // undo restores the previous state exactly
    const undone = replay(exp, actions.slice(0, -1));
    assert.equal(undone.phase, "battle");
    assert.throws(() => replay(exp, [...actions, { type: "loss" }]), "completed is final");
  }
  // first-version saves (no "begin") still replay
  const legacy = replay(exp, [{ type: "win" }]);
  assert.ok(["victory", "completed"].includes(legacy.phase), "old saves without begin");
  console.log(`ok  ${file}: ${exp.routes.length} routes, layout ${exp.forks.map((f) => f.kind + "@" + f.after).join(" + ")}`);
}
