from __future__ import annotations

from dataclasses import dataclass

from .model_registry import ModelRegistry
from .providers import OpenAICompatibleProvider, ProviderError


@dataclass
class DeliberationResult:
    final: str
    attempts: list[dict]
    critique: str
    synthesis_profile: str

    def as_dict(self) -> dict:
        return {
            "final": self.final,
            "attempts": self.attempts,
            "critique": self.critique,
            "synthesis_profile": self.synthesis_profile,
        }


class DeliberationEngine:
    def __init__(self, registry: ModelRegistry):
        self.registry = registry

    def run(self, base_messages: list[dict], *, attempts: int = 2) -> DeliberationResult:
        attempts = max(2, min(int(attempts), 4))
        candidates = self.registry.candidates("reasoning")
        if not candidates:
            raise RuntimeError("no enabled local models for deliberation")

        solutions: list[dict] = []
        failures: list[str] = []
        for index in range(attempts):
            profile = candidates[index % len(candidates)]
            provider = OpenAICompatibleProvider(profile.as_config().validate_privacy())
            messages = [dict(x) for x in base_messages]
            messages[0] = {
                "role": "system",
                "content": messages[0]["content"] + (
                    f"\n\nDELIBERATION ROLE: independent solver {index + 1}. "
                    "Solve the user's problem independently. Do not assume another solver's answer. "
                    "State uncertainties and verification needs."
                ),
            }
            try:
                answer = provider.chat(messages, temperature=0.65, max_tokens=2200)
                solutions.append({"profile": profile.name, "model": profile.model, "answer": answer})
            except ProviderError as exc:
                failures.append(f"{profile.name}: {exc}")

        if not solutions:
            raise ProviderError("all deliberation solver attempts failed: " + "; ".join(failures))

        critic_profile = candidates[0]
        critic_provider = OpenAICompatibleProvider(critic_profile.as_config().validate_privacy())
        packed = "\n\n".join(
            f"ATTEMPT {i + 1} [{item['profile']} / {item['model']}]\n{item['answer'][:14000]}"
            for i, item in enumerate(solutions)
        )
        critic_messages = [
            {
                "role": "system",
                "content": (
                    "You are the ColdVault critic. Compare independent candidate solutions. "
                    "Identify factual, logical, completeness, safety, and verification weaknesses. "
                    "Do not select a winner by style; focus on correctness and supported reasoning."
                ),
            },
            {"role": "user", "content": packed},
        ]
        critique = critic_provider.chat(critic_messages, temperature=0.2, max_tokens=1800)

        synthesis_messages = [dict(x) for x in base_messages]
        synthesis_messages[0] = {
            "role": "system",
            "content": synthesis_messages[0]["content"] + (
                "\n\nDELIBERATION ROLE: final synthesizer. Produce the best supported answer using the "
                "independent attempts and critic report below. Correct their errors rather than merely averaging them."
            ),
        }
        synthesis_messages.append({
            "role": "user",
            "content": f"INDEPENDENT ATTEMPTS\n{packed}\n\nCRITIC REPORT\n{critique}",
        })
        final = critic_provider.chat(synthesis_messages, temperature=0.25, max_tokens=2600)
        return DeliberationResult(
            final=final,
            attempts=solutions,
            critique=critique,
            synthesis_profile=critic_profile.name,
        )
