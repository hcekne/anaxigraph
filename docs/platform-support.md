# Platform support

This matrix describes what the project verifies today, not every environment in which the pure
Python code might happen to run. Docker means Linux containers through Docker Desktop or Docker
Engine; “local CLI” means a host Python 3.11/3.12 installation managed with `uv`.

| Host / execution path | Status | What is covered |
|---|---|---|
| Linux x86-64 · Docker | **Supported** | Primary CI, Compose validation, hardened container, dashboard/MCP, Python 3.11/3.12, Chromium contracts |
| Linux x86-64 · local CLI | **Supported** | `up` process startup/health/clean SIGINT, external user state, scan, history, serve, MCP, semantic workers, hooks and tests |
| Linux ARM64 · Docker | **Best effort** | A `linux/arm64` image is built with the same Dockerfile and published in the multi-architecture manifest; no native ARM runtime runner yet |
| Linux ARM64 · local CLI | **Best effort** | The pinned Tree-sitter binding and JavaScript/TypeScript grammars publish ARM64 wheels, but CI does not execute the CLI on native ARM |
| macOS Apple silicon · Docker Desktop | **Best effort; recommended macOS path** | Uses the `linux/arm64` image and read-only bind mounts; no macOS end-to-end CI runner yet |
| macOS Intel · Docker Desktop | **Best effort; recommended macOS path** | Uses the `linux/amd64` image; no macOS end-to-end CI runner yet |
| macOS · local CLI | **Best effort** | Wheel/sdist install, all pinned parser grammars, packaged dashboard assets, initialization, and CLI startup are release-gated on Python 3.11/3.12; host serving, watching, and browser behavior are not yet end-to-end gated |
| WSL2 · Docker or local CLI | **Best effort** | Use a WSL2 Linux distribution and Linux containers. Keep repositories in the WSL filesystem for usable Git/scan performance |
| Native Windows PowerShell/CMD | **Not supported yet** | Native path, process/signal, watcher, hook, and Windows-container behavior is not tested. Use WSL2 instead |
| Windows containers | **Out of scope** | The shipped image and Compose definitions target Linux containers |

“Best effort” means issues and focused fixes are welcome, but a release is not blocked on that row
until a native CI job and clean-machine smoke test exist. It does not mean the environment is known
to be broken. “Not supported” means maintainers will not claim or debug parity without first adding
the missing platform contract.

## Browser and remote-host notes

The dashboard's automated interaction contracts run in Chromium. Current Safari and Firefox are
best effort. The server binds to `127.0.0.1` by default, so a browser on another machine should use
an SSH port forward. Codex or another MCP client running on the server connects directly to the
server's loopback URL; it does not traverse the browser tunnel.

## Filesystems and mounts

- The target repository must be a normal Git working tree readable by the AnaxiGraph process.
- Docker sidecars mount target repositories read-only and keep AnaxiIndex in a named volume.
- On WSL2, prefer paths under the Linux home/workspace filesystem over `/mnt/c` for Git and scan
  throughput.
- Case-only filename conflicts can behave differently across default macOS/Windows filesystems;
  the tracked quality hooks reject case-conflicting paths before they become cross-platform bugs.

The roadmap promotes a best-effort row to supported only after its fresh-machine install, scan,
dashboard, MCP, update, and cleanup paths run in CI or an equivalent release gate.
