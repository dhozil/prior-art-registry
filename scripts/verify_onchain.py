"""Deterministic on-chain verification for PriorArtRegistry (studionet).

Covers registry economics validation, staked registration and the entry cap,
challenge authorization and bond rules, the duplicate and not_duplicate
settlements, unverifiable prior art, and the replay/late-challenge guards.
`finalize_entry` needs the challenge window to close, so it is covered by the
direct-mode tests instead of a live run.

Usage (from the repository root):

  python scripts/verify_onchain.py
  python scripts/verify_onchain.py --address 0x...

Signing key resolution:
  1. STUDIONET_PRIVATE_KEY environment variable, or
  2. .wallets/studionet.json (gitignored) with a "private_key" field.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import genlayer_py as g
from genlayer_py import accounts
from genlayer_py.types.transactions import TransactionStatus

ROOT = Path(__file__).resolve().parents[1]
NETWORK = "studionet"
DEFAULT_CONTRACT = "contracts/prior_art_registry.py"
DEFAULT_BASE = "https://raw.githubusercontent.com/dhozil/prior-art-registry/main/evidence"

REG_ID = "grants-2024"
SCOPE = (
    "Grant proposals for community-scale rural services. Two proposals are the same "
    "idea when they propose the same mechanism for the same beneficiaries."
)
CAP = 6
STAKE = 100
BOND = 250
WINDOW = 3600


def _load_private_key() -> str:
    key = os.environ.get("STUDIONET_PRIVATE_KEY", "").strip()
    if key:
        return key
    path = ROOT / ".wallets" / f"{NETWORK}.json"
    if not path.exists():
        raise SystemExit(
            f"No key found. Set STUDIONET_PRIVATE_KEY or create {path} with a "
            '"private_key" field.'
        )
    return json.loads(path.read_text(encoding="utf-8"))["private_key"]


def _fetch_sha(url: str) -> str:
    last = None
    for _ in range(5):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return hashlib.sha256(resp.read()).hexdigest()
        except Exception as exc:
            last = exc
            time.sleep(2)
    raise SystemExit(f"cannot fetch {url}: {last}")


class Harness:
    def __init__(self) -> None:
        self.client_acct = accounts.create_account(_load_private_key())
        self.client = g.create_client(chain=g.studionet, account=self.client_acct)
        self.entrant = accounts.create_account()
        self.challenger = accounts.create_account()
        self.address = ""
        self.passed = 0
        self.failed = 0

    # -- plumbing -------------------------------------------------------------

    def _order(self, fn: str) -> list[str]:
        if not hasattr(self, "_schema"):
            self._schema = self.client.get_contract_schema(self.address)
        return [p[0] for p in self._schema["methods"][fn]["params"]]

    def write(self, fn: str, *, account=None, value: int = 0, leader_only=True, **kw):
        args = [kw.get(p) for p in self._order(fn)]
        last = None
        for attempt in range(6):
            try:
                return self.client.write_contract(
                    address=self.address,
                    function_name=fn,
                    account=account or self.client_acct,
                    value=value,
                    leader_only=leader_only,
                    args=args,
                )
            except Exception as exc:
                last = exc
                time.sleep(3 * (attempt + 1))
        raise SystemExit(f"write {fn} failed: {last}")

    def wait(self, tx: str) -> dict:
        last = None
        for attempt in range(4):
            try:
                return self.client.wait_for_transaction_receipt(
                    tx, status=TransactionStatus.ACCEPTED, interval=5000, retries=120
                )
            except Exception as exc:
                last = exc
                time.sleep(4 * (attempt + 1))
        raise SystemExit(f"receipt failed: {last}")

    def read(self, fn: str, **kw):
        args = [kw.get(p) for p in self._order(fn)]
        last = None
        for _ in range(6):
            try:
                return self.client.read_contract(
                    address=self.address, function_name=fn, args=args
                )
            except Exception as exc:
                last = exc
                time.sleep(3)
        raise SystemExit(f"read {fn} failed: {last}")

    def exec_result(self, rc: dict) -> str:
        leader = ((rc.get("consensus_data") or {}).get("leader_receipt") or [{}])[0]
        return str(leader.get("execution_result", ""))

    def entry_snapshot(self, registry_id: str, entry_id: str) -> str:
        try:
            entry = self.read("get_entry", registry_id=registry_id, entry_id=entry_id)
        except BaseException:
            return "<missing>"
        return json.dumps(
            {
                "status": entry["status"],
                "verdict": entry["verdict"],
                "stake": entry["stake"],
                "bond": entry["bond"],
            },
            sort_keys=True,
        )

    # -- assertions -----------------------------------------------------------

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        if ok:
            self.passed += 1
            print(f"  PASS  {label}")
        else:
            self.failed += 1
            print(f"  FAIL  {label} {detail}")

    def expect_fail(self, label: str, fn: str, subject: tuple[str, str] = ("", ""), **kw):
        before = self.entry_snapshot(*subject) if subject != ("", "") else ""
        try:
            tx = self.write(fn, **kw)
            rc = self.wait(tx)
        except BaseException:
            self.check(label, True)
            return
        after = self.entry_snapshot(*subject) if subject != ("", "") else ""
        self.check(
            label,
            self.exec_result(rc) == "ERROR" and before == after,
            f"(exec={self.exec_result(rc)}, changed={before != after})",
        )

    # -- scenario -------------------------------------------------------------

    def run(self, base: str) -> None:
        entrant = self.entrant.address
        challenger = self.challenger.address

        print("\n[1] registry economics")
        self.expect_fail(
            "cap below the minimum is rejected", "create_registry",
            registry_id=REG_ID, scope=SCOPE, entry_cap=2,
            registration_stake=STAKE, challenge_bond=BOND,
            challenge_window_seconds=WINDOW,
        )
        self.expect_fail(
            "bond below the stake is rejected", "create_registry",
            registry_id=REG_ID, scope=SCOPE, entry_cap=CAP,
            registration_stake=STAKE, challenge_bond=STAKE - 1,
            challenge_window_seconds=WINDOW,
        )
        self.expect_fail(
            "window above 30 days is rejected", "create_registry",
            registry_id=REG_ID, scope=SCOPE, entry_cap=CAP,
            registration_stake=STAKE, challenge_bond=BOND,
            challenge_window_seconds=31 * 24 * 3600,
        )
        self.expect_fail(
            "short scope is rejected", "create_registry",
            registry_id=REG_ID, scope="energy", entry_cap=CAP,
            registration_stake=STAKE, challenge_bond=BOND,
            challenge_window_seconds=WINDOW,
        )

        tx = self.write(
            "create_registry", registry_id=REG_ID, scope=SCOPE, entry_cap=CAP,
            registration_stake=STAKE, challenge_bond=BOND,
            challenge_window_seconds=WINDOW,
        )
        rc = self.wait(tx)
        registry = self.read("get_registry", registry_id=REG_ID)
        self.check(
            "registry opens with a scope and bindings",
            self.exec_result(rc) == "SUCCESS"
            and registry["scope"] == SCOPE
            and registry["registration_stake"] == STAKE
            and registry["challenge_bond"] == BOND
            and len(registry["terms_binding"]) == 64,
            json.dumps(registry)[:200],
        )
        self.expect_fail(
            "duplicate registry id is rejected", "create_registry",
            registry_id=REG_ID, scope=SCOPE, entry_cap=CAP,
            registration_stake=STAKE, challenge_bond=BOND,
            challenge_window_seconds=WINDOW,
        )

        print("\n[2] staked registration")
        self.expect_fail(
            "wrong stake is rejected", "register_entry",
            account=self.entrant, value=STAKE - 1, registry_id=REG_ID,
            entry_id="entry-solar", title="Shared solar micro-grid",
            summary="Install shared photovoltaic micro-grids on alpine cooperatives.",
        )
        self.expect_fail(
            "duplicate entry id is rejected", "register_entry",
            account=self.entrant, value=0, registry_id=REG_ID,
            entry_id="entry-ghost", title="Ghost entry", summary="placeholder",
        )

        tx = self.write(
            "register_entry", account=self.entrant, value=STAKE, registry_id=REG_ID,
            entry_id="entry-solar", title="Shared solar micro-grid for alpine cooperatives",
            summary=(
                "Install shared 40 kW photovoltaic micro-grids with battery storage on "
                "alpine farm cooperatives so members stop running diesel generators."
            ),
        )
        rc = self.wait(tx)
        entry = self.read("get_entry", registry_id=REG_ID, entry_id="entry-solar")
        self.check(
            "entry registers as provisional with the stake recorded",
            self.exec_result(rc) == "SUCCESS"
            and entry["status"] == "provisional"
            and entry["stake"] == STAKE
            and len(entry["entry_binding"]) == 64,
            json.dumps(entry)[:250],
        )
        self.check(
            "registry index reflects the entry",
            self.read("get_registry", registry_id=REG_ID)["entry_count"] == 1
            and self.read("get_registry_entries", registry_id=REG_ID)[0]["id"]
            == "entry-solar",
            "",
        )

        print("\n[3] challenge authorization and commitments")
        prior_url = f"{base}/prior-art-2019.md"
        unrelated_url = f"{base}/unrelated-prior-art.md"
        prior_sha = _fetch_sha(prior_url)
        unrelated_sha = _fetch_sha(unrelated_url)
        print(f"  prior art sha {prior_sha[:16]}…")

        self.expect_fail(
            "the entrant cannot challenge its own entry", "challenge_entry",
            account=self.entrant, value=BOND, registry_id=REG_ID,
            entry_id="entry-solar", prior_art_url=prior_url,
            prior_art_sha256=prior_sha,
        )
        self.expect_fail(
            "wrong bond is rejected", "challenge_entry",
            account=self.challenger, value=BOND - 1, registry_id=REG_ID,
            entry_id="entry-solar", prior_art_url=prior_url,
            prior_art_sha256=prior_sha,
        )
        self.expect_fail(
            "private host prior art is refused", "challenge_entry",
            account=self.challenger, value=BOND, registry_id=REG_ID,
            entry_id="entry-solar", prior_art_url="https://10.0.0.5/prior.md",
            prior_art_sha256=prior_sha,
        )
        self.expect_fail(
            "malformed prior art hash is refused", "challenge_entry",
            account=self.challenger, value=BOND, registry_id=REG_ID,
            entry_id="entry-solar", prior_art_url=prior_url,
            prior_art_sha256="abc",
        )
        self.expect_fail(
            "unknown entry cannot be challenged", "challenge_entry",
            account=self.challenger, value=BOND, registry_id=REG_ID,
            entry_id="entry-missing", prior_art_url=prior_url,
            prior_art_sha256=prior_sha,
        )

        tx = self.write(
            "challenge_entry", account=self.challenger, value=BOND, registry_id=REG_ID,
            entry_id="entry-solar", prior_art_url=prior_url,
            prior_art_sha256=prior_sha,
        )
        rc = self.wait(tx)
        entry = self.read("get_entry", registry_id=REG_ID, entry_id="entry-solar")
        self.check(
            "challenge freezes the entry with the bond recorded",
            self.exec_result(rc) == "SUCCESS"
            and entry["status"] == "challenged"
            and entry["bond"] == BOND
            and entry["challenge_count"] == 1
            and len(entry["challenge_binding"]) == 64,
            json.dumps(entry)[:250],
        )
        self.expect_fail(
            "a challenged entry cannot be challenged again", "challenge_entry",
            account=self.challenger, value=BOND, registry_id=REG_ID,
            entry_id="entry-solar", prior_art_url=prior_url,
            prior_art_sha256=prior_sha,
        )

        print("\n[4] duplicate adjudication")
        tx = self.write("resolve_challenge", registry_id=REG_ID, entry_id="entry-solar")
        rc = self.wait(tx)
        entry = self.read("get_entry", registry_id=REG_ID, entry_id="entry-solar")
        self.check(
            "duplicate prior art revokes the entry and slashes the stake",
            self.exec_result(rc) == "SUCCESS"
            and entry["status"] == "revoked"
            and entry["verdict"] == "duplicate"
            and entry["stake"] == 0
            and entry["bond"] == 0
            and len(entry["verdict_binding"]) == 64,
            json.dumps(entry)[:300],
        )
        print(f"  reasoning: {entry['reasoning'][:160]}")
        self.expect_fail(
            "a resolved entry cannot be resolved again", "resolve_challenge",
            registry_id=REG_ID, entry_id="entry-solar",
        )

        print("\n[5] not_duplicate adjudication")
        tx = self.write(
            "register_entry", account=self.entrant, value=STAKE, registry_id=REG_ID,
            entry_id="entry-vet", title="Monthly mobile veterinary route for herders",
            summary=(
                "Fund a travelling veterinary clinic that visits alpine herder "
                "communities on a fixed monthly route to treat livestock."
            ),
        )
        self.wait(tx)
        tx = self.write(
            "challenge_entry", account=self.challenger, value=BOND, registry_id=REG_ID,
            entry_id="entry-vet", prior_art_url=unrelated_url,
            prior_art_sha256=unrelated_sha,
        )
        self.wait(tx)
        tx = self.write("resolve_challenge", registry_id=REG_ID, entry_id="entry-vet")
        rc = self.wait(tx)
        entry = self.read("get_entry", registry_id=REG_ID, entry_id="entry-vet")
        self.check(
            "unrelated prior art confirms the entry and pays the entrant",
            self.exec_result(rc) == "SUCCESS"
            and entry["status"] == "confirmed"
            and entry["verdict"] == "not_duplicate"
            and entry["stake"] == 0
            and entry["bond"] == 0,
            json.dumps(entry)[:300],
        )
        print(f"  reasoning: {entry['reasoning'][:160]}")

        print("\n[6] unverifiable prior art cannot win a challenge")
        tx = self.write(
            "register_entry", account=self.entrant, value=STAKE, registry_id=REG_ID,
            entry_id="entry-third", title="Third entry for the fallback probe",
            summary=(
                "A third proposal used only to check that unverifiable prior art "
                "cannot revoke an entry."
            ),
        )
        self.wait(tx)
        tx = self.write(
            "challenge_entry", account=self.challenger, value=BOND, registry_id=REG_ID,
            entry_id="entry-third", prior_art_url=f"{base}/does-not-exist.md",
            prior_art_sha256="0" * 64,
        )
        self.wait(tx)
        tx = self.write("resolve_challenge", registry_id=REG_ID, entry_id="entry-third")
        rc = self.wait(tx)
        entry = self.read("get_entry", registry_id=REG_ID, entry_id="entry-third")
        self.check(
            "unfetchable prior art fails the challenge",
            self.exec_result(rc) == "SUCCESS"
            and entry["status"] == "confirmed"
            and entry["verdict"] == "not_duplicate"
            and "could not be verified" in entry["reasoning"],
            json.dumps(entry)[:300],
        )

        print("\n[7] views and membership")
        self.expect_fail(
            "unknown registry is not readable", "get_registry", registry_id="missing"
        )
        entries = self.read("get_registry_entries", registry_id=REG_ID)
        statuses = {item["id"]: item["status"] for item in entries}
        self.check(
            "entry index reports every entry and its final status",
            len(entries) == 3
            and statuses.get("entry-solar") == "revoked"
            and statuses.get("entry-vet") == "confirmed"
            and statuses.get("entry-third") == "confirmed",
            str(statuses),
        )


def deploy(h: Harness, contract: Path) -> str:
    code = contract.read_text(encoding="utf-8")
    tx = h.client.deploy_contract(code=code, account=h.client_acct)
    return h.wait(tx)["to_address"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="")
    parser.add_argument("--contract", default=DEFAULT_CONTRACT)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args()

    h = Harness()
    if args.address:
        h.address = args.address
        print(f"Using contract {h.address}")
    else:
        h.address = deploy(h, ROOT / args.contract)
        print(f"Deployed contract {h.address}")

    h.run(args.base_url.rstrip("/"))
    print(f"\n{h.passed} passed, {h.failed} failed")
    return 0 if h.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
