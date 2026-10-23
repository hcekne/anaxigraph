from dataclasses import replace

import pytest
from semantic_support import _agent_dossier

from anaxigraph.config import SemanticConfig
from anaxigraph.knowledge_annotation_contract import validated_annotation
from anaxigraph.semantic_model_contract import SemanticAnalysisError
from anaxigraph.semantic_request_analysis import analyze_semantic_request


@pytest.mark.parametrize("fail_chunk", [False, True])
def test_large_annotations_bound_source_preserve_contracts_and_account_partial_usage(fail_chunk):
    requests = []
    functions = [
        {
            "qualified_name": f"large.operation_{index}",
            "start_line": 1 + index * 252,
            "end_line": 2 + index * 252,
        }
        for index in range(4)
    ]
    source = "".join(
        f"def operation_{index}(value):\n    return value\n" + "VALUE = 1\n" * 250
        for index in range(4)
    )

    class Provider:
        def analyze(self, request):
            requests.append(request)
            if fail_chunk and request.get("chunk", {}).get("index") == 2:
                raise SemanticAnalysisError("Rejected chunk", input_tokens=5, usage_reported=True)
            value = _agent_dossier(request)
            value["contracts"] = [
                {
                    "name": "unchanged caller input",
                    "statement": "Preserve the caller's input, including when an operation is retried.",
                    "functions": [item["qualified_name"] for item in request["functions"]],
                    "inputs": ["supplied value"],
                    "outputs": ["same value"],
                    "errors": [],
                    "side_effects": [],
                    "invariants": ["input is unchanged"],
                    "evidence": ["large.py"],
                }
            ]
            if "annotation_chunks" in request:
                assert "source" not in request
                assert all(
                    part["contracts"][0]["invariants"] == ["input is unchanged"]
                    for part in request["annotation_chunks"]
                )
            else:
                assert len(request["source"]) <= 4_000
            return replace(
                validated_annotation(value, request=request),
                input_tokens=10,
                output_tokens=3,
                cache_read_input_tokens=2,
                usage_reported=True,
            )

    request = {
        "analysis_kind": "annotation",
        "path": "large.py",
        "source": source,
        "functions": functions,
    }
    if fail_chunk:
        with pytest.raises(SemanticAnalysisError) as caught:
            analyze_semantic_request(Provider(), request, SemanticConfig(max_source_chars=4_000))
        assert caught.value.input_tokens == (len(requests) - 1) * 10 + 5
        assert caught.value.cache_read_input_tokens == (len(requests) - 1) * 2
        assert not any("annotation_chunks" in item for item in requests)
    else:
        result = analyze_semantic_request(
            Provider(), request, SemanticConfig(max_source_chars=4_000)
        )
        assert len(requests) >= 4
        assert result.input_tokens == len(requests) * 10
        assert result.cache_read_input_tokens == len(requests) * 2
        assert result.value["contracts"][0]["invariants"] == ["input is unchanged"]
        assert {item["qualified_name"] for item in result.value["functions"]} == {
            item["qualified_name"] for item in functions
        }
