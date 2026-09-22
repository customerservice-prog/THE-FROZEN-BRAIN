# Security Model

ColdVault is designed for high local trust but low implicit authority.

## Rules

1. Model output is untrusted input to tools.
2. Workspace access is path-contained.
3. Writes are disabled by default in the initial tool policy.
4. Real-host administrative operations must never be granted merely because a model asks for them.
5. Destructive actions need explicit policy and audit events.
6. Sandboxes should receive broader authority than the physical host.
7. Model/provider traffic should target loopback or an explicitly trusted offline LAN endpoint.
8. A software "offline" toggle is not an air gap. Enforce isolation with firewall/network design or physical disconnection.
9. Backups and recovery media need separate access controls from the live AI process.
10. Memory imports must preserve source/provenance and should never automatically become unquestioned fact.

## Threats to plan for

- Prompt injection from stored documents.
- Malicious model files or inference runtimes.
- Dependency compromise before archival.
- Memory poisoning.
- Tool path traversal.
- Accidental or model-directed backup deletion.
- LAN exposure without authentication.
- Corrupted checkpoints.
- Storage bit rot.
- A compromised upgrade replacing the trusted model/runtime.

The project should choose boring, auditable mechanisms over magical autonomy whenever the two conflict.
