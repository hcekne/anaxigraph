"""Progressive semantic graph navigation for coding agents, without source reads."""

from anaxigraph.knowledge_detail import entity_detail, neighborhood
from anaxigraph.knowledge_query import entity_page
from anaxigraph.knowledge_subjects import (
    graph_subjects,
    load_subject,
    subject_detail,
    subject_neighborhood,
    subject_page,
)


def register_knowledge_tools(server, context):
    tools = KnowledgeMcpTools(context)
    server.add_tool(
        tools.graph,
        name="ANAXIGRAPH_GRAPH",
        description="Search the complete saved semantic graph by behavior/name; page compact module/function/interface/contract sentences, or expand one entity's typed callers, dependencies and tests. All reads are qualified by repository and saved revision.",
    )
    server.add_tool(
        tools.entity,
        name="ANAXIGRAPH_ENTITY",
        description="Inspect one graph entity by its stable ID: saved paragraph, functions, interfaces, full contract obligations, typed connections, tests and provenance. Works without source access or model calls. Omission counts and expansion limits are explicit.",
    )


class KnowledgeMcpTools:
    def __init__(self, context):
        self.context = context

    def graph(
        self,
        repository: str = "",
        query: str = "",
        kind: str = "module",
        entity_id: str = "",
        snapshot_id: int | None = None,
        direction: str = "both",
        depth: int = 1,
        limit: int = 20,
        offset: int = 0,
        graph_subject: str = "observed",
        list_subjects: bool = False,
        evidence_state: str = "",
    ) -> dict:
        row, _root = self.context.select(repository)
        if list_subjects:
            return graph_subjects(self.context.database, row["id"], snapshot_id)
        if graph_subject != "observed":
            graph = load_subject(self.context.database, row["id"], graph_subject, snapshot_id)
            return _subject_read(
                graph, entity_id, query, kind, direction, depth, limit, offset, evidence_state
            )
        if entity_id:
            return neighborhood(
                self.context.database,
                row["id"],
                entity_id,
                snapshot_id,
                direction=direction,
                depth=depth,
                limit=min(100, max(1, limit)),
                evidence_state=evidence_state,
            )
        return entity_page(
            self.context.database,
            row["id"],
            snapshot_id,
            q=query,
            kind=kind,
            limit=min(100, max(1, limit)),
            offset=offset,
            evidence_state=evidence_state,
        )

    def entity(
        self,
        entity_id: str,
        repository: str = "",
        snapshot_id: int | None = None,
        graph_subject: str = "observed",
        legacy_offset: int = 0,
        legacy_limit: int = 25,
    ) -> dict:
        row, _root = self.context.select(repository)
        if graph_subject != "observed":
            return subject_detail(
                load_subject(self.context.database, row["id"], graph_subject, snapshot_id),
                entity_id,
            )
        return entity_detail(
            self.context.database,
            row["id"],
            entity_id,
            snapshot_id,
            legacy_offset=max(0, legacy_offset),
            legacy_limit=min(100, max(1, legacy_limit)),
        )


def _subject_read(graph, identifier, query, kind, direction, depth, limit, offset, evidence_state):
    if identifier:
        return subject_neighborhood(
            graph,
            identifier,
            direction=direction,
            depth=depth,
            limit=limit,
            evidence_state=evidence_state,
        )
    return subject_page(
        graph, q=query, kind=kind, limit=limit, offset=offset, evidence_state=evidence_state
    )
