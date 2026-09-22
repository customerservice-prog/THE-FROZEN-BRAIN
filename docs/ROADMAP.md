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

- [x] Multi-model registry and capability-aware router
- [x] Separate capability profiles for general/reasoning/coding/vision routing
- [x] Streaming generation
- [x] Conversation/session persistence
- [x] Tool registry with explicit permission gates
- [x] Isolated Python execution with timeout and workspace scope
- [x] Persistent projects and task work queue
- [x] Better lexical + optional embedding retrieval
- [x] Local knowledge source labels returned with answers
- [x] JSONL import/export of durable memory

## Phase 2 — Perception and voice

- [x] Local speech-to-text adapter
- [x] Local text-to-speech adapter
- [x] Local multimodal/vision adapter
- [x] Text/HTML/DOCX document ingestion + local image analysis\n- [ ] Image knowledge ingestion / visual indexing
- [x] Offline PDF extraction through archived pypdf or pdftotext
- [ ] Audio/video indexing pipeline

## Phase 3 — Continuity and agents

- [x] Structured belief/evidence graph
- [x] Prospective memory scheduler
- [x] Crash journal replay for post-checkpoint cognitive state
- [x] Crash-aware tool jobs with interrupted-state recovery and manual retry
- [x] Solver/critic/verifier orchestration
- [x] Multi-agent deliberation with independent attempts
- [ ] Automatic pre-shutdown checkpointing
- [ ] Signed checkpoint manifests

## Phase 4 — Cold-storage Ark

- [x] SHA-256 archive manifest generation and verification
- [x] Runtime/package artifact catalog + SHA-256 inventory
- [x] OS/driver/firmware artifact catalog + missing-category warnings
- [x] Automated archive integrity scanner
- [ ] Rebuild media generator
- [x] Human-readable archive index
- [x] Offline resurrection-test harness wired into CI

## Phase 5 — Survival hardware

- [ ] Linux workstation profile
- [ ] Mini-PC / laptop profile
- [ ] Android ARM survival runtime (Termux/llama.cpp launcher implemented; physical-device verification still required)
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
