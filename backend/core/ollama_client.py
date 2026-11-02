"""Minimal async client for a locally running Ollama server.

Everything stays on localhost. If Ollama isn't installed or running, the
client reports unavailable and the app degrades gracefully — the rules-engine
deck builder works regardless.
"""

import json
import re
from dataclasses import dataclass
from typing import AsyncIterator, Callable, List, Optional, Tuple

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
PREFERRED_MODELS = ("gpt-oss", "gemma4", "qwen3.8", "qwen3.6", "qwen3.5", "qwen3",
                    "llama", "mistral", "gemma", "phi")


@dataclass
class CallStats:
    """Speed numbers for one model call."""

    prompt_tokens: int
    prompt_seconds: float
    output_tokens: int
    output_seconds: float


class ModelError(RuntimeError):
    """The model call failed or returned unusable output."""


def stats_from(data: dict) -> CallStats:
    """Build CallStats from an Ollama response.

    Args:
        data: Ollama response body or final stream chunk. Durations are in
            nanoseconds. A missing field counts as 0.

    Returns:
        The call stats, with durations in seconds.
    """
    return CallStats(
        prompt_tokens=int(data.get("prompt_eval_count") or 0),
        prompt_seconds=(data.get("prompt_eval_duration") or 0) / 1e9,
        output_tokens=int(data.get("eval_count") or 0),
        output_seconds=(data.get("eval_duration") or 0) / 1e9,
    )


def think_value(model: str, think: str):
    """Return the ``think`` request value a model accepts.

    Args:
        model: Model name.
        think: Effort level: "low", "medium" or "high".

    Returns:
        The level string for gpt-oss models, else a boolean (False for "low").
    """
    if model.lower().startswith("gpt-oss"):
        return think
    return think != "low"


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", transport=None):
        """Create a client.

        Args:
            base_url: Ollama server URL.
            transport: Optional httpx transport, passed to every AsyncClient (for tests).
        """
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    async def list_models(self) -> List[str]:
        """Names of locally installed models, or [] if Ollama is unreachable."""
        try:
            async with httpx.AsyncClient(timeout=2.0, transport=self.transport) as client:
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

        async with httpx.AsyncClient(timeout=httpx.Timeout(240.0, connect=3.0),
                                     transport=self.transport) as client:
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

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=3.0),
                                     transport=self.transport) as client:
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

    async def _model_or_raise(self, model: Optional[str]) -> str:
        if model is None:
            model = self.pick_model(await self.list_models())
        if model is None:
            raise ModelError("No Ollama models available")
        return model

    @staticmethod
    def _messages(prompt: str, system: str) -> List[dict]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def chat_structured(
        self,
        prompt: str,
        schema: dict,
        system: str = "",
        model: Optional[str] = None,
        think: str = "low",
        num_ctx: int = 16384,
        num_predict: int = 4096,
    ) -> Tuple[dict, CallStats]:
        """Single-shot completion constrained to a JSON schema.

        Args:
            prompt: User prompt.
            schema: JSON schema for the reply, sent as the request ``format``.
            system: Optional system prompt.
            model: Model name. None picks the preferred installed model.
            think: Reasoning effort: "low", "medium" or "high".
            num_ctx: Context window in tokens.
            num_predict: Cap on output tokens.

        Returns:
            (parsed reply, call stats).

        Raises:
            ModelError: On a timeout, or when both attempts fail on an HTTP error,
                invalid JSON, or a reply that is not a JSON object.
        """
        model = await self._model_or_raise(model)
        payload = {
            "model": model,
            "messages": self._messages(prompt, system),
            "stream": False,
            "format": schema,
            "think": think_value(model, think),
            "options": {"temperature": 0.6, "num_ctx": num_ctx, "num_predict": num_predict},
        }
        last = None  # type: Optional[Exception]
        for _ in range(2):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=3.0),
                                             transport=self.transport) as client:
                    response = await client.post(f"{self.base_url}/api/chat", json=payload)
                    response.raise_for_status()
                    body = response.json()
                content = strip_thinking(body["message"]["content"])
                data = parse_json_loose(content)
                if not isinstance(data, dict):
                    raise ValueError("Reply is not a JSON object")
                return data, stats_from(body)
            except httpx.TimeoutException as exc:
                raise ModelError("Model call timed out: %s" % (exc,))
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                last = exc
        raise ModelError("Model call failed: %s" % (last,))

    async def stream_text(
        self,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
        on_stats: Optional[Callable[[CallStats], None]] = None,
        num_predict: Optional[int] = None,
        num_ctx: int = 16384,
    ) -> AsyncIterator[str]:
        """Stream a chat completion as text chunks.

        Args:
            prompt: User prompt.
            system: Optional system prompt.
            model: Model name. None picks the preferred installed model.
            on_stats: Called with the stats from the final chunk.
            num_predict: Optional cap on output tokens.
            num_ctx: Context window in tokens.

        Yields:
            Text chunks.

        Raises:
            ModelError: On an HTTP error.
        """
        model = await self._model_or_raise(model)
        payload = {
            "model": model,
            "messages": self._messages(prompt, system),
            "stream": True,
            "think": think_value(model, "low"),
        }
        payload["options"] = {"num_ctx": num_ctx}
        if num_predict is not None:
            payload["options"]["num_predict"] = num_predict
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=3.0),
                                         transport=self.transport) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat",
                                         json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(chunk, dict) and chunk.get("error"):
                            raise ModelError("Model stream failed: %s" % (chunk["error"],))
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if chunk.get("done"):
                            if on_stats is not None:
                                on_stats(stats_from(chunk))
        except httpx.HTTPError as exc:
            raise ModelError("Model stream failed: %s" % (exc,))
