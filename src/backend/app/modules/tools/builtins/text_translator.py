"""
Built-in text_translator tool.

Translates text between languages. Uses a translation API if TRANSLATION_API_KEY
is configured; falls back to LLM-based translation via the platform's configured
LLM when no dedicated API is available.

Input:  { text: str, target_language: str, source_language: str | None }
Output: { translated: str, detected_source_language: str | None }
"""
import os
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

_MAX_TEXT_LENGTH = 50_000  # 50 KB text limit for translation


async def text_translator(
    text: str,
    target_language: str,
    source_language: Optional[str] = None,
    **_kwargs: Any,
) -> dict:
    """
    Translate text to the target language.

    Uses TRANSLATION_API_KEY (DeepL or Google Cloud Translation format) when
    configured. Falls back to LLM-based translation using the platform's
    default LLM if no dedicated API key is set.

    Args:
        text: Text to translate.
        target_language: Target language name or ISO 639-1 code.
        source_language: Source language (None = auto-detect).

    Returns:
        dict with 'translated' (translated text) and
        'detected_source_language' (ISO code if detected, else None).
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    if not isinstance(target_language, str) or not target_language.strip():
        raise ValueError("target_language must be a non-empty string")
    if len(text) > _MAX_TEXT_LENGTH:
        raise ValueError(f"text too long (max {_MAX_TEXT_LENGTH} characters)")

    text = text.strip()
    target_language = target_language.strip()
    source_language = source_language.strip() if source_language else None

    translation_api_key = os.environ.get("TRANSLATION_API_KEY")
    translation_provider = os.environ.get(
        "TRANSLATION_PROVIDER", "deepl"
    ).lower()

    if translation_api_key and translation_provider == "deepl":
        return await _translate_deepl(
            text, target_language, source_language, translation_api_key
        )
    if translation_api_key and translation_provider == "google":
        return await _translate_google(
            text, target_language, source_language, translation_api_key
        )

    # LLM-based fallback
    return await _translate_llm(text, target_language, source_language)


async def _translate_deepl(
    text: str,
    target_language: str,
    source_language: Optional[str],
    api_key: str,
) -> dict:
    """Translate using the DeepL API."""
    try:
        import httpx

        payload: dict = {
            "text": [text],
            "target_lang": target_language.upper(),
        }
        if source_language:
            payload["source_lang"] = source_language.upper()

        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=False,
        ) as client:
            response = await client.post(
                "https://api-free.deepl.com/v2/translate",
                json=payload,
                headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
            )
            response.raise_for_status()
            data = response.json()

        translations = data.get("translations", [])
        if not translations:
            raise ValueError("DeepL returned no translations")
        first = translations[0]
        return {
            "translated": first.get("text", ""),
            "detected_source_language": first.get("detected_source_language"),
        }
    except Exception as exc:
        logger.warning("text_translator_deepl_failed", error=str(exc))
        # Fall back to LLM translation
        return await _translate_llm(text, target_language, source_language)


async def _translate_google(
    text: str,
    target_language: str,
    source_language: Optional[str],
    api_key: str,
) -> dict:
    """Translate using Google Cloud Translation API (v2)."""
    try:
        import httpx

        params: dict = {
            "q": text,
            "target": target_language,
            "key": api_key,
            "format": "text",
        }
        if source_language:
            params["source"] = source_language

        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=False,
        ) as client:
            response = await client.post(
                "https://translation.googleapis.com/language/translate/v2",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

        translations = (
            data.get("data", {}).get("translations", [])
        )
        if not translations:
            raise ValueError("Google Translate returned no translations")
        first = translations[0]
        return {
            "translated": first.get("translatedText", ""),
            "detected_source_language": first.get("detectedSourceLanguage"),
        }
    except Exception as exc:
        logger.warning("text_translator_google_failed", error=str(exc))
        return await _translate_llm(text, target_language, source_language)


async def _translate_llm(
    text: str,
    target_language: str,
    source_language: Optional[str],
) -> dict:
    """
    LLM-based translation fallback.

    Uses a simple prompt to the platform's default LLM. This is a best-effort
    fallback — accuracy depends on the LLM's language capabilities.
    """
    source_clause = (
        f"from {source_language}" if source_language and source_language != "auto"
        else ""
    )
    prompt = (
        f"Translate the following text {source_clause} to {target_language}. "
        "Preserve the original tone and formatting. "
        "Return ONLY the translated text, no commentary or explanation.\n\n"
        f"Text:\n{text}"
    )

    try:
        from app.chat.embedding import _get_llm_client  # type: ignore[import]

        llm_client = _get_llm_client()
        response = await llm_client.complete(prompt)
        translated = response.strip()
    except Exception as exc:
        logger.warning("text_translator_llm_failed", error=str(exc))
        return {
            "translated": text,
            "detected_source_language": None,
            "notice": (
                "Translation service unavailable. "
                "Set TRANSLATION_API_KEY or configure the platform LLM."
            ),
        }

    return {
        "translated": translated,
        "detected_source_language": None,
    }
