"""LLM provider abstraction. See PILOT_SPEC.md §13.4 and Phases 6-7.

- Provider interface (`LLMProvider`, `ProviderRequest`, `ProviderResponse`)
  and `MockProvider`: Phase 6.
- `AnthropicProvider`, `OpenAIProvider`: Phase 7.
"""

from .base import LLMProvider, ProviderRequest, ProviderResponse
from .mock import (
    PROSE_RESPONSE,
    MockProvider,
    build_invalid_critic_payload,
    build_valid_critic_payload,
)

__all__ = [
    "PROSE_RESPONSE",
    "LLMProvider",
    "MockProvider",
    "ProviderRequest",
    "ProviderResponse",
    "build_invalid_critic_payload",
    "build_valid_critic_payload",
]
