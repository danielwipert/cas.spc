"""LLM provider abstraction. See PILOT_SPEC.md §13.4 and Phases 6-7.

- Provider interface (`LLMProvider`, `ProviderRequest`, `ProviderResponse`)
  and `MockProvider`: Phase 6.
- `OpenRouterProvider` (one OpenAI-compatible seam to ~1000 models): Phase 7.
- `RecordingProvider` / `ReplayProvider`: capture a real exchange once, then
  replay it offline so CI can regression-test against genuine model output.
"""

from .base import LLMProvider, ProviderRequest, ProviderResponse
from .cassette import (
    CASSETTE_VERSION,
    Cassette,
    CassetteError,
    Exchange,
    RecordingProvider,
    ReplayProvider,
    RunSpec,
    SourceSpec,
    request_digest,
    text_digest,
)
from .mock import (
    PROSE_RESPONSE,
    MockProvider,
    build_invalid_critic_payload,
    build_valid_critic_payload,
)
from .openrouter import (
    DEFAULT_MODEL,
    MODEL_PRICING_PER_MILLION_USD,
    VALUE_MODELS,
    OpenRouterConfigError,
    OpenRouterProvider,
    estimate_cost_usd,
)

__all__ = [
    "CASSETTE_VERSION",
    "DEFAULT_MODEL",
    "MODEL_PRICING_PER_MILLION_USD",
    "PROSE_RESPONSE",
    "VALUE_MODELS",
    "Cassette",
    "CassetteError",
    "Exchange",
    "LLMProvider",
    "MockProvider",
    "OpenRouterConfigError",
    "OpenRouterProvider",
    "ProviderRequest",
    "ProviderResponse",
    "RecordingProvider",
    "ReplayProvider",
    "RunSpec",
    "SourceSpec",
    "build_invalid_critic_payload",
    "build_valid_critic_payload",
    "estimate_cost_usd",
    "request_digest",
    "text_digest",
]
