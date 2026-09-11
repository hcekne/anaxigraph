"""Protocol and rubric checks; model accuracy is measured by the opt-in benchmark."""

import json
from types import SimpleNamespace

from semantic_support import _pattern_evaluation

from anaxigraph.understandability import AGENT_REVIEW_POLICY
from benchmarks.architecture_judgment import FIXTURE, judge_case, judgment_request, judgment_summary


def test_judgment_packets_withhold_answers_and_compile_fixture_sources():
    cases = json.loads(FIXTURE.read_text())["cases"]
    assert len(cases) == 10
    for case in cases:
        request = judgment_request(case)
        assert case["id"] not in json.dumps(request)
        assert "expected" not in request
        assert "category" not in request
        assert request["pattern"]["stable_key"] == case["pattern"]
        assert json.dumps(request).count(AGENT_REVIEW_POLICY) == 1
        for path, source in case["sources"].items():
            compile(source, path, "exec")


def test_judgment_protocol_keeps_independent_review_and_unknown_cost():
    case = json.loads(FIXTURE.read_text())["cases"][0]
    requests = []

    def analyze(request):
        requests.append(request)
        evaluation = _pattern_evaluation(request)
        evaluation["recommendation"] = "retain"
        value = (
            {"evaluation": evaluation}
            if request["analysis_kind"] == "pattern_review"
            else evaluation
        )
        return SimpleNamespace(
            value=value,
            input_tokens=100,
            output_tokens=25,
            cache_read_input_tokens=0,
            usage_reported=True,
        )

    result = judge_case(case, SimpleNamespace(analyze=analyze))
    assert result["passed"]
    assert [request["analysis_kind"] for request in requests] == [
        "pattern_assessment",
        "pattern_review",
    ]
    assert requests[1]["assessment"] == result["assessment"]
    assert json.dumps(requests[1]).count(AGENT_REVIEW_POLICY) == 1
    summary = judgment_summary([result])
    assert summary["known_positive_misses"] == 0
    assert summary["input_tokens"] == 200
    assert summary["cost_usd"] is None


def test_model_failure_is_a_failed_case_not_an_accepted_judgment():
    case = json.loads(FIXTURE.read_text())["cases"][0]

    def fail(_request):
        raise ValueError("invalid model result")

    result = judge_case(case, SimpleNamespace(analyze=fail))
    assert not result["passed"]
    assert "invalid model result" in result["error"]
    assert judgment_summary([result])["known_positive_misses"] == 1
