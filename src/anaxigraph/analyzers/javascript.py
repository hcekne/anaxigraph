"""Dependency and symbol extraction for JavaScript and TypeScript families."""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath

from anaxigraph.analyzer_capabilities import declare_capabilities
from anaxigraph.ir import module_identity, resolver_context, symbol_visibility
from anaxigraph.languages import detect_language
from anaxigraph.models import Dependency, FileAnalysis, Symbol

_IMPORT_PATTERNS = (
    re.compile(
        r"(?:^|\n)\s*import\s+(?P<binding>[^;\n]*?)\s+from\s+['\"](?P<target>[^'\"]+)['\"]",
        re.MULTILINE,
    ),
    re.compile(r"(?:^|\n)\s*import\s+['\"](?P<target>[^'\"]+)['\"]", re.MULTILINE),
    re.compile(
        r"(?:^|\n)\s*export\s+(?:\*|\{[^}]*\})\s+from\s+['\"](?P<target>[^'\"]+)['\"]",
        re.MULTILINE,
    ),
    re.compile(r"\brequire\(\s*['\"](?P<target>[^'\"]+)['\"]\s*\)"),
    re.compile(r"\bimport\(\s*['\"](?P<target>[^'\"]+)['\"]\s*\)"),
)
_CLASS = re.compile(r"(?:^|\n)\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")
_FUNCTION = re.compile(
    r"(?:^|\n)\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
)
_ARROW = re.compile(
    r"(?:^|\n)\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*(?:async\s+)?(?:\(([^)]*)\)|([A-Za-z_$][\w$]*))\s*=>"
)
_ROUTE = re.compile(r"\b(?:router|app)\.(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)")
_TOKEN = re.compile(
    r"(?:[A-Za-z_$][\w$]*|\d+(?:\.\d+)?|===|!==|=>|\?\?|\?\.|&&|\|\||[{}()[\];,.?:+*/%<>=!-])"
)
_BRANCH = re.compile(r"\b(?:if|else\s+if|for|while|case|catch)\b|&&|\|\||\?\?")


class JavaScriptAnalyzer:
    name = "builtin-js-lexer"
    version = "1"
    languages = frozenset({"javascript", "javascriptreact", "typescript", "typescriptreact"})
    capabilities = declare_capabilities(
        name,
        version,
        "lexical",
        deep=("module_identity",),
        lexical=(
            "calls",
            "complexity",
            "entry_points",
            "exports",
            "imports",
            "module_documentation",
            "signatures",
            "source_spans",
            "symbol_kind",
            "symbol_visibility",
            "symbols",
            "types",
        ),
        heuristic=("side_effects",),
        limitations=(
            "Regex extraction cannot prove nested syntax, overloads, or complete call dispatch.",
            "TypeScript types, decorators, control flow, and mutation are not structural facts.",
        ),
    )

    def analyze(self, path: str, content: str) -> FileAnalysis:
        language = detect_language(path) or "javascript"
        identity = module_identity(path, language)
        code, comment_lines, leading_comment = _strip_comments(content)
        structural = " ".join(_TOKEN.findall(code))
        dependencies, aliases = _imports(content)
        for alias, target in aliases.items():
            call_pattern = re.compile(rf"\b{re.escape(alias)}(?:\.[A-Za-z_$][\w$]*)?\s*\(")
            for match in call_pattern.finditer(code):
                dependencies.append(
                    Dependency(
                        target=target,
                        relationship_type="calls",
                        line=code.count("\n", 0, match.start()) + 1,
                        evidence=match.group(0),
                        confidence=0.8,
                    )
                )
                break
        symbols = _symbols(path, code)
        loc = sum(1 for line in code.splitlines() if line.strip())
        complexity = 1 + len(_BRANCH.findall(code))
        public, summary, responsibilities, side_effects = _module_semantics(
            path, language, leading_comment, symbols, dependencies
        )
        return FileAnalysis(
            language=language,
            structural_hash=hashlib.sha256(structural.encode()).hexdigest(),
            lines_of_code=loc,
            comment_lines=len(comment_lines),
            complexity=max(1, complexity),
            summary=summary[:1_000],
            responsibilities=responsibilities,
            side_effects=side_effects,
            public_interfaces=public,
            symbols=symbols,
            dependencies=_deduplicate_dependencies(dependencies),
            analyzer=self.name,
            module_identity=identity,
            exports=public,
            parse_status="lexical",
            analyzer_version=self.version,
            resolver_context=resolver_context(identity, import_aliases=aliases),
            analyzer_capabilities=self.capabilities,
        )


def _module_semantics(path, language, leading_comment, symbols, dependencies):
    name = PurePosixPath(path).stem
    public = [symbol.name for symbol in symbols if not symbol.name.startswith("_")]
    summary = leading_comment or (
        f"{language.title()} module {name} defining {', '.join(public[:5])}"
        if public
        else f"{language.title()} module {name}"
    )
    responsibilities = [
        f"Provide {symbol.symbol_type.replace('_', ' ')} {symbol.name}" for symbol in symbols[:12]
    ]
    side_effects = []
    targets = {item.target for item in dependencies}
    if any(target in targets for target in ("axios", "node-fetch", "http", "https")):
        side_effects.append("network access")
    if any(target in targets for target in ("fs", "node:fs")):
        side_effects.append("filesystem access")
    return public, summary, responsibilities, side_effects


def _strip_comments(content: str) -> tuple[str, set[int], str]:
    output = list(content)
    comment_lines: set[int] = set()
    collected: list[str] = []
    index = 0
    line = 1
    state = "code"
    quote = ""
    while index < len(content):
        char = content[index]
        following = content[index + 1] if index + 1 < len(content) else ""
        if char == "\n":
            line += 1
        if state == "code":
            if char in {"'", '"', "`"}:
                state = "string"
                quote = char
            elif char == "/" and following == "/":
                state = "line_comment"
                comment_lines.add(line)
                output[index] = output[index + 1] = " "
                index += 1
            elif char == "/" and following == "*":
                state = "block_comment"
                comment_lines.add(line)
                output[index] = output[index + 1] = " "
                index += 1
        elif state == "string":
            if char == "\\":
                index += 1
            elif char == quote:
                state = "code"
        elif state == "line_comment":
            if char == "\n":
                state = "code"
            else:
                if line <= 8:
                    collected.append(char)
                output[index] = " "
        elif state == "block_comment":
            comment_lines.add(line)
            if char == "*" and following == "/":
                output[index] = output[index + 1] = " "
                index += 1
                state = "code"
            elif char != "\n":
                if line <= 8:
                    collected.append(char)
                output[index] = " "
        index += 1
    leading = " ".join("".join(collected).replace("*", " ").split())[:1_000]
    return "".join(output), comment_lines, leading


def _imports(content: str) -> tuple[list[Dependency], dict[str, str]]:
    result: list[Dependency] = []
    aliases: dict[str, str] = {}
    for pattern in _IMPORT_PATTERNS:
        for match in pattern.finditer(content):
            target = match.group("target")
            binding = match.groupdict().get("binding") or ""
            names = tuple(
                token
                for token in re.findall(r"[A-Za-z_$][\w$]*", binding)
                if token not in {"type", "as"}
            )
            if binding:
                default = binding.split(",", 1)[0].strip()
                if re.fullmatch(r"[A-Za-z_$][\w$]*", default):
                    aliases[default] = target
                for original, alias in re.findall(
                    r"([A-Za-z_$][\w$]*)(?:\s+as\s+([A-Za-z_$][\w$]*))?", binding
                ):
                    aliases[alias or original] = target
            result.append(
                Dependency(
                    target=target,
                    line=content.count("\n", 0, match.start()) + 1,
                    evidence=" ".join(match.group(0).split())[:500],
                    names=names,
                )
            )
    return _deduplicate_dependencies(result), aliases


def _symbols(path: str, code: str) -> list[Symbol]:
    result: list[Symbol] = []
    module = str(PurePosixPath(path).with_suffix("")).replace("/", ".")
    candidates: list[tuple[int, str, str, str]] = []
    for match in _CLASS.finditer(code):
        candidates.append((match.start(), "class", match.group(1), f"class {match.group(1)}"))
    for match in _FUNCTION.finditer(code):
        candidates.append(
            (
                match.start(),
                "function",
                match.group(1),
                f"function {match.group(1)}({match.group(2).strip()})",
            )
        )
    for match in _ARROW.finditer(code):
        name = match.group(1)
        kind = "react_component" if name[:1].isupper() else "function"
        args = (match.group(2) or match.group(3) or "").strip()
        candidates.append((match.start(), kind, name, f"const {name} = ({args}) =>"))
    for match in _ROUTE.finditer(code):
        name = f"{match.group(1).upper()} {match.group(2)}"
        candidates.append((match.start(), "api_endpoint", name, name))
    seen: set[tuple[str, int]] = set()
    for position, kind, name, signature in sorted(candidates):
        start_line = code.count("\n", 0, position) + 1
        if (name, start_line) in seen:
            continue
        seen.add((name, start_line))
        end_line = _block_end_line(code, position)
        segment = "\n".join(code.splitlines()[start_line - 1 : end_line])
        result.append(
            Symbol(
                symbol_type=kind,
                name=name,
                qualified_name=f"{module}.{name}",
                start_line=start_line,
                end_line=end_line,
                signature=signature[:1_000],
                complexity=1 + len(_BRANCH.findall(segment)),
                logical_lines=max(1, sum(1 for line in segment.splitlines() if line.strip())),
                visibility=symbol_visibility(name),
                start_column=position - code.rfind("\n", 0, position) - 1,
            )
        )
    return result


def _block_end_line(code: str, position: int) -> int:
    open_index = code.find("{", position)
    start_line = code.count("\n", 0, position) + 1
    if open_index < 0 or open_index - position > 500:
        return start_line
    depth = 0
    state = "code"
    quote = ""
    index = open_index
    while index < len(code):
        char = code[index]
        if state == "code" and char in {"'", '"', "`"}:
            state = "string"
            quote = char
        elif state == "string":
            if char == "\\":
                index += 1
            elif char == quote:
                state = "code"
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return code.count("\n", 0, index) + 1
        index += 1
    return min(start_line + 200, len(code.splitlines()) or 1)


def _deduplicate_dependencies(items: list[Dependency]) -> list[Dependency]:
    result: list[Dependency] = []
    seen: set[tuple[str, str, int]] = set()
    for item in items:
        key = (item.target, item.relationship_type, item.line)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result
