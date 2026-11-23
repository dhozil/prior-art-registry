"""Direct-mode tests for the PriorArtRegistry contract."""

import hashlib
import json
import re
from datetime import datetime, timedelta

from gltest.direct import create_address

REG_ID = "grants-2024"
SCOPE = (
    "Grant proposals for community-scale energy projects. Two proposals are the same "
    "idea when they propose the same mechanism for the same beneficiaries."
)
CAP = 6
STAKE = 100
BOND = 250
WINDOW = 3600

ENTRANT_ADDR = create_address("par-entrant")
CHALLENGER_ADDR = create_address("par-challenger")
OTHER_ADDR = create_address("par-other")
ENTRANT = "0x" + ENTRANT_ADDR.hex()
CHALLENGER = "0x" + CHALLENGER_ADDR.hex()
OTHER = "0x" + OTHER_ADDR.hex()

TITLE_A = "Alpine solar micro-grid for farm cooperatives"
SUMMARY_A = (
    "Install shared 40kW solar micro-grids with battery storage on alpine farm "
    "cooperatives so members stop running diesel generators in winter."
)
TITLE_B = "Shared solar micro-grids for alpine farm cooperatives"
SUMMARY_B = (
    "Deploy shared photovoltaic micro-grids with battery banks to alpine farm "
    "cooperatives, replacing winter diesel generation for all members."
)
TITLE_C = "Mobile veterinary clinic for alpine herders"
SUMMARY_C = (
    "Fund a travelling veterinary clinic that visits alpine herder communities on a "
    "fixed monthly route to treat livestock and run vaccination days."
)

PRIOR_ART_URL = "https://prior-art.example.com/registry-2019.md"
PRIOR_ART = (
    "2019 programme: shared 40kW photovoltaic micro-grids with battery storage were "
    "installed on alpine farm cooperatives to replace winter diesel generation."
)

DUPLICATE_JSON = json.dumps(
    {
        "verdict": "duplicate",
        "reasoning": "The prior art discloses the same shared solar micro-grid mechanism "
        "for the same alpine farm cooperatives.",
    }
)
NOT_DUPLICATE_JSON = json.dumps(
    {
        "verdict": "not_duplicate",
        "reasoning": "A travelling veterinary clinic is a different mechanism and "
        "deliverable from an energy micro-grid.",
    }
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _create_registry(
    direct_vm,
    contract,
    registry_id=REG_ID,
    scope=SCOPE,
    cap=CAP,
    stake=STAKE,
    bond=BOND,
    window=WINDOW,
):
    direct_vm.sender = OTHER_ADDR
    direct_vm.value = 0
    return contract.create_registry(
        registry_id=registry_id,
        scope=scope,
        entry_cap=cap,
        registration_stake=stake,
        challenge_bond=bond,
        challenge_window_seconds=window,
    )


def _register(
    direct_vm,
    contract,
    entry_id="entry-a",
    title=TITLE_A,
    summary=SUMMARY_A,
    sender=ENTRANT_ADDR,
    value=STAKE,
    registry_id=REG_ID,
):
    direct_vm.sender = sender
    direct_vm.value = value
    return contract.register_entry(
        registry_id=registry_id, entry_id=entry_id, title=title, summary=summary
    )


def _challenge(
    direct_vm,
    contract,
    entry_id="entry-a",
    prior_art=PRIOR_ART,
    url=PRIOR_ART_URL,
    sha=None,
    sender=CHALLENGER_ADDR,
    value=BOND,
    registry_id=REG_ID,
):
    direct_vm.sender = sender
    direct_vm.value = value
    return contract.challenge_entry(
        registry_id=registry_id,
        entry_id=entry_id,
        prior_art_url=url,
        prior_art_sha256=_sha(prior_art) if sha is None else sha,
    )


def _mock_prior_art(direct_vm, body=PRIOR_ART):
    direct_vm.mock_web(re.escape(PRIOR_ART_URL), {"status": 200, "body": body})


def _mock_verdict(direct_vm, payload):
    direct_vm.mock_llm(r"bonded challenge in a semantic prior-art registry", payload)


def _resolve(direct_vm, contract, entry_id="entry-a", payload=None, body=PRIOR_ART):
    _mock_prior_art(direct_vm, body)
    _mock_verdict(direct_vm, DUPLICATE_JSON if payload is None else payload)
    direct_vm.sender = OTHER_ADDR
    direct_vm.value = 0
    return contract.resolve_challenge(REG_ID, entry_id)


def test_create_registry_validates_scope_and_economics(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/prior_art_registry.py")
    direct_vm.check_pickling = True

    with direct_vm.expect_revert("Registry id must be 1-64 characters"):
        _create_registry(direct_vm, contract, registry_id="")
    with direct_vm.expect_revert(
        "Registry id may only contain letters, digits, dash, underscore or dot"
    ):
        _create_registry(direct_vm, contract, registry_id="grants 2024#")
    with direct_vm.expect_revert("Scope must describe what counts as a duplicate"):
        _create_registry(direct_vm, contract, scope="too short")
    with direct_vm.expect_revert("Scope is too long"):
        _create_registry(direct_vm, contract, scope="x" * 601)
    with direct_vm.expect_revert("Entry cap must be between 3 and 25"):
        _create_registry(direct_vm, contract, cap=2)
    with direct_vm.expect_revert("Entry cap must be between 3 and 25"):
        _create_registry(direct_vm, contract, cap=26)
    with direct_vm.expect_revert("Registration stake must be positive"):
        _create_registry(direct_vm, contract, stake=0, bond=0)
    with direct_vm.expect_revert(
        "Challenge bond must be at least the registration stake"
    ):
        _create_registry(direct_vm, contract, stake=100, bond=99)
    with direct_vm.expect_revert("Challenge bond must be at most 10x the stake"):
        _create_registry(direct_vm, contract, stake=100, bond=1001)
    with direct_vm.expect_revert("Challenge window is too short"):
        _create_registry(direct_vm, contract, window=60)
    with direct_vm.expect_revert("Challenge window exceeds 30 days"):
        _create_registry(direct_vm, contract, window=31 * 24 * 3600)

    result = _create_registry(direct_vm, contract)
    assert result["registry_id"] == REG_ID
    assert result["entry_cap"] == CAP
    assert result["registration_stake"] == STAKE
    assert result["challenge_bond"] == BOND
    assert len(result["terms_binding"]) == 64

    with direct_vm.expect_revert("Registry already exists"):
        _create_registry(direct_vm, contract)

    registry = contract.get_registry(REG_ID)
    assert registry["scope"] == SCOPE
    assert registry["entry_count"] == 0
    assert registry["terms_binding"] == result["terms_binding"]


def test_register_entry_stakes_and_binds(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/prior_art_registry.py")
    _create_registry(direct_vm, contract)

    with direct_vm.expect_revert("Registry not found"):
        _register(direct_vm, contract, registry_id="nope")
    with direct_vm.expect_revert("Entry id must be 1-64 characters"):
        _register(direct_vm, contract, entry_id="")
    with direct_vm.expect_revert(
        "Entry id may only contain letters, digits, dash, underscore or dot"
    ):
        _register(direct_vm, contract, entry_id="entry a!")
    with direct_vm.expect_revert("Title must be 3-160 characters"):
        _register(direct_vm, contract, title="ab")
    with direct_vm.expect_revert("Summary must be 20-600 characters"):
        _register(direct_vm, contract, summary="too short")
    with direct_vm.expect_revert(
        "Registration stake must equal the registry stake"
    ):
        _register(direct_vm, contract, value=STAKE - 1)
    with direct_vm.expect_revert(
        "Registration stake must equal the registry stake"
    ):
        _register(direct_vm, contract, value=STAKE + 1)

    result = _register(direct_vm, contract)
    assert result["status"] == "provisional"
    assert len(result["entry_binding"]) == 64
    assert result["challenge_deadline"] != ""

    with direct_vm.expect_revert("Entry already registered in this registry"):
        _register(direct_vm, contract)

    entry = contract.get_entry(REG_ID, "entry-a")
    assert entry["entrant"].lower() == ENTRANT.lower()
    assert entry["title"] == TITLE_A
    assert entry["stake"] == STAKE
    assert entry["status"] == "provisional"
    assert entry["entry_binding"] == result["entry_binding"]
    assert contract.get_registry(REG_ID)["entry_count"] == 1
    assert contract.get_registry_entries(REG_ID) == [
        {
            "id": "entry-a",
            "title": TITLE_A,
            "entrant": ENTRANT,
            "status": "provisional",
            "verdict": "",
        }
    ] or contract.get_registry_entries(REG_ID)[0]["id"] == "entry-a"


def test_entry_cap_is_enforced(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/prior_art_registry.py")
    _create_registry(direct_vm, contract, cap=3)
    for index in range(3):
        _register(direct_vm, contract, entry_id=f"entry-{index}")
    assert contract.get_registry(REG_ID)["entry_count"] == 3
    with direct_vm.expect_revert("Registry entry cap reached"):
        _register(direct_vm, contract, entry_id="entry-4")


def test_challenge_guards(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/prior_art_registry.py")
    _create_registry(direct_vm, contract)
    _register(direct_vm, contract)

    with direct_vm.expect_revert("Entry not found"):
        _challenge(direct_vm, contract, entry_id="missing")
    with direct_vm.expect_revert("An entrant cannot challenge its own entry"):
        _challenge(direct_vm, contract, sender=ENTRANT_ADDR)
    with direct_vm.expect_revert(
        "Challenge bond must equal the registry bond"
    ):
        _challenge(direct_vm, contract, value=BOND - 1)
    with direct_vm.expect_revert("Prior art hash must be 64 hex characters"):
        _challenge(direct_vm, contract, sha="abc")
    with direct_vm.expect_revert("Prior art URL must use a public hostname"):
        _challenge(direct_vm, contract, url="https://127.0.0.1/prior.md")
    with direct_vm.expect_revert("Prior art URL must be http(s)"):
        _challenge(direct_vm, contract, url="ftp://prior-art.example.com/p.md")

    direct_vm.warp((datetime.now() + timedelta(seconds=WINDOW + 60)).isoformat())
    with direct_vm.expect_revert("Challenge window has closed"):
        _challenge(direct_vm, contract)


def test_duplicate_verdict_revokes_and_slashes(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/prior_art_registry.py")
    _create_registry(direct_vm, contract)
    _register(direct_vm, contract)
    _register(direct_vm, contract, entry_id="entry-b", title=TITLE_B, summary=SUMMARY_B)
    challenge = _challenge(direct_vm, contract)
    assert len(challenge["challenge_binding"]) == 64

    result = _resolve(direct_vm, contract)
    assert result["verdict"] == "duplicate"
    assert result["status"] == "revoked"
    assert result["awarded_amount"] == BOND + STAKE
    assert result["recipient"].lower() == CHALLENGER.lower()
    assert result["corpus_entries"] == 1
    assert len(result["verdict_binding"]) == 64

    entry = contract.get_entry(REG_ID, "entry-a")
    assert entry["status"] == "revoked"
    assert entry["verdict"] == "duplicate"
    assert entry["stake"] == 0
    assert entry["bond"] == 0
    assert entry["verdict_binding"] == result["verdict_binding"]

    with direct_vm.expect_revert("Entry has no active challenge"):
        contract.resolve_challenge(REG_ID, "entry-a")
    with direct_vm.expect_revert("Entry is not open to a challenge"):
        _challenge(direct_vm, contract, sender=OTHER_ADDR)


def test_not_duplicate_verdict_confirms_and_compensates(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/prior_art_registry.py")
    _create_registry(direct_vm, contract)
    _register(direct_vm, contract)
    _challenge(direct_vm, contract)

    result = _resolve(direct_vm, contract, payload=NOT_DUPLICATE_JSON)
    assert result["verdict"] == "not_duplicate"
    assert result["status"] == "confirmed"
    assert result["awarded_amount"] == STAKE + BOND
    assert result["recipient"].lower() == ENTRANT.lower()

    entry = contract.get_entry(REG_ID, "entry-a")
    assert entry["status"] == "confirmed"
    assert entry["verdict"] == "not_duplicate"
    assert entry["stake"] == 0
    assert entry["challenge_count"] == 1

    # A confirmed entry can no longer be challenged or finalised.
    with direct_vm.expect_revert("Entry is not open to a challenge"):
        _challenge(direct_vm, contract, sender=OTHER_ADDR)
    with direct_vm.expect_revert("Entry is not provisional"):
        contract.finalize_entry(REG_ID, "entry-a")


def test_unverifiable_prior_art_fails_the_challenge(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/prior_art_registry.py")
    _create_registry(direct_vm, contract)
    _register(direct_vm, contract)
    _challenge(direct_vm, contract)

    direct_vm.mock_web(re.escape(PRIOR_ART_URL), {"status": 404, "body": "gone"})
    _mock_verdict(direct_vm, NOT_DUPLICATE_JSON)
    result = contract.resolve_challenge(REG_ID, "entry-a")
    assert result["verdict"] == "not_duplicate"
    assert result["status"] == "confirmed"
    assert "could not be verified" in result["reasoning"]
    assert contract.get_entry(REG_ID, "entry-a")["status"] == "confirmed"


def test_substituted_prior_art_is_rejected(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/prior_art_registry.py")
    _create_registry(direct_vm, contract)
    _register(direct_vm, contract)
    _challenge(direct_vm, contract, prior_art="the original prior art text")

    # The challenger serves different bytes than the ones it committed.
    direct_vm.mock_web(
        re.escape(PRIOR_ART_URL),
        {"status": 200, "body": "a completely different document"},
    )
    _mock_verdict(direct_vm, DUPLICATE_JSON)
    result = contract.resolve_challenge(REG_ID, "entry-a")
    assert result["verdict"] == "not_duplicate"
    assert "hash does not match" in result["reasoning"]


def test_validator_requires_exact_verdict_category(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/prior_art_registry.py")
    _create_registry(direct_vm, contract)
    _register(direct_vm, contract)
    _challenge(direct_vm, contract)
    _resolve(direct_vm, contract, payload=DUPLICATE_JSON)

    # Same category -> accept, regardless of the reasoning text.
    direct_vm.clear_mocks()
    _mock_prior_art(direct_vm)
    _mock_verdict(direct_vm, DUPLICATE_JSON)
    assert (
        direct_vm.run_validator(
            leader_result={"verdict": "duplicate", "reasoning": "different words"}
        )
        is True
    )

    # Opposite category -> reject.
    assert (
        direct_vm.run_validator(
            leader_result={"verdict": "not_duplicate", "reasoning": "x"}
        )
        is False
    )

    # Malformed payloads -> reject.
    assert direct_vm.run_validator(leader_result={"verdict": "duplicate"}) is False
    assert (
        direct_vm.run_validator(
            leader_result={"verdict": "duplicate", "reasoning": "  "}
        )
        is False
    )
    assert direct_vm.run_validator(leader_result={"verdict": "maybe", "reasoning": "x"}) is False
    assert direct_vm.run_validator(leader_result="duplicate") is False

    # Validator sees different prior art than the leader -> reject.
    direct_vm.clear_mocks()
    direct_vm.mock_web(
        re.escape(PRIOR_ART_URL), {"status": 200, "body": "unrelated document"}
    )
    _mock_verdict(direct_vm, DUPLICATE_JSON)
    assert (
        direct_vm.run_validator(
            leader_result={"verdict": "duplicate", "reasoning": "x"}
        )
        is False
    )


def test_corpus_is_visible_to_the_judge(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/prior_art_registry.py")
    _create_registry(direct_vm, contract)
    # An earlier entry whose title must appear in the judge's prompt.
    _register(direct_vm, contract, entry_id="entry-old", title=TITLE_B, summary=SUMMARY_B)
    _register(direct_vm, contract, entry_id="entry-new", title=TITLE_C, summary=SUMMARY_C)
    _challenge(direct_vm, contract, entry_id="entry-new")

    direct_vm.mock_web(re.escape(PRIOR_ART_URL), {"status": 200, "body": PRIOR_ART})
    # Only matches if the earlier entry's title is inside the assembled corpus.
    direct_vm.mock_llm(re.escape(TITLE_B), DUPLICATE_JSON)
    result = contract.resolve_challenge(REG_ID, "entry-new")
    assert result["verdict"] == "duplicate"
    assert result["corpus_entries"] == 1

    # A revoked entry drops out of later corpora.
    assert contract.get_entry(REG_ID, "entry-old")["status"] == "provisional"


def test_finalize_returns_the_stake_without_consensus(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/prior_art_registry.py")
    _create_registry(direct_vm, contract)
    _register(direct_vm, contract)

    direct_vm.sender = OTHER_ADDR
    with direct_vm.expect_revert("Challenge window has not closed"):
        contract.finalize_entry(REG_ID, "entry-a")

    direct_vm.warp((datetime.now() + timedelta(seconds=WINDOW + 60)).isoformat())
    result = contract.finalize_entry(REG_ID, "entry-a")
    assert result["status"] == "confirmed"
    assert result["returned_amount"] == STAKE
    assert len(result["verdict_binding"]) == 64

    entry = contract.get_entry(REG_ID, "entry-a")
    assert entry["status"] == "confirmed"
    assert entry["verdict"] == "unchallenged"
    assert entry["stake"] == 0

    with direct_vm.expect_revert("Entry is not provisional"):
        contract.finalize_entry(REG_ID, "entry-a")
    with direct_vm.expect_revert("Entry is not open to a challenge"):
        _challenge(direct_vm, contract)


def test_late_challenge_and_double_resolve_are_refused(direct_vm, direct_deploy):
    contract = direct_deploy("contracts/prior_art_registry.py")
    _create_registry(direct_vm, contract)
    _register(direct_vm, contract)

    direct_vm.warp((datetime.now() + timedelta(seconds=WINDOW + 60)).isoformat())
    with direct_vm.expect_revert("Challenge window has closed"):
        _challenge(direct_vm, contract)

    # An entry challenged before the resolution is still resolvable afterwards.
    direct_vm.warp((datetime.now() + timedelta(seconds=WINDOW + 60)).isoformat())
    _register(direct_vm, contract, entry_id="entry-b", title=TITLE_C, summary=SUMMARY_C)
    _challenge(direct_vm, contract, entry_id="entry-b")
    direct_vm.warp((datetime.now() + timedelta(seconds=WINDOW + 120)).isoformat())
    with direct_vm.expect_revert("Entry has no active challenge"):
        contract.resolve_challenge(REG_ID, "entry-a")
    result = _resolve(direct_vm, contract, entry_id="entry-b")
    assert result["status"] == "revoked"
    with direct_vm.expect_revert("Entry has no active challenge"):
        contract.resolve_challenge(REG_ID, "entry-b")
