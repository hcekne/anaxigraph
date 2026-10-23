"""Bounded cold-result compression; current semantic records remain readable JSONL."""

from __future__ import annotations

import lzma
from typing import Any

from anaxigraph.semantic_payload import modern_semantic_value

MAX_DECODED_BYTES = 100_000_000
MAX_DECODED_PART = 4_000_000
MAX_LEGACY_PART = 16_000_000


def document_codec(table: str, row: Any) -> str:
    if table == "legacy_records":
        return "xz"
    if table != "semantic_documents":
        return "jsonl"
    record = row["value"]
    value = record.get("value_json") or {}
    return "jsonl" if modern_semantic_value(record.get("document_kind", ""), value) else "xz"


def partition_tables(tables: Any) -> dict[str, Any]:
    documents = tables.get("semantic_documents", [])
    legacy = {row["key"] for row in documents if document_codec("semantic_documents", row) == "xz"}
    if not legacy:
        return tables
    all_legacy = len(legacy) == len(documents)
    hashes = {row["value"].get("input_hash") for row in documents if row["key"] in legacy}
    result: dict[str, list[Any]] = {"legacy_records": []}
    for table, rows in tables.items():
        for row in rows:
            if all_legacy or _cold_checkpoint(table, row, legacy, hashes):
                result["legacy_records"].append({"table": table, **row})
            else:
                result.setdefault(table, []).append(row)
    return result


def _cold_checkpoint(table, row, legacy, hashes):
    if table == "semantic_documents":
        return row["key"] in legacy
    value = row["value"]
    if table == "semantic_jobs":
        return value.get("input_hash") in hashes
    if table != "semantic_scope_states":
        return False
    references = [value.get(field) for field in ("intrinsic_document_id", "context_document_id")]
    links = {item["$ref"] for item in references if isinstance(item, dict) and "$ref" in item}
    return bool(links) and links <= legacy


def partition_identity(table: str, row: Any) -> str:
    if table != "legacy_records":
        return row["key"]
    value = row["value"]
    kind = row["table"]
    scope = value.get("scope_type")
    if scope == "taxonomy" or kind.startswith("semantic_taxonom"):
        return "@taxonomy"
    if scope in {"pattern", "pattern_plan", "fresh_eyes"}:
        return "@" + ("patterns" if scope.startswith("pattern") else "fresh_eyes")
    return str(value.get("scope_key") or value.get("path") or row["key"])


def encode_partition(content: bytes, codec: str) -> bytes:
    return lzma.compress(content, preset=7 | lzma.PRESET_EXTREME) if codec == "xz" else content


def decode_partition(content: bytes, part: Any) -> bytes:
    codec = part.get("codec", part.get("encoding", "jsonl"))
    if codec == "jsonl":
        return content
    if codec != "xz":
        raise ValueError("Unsupported portable partition codec; update AnaxiGraph")
    size = part.get("decoded_bytes", part.get("uncompressed_bytes"))
    limit = (
        MAX_LEGACY_PART if part.get("table") in {"mixed", "legacy_records"} else MAX_DECODED_PART
    )
    if not isinstance(size, int) or not 0 <= size <= limit:
        raise ValueError("Invalid decoded portable partition size")
    decoder = lzma.LZMADecompressor(memlimit=64_000_000)
    try:
        value = decoder.decompress(content, max_length=size + 1)
    except lzma.LZMAError as error:
        raise ValueError("Invalid compressed portable partition") from error
    if len(value) != size or not decoder.eof or decoder.unused_data:
        raise ValueError("Compressed portable partition exceeds its declared size")
    return value
