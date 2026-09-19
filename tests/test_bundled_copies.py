"""Pin the files this repo keeps in two places.

`templates/` holds what the `workflow` skill's `init` mode copies into a
consuming project; this repo then dogfoods the same guard from `scripts/`.
Two copies with no check between them drift the moment either is edited by
hand -- and a drifted guard is worse than no guard, because the version CI
proves green here is not the version consumers are handed.
"""

from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]

PAIRS = [
    (
        "scripts/check_committed_permission_grants.sh",
        "templates/check_committed_permission_grants.sh",
    ),
]


@pytest.mark.parametrize(("ours", "shipped"), PAIRS)
def test_the_guard_we_run_is_the_guard_we_ship(ours: str, shipped: str):
    run, ship = PLUGIN / ours, PLUGIN / shipped
    assert run.exists(), f"{ours} is missing"
    assert ship.exists(), f"{shipped} is missing"
    assert run.read_bytes() == ship.read_bytes(), (
        f"{ours} and {shipped} have drifted; apply the edit to both"
    )
