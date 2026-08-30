# ADR 0004: Keep model credentials outside AnaxiGraph

- Status: Accepted
- Date: 30 August 2026
- Owners: AnaxiGraph maintainers

## Context

AnaxiGraph had two competing semantic products. Its primary workflow prepared evidence for the
coding agent already working in the repository, while optional OpenAI/Anthropic HTTP clients and a
periodic container worker made AnaxiGraph host a second model runtime and its credentials. The
second path duplicated authentication, scheduling, transport errors, provider schemas, operations,
and documentation without improving the shared AnaxiIndex or semantic contracts.

## Decision

AnaxiGraph owns deterministic extraction, bounded semantic work packets, validation, leases,
provenance, and durable write-back. Model execution belongs to the user's authenticated coding
agent:

- a connected agent processes bounded work through AnaxiMCP; or
- `anaxigraph understand --executor codex|claude --background` drives the same queue durably with
  the host's existing authenticated CLI.

An advanced JSON-over-stdin command adapter remains for operator-owned local runtimes. AnaxiGraph
does not accept OpenAI or Anthropic API-key provider policies, ship their HTTP clients, or create an
`ai` Compose profile. `semantic.refresh` supports `manual`, `on_scan`, and `watch`; the redundant
periodic semantic worker command is removed.

## Consequences

- AnaxiGraph stores no model credential and has one semantic queue, validation path, and provenance
  model for both humans and agents.
- Codex, Claude, and future coding agents choose their own supported model and account boundary.
- Existing `provider: openai|anthropic` or `refresh: periodic` policies must migrate to
  `provider: agent`, then use the connected-agent or durable host-executor workflow.
- Removing a hosted provider does not remove saved dossiers; provider/model provenance remains in
  AnaxiIndex and historical records remain readable.
- Adding another hosted API client would reverse this decision and requires a new ADR with evidence
  that it advances the core shared-architecture-intelligence workflow.
