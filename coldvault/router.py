from __future__ import annotations


def classify_request(text: str) -> str:
    lower = text.lower()
    if any(x in lower for x in ("code", "bug", "python", "javascript", "typescript", "repository", "function", "compile")):
        return "coding"
    if any(x in lower for x in ("image", "photo", "screenshot", "diagram", "picture")):
        return "vision"
    if any(x in lower for x in ("prove", "reason", "analyze", "compare", "calculate", "plan", "research")):
        return "reasoning"
    return "general"


def model_hint(route: str) -> str:
    return {
        "coding": "Use the strongest installed coding model when available.",
        "vision": "Use an installed multimodal model when image input is present.",
        "reasoning": "Prefer the strongest reasoning model and verification tools.",
        "general": "Prefer the fastest capable general model.",
    }.get(route, "Use an appropriate local model.")
