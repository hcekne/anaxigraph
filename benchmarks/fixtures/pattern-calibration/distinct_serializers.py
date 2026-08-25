"""Superficially similar serializers with intentionally incompatible contracts."""

import json


def public_response(record: dict) -> str:
    """Return stable client JSON while removing internal fields."""

    visible = {key: value for key, value in record.items() if not key.startswith("_")}
    return json.dumps(visible, sort_keys=True)


def audit_record(record: dict) -> str:
    """Retain every internal field and preserve insertion order for forensic replay."""

    return json.dumps(record, sort_keys=False, separators=(",", ":"))
