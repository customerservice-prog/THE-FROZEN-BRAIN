# Android / Old-Phone Survival Runtime

This is the first deployable **phone survival profile** for THE FROZEN BRAIN.

It is intentionally not an app-store/cloud design. It runs the existing ColdVault core and a locally archived GGUF model directly on an Android phone through a Termux-style Linux userspace.

## What it does

- Uses the phone's own RAM to choose the largest GGUF that fits a conservative memory budget.
- Starts an archived ARM build of \`llama-server\` on \`127.0.0.1\`.
- Starts ColdVault on \`127.0.0.1:7777\`.
- Keeps identity, SQLite memory, cognitive state, prospective memory, knowledge, and checkpoints in \`$COLDVAULT_HOME\`.
- Uses CPU inference by default (\`-ngl 0\`) for maximum compatibility with older Android hardware.
- Makes **zero download/install requests**.
- Stops instead of falling back to the cloud when required local components are missing.

## Prepare while the outside world is available

Your physical ColdVault Ark should include, for every phone architecture you intend to support:

1. A verified Termux APK or equivalent local Linux userspace installer.
2. A compatible Python 3.11+ runtime and all packages needed to restore it offline.
3. An ARM/\`aarch64\` \`llama-server\` binary and its required shared libraries.
4. Several GGUF brains at different sizes/quantizations.
5. This repository and full Git history.
6. Your exported ColdVault state and critical knowledge subset.
7. Checksums for every artifact.
8. Printed/manual recovery instructions.

Do not assume F-Droid, GitHub, PyPI, Hugging Face, Google Play, DNS, or any other service will be available later.

## Suggested model ladder

Do not archive only one phone model. Keep several.

Example storage strategy:

- micro: roughly sub-1 GB GGUF for very weak devices
- survival: roughly 1–2 GB GGUF
- mobile: roughly 2–4 GB GGUF
- strong mobile: larger model for phones with substantially more RAM

The selector uses actual file size and measured RAM. It will refuse to select a model if none fit its conservative budget.

## Directory example

\`\`\`text
~/THE-FROZEN-BRAIN/
~/coldvault-models/
    micro.gguf
    survival.gguf
    mobile.gguf
~/.coldvault/
    coldvault.sqlite3
    checkpoints/
    knowledge/
    workspace/
\`\`\`

## Start

From the repository:

\`\`\`bash
bash survival/android-termux/start-coldvault.sh
\`\`\`

Then, on the same phone, open:

\`\`\`text
http://127.0.0.1:7777
\`\`\`

## Inspect selection without starting

\`\`\`bash
python -m coldvault.cli survival-select ~/coldvault-models
\`\`\`

For testing a hypothetical RAM level:

\`\`\`bash
python -m coldvault.cli survival-select ~/coldvault-models --memory-gb 4
\`\`\`

## Important limitation

A tiny phone does **not** magically gain server-class reasoning power. In standalone mode it runs the best local model that safely fits.

The continuity architecture is what survives: identity, memories, projects, beliefs/evidence, future commitments, local knowledge, and unfinished work remain portable. When stronger local hardware becomes available again, the same durable state can be opened by a stronger brain.

## Before calling a phone "survival ready"

Physically disable WAN/cellular access and prove all of these:

- Termux/userspace installs from your archived APK.
- Python starts from archived packages.
- \`llama-server\` starts without package downloads.
- A GGUF is selected and answers locally.
- ColdVault UI opens locally.
- Memory survives a restart.
- A checkpoint restores.
- A post-checkpoint state change is replayed.
- The critical knowledge library is searchable.
- No DNS or external host is required.

A real physical-device test is required before this roadmap item can be called fully complete.
