# Security Audit — PriorArtRegistry

**Scope:** `contracts/prior_art_registry.py`, its five write paths, the challenge/adjudication
cycle and the bond accounting.
**Method:** adversarial review against the failure classes found in this portfolio's earlier
audits, direct-mode regression tests, and a live studionet verification run.

---

## 1. Design controls carried in from earlier audits

| Prior finding class | Control here |
|---|---|
| Model output used directly to move money | The model returns one of two category words; bond movement is deterministic code keyed on that word |
| Participants writing the evidence instead of the contract fetching it | Prior art is fetched contract-side and verified against the committed SHA-256 |
| Claimant controlling the evidence to fake a win | The challenger controls the prior-art URL, so **unverifiable prior art loses the challenge** — the burden sits with the party who owns the URL |
| Free-text reasoning reused downstream | `reasoning` is required to be non-empty, stored, and never read by any computation |
| Griefing / unbounded disputes | A challenge costs the bond, one active challenge per entry, one resolution per challenge, entry cap 3–25 |
| Funds stranded when nobody acts | `finalize_entry` is permissionless after the window and returns the stake |
| Double payout from one bond | `stake` and `bond` are zeroed on settlement; every payout path requires a specific prior status |
| Entrant attacking itself (wash challenge) | An entrant cannot challenge its own entry |
| Registry owner changing the rules mid-flight | `scope` and economics are fixed at creation and bound in `terms_binding` |
| Corpus / prompt manipulation | Corpus is assembled by contract code in registration order, excludes revoked entries and the challenged entry, and is capped by `entry_cap` |
| SSRF / private-host fetch | Public dotted host only, on submission **and** fetch |
| Pre-parse input bombs | Id/scope/title/summary length caps, 300 KB document cap, 6000-char prompt cap, 12000-char corpus cap |
| Transfer before state write | Bonds are settled after all writes in `resolve_challenge` / `finalize_entry` |
| Zero address / id confusion | Id allowlist without `#` or `@`, so registry and entry keys cannot collide |
| Prohibited float division | No `/` in the contract; `bond <= stake * 10` written as multiplication |

---

## 2. Findings from this contract's own audit

| ID | Severity | Issue | Status |
|---|---|---|---|
| H-1 | **High** | An entrant could register a duplicate and, if nobody is watching, keep the slot forever | **Mitigated** — the entry stays `provisional` for the whole window, any address can challenge, and the stake is forfeited to the challenger on a `duplicate` verdict |
| H-2 | **High** | A challenger could submit an unrelated document, get `not_duplicate`, and cost the entrant only time | **Mitigated** — a failed challenge pays `stake + bond` to the entrant, so a frivolous challenge is strictly loss-making |
| M-1 | Medium | Corpus assembled from storage could differ between validators if it depended on time or on settlement order | **Fixed** — corpus is built deterministically from the registry index before consensus, ordered by registration, excluding the challenged and revoked entries |
| M-2 | Medium | A revoked entry could keep influencing later judgments | **Fixed** — `EN_REVOKED` entries are skipped when building the corpus |
| M-3 | Medium | Two challenges racing on one entry could double-count bonds | **Fixed** — a challenge requires `status == provisional`, and the first one flips the entry to `challenged` |
| M-4 | Medium | `finalize_entry` could be called on a challenged entry to dodge adjudication | **Fixed** — finalise requires `provisional`; a challenged entry can only leave that state through `resolve_challenge` |
| M-5 | Medium | Bond parameters could be set to a value nobody can pay (griefing registry creators / entrants) | **Fixed** — `stake <= bond <= 10 * stake`, enforced at creation |
| M-6 | Low | Settlement could run before the window closes, letting a challenger settle an entry nobody had time to finalise | **Accepted by design** — the challenger paid the bond to force a decision; the entrant is compensated if the challenge fails |
| L-1 | Low | One challenge per entry, no appeals | **Accepted, documented** — the bond size is the appeal budget |
| L-2 | Low | Prior art outside the registry must be supplied as a document | **Accepted, documented** — the contract does not search the world |
| L-3 | Low | The judge is only as good as the registry's scope text | **Accepted, documented** — the scope is public, on-chain and immutable |
| L-4 | Low | A `duplicate` verdict is a semantic judgement, not a legal finding | **Accepted, documented** |

### H-1 / H-2 detail — the two-sided bond

The interesting property of this contract is that the incentive analysis is symmetric:

```
register a real entry        -> window with no challenge -> stake returned
register a duplicate          -> challenge succeeds      -> stake forfeited to the challenger
challenge a real entry        -> not_duplicate           -> stake + bond paid to the entrant
challenge a duplicate         -> duplicate               -> bond + stake paid to the challenger
```

Neither side can profit by lying, because the party who is wrong *always* pays the party who
is right, and the payout is decided by a category that validators must agree on exactly.

---

## 3. Double-submit / replay matrix

| Attempt | Result |
|---|---|
| `create_registry` with an existing id | revert `Registry already exists` |
| `register_entry` with an existing entry id in the registry | revert `Entry already registered in this registry` |
| `register_entry` paying the wrong stake | revert `Registration stake must equal the registry stake` |
| `register_entry` past the cap | revert `Registry entry cap reached` |
| `challenge_entry` twice on the same entry | revert `Entry is not open to a challenge` |
| `challenge_entry` on your own entry | revert `An entrant cannot challenge its own entry` |
| `challenge_entry` after the window | revert `Challenge window has closed` |
| `challenge_entry` with the wrong bond | revert `Challenge bond must equal the registry bond` |
| `resolve_challenge` twice | revert `Entry has no active challenge` |
| `resolve_challenge` on an unchallenged entry | revert `Entry has no active challenge` |
| `finalize_entry` before the window | revert `Challenge window has not closed` |
| `finalize_entry` on a challenged/confirmed/revoked entry | revert `Entry is not provisional` |
| Double payout for one entry | impossible: `stake`/`bond` zeroed, and each payout path requires its own prior status |

---

## 4. Caller / authorization matrix

| Actor | Can | Cannot |
|---|---|---|
| Registry creator | set the scope, cap, stake, bond and window at creation | change them later, censor entries, or seize bonds |
| Entrant | register one entry per id by paying the stake; reads | challenge its own entry; withdraw the stake after the window without finalising; block a challenge |
| Challenger | challenge any provisional entry by paying the bond and committing prior art; reads | challenge twice; settle the verdict itself; supply evidence that does not match the commitment |
| Stranger / crank | `resolve_challenge`, `finalize_entry`, reads | influence the verdict; move funds to themselves |
| Anyone | — | mutate a resolved verdict |

---

## 5. Consensus-path audit

**Consequential-field budget.** Creator: scope, cap, stake, bond, window. Entrant: id, title,
summary, stake. Challenger: prior-art URL + hash, bond. Validators: the verdict category.
Everything else is audit data.

**Validator obligations.** `validator_fn` rejects anything that is not a `gl.vm.Return` with an
allowed category and a non-empty reasoning string, re-runs `judge()`, and requires the
category to match **exactly**. No score, no tolerance, no secondary field.

**What consensus cannot do.** It cannot choose a recipient, an amount, a registry, an entry
state, or a corpus. It selects one of two words; `resolve_challenge` maps that word to a fixed
payout and a fixed state.

**Failure handling.**

| Failure | Behaviour |
|---|---|
| Prior art unreachable | `not_duplicate` — the challenge fails, the entry is confirmed |
| Prior-art hash mismatch | `not_duplicate` — substituted evidence is rejected |
| Model returns an unknown category | consensus rotation; the leader's payload is rejected by validators |
| Model returns prose instead of JSON | `_exec_prompt_json` yields `{}` → rejected |
| Leader raises | validator returns `False` → rotation |
| Validators disagree | rotation; no state change, no bond movement |

**Prompt injection.** The scope, entry summary, corpus and prior art are delimited and
labelled untrusted, with an explicit instruction to ignore embedded instructions (including
"return duplicate"). The only consumed output is a category from a two-element set.

---

## 6. Staff feedback mapping

| Feedback theme | Verdict |
|---|---|
| Validators must verify the field that decides the outcome | **Applied** — one categorical field, exact agreement, re-derived from the fetched document |
| Fetch evidence contract-side; bind to what was fetched | **Applied** — prior art is fetched and hash-verified before judging |
| Deterministic settlement after consensus | **Applied** — bond movement is code keyed on the verdict |
| No locks on inconclusive outcomes | **Applied** — permissionless finalise, and both verdicts settle immediately |
| No premature payout; record the adverse outcome first | **Applied** — an entry only changes state through a recorded verdict or a closed window |
| Restrict who can force a resolution | **Applied** — resolution is a permissionless crank that cannot choose the outcome; challenges require the bond |
| Bind every field reused downstream | **Applied** — reasoning is never reused; entries are excluded from the corpus once revoked |
| No prohibited float division | **Compliant** |
| Verification ids and a pinned dependency | **Compliant** — four bindings; pinned `py-genlayer:1jb45aa8…` |
| Storage declared at class level | **Applied** — learned from ThreeWayMatchEscrow's first deployment |
| Sealed commit must not receive plaintext | **N/A** — this contract has no sealed phase |

---

## 7. Verification evidence

| Check | Result |
|---|---|
| `genvm-lint check` | pass — 8 methods (3 view, 5 write), 0 ctor params |
| Direct-mode tests | **12/12 passed** |
| Deterministic on-chain (`leader_only=True`) | **23/23 PASS** on `0xBaf1f3C9…28CB` |
| Full AI consensus (`duplicate`) | 3/3 `agree`, empty `stderr`, entry `revoked` — tx `0x22ee2e3e…6df5` |
| Full AI consensus (`not_duplicate`) | 3/3 `agree`, empty `stderr`, entry `confirmed` — tx `0xf7c6ec2d…c880` |
| Source ↔ deployment | byte-identical (SHA-256 `caefa70b…98fc`) |
| Deployment | `0xBaf1f3C9efC1aDd1C145788aE7529aC5dd8728CB` |
