// seat_gate.mjs — per-seat authorization gate for cartooner-* skill CLIs.
//
// Hard-stop entry guard. Add to the top of any cartooner-* skill executable
// (generate_*.mjs / cli.mjs / run-*.mjs / etc.) so unauthorized seats can
// never invoke the binary directly via absolute path:
//
//   import { gate } from "<CLAWSEAT_ROOT>/core/skills/cartooner-harness/scripts/seat_gate.mjs";
//   gate({ skill: "cartooner-audio", allowed: ["builder-av"] });
//
// Reads $CLAWSEAT_SEAT (set by core/launchers/agent-launcher.sh per session.toml).
// If unset (running outside ClawSeat sandbox), gate is a no-op — preserving
// CLI usability for human / non-seat invocations from operator's shell.
//
// If $CLAWSEAT_SEAT is set AND not in `allowed`: print structured JSON
// refusal to stderr, exit 2. Memory's bash subprocess sees exit 2 + the
// "fix:" hint pointing at spawn_lane.py / dispatch_brief.py.
//
// Why this layer exists
// ---------------------
// cartooner-harness Authorization Matrix is soft-enforced via patrol audit
// (post-hoc) + AGENTS.md prose (LLM compliance). Both fail under the
// "convenient shortcut" pull — memory has API key, knows how to call
// generate_song.mjs, and does it instead of dispatching to builder-av.
// This gate is the structural enforcement that rationalization can't bypass.

const REFUSAL_EXIT_CODE = 2;

/**
 * @param {{ skill: string, allowed: string[] }} opts
 * @returns {void} — exits 2 if seat is not authorized.
 */
export function gate({ skill, allowed }) {
  if (!skill || typeof skill !== "string") {
    throw new Error("seat_gate: missing or non-string `skill`");
  }
  if (!Array.isArray(allowed) || allowed.length === 0) {
    throw new Error("seat_gate: `allowed` must be a non-empty array");
  }
  const seat = (process.env.CLAWSEAT_SEAT || "").trim().toLowerCase();
  if (!seat) {
    // No seat context — running outside ClawSeat sandbox (e.g., operator
    // testing the script directly). Gate is a no-op.
    return;
  }
  const allowedSet = new Set(allowed.map((s) => s.trim().toLowerCase()));
  if (allowedSet.has(seat)) {
    return;
  }
  const allowedList = [...allowedSet];
  const payload = {
    ok: false,
    error: "SEAT_NOT_AUTHORIZED",
    seat,
    skill,
    allowed: allowedList,
    fix:
      `seat ${JSON.stringify(seat)} cannot invoke ${skill} CLIs directly. ` +
      `Per cartooner-harness Authorization Matrix, only ${allowedList.join(" / ")} ` +
      `may produce this asset type. From memory's pane, dispatch with: ` +
      `spawn_lane.py --seat ${allowedList[0]} --count N --shot-id <id> --prompt <L2>`,
  };
  process.stderr.write(JSON.stringify(payload) + "\n");
  process.exit(REFUSAL_EXIT_CODE);
}

/**
 * Convenience for skills that need to check themselves multiple times or
 * inspect the seat without exiting.
 */
export function currentSeat() {
  return (process.env.CLAWSEAT_SEAT || "").trim().toLowerCase();
}
