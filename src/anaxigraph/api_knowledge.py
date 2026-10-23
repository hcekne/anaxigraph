"""REST access to the authoritative semantic property graph."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from anaxigraph.knowledge_detail import entity_detail, neighborhood
from anaxigraph.knowledge_query import entity_page
from anaxigraph.knowledge_subjects import (
    graph_subjects,
    load_subject,
    subject_detail,
    subject_neighborhood,
    subject_page,
)
from anaxigraph.knowledge_sync import GraphCacheBusyError


class KnowledgeRoutes:
    def __init__(self, database, selected_repository):
        self.database, self.selected_repository = database, selected_repository
        self.router = APIRouter()
        self.router.add_api_route("/api/graph/entities", self.entities, methods=["GET"])
        self.router.add_api_route("/api/graph/subjects", self.subjects, methods=["GET"])
        self.router.add_api_route("/api/graph/entity", self.entity, methods=["GET"])
        self.router.add_api_route("/api/graph/neighborhood", self.neighbors, methods=["GET"])

    def entities(
        self,
        repository_id: int | None = None,
        snapshot_id: int | None = None,
        kind: str = "",
        scope: str = "",
        q: str = Query(default="", max_length=2000),
        sort: str = "path",
        direction: str = "asc",
        area: str = "",
        subsystem: str = "",
        language: str = "",
        map_layer: str = "current",
        graph_subject: str = "observed",
        graph_kind: str = "",
        evidence_state: str = "",
        include_reference: bool = False,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        repository = self.selected_repository(repository_id)
        filters = {
            "kind": kind,
            "scope": scope,
            "q": q,
            "sort": sort,
            "direction": direction,
            "area": area,
            "subsystem": subsystem,
            "language": language,
            "map_layer": map_layer,
            "include_reference": include_reference,
            "evidence_state": evidence_state,
            "offset": offset,
            "limit": limit,
        }
        try:
            if graph_subject != "observed":
                graph = load_subject(
                    self.database, int(repository["id"]), graph_subject, snapshot_id, graph_kind
                )
                return subject_page(graph, **filters)
            _require_observed(graph_kind)
            return entity_page(self.database, int(repository["id"]), snapshot_id, **filters)
        except GraphCacheBusyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def entity(
        self,
        entity_id: str = Query(min_length=1, max_length=2000),
        repository_id: int | None = None,
        snapshot_id: int | None = None,
        graph_subject: str = "observed",
        graph_kind: str = "",
        legacy_offset: int = Query(default=0, ge=0),
        legacy_limit: int = Query(default=25, ge=1, le=100),
    ):
        repository = self.selected_repository(repository_id)
        try:
            if graph_subject != "observed":
                return subject_detail(
                    load_subject(
                        self.database, int(repository["id"]), graph_subject, snapshot_id, graph_kind
                    ),
                    entity_id,
                )
            _require_observed(graph_kind)
            return entity_detail(
                self.database,
                int(repository["id"]),
                entity_id,
                snapshot_id,
                legacy_offset=legacy_offset,
                legacy_limit=legacy_limit,
            )
        except GraphCacheBusyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def neighbors(
        self,
        entity_id: str = Query(min_length=1, max_length=2000),
        repository_id: int | None = None,
        snapshot_id: int | None = None,
        direction: str = "both",
        depth: int = Query(default=1, ge=1, le=3),
        relationship_type: str = "",
        limit: int = Query(default=100, ge=1, le=500),
        graph_subject: str = "observed",
        graph_kind: str = "",
        evidence_state: str = "",
    ):
        repository = self.selected_repository(repository_id)
        try:
            if graph_subject != "observed":
                graph = load_subject(
                    self.database, int(repository["id"]), graph_subject, snapshot_id, graph_kind
                )
                return subject_neighborhood(
                    graph,
                    entity_id,
                    direction=direction,
                    depth=depth,
                    relationship_type=relationship_type,
                    limit=limit,
                    evidence_state=evidence_state,
                )
            _require_observed(graph_kind)
            return neighborhood(
                self.database,
                int(repository["id"]),
                entity_id,
                snapshot_id,
                direction=direction,
                depth=depth,
                relationship_type=relationship_type,
                limit=limit,
                evidence_state=evidence_state,
            )
        except GraphCacheBusyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def subjects(self, repository_id: int | None = None, snapshot_id: int | None = None):
        repository = self.selected_repository(repository_id)
        try:
            return graph_subjects(self.database, int(repository["id"]), snapshot_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_observed(kind):
    if kind not in {"", "observed"}:
        raise ValueError("Select a saved graph subject for this graph kind")
