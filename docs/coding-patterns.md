# Coding patterns

This document is the canonical human-readable architecture policy for AnaxiGraph. The
machine-readable thresholds are in [`.anaxigraph.yml`](../.anaxigraph.yml).

Prefer pure functions for hashing, normalization, rule evaluation, and graph transforms. Use
classes only where identity or lifecycle is real: the database handle, analyzer registry, scanner,
and external provider. Keep filesystem, Git, subprocess, database, and network effects behind
their existing modules.

Language analyzers produce neutral records and never persist. Persistence does not import API or
dashboard code. Interfaces call application services; they do not duplicate graph logic. A new
adapter must remove provider conditionals from the scanner rather than add a second analysis path.

Treat 40 logical lines per function and 500 source LOC per module as inspection signals. Prefer a
cohesive module over forwarding layers. Add an abstraction only for multiple real implementations
or a demonstrated bug class. Avoid hidden global state and circular dependencies. Changed behavior
requires focused tests; MCP behavior requires a real SDK protocol test.

The analyzed repository is untrusted input. Never import or execute it, follow its symlinks, write
analysis state into it by default, or interpolate its values into a shell. Refactoring findings are
recommendations requiring human approval; the product never mutates target code.
