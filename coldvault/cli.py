from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import ColdVault
from .server import serve


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="coldvault", description="THE FROZEN BRAIN local-first AI continuity system")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    chat = sub.add_parser("chat")
    chat.add_argument("message", nargs="+")
    remember = sub.add_parser("remember")
    remember.add_argument("content")
    remember.add_argument("--kind", default="semantic")
    remember.add_argument("--source", default="user")
    search = sub.add_parser("memory-search")
    search.add_argument("query")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("path")
    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("--reason", default="manual")
    state = sub.add_parser("state")
    state.add_argument("--objective")
    state.add_argument("--project")
    state.add_argument("--next-action")
    server = sub.add_parser("serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=7777)
    return p


def main() -> None:
    args = build_parser().parse_args()
    vault = ColdVault(repo_root=Path(__file__).resolve().parent.parent)
    if args.cmd == "status":
        print(json.dumps(vault.status(), indent=2))
    elif args.cmd == "chat":
        print(vault.chat(" ".join(args.message))["answer"])
    elif args.cmd == "remember":
        print(vault.memory.remember(args.content, kind=args.kind, source=args.source))
    elif args.cmd == "memory-search":
        print(json.dumps([m.__dict__ for m in vault.memory.search(args.query)], indent=2))
    elif args.cmd == "ingest":
        print(json.dumps(vault.knowledge.ingest_file(Path(args.path)), indent=2))
    elif args.cmd == "checkpoint":
        print(json.dumps(vault.checkpoint(args.reason), indent=2))
    elif args.cmd == "state":
        changes = {}
        if args.objective is not None:
            changes["objective"] = args.objective
        if args.project is not None:
            changes["active_project"] = args.project
        if args.next_action is not None:
            changes["next_action"] = args.next_action
        print(json.dumps(vault.set_state(changes), indent=2))
    elif args.cmd == "serve":
        serve(vault, args.host, args.port)


if __name__ == "__main__":
    main()
