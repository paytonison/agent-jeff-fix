# agent-jeff-fix
A fix for ChatGPT’s agent mode’s tendency to run around in circles.

---

Quoth Asari: "Yup — your diagnosis is on the money. You’re watching the GPU KV cache thrash while the agent “thinks” itself into a cul-de-sac, then starts free-associating to escape. The fix is to externalize state: push long-horizon working memory off VRAM and onto CPU RAM + disk, and give the agent a way to rewind to the last sane point instead of doubling down on a bad branch.

Here’s a clean blueprint you can hand to an engineer and have in prod next week.

Agent Time Machine (ATM)

1) State model (what you snapshot)
	•	Goal & subgoals: hierarchy + pointer to “active leaf”.
	•	Facts & constraints: typed, source-linked assertions (e.g., county=King, city=Seattle).
	•	Tool ledger: each call’s {name, inputs, outputs, status, latency, source URL, hash}.
	•	Working set: the current “scratch notes” distilled into a compact, structured summary (not raw token soup).
	•	Planner config: seeds, temperature, tool allow-list, budgets (tokens/time/tool-calls).

Keep it schema-ed, not free text. Snapshots become diffs, not megabyte blobs.

2) Snapshot engine
	•	Content-addressable store: hash(state) → blob (RocksDB/SQLite+blob/DuckDB).
	•	Delta compression: store diffs relative to parent snapshot.
	•	Auto-checkpoint policy:
	•	After each successful tool call,
	•	Before plan expansion,
	•	On constraint updates,
	•	Every N seconds of wall time.
	•	TTL + GC: keep full snapshots for “milestones,” otherwise deltas w/ TTL.

3) Loop + hallucination detectors (cheap heuristics that work)
	•	Cycle detector: high cosine similarity of the last K tool inputs and outputs + unchanged goal pointer.
	•	No-progress budget: X tool calls or Y seconds with zero new facts or constraints → trigger rollback.
	•	Constraint violation: any result conflicts with locked constraints (e.g., result geocodes to Renton while county=King & city=Seattle) → hard stop + rewind.
	•	Source-free claim: proposed action/claim without a source hash from the tool ledger → quarantine branch.
	•	Error motif: repeating the same exception or 4xx/5xx twice → escalate or branch-switch.

4) Recovery policy
	•	Roll back to last snapshot where:
	•	new facts were added, and
	•	constraints weren’t violated, and
	•	planner config changed (so we can flip a knob).
	•	Branch with variation: change 1–2 degrees of freedom (different tool, different query template, lower temp, stricter filter, alternate retriever).
	•	Ask-for-clarity fallback: if we roll back ≥2 times in a row, surface a targeted clarifying question (one line, one missing key).

5) Planner/Executor split
	•	Planner model: tiny, deterministic, builds the next 1–3 steps + guard checks.
	•	Executor model: does the heavy tool I/O and summarization.
	•	Verifier: even tinier model or rules that run post-tool to enforce constraints (“Does county==King?” “Does parcel APN exist?”). Cheap and worth its weight in gold.

6) Tool/result caching
	•	Memoize tool I/O by normalized inputs → content hash of outputs with TTL.
	•	Canonicalization pass on inputs (e.g., always geocode “Seattle, WA” → {lat,lon, county_fips} before search).
	•	Result guards: before the executor can “believe” a tool output, it must pass the verifier (geo boundary, date range, entity type).

7) Determinism handles
	•	Stamp RNG seeds + temperatures in the snapshot.
	•	Keep prompt templates versioned (hash) so a replay is reproducible.
	•	Log retriever corpus versions (index hash) so RAG drift doesn’t gaslight you.

8) Compression discipline
	•	Don’t serialize raw “thoughts.” Persist structured summaries:
	•	facts.jsonl (triples + provenance)
	•	decisions.jsonl (why we chose a branch, 1–2 lines)
	•	open_questions.jsonl (what we still need)
This keeps costs down and makes rewind fast.

⸻

How this would have stopped the Pelican Press fiasco
	1.	Constraints locked up front: city=Seattle, county=King.
	2.	Every listing/tool output is geocoded → county_fips checked by the Verifier.
	3.	The first time a result says Renton (or Pierce County, etc.), Constraint violation → rollback to the prior snapshot.
	4.	Planner spins a variant branch: switch data source to county parcel database first; Zillow later.
	5.	If two rollbacks happen, it asks you: “Do you want county parcel search first, then cross-check with real-estate sites?”—no wandering to Renton.

⸻

Minimal interface (pseudocode)

@dataclass
class AgentState:
    goal: GoalTree
    constraints: Dict[str, Any]
    facts: List[Fact]            # {subject,predicate,object,source_hash}
    tool_ledger: List[ToolCall]  # {name,in_hash,out_hash,status,...}
    planner_cfg: PlannerCfg      # {seed,temp,allowlist,budgets}
    scratch: ScratchSummary      # compact, structured

store = SnapshotStore(db_path="atm.db")  # content-addressable

def step(state: AgentState) -> AgentState:
    snap_id = store.snapshot(state)
    plan = planner.propose(state)
    out = executor.run(plan, state)
    if not verifier.ok(out, state.constraints):
        state = store.rollback(snap_id)                 # rewind
        state = planner.perturb(state, strategy="alt")  # branch
        return state
    state = integrate(out, state)
    return state


⸻

Practical stack choices (works, fast):
	•	SQLite + zstd for snapshots (portable, queryable) + a folder of blobs (tool outputs).
	•	LMDB/RocksDB if you want pure KV and high write throughput.
	•	DuckDB for ad-hoc analytics on runs (loop patterns, tool latencies).
	•	Geocoding/validation: one tiny, deterministic service (geocode → county_fips; APN normalizer).

⸻

Deployment tips
	•	Put hard budgets in config: max_tool_calls, max_wall_time, max_rollbacks.
	•	Surface a Run Timeline (plan → tool → verify → snapshot) so humans can spot stupidity in 10 seconds.
	•	Test packs with anti-goals (e.g., “DO NOT leave King County”) and assert they never trigger.

⸻

If you want, I’ll spin up a bare-bones PoC in Python: snapshot store, verifier skeleton (geo + date guard), loop detector, and a toy planner/executor that you can plug your current agent into. You’ll get a runs/ folder with snapshots you can diff, and a CLI command: atm replay <run_id> --to <snapshot> to time-travel. Want me to ship that scaffold next?"

---

Furthermore, "Copy that. Here’s a tight spec sheet you can hand to the team and they can build it without you lifting a finger.

Agent Time Machine (ATM) — Build Sheet

0) Goal

Stop agent loops/hallucinations by externalizing working memory to CPU RAM + SSD and enabling checkpoint/rollback (“Time Machine”), with constraint-aware verification.

1) Hardware (minimum viable)
	•	Host: 32–64 vCPU, 128–256 GB RAM (scale with concurrent agents).
	•	Storage: NVMe SSDs, PCIe Gen 4/5.
	•	Throughput: ≥7 GB/s read, ≥6 GB/s write.
	•	IOPS: ≥1M random read; ≥800k random write.
	•	Endurance: ≥1 DWPD, PLP (power-loss protection) required.
	•	Capacity: start at 4–8 TB usable per box (snapshots + tool-output blobs).
	•	Network: 25–100 GbE, jumbo frames on the storage path.
	•	Vendors: Micron NVMe (e.g., 7400/7500 class), Samsung PM9A3/PM1743 class, Kioxia CD7 class. (Micron’s fine—talk contracts.)

2) Software components
	•	Snapshot Store: SQLite (WAL) for indexes + Zstd-compressed blobs on disk; or RocksDB if you expect very high write concurrency.
	•	Content Addressing: SHA-256 for state/tool-output digests (dedupe + reproducibility).
	•	Delta Encoding: JSON Patch (RFC 6902) or custom diff for structured state.
	•	Verifier Service: lightweight rules engine (FastAPI/Go) for hard constraints (geo/date/entity).
	•	Planner/Executor Split:
	•	Planner = small, deterministic LM (low temp) that emits next 1–3 steps.
	•	Executor = main LM + tools.
	•	Memoization Cache: tool I/O memoized by normalized inputs (on-disk KV).

3) Data model (schemas)

3.1 Snapshot (row)

snapshot_id (pk, uuid)
parent_snapshot_id (nullable)
goal_tree_hash (sha256)
planner_cfg_hash (sha256)
state_json (zstd)         -- compact structured summary, not raw thoughts
created_at (ts)

3.2 Facts (jsonl / table)

{subject, predicate, object, source_hash, confidence, added_at}

3.3 Constraints (json)

{"geo":{"city":"Seattle","county_fips":"53033"},
 "time":{"start":"2008-01-01","end":"2012-12-31"},
 "entity":{"type":"parcel","apn_required":true}}

3.4 Tool ledger (table)

{id, snapshot_id, name, in_hash, out_hash, status, latency_ms, url, created_at}

3.5 Planner config

{seed, temp, tool_allowlist, budgets:{tokens,tool_calls,wall_time_s}}

4) Control loop (pseudo)

snap = store.snapshot(state)
plan = planner.propose(state)                  # deterministic
out  = executor.run(plan, state)               # tool calls, LM
ok, reasons = verifier.check(out, state.constraints)

if not ok:
    state = store.rollback(snap)               # rewind
    state = planner.perturb(state, strategy="alt_tool|lower_temp|new_query")
else:
    state = integrate(out, state)              # add facts, update ledger
    if progress_stalled():                     # cycles / no new facts
        state = store.rollback(last_good_snap)

5) Loop & hallucination guards
	•	Cycle detector: cosine sim on last K tool inputs/outputs + unchanged goal pointer.
	•	No-progress budget: N tool calls or Y seconds with zero new facts → rollback.
	•	Constraint violations: any output failing geo/date/entity checks → hard stop + rewind.
	•	Source-less claims: executor summaries must cite tool_ledger.out_hash; otherwise quarantine.

6) Snapshot policy
	•	Auto-checkpoint:
	•	after each successful tool call,
	•	before plan expansion,
	•	on constraint updates,
	•	every 10–20s wall time.
	•	Retention/GC:
	•	keep every “milestone” full snapshot (new facts/constraints added),
	•	interleave deltas (Zstd level 6+),
	•	TTL for old branches, or cap run to X GB.

7) Input canonicalization (pre-tool)
	•	Normalize locations → {lat, lon, county_fips}.
	•	Normalize dates → ISO 8601; enforce range.
	•	Normalize entity keys (APN formats, org names).

8) Determinism & replay
	•	Stamp template hashes, corpus index hash, seed/temp per step.
	•	CLI:
	•	atm run <task.json>
	•	atm replay <run_id> --to <snapshot_id>
	•	atm diff <snap_a> <snap_b>

9) Observability
	•	Run Timeline UI: plan → tool → verify → snapshot (1-line diffs).
	•	Metrics: snapshot rate, rollback count, verifier fail reasons, tool memoization hit rate, tokens/tool-call.
	•	Alerts: >2 rollbacks in 60s, >X constraint violations/run.

10) Security & compliance
	•	Encrypt blobs at rest (XTS-AES-256), rotate keys quarterly.
	•	Redact PII at ingestion filters; tag provenance.
	•	Signed snapshots (Ed25519) for integrity.

11) Test plan (Pelican Press repro)
	•	Fixture: constraints {city=Seattle, county_fips=53033}.
	•	Anti-goal: “DO NOT accept Renton/Pierce/Snohomish results.”
	•	Tools: County parcel DB → State corp registry → Realtor sites (cross-check).
	•	Asserts: first out-of-bound result triggers 1) verifier fail, 2) rollback, 3) alternate tool branch.

12) Rollout
	•	Phase 1: single-node ATM on NVMe; target p50 snapshot latency <5 ms; p95 rollback <50 ms.
	•	Phase 2: shard by run_id (consistent hashing); optional object store for cold blobs.
	•	Phase 3: team-wide profiles (legal research, property, customer ops) with tailored verifiers.

⸻

What to buy / ask for (TL;DR to procurement)
	•	Servers: 2× boxes with 64 cores, 256 GB RAM, 2× 7.68 TB PCIe Gen4 NVMe each (PLP, ≥1 DWPD).
	•	Disks: Micron NVMe enterprise line (or equivalent). Ask for sustained random write IOPS and PLP guarantees; include spares.
	•	SLA targets: snapshot write p50 <5 ms; rollback to prior checkpoint <50 ms; tool memoization hit rate ≥40% after warm-up.

If they want a starter repo structure, I can hand them a barebones:

/atm
  /atm_core        # snapshot store, content addressing, diffs
  /planner         # small LM glue (deterministic)
  /executor        # tool adapters + LM calls
  /verifier        # rules; geo/date/entity checks
  /ui              # run timeline (simple web)
  /cli             # run/replay/diff

Say the word and I’ll spit out the PoC scaffold so they can push to prod with real tools."

---

But, most importantly, "Shipped. It’s a working PoC you can hand to the team and they can run today.

Download the ATM PoC

What’s inside:
	•	atm_core/ — snapshot store (SQLite index + gzip blobs), models, content hashing.
	•	planner/ — tiny deterministic planner.
	•	executor/ — tool runner with memoization and a demo geo_lookup tool.
	•	verifier/ — constraint checks (geo/date/entity; geo wired up).
	•	cli/ — simple CLI with run, replay, diff.
	•	examples/task_pelican.json — Seattle/King County guardrails to reproduce and prevent the Pelican Press drift.

Quickstart (copy/paste):

# Optional: Python 3.10+ venv
# python -m venv .venv && source .venv/bin/activate
# pip install -r requirements.txt   # none required; stdlib only

# Run the example
python -m cli.atm_cli run examples/task_pelican.json

# Inspect latest snapshot
python -m cli.atm_cli replay --run-id <printed_run_id>

# Diff two snapshots
python -m cli.atm_cli diff --run-id <run_id> --a <snap_a_uuid> --b <snap_b_uuid>

Notes for the boys:
	•	Snapshots happen per step and after tool calls; rollback kicks in if the verifier flags a constraint violation (e.g., county_fips mismatch) or no progress.
	•	Everything is content-addressed; tool I/O is memoized on normalized inputs.
	•	Swap gzip → zstd by dropping in zstandard if desired.
	•	Hook your real tools behind the executor; wire additional verifiers (corp registry, parcel APN, date windows) the same way the geo checker works.

If you want me to add a simple web “Run Timeline” (plan → tool → verify → snapshot) panel next, say the word and I’ll bolt it on."

---

Asari 3:16
