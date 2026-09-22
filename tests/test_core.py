from __future__ import annotations

import json
import tempfile
import threading
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from coldvault.ark import build_ark_catalog, verify_ark
from coldvault.config import EmbeddingConfig, ModelConfig, Paths
from coldvault.core import ColdVault
from coldvault.embeddings import LocalEmbeddingProvider
from coldvault.speech import LocalSpeechProvider, SpeechSettings
from coldvault.survival import select_survival_model
from coldvault.survival_bundle import build_survival_bundle, verify_survival_bundle
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
        raw = self.rfile.read(length)

        if self.path.endswith("/audio/transcriptions"):
            body = json.dumps({"text": "offline transcript"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.endswith("/audio/speech"):
            body = b"RIFF-COLDVAULT-FAKE-AUDIO"
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        payload = json.loads(raw.decode("utf-8"))
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
        messages = payload.get("messages", [])
        is_vision = any(isinstance(message.get("content"), list) for message in messages if isinstance(message, dict))
        answer = "vision-ok" if is_vision else "Hello"
        body = json.dumps({"choices": [{"message": {"content": answer}}]}).encode("utf-8")
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


    def test_local_speech_and_vision_adapters(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                paths = Paths(root, root / "db.sqlite3", root / "knowledge", root / "checkpoints", root / "workspace", root / "logs").ensure()
                model = ModelConfig(
                    name="test",
                    base_url=f"http://127.0.0.1:{server.server_port}/v1",
                    timeout_seconds=2,
                )
                vault = ColdVault(paths=paths, model=model)
                vault.speech = LocalSpeechProvider(
                    SpeechSettings(stt=model, tts=model, voice="coldvault-test")
                )

                audio = root / "sample.wav"
                audio.write_bytes(b"RIFF-FAKE-INPUT")
                transcript = vault.transcribe(audio)
                self.assertEqual(transcript["text"], "offline transcript")

                spoken = root / "spoken.wav"
                speech_result = vault.speak("ColdVault is awake.", spoken)
                self.assertTrue(spoken.exists())
                self.assertGreater(speech_result["bytes"], 0)
                self.assertEqual(speech_result["voice"], "coldvault-test")

                image = root / "panel.png"
                image.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
                vision = vault.analyze_image(
                    image,
                    "Inspect this control panel.",
                    conversation_id="vision-test",
                )
                self.assertTrue(vision["ok"])
                self.assertEqual(vision["answer"], "vision-ok")
                self.assertEqual(len(vision["image_sha256"]), 64)
                history = vault.conversations.history("vision-test")
                self.assertEqual(history[-1]["content"], "vision-ok")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


    def test_prospective_memory_survives_and_becomes_due(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = self.make_vault(root)
            now = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
            due_id = vault.prospective.create(
                "Check the generator fuel after restart",
                now - timedelta(minutes=5),
                source="unit-test",
            )
            future_id = vault.prospective.create(
                "Rotate the cold-storage drives",
                now + timedelta(days=30),
                source="unit-test",
            )
            due = vault.prospective.due(now)
            self.assertEqual([item["id"] for item in due], [due_id])
            summary = vault.prospective.summary_for_prompt(now)
            self.assertIn("DUE", summary)
            self.assertIn("generator fuel", summary)

            restored = self.make_vault(root)
            pending_ids = {item["id"] for item in restored.prospective.list("pending")}
            self.assertEqual(pending_ids, {due_id, future_id})
            restored.prospective.set_status(due_id, "done")
            self.assertNotIn(due_id, {item["id"] for item in restored.prospective.list("pending")})


    def test_continuity_replays_updates_after_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = self.make_vault(root)
            vault.set_state({"active_project": "Generator", "objective": "Diagnose no-start"})
            vault.checkpoint("before-more-work")
            vault.set_state({"next_action": "Inspect fuel flow", "uncertainties": ["Fuel age unknown"]})

            restored = self.make_vault(root)
            state = restored.continuity.snapshot()
            self.assertEqual(state["active_project"], "Generator")
            self.assertEqual(state["objective"], "Diagnose no-start")
            self.assertEqual(state["next_action"], "Inspect fuel flow")
            self.assertEqual(state["uncertainties"], ["Fuel age unknown"])

    def test_tool_jobs_recover_interrupted_and_retry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = self.make_vault(root)
            vault.memory.remember("Generator spark confirmed", source="unit-test")
            success = vault.run_tool("memory.search", {"query": "generator spark"})
            self.assertTrue(success["ok"])
            completed = vault.jobs.get(success["job_id"])
            self.assertEqual(completed.status, "succeeded")

            now = datetime.now(timezone.utc).isoformat()
            interrupted_id = "interrupted-job-test"
            with vault.db.connect() as con:
                con.execute(
                    """INSERT INTO tool_jobs
                       (id, created_at, updated_at, started_at, finished_at, tool_name,
                        args_json, status, result_json, error, attempt, parent_job_id)
                       VALUES (?, ?, ?, ?, NULL, ?, ?, 'running', NULL, NULL, 1, NULL)""",
                    (
                        interrupted_id,
                        now,
                        now,
                        now,
                        "memory.search",
                        json.dumps({"query": "generator spark"}),
                    ),
                )

            restored = self.make_vault(root)
            interrupted = restored.jobs.get(interrupted_id)
            self.assertEqual(interrupted.status, "interrupted")
            retried = restored.retry_tool_job(interrupted_id)
            self.assertTrue(retried["ok"])
            self.assertEqual(retried["job"]["status"], "succeeded")
            self.assertEqual(retried["job"]["parent_job_id"], interrupted_id)
            self.assertEqual(retried["job"]["attempt"], 2)


    def test_ark_catalog_detects_corruption_and_completeness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payloads = {
                "source/core.py": b"print('coldvault')\n",
                "models/brain.gguf": b"MODEL",
                "runtimes/llama-server": b"RUNTIME",
                "packages/base.whl": b"PACKAGE",
                "state/coldvault.sqlite3": b"STATE",
                "knowledge/manual.txt": b"KNOWLEDGE",
                "recovery/RESTORE.md": b"RECOVERY",
                "os-media/linux.iso": b"OS",
                "drivers/gpu.bin": b"DRIVER",
                "firmware/board.bin": b"FIRMWARE",
                "hardware-docs/server.md": b"HARDWARE",
            }
            for relative, data in payloads.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

            manifest = build_ark_catalog(root)
            self.assertTrue(manifest["summary"]["complete"])
            self.assertEqual(manifest["summary"]["missing_critical"], [])
            self.assertEqual(manifest["summary"]["missing_recommended"], [])
            self.assertEqual(
                next(x for x in manifest["files"] if x["path"] == "runtimes/llama-server")["category"],
                "runtimes",
            )
            self.assertEqual(
                next(x for x in manifest["files"] if x["path"] == "firmware/board.bin")["category"],
                "firmware",
            )
            verified = verify_ark(root, manifest, strict=True)
            self.assertTrue(verified["ok"])
            self.assertTrue(verified["archive_complete"])

            (root / "models/brain.gguf").write_bytes(b"CORRUPTED")
            broken = verify_ark(root, manifest, strict=True)
            self.assertFalse(broken["ok"])
            self.assertTrue(any(item["path"] == "models/brain.gguf" for item in broken["failures"]))


    def test_survival_model_selector_respects_ram_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            small = root / "small.gguf"
            medium = root / "medium.gguf"
            large = root / "large.gguf"
            with small.open("wb") as handle:
                handle.truncate(256 * 1024 * 1024)
            with medium.open("wb") as handle:
                handle.truncate(640 * 1024 * 1024)
            with large.open("wb") as handle:
                handle.truncate(1200 * 1024 * 1024)

            selection = select_survival_model(root, memory_bytes=2 * 1024 ** 3)
            self.assertEqual(Path(selection.model_path).name, "medium.gguf")
            self.assertLessEqual(selection.model_bytes, selection.budget_bytes)
            self.assertEqual(selection.context_tokens, 2048)

            too_small = select_survival_model(root, memory_bytes=512 * 1024 ** 2)
            self.assertIsNone(too_small.model_path)
            self.assertIn("no GGUF fits", too_small.reason)


    def test_phone_survival_bundle_contains_open_state_and_verifies(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = self.make_vault(root / "vault")
            vault.memory.remember(
                "Generator spark was confirmed",
                kind="episodic",
                source="unit-test",
                tags=["critical", "generator"],
            )
            belief_id = vault.beliefs.create(
                "Fuel delivery may be restricted",
                classification="hypothesis",
                confidence=0.62,
                source="unit-test",
            )
            vault.beliefs.add_evidence(
                belief_id,
                "Fuel flow is below specification",
                kind="supports",
                source="unit-test",
            )
            vault.prospective.create(
                "Recheck generator fuel after restart",
                datetime.now(timezone.utc) + timedelta(hours=2),
                source="unit-test",
            )
            vault.set_state({
                "active_project": "Generator recovery",
                "objective": "Restore reliable emergency power",
                "next_action": "Inspect fuel delivery",
            })

            manual = root / "generator-manual.txt"
            manual.write_text(
                "Emergency generator fuel delivery inspection: isolate load, inspect filter, verify fuel flow.",
                encoding="utf-8",
            )
            vault.knowledge.ingest_file(manual, "manuals/generator.txt")

            models = root / "models"
            models.mkdir()
            (models / "micro.gguf").write_bytes(b"M" * 1024)
            (models / "survival.gguf").write_bytes(b"S" * 4096)

            output = root / "phone-survival.zip"
            result = build_survival_bundle(
                vault,
                output,
                model_dir=models,
                memory_bytes=2 * 1024 ** 3,
                include_model=True,
                knowledge_queries=["generator fuel"],
                knowledge_limit=20,
            )
            self.assertTrue(result["ok"])
            self.assertTrue(output.exists())
            verified = verify_survival_bundle(output)
            self.assertTrue(verified["ok"])
            self.assertGreater(verified["files_checked"], 5)
            self.assertTrue(verified["metadata"]["model_included"])

            with zipfile.ZipFile(output, "r") as archive:
                names = set(archive.namelist())
                self.assertIn("COLDVAULT-SURVIVAL/MANIFEST.json", names)
                self.assertIn("COLDVAULT-SURVIVAL/state/coldvault.sqlite3", names)
                self.assertIn("COLDVAULT-SURVIVAL/state/latest-checkpoint.json", names)
                self.assertIn("COLDVAULT-SURVIVAL/memory/memories.jsonl", names)
                self.assertIn("COLDVAULT-SURVIVAL/memory/beliefs.jsonl", names)
                self.assertIn("COLDVAULT-SURVIVAL/memory/reminders.jsonl", names)
                self.assertIn("COLDVAULT-SURVIVAL/knowledge/critical-chunks.jsonl", names)
                self.assertIn("COLDVAULT-SURVIVAL/model/survival.gguf", names)
                state = json.loads(archive.read("COLDVAULT-SURVIVAL/cognitive-state.json"))
                self.assertEqual(state["active_project"], "Generator recovery")
                chunks = archive.read("COLDVAULT-SURVIVAL/knowledge/critical-chunks.jsonl").decode("utf-8")
                self.assertIn("fuel delivery", chunks.lower())
                memories = archive.read("COLDVAULT-SURVIVAL/memory/memories.jsonl").decode("utf-8")
                self.assertIn("Generator spark was confirmed", memories)
                beliefs = archive.read("COLDVAULT-SURVIVAL/memory/beliefs.jsonl").decode("utf-8")
                self.assertIn("Fuel delivery may be restricted", beliefs)
                self.assertIn("Fuel flow is below specification", beliefs)


if __name__ == "__main__":
    unittest.main()
