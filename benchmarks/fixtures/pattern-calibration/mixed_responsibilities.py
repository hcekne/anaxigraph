"""A low-cohesion module mixing persistence, tax, email, and HTML behavior."""

import json
from decimal import Decimal
from pathlib import Path


def load_customer(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def calculate_tax(amount: Decimal, region: str) -> Decimal:
    rates = {"north": Decimal("0.20"), "south": Decimal("0.15")}
    return amount * rates[region]


def render_invoice(customer: dict, total: Decimal) -> str:
    return f"<h1>{customer['name']}</h1><strong>{total}</strong>"


def email_invoice(address: str, html: str) -> dict:
    return {"recipient": address, "body": html, "transport": "smtp"}


def append_audit(path: Path, event: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")
