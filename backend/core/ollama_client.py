"""Minimal async client for a locally running Ollama server.

Everything stays on localhost. If Ollama isn't installed or running, the
client reports unavailable and the app degrades gracefully — the rules-engine
deck builder works regardless.
"""

import json
import re
from typing import AsyncIterator, List, Optional

import httpx


THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_thinking(text: str) -> str:
    """Remove <think>…</think> blocks emitted by reasoning models (qwen3 etc.)."""
    return THINK_BLOCK_RE.sub("", text).strip()


def parse_json_loose(text: str) -> dict:
    """Parse JSON, salvaging the outermost object if there's surrounding noise."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


# Models we prefer when several are installed, best-first
PREFERRED_MODELS = ("qwen", "llama", "mistral", "gemma", "phi")


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")

    async def list_models(self) -> List[str]:
        """Names of locally installed models, or [] if Ollama is unreachable."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    async def status(self) -> dict:
        models = await self.list_models()
        return {
            "available": bool(models),
            "models": models,
            "default_model": self.pick_model(models),
        }

    @staticmethod
    def pick_model(models: List[str]) -> Optional[str]:
        for preferred in PREFERRED_MODELS:
            for model in models:
                if preferred in model.lower():
                    return model
        return models[0] if models else None

    async def chat_json(
        self,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
    ) -> dict:
        """Single-shot completion constrained to JSON output."""
        if model is None:
            model = self.pick_model(await self.list_models())
        if model is None:
            raise RuntimeError("No Ollama models available")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=httpx.Timeout(240.0, connect=3.0)) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    # Reasoning models: ask for the answer directly
                    "think": False,
                    "options": {
                        "temperature": 0.6,
                        # Large prompts (a full card pool) blow past the default
                        # context window and truncate the reply, so widen it
                        "num_ctx": 16384,
                        "num_predict": 4096,
                    },
                },
            )
            response.raise_for_status()
            content = strip_thinking(response.json()["message"]["content"])
            return parse_json_loose(content)

    async def stream_chat(
        self,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream a chat completion as text chunks."""
        if model is None:
            model = self.pick_model(await self.list_models())
        if model is None:
            raise RuntimeError("No Ollama models available")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=3.0)) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={"model": model, "messages": messages, "stream": True, "think": False},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done"):
                        break
