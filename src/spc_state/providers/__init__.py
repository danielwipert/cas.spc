"""LLM provider abstraction. See PILOT_SPEC.md §13.4 and Phases 6-7.

- Provider interface (`LLMProvider`, `ProviderRequest`, `ProviderResponse`)
  and `MockProvider`: Phase 6.
- `OpenRouterProvider` (one OpenAI-compatible seam to ~1000 models): Phase 7.
"""

from .base import LLMProvider, ProviderRequest, ProviderResponse
from .mock import (
    PROSE_RESPONSE,
    MockProvider,
    build_invalid_critic_payload,
    build_valid_critic_payload,
)
from .openrouter import (
    DEFAULT_MODEL,
    VALUE_MODELS,
    OpenRouterConfigError,
    OpenRouterProvider,
)

__all__ = [
    "DEFAULT_MODEL",
    "PROSE_RESPONSE",
    "VALUE_MODELS",
    "LLMProvider",
    "MockProvider",
    "OpenRouterConfigError",
    "OpenRouterProvider",
    "ProviderRequest",
    "ProviderResponse",
    "build_invalid_critic_payload",
    "build_valid_critic_payload",
]
