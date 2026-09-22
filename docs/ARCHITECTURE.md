# Architecture

THE FROZEN BRAIN is intentionally split into replaceable layers.

## 1. Frozen Brain
Model weights are interchangeable. The first provider speaks the OpenAI-compatible local HTTP protocol so a local runtime such as Ollama, llama.cpp server, vLLM, or another compatible engine can be attached without changing durable state.

## 2. Ignition
The inference runtime, model loader, tokenizer, drivers, and compatible system packages are archived outside Git. Git stores the orchestration source; the ColdVault archive stores the heavy artifacts and their hashes.

## 3. Active Cognition
Temporary model inference is treated as ephemeral. ColdVault does not pretend temporary activations are durable memory.

## 4. Continuity Engine
The continuity layer stores explicit cognitive state: active project, objective, subgoals, known facts, hypotheses, uncertainties, next action, pending actions, relevant files, and commitments.

## 5. Durable Memory
SQLite stores explicit episodic, semantic, procedural, prospective, preference, and relationship memories. Every memory can carry source and confidence metadata.

## 6. Knowledge
Source files remain authoritative. The current v0.1 index is deliberately simple lexical retrieval so the core has no third-party dependency. A future embedding index is an acceleration layer, never the only copy of knowledge.

## 7. World and Tools
A dedicated workspace root prevents path traversal. Read/write permissions are explicit. Future shell, VM, browser, and physical-device tools must pass through the same permission model.

## 8. Identity
Identity and operating principles live outside model weights. Replacing a model therefore does not erase the system's purpose or durable state.

## 9. Hardware scaling
The orchestration layer is model-agnostic. A server can use a large model; a laptop can use a smaller model; a phone survival build can use a compact model while reading the same exported identity, memory, project state, and knowledge subset.

## 10. Trust boundary
Broad authority belongs inside disposable sandboxes. Real-host writes, backup changes, hardware control, and other destructive capabilities should require stronger permission gates.

## Current v0.1 data flow

```text
Browser / CLI
      |
      v
 ColdVault Core
   |    |     \
   |    |      -> Continuity Engine -> checkpoints
   |    -> Memory Store ------------> SQLite WAL
   -> Knowledge Store --------------> SQLite + source files
      |
      v
Local OpenAI-compatible endpoint
      |
      v
Replaceable model weights
```

## What v0.1 deliberately does not claim

- It is not a frontier model.
- It does not ship model weights.
- It does not preserve every neural activation.
- It does not yet autonomously execute model-generated tool calls.
- It does not yet ingest PDFs, images, audio, or video without optional adapters.
- It is not yet the Android survival build.

Those are roadmap items, not simulated features.
