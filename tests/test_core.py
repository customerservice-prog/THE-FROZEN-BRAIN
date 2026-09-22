from __future__ import annotations

import json
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from coldvault.config import EmbeddingConfig, ModelConfig, Paths
from coldvault.core import ColdVault
from coldvault.embeddings import LocalEmbeddingProvider
from coldvault.tools import ToolPolicy, WorkspaceTools


class _FakeModelHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path.endswith("/models"):
            body = json.dumps({"data": [{"id": "test"}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if self.path.endswith("/embeddings"):
            inputs = payload.get("input", [])
            data = []
            for index, text in enumerate(inputs):
                lower = str(text).lower()
                if any(word in lower for word in ("car", "vehicle", "automobile")):
                    vector = [1.0, 0.0, 0.0]
                elif "generator" in lower:
                    vector = [0.0, 1.0, 0.0]
                else:
                    vector = [0.0, 0.0, 1.0]
                data.append({"index": index, "embedding": vector})
            body = json.dumps({"data": data}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if payload.get("stream"):
            body = (
                b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
                b'data: [DONE]\n\n'
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            return
        body = json.dumps({"choices": [{"message": {"content": "Hello"}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ColdVaultTests(unittest.TestCase):
    def make_vault(self, root: Path) -> ColdVault:
        paths = Paths(root, root / "db.sqlite3", root / "knowledge", root / "checkpoints", root / "workspace", root / "logs").ensure()
        return ColdVault(paths=paths, model=ModelConfig(name="test", base_url="http://127.0.0.1:9/v1", timeout_seconds=1))

    def test_memory_search(self):
        with tempfile.TemporaryDirectory() as td:
            vault = self.make_vault(Path(td))
            vault.memory.remember("Generator spark was confirmed", source="test")
            found = vault.memory.search("generator spark")
            self.assertTrue(found)
            self.assertIn("spark", found[0].content.lower())

    def test_checkpoint_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            vault = self.make_vault(Path(td))
            vault.set_state({"active_project": "Alpha", "next_action": "Test"})
            vault.checkpoint("unit-test")
            restored = vault.continuity.restore_latest()
            self.assertEqual(restored.active_project, "Alpha")
            self.assertEqual(restored.next_action, "Test")

    def test_workspace_escape_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            tools = WorkspaceTools(Path(td), ToolPolicy(allow_reads=True, allow_writes=True))
            with self.assertRaises(PermissionError):
                tools.write_text("../escape.txt", "no")

    def test_knowledge_retrieval(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = self.make_vault(root)
            f = root / "guide.txt"
            f.write_text("Carburetor jet cleaning procedure and fuel flow inspection", encoding="utf-8")
            vault.knowledge.ingest_file(f, "guide.txt")
            found = vault.knowledge.search("fuel carburetor")
            self.assertTrue(found)
            self.assertEqual(found[0]["source"], "guide.txt")


    def test_belief_evidence_preserves_contradiction(self):
        with tempfile.TemporaryDirectory() as td:
            vault = self.make_vault(Path(td))
            belief_id = vault.beliefs.create(
                "Fuel pump has failed",
                classification="hypothesis",
                confidence=0.55,
                source="diagnostic-session",
            )
            vault.beliefs.add_evidence(
                belief_id,
                "Measured fuel pressure is below specification",
                kind="supports",
                source="pressure-test",
            )
            vault.beliefs.add_evidence(
                belief_id,
                "Pump motor can still be heard",
                kind="contradicts",
                source="user-observation",
            )
            belief = vault.beliefs.get(belief_id)
            self.assertEqual(belief.classification, "hypothesis")
            self.assertEqual(len(belief.evidence), 2)
            self.assertEqual({e["kind"] for e in belief.evidence}, {"supports", "contradicts"})
            prompt_summary = vault.beliefs.summary_for_prompt("fuel pump")
            self.assertIn("hypothesis", prompt_summary)
            self.assertIn("contradiction=1", prompt_summary)


    def test_streaming_chat_is_durable(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                paths = Paths(root, root / "db.sqlite3", root / "knowledge", root / "checkpoints", root / "workspace", root / "logs").ensure()
                model = ModelConfig(name="test", base_url=f"http://127.0.0.1:{server.server_port}/v1", timeout_seconds=2)
                vault = ColdVault(paths=paths, model=model)
                events = list(vault.chat_stream("hello", conversation_id="stream-test"))
                self.assertEqual([e["text"] for e in events if e["type"] == "delta"], ["Hel", "lo"])
                done = [e for e in events if e["type"] == "done"][0]
                self.assertTrue(done["ok"])
                self.assertEqual(done["answer"], "Hello")
                history = vault.conversations.history("stream-test")
                self.assertEqual([x["role"] for x in history], ["user", "assistant"])
                self.assertEqual(history[-1]["content"], "Hello")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_belief_state_is_in_reasoning_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            vault = self.make_vault(Path(td))
            vault.beliefs.create(
                "Fuel delivery may be restricted",
                classification="hypothesis",
                confidence=0.6,
                source="diagnostic-session",
            )
            conversation_id = vault.conversations.ensure("belief-prompt")
            messages, _ = vault.build_messages("fuel delivery", conversation_id, "reasoning", "default")
            system = messages[0]["content"]
            self.assertIn("CURRENT BELIEF / EVIDENCE STATE", system)
            self.assertIn("Fuel delivery may be restricted", system)
            self.assertIn("Never silently promote a hypothesis", system)


    def test_docx_document_ingestion(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = self.make_vault(root)
            docx = root / "manual.docx"
            document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Emergency generator reset procedure</w:t></w:r></w:p>
    <w:p><w:r><w:t>Disconnect the load before restarting.</w:t></w:r></w:p>
  </w:body>
</w:document>"""
            with zipfile.ZipFile(docx, "w") as archive:
                archive.writestr("word/document.xml", document_xml)
            result = vault.knowledge.ingest_file(docx, "manuals/generator.docx")
            self.assertEqual(result["extractor"], "stdlib-docx")
            found = vault.knowledge.search("generator restart")
            self.assertTrue(found)
            self.assertEqual(found[0]["source"], "manuals/generator.docx")

    def test_local_embedding_provider_and_hybrid_retrieval(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                vault = self.make_vault(root)
                config = EmbeddingConfig(
                    name="fake-embed",
                    base_url=f"http://127.0.0.1:{server.server_port}/v1",
                    timeout_seconds=2,
                )
                vault.knowledge.embedder = LocalEmbeddingProvider(config)
                cars = root / "cars.txt"
                generators = root / "generators.txt"
                cars.write_text("A compact car needs tire pressure checks and regular maintenance.", encoding="utf-8")
                generators.write_text("Generator fuel systems require clean filters.", encoding="utf-8")
                cars_result = vault.knowledge.ingest_file(cars, "cars.txt")
                vault.knowledge.ingest_file(generators, "generators.txt")
                self.assertEqual(cars_result["embedding"]["embedded"], 1)
                found = vault.knowledge.search("vehicle maintenance")
                self.assertTrue(found)
                self.assertEqual(found[0]["source"], "cars.txt")
                self.assertEqual(found[0]["retrieval"], "hybrid")
                self.assertGreater(found[0]["semantic_score"], 0.9)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
