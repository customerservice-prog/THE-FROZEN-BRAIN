from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coldvault.config import ModelConfig
from coldvault.deliberation import DeliberationEngine
from coldvault.hardware import detect_hardware
from coldvault.model_registry import ModelRegistry


class FakeProvider:
    calls = 0

    def __init__(self, config):
        self.config = config

    def chat(self, messages, **kwargs):
        FakeProvider.calls += 1
        system = messages[0]["content"]
        if "ColdVault critic" in system:
            return "Critique: verify the strongest factual claims."
        if "final synthesizer" in system:
            return "Final synthesized answer."
        return f"Independent solution {FakeProvider.calls}."


class DeliberationTests(unittest.TestCase):
    def test_deep_think_runs_independent_attempts_critic_and_synthesis(self):
        with tempfile.TemporaryDirectory() as td:
            registry = ModelRegistry(
                Path(td),
                ModelConfig(name="local-test", base_url="http://127.0.0.1:11434/v1"),
            )
            engine = DeliberationEngine(registry)
            FakeProvider.calls = 0
            with patch("coldvault.deliberation.OpenAICompatibleProvider", FakeProvider):
                result = engine.run([
                    {"role": "system", "content": "Local system"},
                    {"role": "user", "content": "Solve this carefully"},
                ], attempts=2)
            self.assertEqual(len(result.attempts), 2)
            self.assertEqual(result.final, "Final synthesized answer.")
            self.assertIn("Critique", result.critique)
            self.assertEqual(FakeProvider.calls, 4)

    def test_hardware_profile_is_classified(self):
        profile = detect_hardware()
        self.assertIn(profile.tier, {"survival", "mobile", "portable", "workstation", "frontier"})
        self.assertGreaterEqual(profile.logical_cpus, 1)


if __name__ == "__main__":
    unittest.main()
