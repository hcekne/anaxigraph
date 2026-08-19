from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from anaxigraph.storage import AnaxiIndex


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "sample"
    (root / "pkg").mkdir(parents=True)
    (root / "web").mkdir()
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / "pkg" / "__init__.py").write_text('"""Sample package."""\n', encoding="utf-8")
    (root / "pkg" / "util.py").write_text(
        '"""Small arithmetic helpers."""\n\ndef double(value: int) -> int:\n    return value * 2\n',
        encoding="utf-8",
    )
    (root / "pkg" / "core.py").write_text(
        '"""Public calculation service."""\n\n'
        "from .util import double\n\n"
        "class Calculator:\n"
        '    """Owns calculation behavior."""\n\n'
        "    def calculate(self, value: int) -> int:\n"
        "        return double(value)\n",
        encoding="utf-8",
    )
    (root / "pkg" / "consumer.py").write_text(
        "from pkg.core import Calculator\n\n"
        "def run(value: int) -> int:\n"
        "    return Calculator().calculate(value)\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_core.py").write_text(
        "from pkg.core import Calculator\n"
        "from pkg.util import double\n\n"
        "def test_calculate():\n"
        "    assert Calculator().calculate(3) == double(3)\n",
        encoding="utf-8",
    )
    (root / "web" / "App.tsx").write_text(
        "// Main application component.\n"
        "import { label } from './helper';\n\n"
        "export const App = () => <main>{label()}</main>;\n",
        encoding="utf-8",
    )
    (root / "web" / "helper.ts").write_text(
        "export function label(): string {\n  return 'Sample';\n}\n",
        encoding="utf-8",
    )
    (root / "docs" / "architecture.md").write_text(
        "# Sample architecture\n\nThe package is independent from the web client.\n",
        encoding="utf-8",
    )
    (root / "coverage.xml").write_text(
        """<?xml version="1.0" ?>
<coverage>
  <packages><package name="pkg"><classes>
    <class name="Calculator" filename="pkg/core.py" line-rate="0.5" branch-rate="0.25">
      <lines><line number="1" hits="1"/><line number="8" hits="0"/></lines>
    </class>
  </classes></package></packages>
</coverage>
""",
        encoding="utf-8",
    )
    (root / ".anaxigraph.yml").write_text(
        """project:
  name: Sample Observatory
groups:
  domain:
    paths: [pkg/**]
  presentation:
    paths: [web/**]
architecture:
  policy: docs/architecture.md
  protected_paths: [pkg/core.py]
  rules:
    - id: small-module-signal
      type: max_module_loc
      severity: info
      max: 6
    - id: web-domain-boundary
      type: forbid_dependency
      severity: error
      from: presentation
      to: domain
agent:
  context_limit: 12
  neighbor_depth: 2
aliases:
  "@/": web/
coverage:
  files: [coverage.xml]
ignore:
  - ignored/**
""",
        encoding="utf-8",
    )
    (root / "ignored").mkdir()
    (root / "ignored" / "secret.py").write_text("SECRET = True\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "Initial sample"], check=True)
    return root


@pytest.fixture
def database(tmp_path: Path) -> AnaxiIndex:
    return AnaxiIndex(tmp_path / "state" / "anaxi-index.db")
