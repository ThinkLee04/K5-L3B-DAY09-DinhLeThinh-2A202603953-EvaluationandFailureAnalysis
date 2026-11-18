"""Regression case for the first wrong decision in the seeded C-002 trace."""

import pytest

from lab9.trace_case import investigate

pytestmark = pytest.mark.student


def test_c002_seed_55_detects_ticket_trust_regression():
    bad = investigate("seeded_regression", "C-002", 55)["trial"]
    fixed = investigate("fixed", "C-002", 55)["trial"]

    assert bad["lab8_pass"] is False
    assert bad["lab8_reason"] == "status resolved != denied"
    assert any(event["kind"] == "model_override" for event in bad["events"])
    assert bad["snapshot"]["refund_vnd"] == 20_000

    assert fixed["lab8_pass"] is True
    assert not any(event["kind"] == "model_override" for event in fixed["events"])
    assert fixed["snapshot"]["refund_vnd"] == 0
