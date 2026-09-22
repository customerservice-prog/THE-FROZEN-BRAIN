from __future__ import annotations

import argparse
import json
from pathlib import Path

from .archive import build_manifest, verify_manifest
from .ark import build_ark_catalog, verify_ark
from .core import ColdVault
from .portability import export_memories, import_memories
from .server import serve
from .survival import select_survival_model


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="coldvault", description="THE FROZEN BRAIN local-first AI continuity system")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    sub.add_parser("db-check")
    sub.add_parser("models")
    sub.add_parser("tools")
    sub.add_parser("jobs")

    job_retry = sub.add_parser("job-retry")
    job_retry.add_argument("id")

    job_cancel = sub.add_parser("job-cancel")
    job_cancel.add_argument("id")
    sub.add_parser("conversations")
    sub.add_parser("projects")
    sub.add_parser("beliefs")
    sub.add_parser("reminders")

    remind = sub.add_parser("remind")
    remind.add_argument("content")
    remind.add_argument("--due", required=True, help="ISO-8601 timestamp; naive values are treated as UTC")
    remind.add_argument("--source", default="user")

    reminder_done = sub.add_parser("reminder-done")
    reminder_done.add_argument("id")

    reminder_cancel = sub.add_parser("reminder-cancel")
    reminder_cancel.add_argument("id")

    belief_add = sub.add_parser("belief-add")
    belief_add.add_argument("claim")
    belief_add.add_argument("--classification", default="hypothesis")
    belief_add.add_argument("--confidence", type=float, default=0.5)
    belief_add.add_argument("--source", default="user")

    belief_search = sub.add_parser("belief-search")
    belief_search.add_argument("query")
    belief_search.add_argument("--limit", type=int, default=8)

    evidence_add = sub.add_parser("evidence-add")
    evidence_add.add_argument("belief_id")
    evidence_add.add_argument("content")
    evidence_add.add_argument("--kind", choices=["supports", "contradicts", "context"], default="supports")
    evidence_add.add_argument("--source", default="user")
    evidence_add.add_argument("--confidence", type=float, default=1.0)

    chat = sub.add_parser("chat")
    chat.add_argument("message", nargs="+")
    chat.add_argument("--session", default="default")

    think = sub.add_parser("think")
    think.add_argument("message", nargs="+")
    think.add_argument("--session", default="default")
    think.add_argument("--attempts", type=int, default=2, choices=[2, 3, 4])

    new_chat = sub.add_parser("new-conversation")
    new_chat.add_argument("--title", default="New conversation")

    remember = sub.add_parser("remember")
    remember.add_argument("content")
    remember.add_argument("--kind", default="semantic")
    remember.add_argument("--source", default="user")
    remember.add_argument("--confidence", type=float, default=1.0)
    remember.add_argument("--tag", action="append", default=[])

    search = sub.add_parser("memory-search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=8)

    mem_export = sub.add_parser("memory-export")
    mem_export.add_argument("path")

    mem_import = sub.add_parser("memory-import")
    mem_import.add_argument("path")

    sub.add_parser("knowledge-reindex")

    transcribe = sub.add_parser("transcribe")
    transcribe.add_argument("path")

    speak = sub.add_parser("speak")
    speak.add_argument("text")
    speak.add_argument("--output", default="coldvault-speech.wav")

    vision = sub.add_parser("vision")
    vision.add_argument("path")
    vision.add_argument("prompt", nargs="*", default=[])
    vision.add_argument("--session", default="default")

    ingest = sub.add_parser("ingest")
    ingest.add_argument("path")
    ingest.add_argument("--logical-path")

    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("--reason", default="manual")

    state = sub.add_parser("state")
    state.add_argument("--objective")
    state.add_argument("--project")
    state.add_argument("--next-action")

    task_add = sub.add_parser("task-add")
    task_add.add_argument("project")
    task_add.add_argument("title")
    task_add.add_argument("--details", default="")

    tasks = sub.add_parser("tasks")
    tasks.add_argument("project")

    task_status = sub.add_parser("task-status")
    task_status.add_argument("task_id")
    task_status.add_argument("status", choices=["todo", "doing", "blocked", "done", "cancelled"])

    tool_run = sub.add_parser("tool-run")
    tool_run.add_argument("name")
    tool_run.add_argument("--args", default="{}", help="JSON object")

    manifest = sub.add_parser("archive-manifest")
    manifest.add_argument("root")
    manifest.add_argument("--output", default="COLDVAULT-MANIFEST.json")

    ark_build = sub.add_parser("ark-build")
    ark_build.add_argument("root")
    ark_build.add_argument("--manifest", default="COLDVAULT-ARK.json")
    ark_build.add_argument("--index", default="COLDVAULT-INDEX.md")

    ark_verify = sub.add_parser("ark-verify")
    ark_verify.add_argument("root")
    ark_verify.add_argument("--manifest", default="COLDVAULT-ARK.json")
    ark_verify.add_argument("--strict", action="store_true")

    verify = sub.add_parser("archive-verify")
    verify.add_argument("root")
    verify.add_argument("manifest")

    survival = sub.add_parser("survival-select")
    survival.add_argument("model_dir")
    survival.add_argument("--memory-gb", type=float)
    survival.add_argument("--path-only", action="store_true")

    server = sub.add_parser("serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=7777)
    return p


def print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> None:
    args = build_parser().parse_args()
    vault = ColdVault(repo_root=Path(__file__).resolve().parent.parent)

    if args.cmd == "status":
        print_json(vault.status())
    elif args.cmd == "db-check":
        print_json(vault.db.integrity_check())
    elif args.cmd == "models":
        print_json(vault.models.summary())
    elif args.cmd == "tools":
        print_json(vault.tools.list())
    elif args.cmd == "jobs":
        print_json(vault.jobs.list(limit=100))
    elif args.cmd == "job-retry":
        print_json(vault.retry_tool_job(args.id))
    elif args.cmd == "job-cancel":
        print_json(vault.cancel_tool_job(args.id))
    elif args.cmd == "conversations":
        print_json(vault.conversations.list())
    elif args.cmd == "projects":
        print_json(vault.projects.list())
    elif args.cmd == "beliefs":
        print_json([b.as_dict() for b in vault.beliefs.search("", limit=50)])
    elif args.cmd == "reminders":
        print_json(vault.prospective.list("pending", limit=100))
    elif args.cmd == "remind":
        print(vault.prospective.create(args.content, args.due, source=args.source))
    elif args.cmd == "reminder-done":
        vault.prospective.set_status(args.id, "done")
        print_json({"ok": True, "id": args.id, "status": "done"})
    elif args.cmd == "reminder-cancel":
        vault.prospective.set_status(args.id, "cancelled")
        print_json({"ok": True, "id": args.id, "status": "cancelled"})
    elif args.cmd == "belief-add":
        print(vault.beliefs.create(
            args.claim, classification=args.classification,
            confidence=args.confidence, source=args.source,
        ))
    elif args.cmd == "belief-search":
        print_json([b.as_dict() for b in vault.beliefs.search(args.query, limit=args.limit)])
    elif args.cmd == "evidence-add":
        print(vault.beliefs.add_evidence(
            args.belief_id, args.content, kind=args.kind,
            source=args.source, confidence=args.confidence,
        ))
    elif args.cmd == "chat":
        print_json(vault.chat(" ".join(args.message), conversation_id=args.session))
    elif args.cmd == "think":
        print_json(vault.deep_think(" ".join(args.message), conversation_id=args.session, attempts=args.attempts))
    elif args.cmd == "new-conversation":
        print(vault.conversations.create(args.title))
    elif args.cmd == "remember":
        print(vault.memory.remember(
            args.content, kind=args.kind, source=args.source,
            confidence=args.confidence, tags=args.tag,
        ))
    elif args.cmd == "memory-search":
        print_json([m.__dict__ for m in vault.memory.search(args.query, limit=args.limit)])
    elif args.cmd == "memory-export":
        print_json(export_memories(vault.memory, Path(args.path)))
    elif args.cmd == "memory-import":
        print_json(import_memories(vault.memory, Path(args.path)))
    elif args.cmd == "ingest":
        print_json(vault.knowledge.ingest_file(Path(args.path), args.logical_path))
    elif args.cmd == "knowledge-reindex":
        print_json(vault.knowledge.reindex_embeddings())
    elif args.cmd == "transcribe":
        print_json(vault.transcribe(Path(args.path)))
    elif args.cmd == "speak":
        print_json(vault.speak(args.text, Path(args.output)))
    elif args.cmd == "vision":
        prompt = " ".join(args.prompt).strip() or "Describe and analyze this image."
        print_json(vault.analyze_image(Path(args.path), prompt, conversation_id=args.session))
    elif args.cmd == "checkpoint":
        print_json(vault.checkpoint(args.reason))
    elif args.cmd == "state":
        changes = {}
        if args.objective is not None:
            changes["objective"] = args.objective
        if args.project is not None:
            changes["active_project"] = args.project
        if args.next_action is not None:
            changes["next_action"] = args.next_action
        print_json(vault.set_state(changes))
    elif args.cmd == "task-add":
        print_json(vault.projects.add_task(args.project, args.title, args.details))
    elif args.cmd == "tasks":
        print_json(vault.projects.tasks(args.project))
    elif args.cmd == "task-status":
        vault.projects.set_task_status(args.task_id, args.status)
        print_json({"ok": True, "task_id": args.task_id, "status": args.status})
    elif args.cmd == "tool-run":
        parsed = json.loads(args.args)
        if not isinstance(parsed, dict):
            raise SystemExit("--args must decode to a JSON object")
        print_json(vault.run_tool(args.name, parsed))
    elif args.cmd == "archive-manifest":
        root = Path(args.root).resolve()
        output = Path(args.output)
        if not output.is_absolute():
            output = root / output
        print_json(build_manifest(root, output))
    elif args.cmd == "ark-build":
        root = Path(args.root).resolve()
        manifest_path = Path(args.manifest)
        index_path = Path(args.index)
        if not manifest_path.is_absolute():
            manifest_path = root / manifest_path
        if not index_path.is_absolute():
            index_path = root / index_path
        print_json(build_ark_catalog(root, manifest_path, index_path))
    elif args.cmd == "ark-verify":
        root = Path(args.root).resolve()
        manifest_path = Path(args.manifest)
        if not manifest_path.is_absolute():
            manifest_path = root / manifest_path
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print_json(verify_ark(root, manifest, strict=args.strict))
    elif args.cmd == "archive-verify":
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        print_json(verify_manifest(Path(args.root), manifest))
    elif args.cmd == "survival-select":
        memory_bytes = None if args.memory_gb is None else int(args.memory_gb * (1024 ** 3))
        selection = select_survival_model(Path(args.model_dir), memory_bytes=memory_bytes)
        if args.path_only:
            if not selection.model_path:
                raise SystemExit(selection.reason)
            print(selection.model_path)
        else:
            print_json(selection.as_dict())
    elif args.cmd == "serve":
        serve(vault, args.host, args.port)


if __name__ == "__main__":
    main()
