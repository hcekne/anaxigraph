"""Matched source states and known contracts for maintenance acceptance."""

STATES = ("baseline", "frontend_only", "stable_provider", "contract_broken", "contract_migrated")
PROVIDER_CONTRACT = (
    "Reject blank prompts; return a stripped uppercase reply; perform no file writes."
)


def fixture(state):
    enveloped = state.startswith("contract_")
    result = '{"text": reply}' if enveloped else "reply"
    reply = (
        '"".join(char.upper() for char in prompt.strip())'
        if state == "stable_provider"
        else "prompt.strip().upper()"
    )
    files = {
        "providers/__init__.py": "",
        "backend/__init__.py": "",
        "frontend/__init__.py": "",
        "shared/__init__.py": "",
        "providers/alpha.py": (
            '"""Own the uppercase agent execution behavior behind its public contract."""\n'
            'def execute(prompt):\n    """Reject blank input and return the uppercase reply."""\n'
            '    if not prompt.strip(): raise ValueError("blank prompt")\n'
            f"    reply = {reply}\n    return {result}\n"
            'def health():\n    """Report provider health independently of execution."""\n    return "ok"\n'
        ),
        "backend/orchestrator.py": (
            '"""Deliver replies through the provider execution contract."""\n'
            "from providers.alpha import execute\n"
            'def respond(prompt):\n    """Return the caller-visible reply text."""\n'
            + (
                '    return execute(prompt)["text"]\n'
                if state == "contract_migrated"
                else "    return execute(prompt)\n"
            )
        ),
        "backend/health.py": "from providers.alpha import health\ndef provider_status(): return health()\n",
        "backend/api.py": (
            "from backend.orchestrator import respond\n"
            'def request_message(prompt):\n    """Return the public reply text."""\n    return respond(prompt)\n'
        ),
        "frontend/view.py": (
            '"""Render a reply without changing its backend contract."""\n'
            "from backend.api import request_message\n"
            "def render(prompt):\n"
            + (
                '    return "<section>" + request_message(prompt) + "</section>"\n'
                if state == "frontend_only"
                else '    return "<p>" + request_message(prompt) + "</p>"\n'
            )
        ),
        "shared/text.py": (
            '"""Normalize whitespace through one pure cohesive utility contract."""\n'
            'def normalize(text):\n    """Strip surrounding whitespace without side effects."""\n    return text.strip()\n'
        ),
        "backend/hub.py": (
            '"""Combine billing formatting, authorization and mutable audit storage."""\n'
            "events = []\n"
            'def invoice(total):\n    """Format a billing amount."""\n    return f"invoice:{total}"\n'
            'def authorize(role):\n    """Decide whether a role may administer the system."""\n    return role == "admin"\n'
            'def audit(event):\n    """Append an event to shared mutable audit state."""\n    events.append(event)\n    return len(events)\n'
        ),
        "tests/test_provider.py": (
            "from providers.alpha import execute, health\n"
            "def test_reply():\n"
            + (
                '    assert execute(" hi ") == {"text": "HI"}\n'
                if state == "contract_migrated"
                else '    assert execute(" hi ") == "HI"\n'
            )
            + 'def test_blank():\n    try: execute(" ")\n    except ValueError: return\n    raise AssertionError("blank prompt accepted")\n'
            + 'def test_health(): assert health() == "ok"\n'
        ),
        "tests/test_view.py": (
            "from frontend.view import render\n"
            + (
                'def test_presentation(): assert render(" hi ") == "<section>HI</section>"\n'
                if state == "frontend_only"
                else 'def test_presentation(): assert render(" hi ") == "<p>HI</p>"\n'
            )
        ),
        "tests/test_api.py": 'from backend.api import request_message\ndef test_api(): assert request_message(" hi ") == "HI"\n',
    }
    for index in range(24):
        files[f"clients/utility_{index}.py"] = (
            f"from shared.text import normalize\ndef run_{index}(text): return normalize(text)\n"
        )
        operation = ("invoice", "authorize", "audit")[index % 3]
        files[f"clients/hub_{index}.py"] = (
            f"from backend.hub import {operation}\ndef run_{index}(value): return {operation}(value)\n"
        )
    return files
