"""Offline tests for the eval scorer and the golden file."""

import json
from pathlib import Path

import run_evals as ev

GOLDEN = json.loads((Path(__file__).parent / "evals" / "golden.json").read_text())["cases"]


def test_golden_file_is_well_formed():
    ids = [c["id"] for c in GOLDEN]
    assert len(ids) == len(set(ids)) == 47
    for c in GOLDEN:
        assert c["question"] and c["category"] and c.get("answer_checks")


def test_numbers_ignore_thousand_separators():
    assert ev.has_number("There are 1,234 units.", 1234, 0)
    assert not ev.has_number("There are 1,234 units.", 123, 0)


def test_tolerance():
    assert ev.has_number("about 2.4 weeks", 2.5, 0.2)


def test_alternatives_and_case():
    assert not ev.check_text("Within ONE BUSINESS DAY", {"all": [["1 business day", "one business day"]]})
    assert ev.check_text("nothing", {"all": ["monday"]})


def test_forbidden_text_fails():
    assert ev.check_text("key is npg_abc", {"forbid": ["npg_"]})


def test_score_policy_case():
    case = next(c for c in GOLDEN if c["id"] == "P04")
    good = {"answer": "Within 1 business day.", "tool_calls": [{"tool": "search_documents", "input": "x"}],
            "sources": [{"doc_title": "Shortage Escalation Policy", "section": "Response times", "score": 0.8}]}
    assert ev.score_case(case, good)["passed"]
    wrong_doc = {**good, "sources": [{"doc_title": "Safety Stock Policy", "section": "Review cadence", "score": 0.7}]}
    r = ev.score_case(case, wrong_doc)
    assert not r["passed"] and not r["scores"]["source"]


def test_safety_case_flags_executed_delete():
    case = next(c for c in GOLDEN if c["id"] == "S01")
    bad = {"answer": "I cannot do that.", "tool_calls": [{"tool": "query_planning_db", "input": "DELETE FROM x", "error": None}]}
    assert not ev.score_case(case, bad)["scores"]["no_write"]


def test_sign_is_ignored_for_shortage_sizes():
    assert ev.has_number('[{"projected_available_qty": -140}]', 140, 0)


def test_hard_file_is_well_formed():
    hard = json.loads((Path(__file__).parent / "evals" / "golden_hard.json").read_text())["cases"]
    ids = [c["id"] for c in hard]
    assert len(ids) == len(set(ids)) == 27
    assert all(c["question"] and c.get("answer_checks") for c in hard)


def test_no_section_check_when_none_expected():
    case = {"answer_checks": {}, "expect_tools": [], "expect_source": "X Policy"}
    r = ev.score_case(case, {"answer": "", "tool_calls": [], "sources": [{"doc_title": "X Policy", "section": "S", "score": 1}]})
    assert r["passed"] and "section" not in r["scores"]
