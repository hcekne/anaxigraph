"""Small deterministic module-language projection for JavaScript-family facts."""

from __future__ import annotations

from pathlib import PurePosixPath

from anaxigraph.analyzer_facts import AnalyzerFact
from anaxigraph.analyzers.javascript_dependencies import DependencyFacts
from anaxigraph.ir import Symbol


def module_semantics(
    path: str,
    language: str,
    documentation: str,
    symbols: list[Symbol],
    references: DependencyFacts,
    evidence: list[AnalyzerFact],
) -> tuple[str, list[str], list[str], list[str], list[str], list[str]]:
    public = list(dict.fromkeys(references.exports))
    if not public:
        public = [item.name for item in symbols if item.visibility == "public"]
    display = {
        "javascript": "JavaScript",
        "javascriptreact": "JSX",
        "typescript": "TypeScript",
        "typescriptreact": "TSX",
    }.get(language, language.title())
    name = PurePosixPath(path).stem
    summary = documentation or (
        f"{display} module {name} defining {', '.join(public[:5])}"
        if public
        else f"{display} module {name}"
    )
    responsibilities = [
        f"Provide {item.symbol_type.replace('_', ' ')} {item.name}" for item in symbols[:12]
    ]
    inputs = list(
        dict.fromkeys(
            item.target for item in references.dependencies if item.relationship_type == "imports"
        )
    )
    outputs = public[:50]
    side_effects = list(
        dict.fromkeys(item.value for item in evidence if item.fact == "side_effects")
    )
    return summary[:1_000], responsibilities, inputs, outputs, side_effects, public
