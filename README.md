<div align="center">

# PriorArtRegistry

**A bonded registry where "that idea already exists" is a decision someone has to pay to make — and only validators can settle.**

![GenLayer](https://img.shields.io/badge/GenLayer-Intelligent%20Contract-6a4cff)
![Python](https://img.shields.io/badge/Python-3.12-3776AB)
![Status](https://img.shields.io/badge/status-live%20on%20studionet-2ea44f)
![Tests](https://img.shields.io/badge/tests-12%20passed-2ea44f)

[Live Contract](https://explorer-studio.genlayer.com/address/0xBaf1f3C9efC1aDd1C145788aE7529aC5dd8728CB) ·
[Security Audit](AUDIT.md) ·
[GenLayer Docs](https://docs.genlayer.com)

</div>

---

## Why

Every registry of ideas has the same unsolved problem: **uniqueness is semantic**.
A hash-deduplicated registry is defeated by one synonym. A human review board is the
bottleneck everyone is trying to remove. And an LLM-as-judge registry is worse still —
whoever writes the cleverest prompt wins, and the money moves on the model's opinion.

Two things are needed instead:

1. **plagiarism has to cost something to allege** — otherwise every entry gets spammed with
   challenges, and
2. **the verdict has to be a category, not prose** — so that the payout, which is just the
   movement of two bonds, cannot be bent by wording.

PriorArtRegistry does both. Registration is cheap and immediate. Adjudication only happens
when someone puts money behind a claim, and the only thing consensus produces is one of two
words: `duplicate` or `not_duplicate`.

## Live Deployment

| | |
|---|---|
| **Contract** | [PriorArtRegistry](https://explorer-studio.genlayer.com/address/0xBaf1f3C9efC1aDd1C145788aE7529aC5dd8728CB) |
| **Address** | `0xBaf1f3C9efC1aDd1C145788aE7529aC5dd8728CB` |
| **Network** | GenLayer studionet (chain `61999`) |
| **Constructor args** | none |
| **Deploy** | `python scripts/verify_onchain.py` (without `--address` it deploys a fresh instance and runs the 23 checks) |
| **On-chain code** | byte-identical to `contracts/prior_art_registry.py` (SHA-256 `caefa70b…98fc`) |

## The Mechanism

```
create_registry(registry_id, scope, entry_cap, stake, bond, challenge_window)
      |  the scope IS the standard: "what counts as the same idea here"
      v
register_entry(registry, entry_id, title, summary)   payable = stake
      |  status: provisional, challengeable until deadline
      +---------------------------+
      |                           |
  nobody challenges           someone challenges (pays bond + commits prior art)
      |                           |
      v                           v
finalize_entry (no AI)      resolve_challenge (consensus, permissionless crank)
 after the window                 |
 stake returned                   +-- duplicate     -> entry revoked,
 to the entrant                   |                    challenger takes bond + stake
                                  |
                                  +-- not_duplicate -> entry confirmed,
                                                       entrant takes stake + bond
```

Everything the contract holds is one of two bonds on a live entry, and every state has an
exit: the registry can never strand funds.

## Why Lazy Adjudication

| Design | Cost | Failure mode |
|---|---|---|
| Judge every registration | one consensus round per entry | expensive, and the model decides things nobody disputed |
| Never judge, trust the registry owner | free | the owner is the censor |
| **Judge only when challenged (this contract)** | **zero for honest use, one round per dispute** | **a challenge costs the bond, so disputes are rationed** |

The happy path touches no model at all. `finalize_entry` is permissionless: after the window
closes, anyone can confirm an uncontested entry and return the stake to its author.

## The Verdict Is the Settlement

```
judge:
  fetch the challenger's prior-art document -> verify sha256 against the commitment
    unreachable / mismatch -> not_duplicate  (the challenger controls this URL)
  build the corpus deterministically: every non-revoked entry in this registry,
    excluding the challenged one, capped by the registry's own entry_cap
  exec_prompt(scope + challenged entry + corpus + prior art, response_format="json")
    verdict must be "duplicate" or "not_duplicate"

validator_fn:
  require leader Return + an allowed category + non-empty reasoning
  re-run the whole judge path independently
  accept only if the category matches EXACTLY
```

Then, in deterministic code:

| Verdict | Entry | Publisher | Entrant receives |
|---|---|---|---|
| `duplicate` | `revoked` | challenger receives `bond + stake` | nothing — the stake is the cost of a duplicate claim |
| `not_duplicate` | `confirmed` | challenger receives nothing | `stake + bond` — the bond compensates a failed challenge |
| `unchallenged` (window closed) | `confirmed` | — | `stake` returned |

The model chooses none of those numbers, recipients or states. It picks one of two words.

## Governing the Judge

A registry is only as fair as the standard it is judged against, so the standard is
on-chain and bound:

- **`scope` is set at creation** and enters `terms_binding`; it is quoted verbatim in every
  prompt for that registry, so an entry cannot be judged against a scope nobody agreed to.
- **The corpus is assembled by contract code**, in registration order, excluding the
  challenged entry and every revoked entry. Validators cannot be shown different reference
  records.
- **The corpus size is capped by `entry_cap`** (3–25), which bounds both prompt size and
  the cost of a consensus round.
- **The prompt defines both verdicts against the scope**: rewording, translation or a strict
  subset/superset is a duplicate; a different mechanism, scope or deliverable is not.
- **`reasoning` is audit-only** — required to exist, stored, never read again.

## Methods

| Role | Method | Guard |
|---|---|---|
| Anyone | `create_registry` | id allowlist; scope 20–600 chars; cap 3–25; stake > 0; stake ≤ bond ≤ 10× stake; window 1h–30d |
| Entrant | `register_entry` | payable exactly the stake; entry id unique in the registry; title 3–160; summary 20–600; cap enforced |
| Challenger | `challenge_entry` | payable exactly the bond; entry must be `provisional`; inside the window; not the entrant; public http(s) prior-art URL + 64-hex hash |
| Any (crank) | `resolve_challenge` | entry must be `challenged`; consensus over fetched, hash-verified prior art |
| Any (crank) | `finalize_entry` | window closed; no challenge; returns the stake |
| Any | `get_registry`, `get_entry`, `get_registry_entries` | read-only |

## Security Controls

- prior art is fetched **contract-side** and verified against the committed SHA-256; the
  challenger's evidence is what gets judged
- unverifiable prior art **loses** the challenge (the challenger carries that burden, and it
  is the URL they control)
- exactly one consequential consensus field, compared exactly, with no tolerance
- one active challenge per entry, one resolution per challenge; revoked entries leave the
  corpus and can never be revived
- bonds are settled **after** all state writes; accounting per entry (`stake`, `bond`) is
  zeroed on settlement so no path can pay twice
- SSRF-hardened URL validation; 300 KB document cap; 6000-char prompt cap; 12000-char corpus cap
- entrant cannot challenge its own entry; a challenger cannot be the entrant by address case
- `terms_binding`, `entry_binding`, `challenge_binding`, `verdict_binding`
- integer arithmetic only

## Limitations

- **The corpus is this registry only.** Prior art outside the registry must be supplied as a
  document by the challenger; the contract does not search the world.
- **A challenge is a one-shot at the entry level.** Once resolved, an entry is `confirmed` or
  `revoked` for good; there is no appeal, which is why the bond is large enough to make a
  frivolous challenge expensive.
- **The registry owner chooses the scope and the economics**, and cannot change them
  afterwards. Choose registries whose scope you would accept as a member.
- **`finalize_entry` requires the wall-clock window to close**, so it is exercised in
  direct-mode tests rather than in a live run.
- **Semantic judgement is not certainty.** The verdict is a bounded, paid, auditable
  decision — not a court ruling.
- **Not a trademark or patent office.** It records and settles *claims of sameness* inside a
  scope; it creates no legal right.

## Usage Sketch

```text
# 1. someone opens a registry with a scope and its economics
create_registry(
  registry_id="grants-2024",
  scope="Grant proposals for community-scale rural services. Two proposals are the same idea when they propose the same mechanism for the same beneficiaries.",
  entry_cap=20,
  registration_stake=100,
  challenge_bond=250,
  challenge_window_seconds=1209600,
)   # returns terms_binding

# 2. an entrant stakes a claim
register_entry(registry_id="grants-2024", entry_id="entry-solar",
               title="Shared solar micro-grid for alpine cooperatives",
               summary="Install shared photovoltaic micro-grids ...")   # value = 100

# 3a. nobody objects -> anyone finalises it after the window, stake returned
finalize_entry(registry_id="grants-2024", entry_id="entry-solar")

# 3b. someone contests it
challenge_entry(registry_id="grants-2024", entry_id="entry-solar",
                prior_art_url="https://raw.githubusercontent.com/org/repo/<commit>/prior-art.md",
                prior_art_sha256="<64 hex>")   # value = 250
resolve_challenge(registry_id="grants-2024", entry_id="entry-solar")
# -> {"verdict": "duplicate", "status": "revoked", "awarded_amount": 350, ...}
```

## Test

```bash
gltest tests/ -q      # 12 passed (direct mode)
```

Coverage: registry economics validation, staked registration with exact-stake enforcement,
the entry cap, challenge authorization (own entry, wrong bond, private host, bad hash, closed
window), the duplicate settlement (revoke + slash) and the not_duplicate settlement
(confirm + compensate), replay and double-resolve guards, unverifiable and substituted prior
art losing the challenge, validator exact-category enforcement, corpus assembly, and
finalising an uncontested entry without any consensus.

## Lint

```bash
genvm-lint check contracts/prior_art_registry.py
```

`check` passes: 8 methods (3 view, 5 write), 0 constructor params.

## On-Chain Verification

Deterministic studionet run (`leader_only=True`), script
[`scripts/verify_onchain.py`](scripts/verify_onchain.py) — **23/23 PASS**:

| Step | Result |
|---|---|
| Cap below minimum / bond below stake / window above 30 days / short scope | reverted (expected) |
| `create_registry` | accepted, scope + economics stored, `terms_binding` 64 hex |
| Duplicate registry id | reverted (expected) |
| Wrong stake on registration | reverted (expected) |
| `register_entry` | accepted, `status=provisional`, stake recorded, index updated |
| Entrant challenging its own entry / wrong bond / private host / bad hash | reverted (expected) |
| Unknown entry challenged | reverted (expected) |
| `challenge_entry` | accepted, `status=challenged`, bond recorded, binding stored |
| Second challenge on the same entry | reverted (expected) |
| `resolve_challenge` with matching prior art | `duplicate` → `revoked`, stake and bond zeroed |
| Second resolution of the same entry | reverted (expected) |
| `resolve_challenge` with unrelated prior art | `not_duplicate` → `confirmed`, bonds zeroed |
| `resolve_challenge` with unfetchable prior art | `not_duplicate`, reasoning *"could not be verified"* |
| Unknown registry read / entry index | raises / lists every entry with its final status |

`finalize_entry` requires the wall-clock window to close, so it is verified in direct mode
rather than on a live run.

### Full AI consensus (real validators)

Prior art pinned to the repository's `evidence/` documents, fetched and hash-verified by the
contract itself. Both runs: 3 validators `agree`, `stderr` empty.

**Case A — a duplicate is revoked and slashed.**

| | |
|---|---|
| Registry | `grants-live` (scope: community-scale rural services), stake 100, bond 250 |
| Entry | `entry-solar` — *shared solar micro-grid for alpine cooperatives* |
| `register_entry` tx | `0xe9f9db32f413f6552619c6491ccfcb0416e5c2d2a409745a5c6bfd129e52ba63` |
| `challenge_entry` tx | `0x796eea124ea0eec8bcaacc51a9021ca41cd87549e36c21e19f7819fbac590b2c` |
| `resolve_challenge` tx | `0x22ee2e3e8d803b4db9df54df67bd96c4bfb69b3e28b672e4a44a47c612cf6df5` |
| Verdict | `duplicate` — *"…matches the prior art in mechanism (shared PV micro-grid with battery storage), beneficiaries (alpine farm cooperatives) and purpose…"* |
| Result | `status=revoked`, stake and bond zeroed, challenger awarded `350` |
| `verdict_binding` | `c23ed7035a8415733fbe7e33529564ba358f863a0603bc1ef60f70bd8aa3a3fb` |

**Case B — an unrelated prior art document loses the challenge.**

| | |
|---|---|
| Entry | `entry-vet` — *monthly mobile veterinary route for herder communities* |
| Prior art | the 2019 fibre-backhaul report (no energy, no veterinary activity) |
| `register_entry` tx | `0x13acc768b01e53ae63b718f015f4b22c9c4b92373c5ff0f9449958403a63f60a` |
| `challenge_entry` tx | `0x6d6d08f78c5e2c4d1b80a55bf9ea894a495e905247646910458a8aa8a1fb2492` |
| `resolve_challenge` tx | `0xf7c6ec2d3c2b2981bd9068ff28da17311da924715eec19c5fc6b7c7eeecdc880` |
| Verdict | `not_duplicate` — *"Component 9 discloses school telecommunications infrastructure… the proposed mechanism, beneficiaries, and deliverables are materially different."* |
| Result | `status=confirmed`, entrant awarded `350` |
| `verdict_binding` | `e2fdfb7935d3cdc9857bba34fc8f15af63028549dd49eccf512688d84fd58871` |

The two runs differ only in which prior-art document was committed. Both ended with a 3/3
agreement, and the bonds moved in opposite directions — because the settlement is code keyed
on one of two words, not a model opinion about how much to pay.
