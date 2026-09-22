# Roadmap

## Phase 0 — Working core (current)

- [x] SQLite WAL event journal
- [x] Explicit durable memory with provenance/confidence
- [x] Cognitive state and SHA-256 checkpoints
- [x] Text knowledge ingestion and local retrieval
- [x] Local OpenAI-compatible model adapter
- [x] Permission-scoped workspace file tools
- [x] CLI
- [x] Dependency-light local browser UI
- [x] Offline smoke tests

## Phase 1 — Real local assistant

- [ ] Multi-model registry and capability-aware router
- [ ] Separate fast/reasoning/coding/vision profiles
- [ ] Streaming generation
- [ ] Conversation/session persistence
- [ ] Tool-call protocol with explicit permission gates
- [ ] Sandboxed Python/code execution
- [ ] Project workspaces and task graph
- [ ] Better lexical + optional embedding retrieval
- [ ] Source citations in answers
- [ ] Import/export of durable memory in open formats

## Phase 2 — Perception and voice

- [ ] Local speech-to-text adapter
- [ ] Local text-to-speech adapter
- [ ] Local multimodal/vision adapter
- [ ] Image/document ingestion
- [ ] Offline PDF extraction
- [ ] Audio/video indexing pipeline

## Phase 3 — Continuity and agents

- [ ] Structured belief/evidence graph
- [ ] Prospective memory scheduler
- [ ] Crash journal replay
- [ ] Resumable tool jobs
- [ ] Solver/critic/verifier orchestration
- [ ] Multi-agent deliberation with independent attempts
- [ ] Automatic pre-shutdown checkpointing
- [ ] Signed checkpoint manifests

## Phase 4 — Cold-storage Ark

- [ ] Model manifest with SHA-256/BLAKE3 verification
- [ ] Runtime/package archive manifests
- [ ] Offline OS/driver/firmware catalog
- [ ] Automated archive integrity scanner
- [ ] Rebuild media generator
- [ ] Human-readable archive index
- [ ] Periodic resurrection-test harness

## Phase 5 — Survival hardware

- [ ] Linux workstation profile
- [ ] Mini-PC / laptop profile
- [ ] Android ARM survival runtime
- [ ] Phone-local memory and critical-library subset
- [ ] Automatic LAN server discovery without Internet
- [ ] Automatic downgrade to on-device model when server is unavailable
- [ ] Offline LAN appliance image

## Phase 6 — Evaluation and improvement lab

- [ ] Permanent capability benchmark suite
- [ ] Model A/B harness
- [ ] Coding execution benchmarks
- [ ] Hallucination/provenance benchmarks
- [ ] Memory continuity benchmarks
- [ ] Hardware performance/energy benchmarks
- [ ] Safe model upgrade/quarantine pipeline
- [ ] Fine-tuning and training-tool archive
