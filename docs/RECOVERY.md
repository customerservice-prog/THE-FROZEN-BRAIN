# Offline Recovery / Resurrection Procedure

The final ColdVault acceptance test is a rebuild with WAN disconnected. v0.1 establishes the software-state portion of that process.

## Archive before disconnecting

Keep verified offline copies of:

1. This repository and full Git history.
2. A supported Python 3.11+ installer/runtime for every target platform.
3. The chosen local inference runtime and its dependencies.
4. Model weights and tokenizer/config files.
5. `COLDVAULT_HOME` including SQLite database, checkpoints, workspace, and knowledge sources.
6. Operating-system installers, drivers, firmware, and hardware documentation.
7. Package/install artifacts needed by future optional modules.
8. SHA-256 manifest for all archive payloads.

## Restore the core

```bash
# With no Internet connection
python -m venv .venv
# Activation command varies by OS.
# This core has no runtime PyPI dependencies.
python -m unittest discover -s tests -v
python scripts/smoke_test.py
```

You may also install the project from the local source archive if local build tooling is already archived:

```bash
python -m pip install --no-index --no-deps .
```

## Restore durable state

Place the recovered data directory at the desired path and set:

```bash
export COLDVAULT_HOME=/path/to/recovered/coldvault-data
```

ColdVault verifies the SHA-256 digest on the latest cognitive checkpoint stored in SQLite before restoring it.

## Restore the brain

Start an archived local inference server and configure its OpenAI-compatible endpoint:

```bash
export COLDVAULT_BASE_URL=http://127.0.0.1:11434/v1
export COLDVAULT_MODEL=<installed-local-model-name>
```

The endpoint and model name are intentionally configurable so the durable system is not tied to one inference runtime.

## Start the interface

```bash
python -m coldvault.cli serve --host 127.0.0.1 --port 7777
```

Open `http://127.0.0.1:7777` on the local machine.

For an offline LAN, bind to the machine's LAN interface only after configuring host firewall rules and local authentication.

## Recovery checks

A valid recovery should demonstrate all of the following without WAN access:

- UI and CLI start.
- SQLite database opens in WAL mode.
- Latest valid cognitive state restores.
- Explicit memories are searchable.
- Local knowledge is searchable.
- A new checkpoint can be written and verified.
- A local model answers through the provider adapter.
- Restart preserves the same durable state.

## Never rely on GitHub as the cold archive

GitHub is the development source. The survivable archive must include verified local copies of the repository, models, runtimes, operating systems, and state.
