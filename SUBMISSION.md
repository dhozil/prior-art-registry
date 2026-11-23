# Submission: PriorArtRegistry

## Category
Intelligent Contracts

## Contract Name
PriorArtRegistry

## Summary
A bonded registry of ideas where "that already exists" is a claim someone has to pay to make.
Anyone opens a registry by fixing its **scope** ("what counts as the same idea here") and its
economics: a registration stake, a challenge bond and a challenge window. Entrants register an
entry by paying the stake; the entry is provisional until the window closes. Consensus is spent
**only** on a challenge: the challenger posts the bond and commits a prior-art document by
SHA-256, validators fetch that document, verify the hash, and compare the entry against the
registry's earlier entries and the document. The verdict is one categorical answer —
`duplicate` or `not_duplicate` — and deterministic code settles both bonds from it:
`duplicate` revokes the entry and pays the challenger `bond + stake`, `not_duplicate` confirms
the entry and pays the entrant `stake + bond`. Uncontested entries finalise with no AI at all.

## What Makes This Unique
- **Lazy adjudication**: consensus is used only where there is a real dispute, so an honest
  registry costs zero model calls and a dispute is rationed by a bond.
- **The verdict is the settlement**: the model returns one of two words, never an amount, a
  recipient or a state. Two accepted rounds cannot move different money.
- **Two-sided bonds**: the party that is wrong always pays the party that is right, so neither
  spamming entries nor spamming challenges is profitable.
- **The standard is on-chain**: the scope is set at creation, enters `terms_binding`, and is
  quoted verbatim in every prompt for that registry.
- **The corpus is built by contract code**, in registration order, excluding the challenged
  entry and every revoked entry — validators cannot be shown different reference records.
- **Unverifiable prior art loses**: the challenger controls that URL, so a document that no
  longer matches its hash cannot revoke anybody's entry.
- **No lock states**: permissionless `finalize_entry` after the window, and both verdicts
  settle immediately.

## How Consensus Is Used
`resolve_challenge` runs `gl.vm.run_nondet_unsafe(judge, validator_fn)`.

- `judge` fetches the challenger's prior-art document, verifies it against the committed
  SHA-256, and calls `gl.nondet.exec_prompt(...)` with the registry scope, the challenged
  entry, the deterministically assembled corpus and the fetched prior art
  (`response_format="json"`).
- `validator_fn` requires a `Return` with an allowed category and a non-empty reasoning string,
  re-runs the same judge, and accepts only an **exactly** equal category.
- Storage is snapshotted into plain values before consensus; bonds are paid afterwards in
  deterministic code, after every state write.

## Technical Details
- Python GenLayer Intelligent Contract, pinned runner
  `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`
- Storage: class-level `TreeMap` declarations for `Registry` and `Entry` records plus a
  per-registry entry index; `u256` for stakes, bonds and counters
- Bounds: entry cap 3–25, `stake <= bond <= 10 × stake`, challenge window 1h–30 days, title
  3–160 chars, summary 20–600 chars, scope ≤ 600 chars, 300 KB prior art, 6000-char prompt cap
- Methods: 8 (5 write, 3 view), no constructor params
- `genvm-lint check`: passed

## Use Case
Grant programmes and hackathons (proposal deduplication), DAO proposal registries, prior-art
screening for patents and research, bug-bounty "first report wins" registries, and any
namespace where claiming an idea should cost something to occupy.

## Security Review
Full report: `AUDIT.md`.

| ID | Severity | Issue | Outcome |
|---|---|---|---|
| H-1 | High | A duplicate could occupy a registry slot unchallenged | Provisional status for the whole window, open challenges, stake forfeited on `duplicate` |
| H-2 | High | Frivolous challenges costing the entrant only time | A failed challenge pays `stake + bond` to the entrant |
| M-1 | Medium | Corpus could differ between validators | Deterministic, code-assembled, ordered, capped corpus |
| M-2 | Medium | Revoked entries influencing later judgments | Revoked entries excluded from the corpus |
| M-3 | Medium | Racing challenges double-counting bonds | Challenge requires `provisional`; the first flips the entry to `challenged` |
| M-4 | Medium | Finalising a challenged entry to dodge adjudication | `finalize_entry` requires `provisional` |
| M-5 | Medium | Unpayable bond parameters | `stake <= bond <= 10 × stake` enforced at creation |

## Verification
- 12/12 direct-mode tests (`gltest tests/ -q`)
- Deterministic on-chain verification on studionet (`scripts/verify_onchain.py`): **23/23 PASS**
- Full AI consensus on studionet:
  - `duplicate` (solar micro-grid entry vs the 2019 energy report): 3/3 `agree`, empty `stderr`,
    entry `revoked`, tx `0x22ee2e3e8d803b4db9df54df67bd96c4bfb69b3e28b672e4a44a47c612cf6df5`
  - `not_duplicate` (veterinary-route entry vs the 2019 fibre report): 3/3 `agree`, empty
    `stderr`, entry `confirmed`, tx `0xf7c6ec2d3c2b2981bd9068ff28da17311da924715eec19c5fc6b7c7eeecdc880`
- On-chain code byte-identical to `contracts/prior_art_registry.py`

## Live Deployment
Deployed on GenLayer studionet (chain `61999`):
[`0xBaf1f3C9efC1aDd1C145788aE7529aC5dd8728CB`](https://explorer-studio.genlayer.com/address/0xBaf1f3C9efC1aDd1C145788aE7529aC5dd8728CB)

## Source Code
See `contracts/prior_art_registry.py`
