"""`OpenRouterProvider` — one seam to ~1000 models. See PILOT_SPEC.md Phase 7.

OpenRouter exposes an OpenAI-compatible Chat Completions API, so a single
provider reaches Anthropic, OpenAI, Google, DeepSeek, Meta, Qwen, and the
rest behind one `model` string. We talk to it through the `openai` SDK with
`base_url` pointed at OpenRouter.

Model choice is fully configurable (constructor arg → `SPC_OPENROUTER_MODEL`
env → a value-based default). The default is deliberately *not* a frontier
flagship: a critic rarely needs one, and the point of OpenRouter is to fit a
cheap, capable model to each task.

Structured output is requested with `response_format={"type": "json_object"}`
(broadly supported) rather than strict `json_schema` (supported by far fewer
models) — the runtime's validation-feedback retry loop (spec §15.6) repairs
the occasional malformed patch. That keeps the widest range of value models
usable.
"""

from __future__ import annotations

import os
from typing import Any

from ..models import ModelFingerprint
from .base import LLMProvider, ProviderRequest, ProviderResponse

#: A value-based default — cheap and strong at reasoning. Overridable.
DEFAULT_MODEL = "deepseek/deepseek-chat"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

#: Curated value-based slugs for `model=` (verify current availability on
#: https://openrouter.ai/models — slugs evolve). These are suggestions, not a
#: closed set: any OpenRouter slug works.
VALUE_MODELS: dict[str, str] = {
    "deepseek": "deepseek/deepseek-chat",
    "gemini-flash": "google/gemini-2.5-flash",
    "gpt-mini": "openai/gpt-4o-mini",
    "claude-haiku": "anthropic/claude-3.5-haiku",
    "llama": "meta-llama/llama-3.3-70b-instruct",
    "qwen": "qwen/qwen-2.5-72b-instruct",
}


class OpenRouterConfigError(RuntimeError):
    """The provider is missing an API key or the `openai` SDK."""


class OpenRouterProvider(LLMProvider):
    """An `LLMProvider` backed by OpenRouter's OpenAI-compatible API."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        json_object: bool = True,
        referer: str | None = "https://github.com/danielwipert/cas.spc",
        title: str | None = "SPC Shared Semantic State",
        timeout: float = 60.0,
        client: Any | None = None,
    ) -> None:
        self.model = model or os.environ.get("SPC_OPENROUTER_MODEL") or DEFAULT_MODEL
        self.base_url = base_url or os.environ.get("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.json_object = json_object
        self.referer = referer
        self.title = title
        self.timeout = timeout

        # Tests inject a fake client; otherwise we build a real one lazily so
        # the `openai` dependency stays optional and the key is checked early.
        self._client = client
        if client is None:
            self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
            if not self._api_key:
                raise OpenRouterConfigError(
                    "No OpenRouter API key. Set OPENROUTER_API_KEY or pass api_key=..."
                )
        else:
            self._api_key = api_key or "injected-client"

    # -- client ------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - exercised only without the extra
                raise OpenRouterConfigError(
                    "The OpenRouter provider needs the 'openai' SDK. "
                    "Install it with: pip install 'spc-state[openrouter]'"
                ) from exc
            headers: dict[str, str] = {}
            if self.referer:
                headers["HTTP-Referer"] = self.referer
            if self.title:
                headers["X-Title"] = self.title
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self._api_key,
                timeout=self.timeout,
                default_headers=headers or None,
            )
        return self._client

    # -- the seam ----------------------------------------------------------

    def _messages(self, request: ProviderRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.user})
        if request.feedback:
            joined = "\n".join(f"- {f}" for f in request.feedback)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous output was rejected by the validator:\n"
                        f"{joined}\n"
                        "Return a corrected SemanticPatch as a single JSON object."
                    ),
                }
            )
        return messages

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(request),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.json_object:
            kwargs["response_format"] = {"type": "json_object"}

        completion = client.chat.completions.create(**kwargs)
        text = completion.choices[0].message.content or ""
        fingerprint = ModelFingerprint(
            provider="openrouter",
            model=self.model,
            model_version=getattr(completion, "model", None),
            sampling={"temperature": self.temperature, "max_tokens": self.max_tokens},
        )
        return ProviderResponse(text=text, fingerprint=fingerprint)


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "VALUE_MODELS",
    "OpenRouterConfigError",
    "OpenRouterProvider",
]
