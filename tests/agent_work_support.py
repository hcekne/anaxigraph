"""Shared assertions for agent-funded semantic work packets."""

from __future__ import annotations


def _charter_task(packet: dict) -> bool:
    """Report whether this packet is the repository Charter task, checking its contract."""

    request = packet["analysis_request"]
    if request.get("scope_type") != "repository":
        return False
    if not str(request.get("analysis_kind")).startswith("synthesis"):
        return False
    assert packet["response_contract"]["artifact"] == "architecture_charter"
    assert "capability_brief" in packet["response_contract"]["required_fields"]
    return True


def _assert_evidence_pages_readable(engine, repository_id, repository, config, packet) -> None:
    """Read every evidence page a packet advertises, so paging stays exercised."""

    manifest = packet["evidence_manifest"]
    if not manifest:
        return
    pages = [
        engine.agent_evidence_page(
            repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            page=page,
        )
        for page in range(1, manifest["page_count"] + 1)
    ]
    assert all(item["status"] == "evidence" for item in pages)
