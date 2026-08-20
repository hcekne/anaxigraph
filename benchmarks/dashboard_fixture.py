"""Build the deterministic repository used by dashboard browser contracts."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

_CONFIG = """project:
  name: AnaxiGraph Dashboard Contract
groups:
  frontend-features:
    level: subsystem
    parent: frontend
    paths: [frontend/features/**]
  frontend-lib:
    level: subsystem
    parent: frontend
    paths: [frontend/lib/**]
  frontend-shell:
    level: subsystem
    parent: frontend
    paths: [frontend/shell/**]
  backend-api:
    level: subsystem
    parent: backend
    paths: [backend/api/**]
  backend-services:
    level: subsystem
    parent: backend
    paths: [backend/services/**]
  backend-models:
    level: subsystem
    parent: backend
    paths: [backend/models/**]
  testing:
    level: subsystem
    paths: [tests/**]
  documentation:
    level: subsystem
    paths: [docs/**, '*.md']
  infrastructure:
    level: runtime
    paths: [infrastructure/**]
  runner:
    level: runtime
    paths: [runner/**]
  shared-contracts:
    level: subsystem
    paths: [shared/**]
architecture:
  rules:
    - id: function-size
      type: max_function_lines
      severity: info
      max: 1
coverage:
  required: false
  files: [reports/coverage.xml]
semantic:
  enabled: false
"""

_STATIC_FILES = {
    "frontend/features/catalog.js": (
        "import { request } from '../lib/client.js';\n\n"
        "export function loadCatalog() {\n  return request('/catalog');\n}\n"
    ),
    "frontend/features/checkout.js": (
        "import { request } from '../lib/client.js';\n\n"
        "export function submitOrder(order) {\n  return request('/orders', order);\n}\n"
    ),
    "frontend/lib/client.js": (
        "export function request(path, body = null) {\n  return { path, body };\n}\n"
    ),
    "frontend/shell/app.js": (
        "import { loadCatalog } from '../features/catalog.js';\n\n"
        "export function startApp() {\n  return loadCatalog();\n}\n"
    ),
    "backend/api/routes.py": (
        "from backend.services.catalog import list_catalog\n\n"
        "def get_catalog():\n    return list_catalog()\n"
    ),
    "backend/models/item.py": (
        "def item_record(name: str) -> dict[str, str]:\n    return {'name': name}\n"
    ),
    "runner/worker.py": (
        "from backend.services.orders import submit_order\n\n"
        "def run_order(order):\n    return submit_order(order)\n"
    ),
    "tests/test_catalog.py": (
        "from backend.services.catalog import list_catalog\n\n"
        "def test_catalog():\n    assert list_catalog()\n"
    ),
    "tests/test_orders.py": (
        "from backend.services.orders import submit_order\n\n"
        "def test_order():\n    assert submit_order({'id': 1})\n"
    ),
    "docs/architecture.md": "# Architecture\n\nFixture architecture contract.\n",
    "docs/feedback-log.md": "# Feedback log\n\nA reference record excluded from code triage.\n",
    "infrastructure/deploy.go": (
        'package infrastructure\n\nfunc Deploy() string {\n    return "ready"\n}\n'
    ),
    "shared/schema.json": '{"type": "object", "title": "Order"}\n',
}


def create_dashboard_repository(root: Path) -> Path:
    """Create a small, stable repo with every UI contract's required evidence."""

    root = root.expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"dashboard fixture target must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    _write(root, ".anaxigraph.yml", _CONFIG)
    for path, content in _STATIC_FILES.items():
        _write(root, path, content)
    for index in range(12):
        prior = ""
        if index:
            prior = f"from backend.services.service_{index - 1:02d} import operation\n\n"
        _write(
            root,
            f"backend/services/service_{index:02d}.py",
            (
                f'"""Contract fixture service {index}."""\n\n'
                f"{prior}"
                "def operation(value: int = 0) -> int:\n"
                f"    return value + {index + 1}\n"
            ),
        )
    _write(
        root,
        "backend/services/catalog.py",
        "from backend.models.item import item_record\n\n"
        "def list_catalog():\n    return [item_record('sample')]\n",
    )
    _write(
        root,
        "backend/services/orders.py",
        "def submit_order(order):\n    return {'accepted': bool(order)}\n",
    )
    _initialize_git(root)
    return root


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _initialize_git(root: Path) -> None:
    commands = (
        ("init", "-q"),
        ("config", "user.email", "dashboard-fixture@example.invalid"),
        ("config", "user.name", "AnaxiGraph Dashboard Fixture"),
        ("add", "."),
        ("commit", "-qm", "Create deterministic dashboard fixture"),
    )
    for command in commands:
        subprocess.run(["git", "-C", str(root), *command], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    root = create_dashboard_repository(args.target)
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
