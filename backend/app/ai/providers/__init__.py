"""Provider adapters (DESIGN 12.4) and the factory that picks one from the settings."""

from __future__ import annotations

from app.ai.types import AIProvider
from app.config import Settings


def make_provider(settings: Settings, *, vision: bool = False) -> AIProvider | None:
    """The configured provider, or ``None`` when AI is off. ``vision=True`` returns the
    provider for reading paper forms (``JUSTFORMS_AI_VISION_MODEL`` if set), or ``None`` when
    the configured model can't read images."""
    if not settings.ai_enabled or (vision and not settings.ai_vision_enabled):
        return None
    model = (settings.ai_vision_model or settings.ai_model) if vision else settings.ai_model
    key = settings.ai_api_key.get_secret_value() if settings.ai_api_key else None
    timeout = settings.ai_request_timeout_seconds
    sees = settings.ai_vision_enabled
    match settings.ai_provider:
        case "anthropic":
            from app.ai.providers.anthropic import AnthropicProvider

            return AnthropicProvider(
                model=model,
                api_key=key or "",
                base_url=settings.ai_base_url,
                vision=sees,
                timeout=timeout,
            )
        case "gemini":
            from app.ai.providers.gemini import GeminiProvider

            return GeminiProvider(
                model=model,
                api_key=key or "",
                base_url=settings.ai_base_url,
                vision=sees,
                timeout=timeout,
            )
        case "openai_compat":
            from app.ai.providers.openai_compat import OpenAICompatProvider

            return OpenAICompatProvider(
                model=model,
                base_url=settings.ai_base_url or "",
                api_key=key,
                vision=sees,
                timeout=timeout,
            )
        case "fake":
            from app.ai.providers.fake import FileScriptProvider

            return FileScriptProvider(settings.ai_fake_script)
    return None
