"""
InstrumentedLLMClient (P2LLM-009 + P2LLM-011).

Wraps LLM provider adapters with:
- Tenant config lookup (model_source: library | byollm)
- Adapter selection based on tenant config
- Fire-and-forget usage event recording (asyncio.create_task)
- Cost calculation from llm_library pricing (P2LLM-011)

BYOLLM keys are decrypted in-memory, used for one call, then discarded.
They are NEVER logged or stored in any attribute.
"""
import asyncio
import json
import os
import uuid
from typing import Optional

import structlog

from app.core.llm.base import CompletionResponse, LLMProvider
from app.core.tenant_config_service import TenantConfigService

logger = structlog.get_logger()

_PRICING_CACHE_TTL = 3600  # 1 hour


class InstrumentedLLMClient:
    """
    Tenant-aware LLM client that instruments every call with usage tracking.

    Usage::

        client = InstrumentedLLMClient()
        response = await client.complete(
            tenant_id="...",
            messages=[{"role": "user", "content": "Hello"}],
        )
    """

    def __init__(self) -> None:
        self._config_svc = TenantConfigService()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def complete(
        self,
        tenant_id: str,
        messages: list[dict],
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        **kwargs,
    ) -> CompletionResponse:
        """
        Execute a chat completion for a tenant, route through configured adapter,
        and fire-and-forget a usage event.

        Args:
            tenant_id:       UUID string of the calling tenant.
            messages:        OpenAI-compatible messages list.
            user_id:         Optional user UUID for usage attribution.
            conversation_id: Optional conversation UUID for usage attribution.
            **kwargs:        Forwarded to provider (temperature, max_tokens, etc.).

        Returns:
            CompletionResponse from the configured provider.
        """
        adapter, model, model_source = await self._resolve_adapter(tenant_id)

        response = await adapter.complete(messages=messages, model=model, **kwargs)

        # Fire-and-forget usage event — never block the caller
        asyncio.create_task(
            self._write_usage_event(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
                response=response,
                model_source=model_source,
            )
        )

        return response

    async def embed(
        self,
        tenant_id: str,
        texts: list[str],
        **kwargs,
    ) -> list[list[float]]:
        """
        Generate embeddings for a tenant, routing through the configured adapter.

        Falls back to the platform Azure OpenAI embedding provider if BYOLLM
        is configured but doesn't support embeddings.
        """
        from app.core.llm.azure_openai import AzureOpenAIEmbeddingProvider

        model_source_config = await self._config_svc.get(tenant_id, "llm_config")
        model_source = "library"
        if model_source_config and isinstance(model_source_config, dict):
            model_source = model_source_config.get("model_source", "library")

        embedding_model = os.environ.get("EMBEDDING_MODEL", "").strip()
        if not embedding_model:
            raise ValueError(
                "EMBEDDING_MODEL environment variable is required. Set it in .env."
            )

        # Embeddings always route through platform provider (BYOLLM embedding TBD)
        provider = AzureOpenAIEmbeddingProvider()
        return await provider.embed(texts=texts, model=embedding_model)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_adapter(self, tenant_id: str) -> tuple[LLMProvider, str, str]:
        """
        Resolve the LLM adapter, model name, and model_source for a tenant.

        Returns:
            (adapter, model_name, model_source)

        Raises:
            ValueError: If configuration is missing or invalid.
        """
        llm_config = await self._config_svc.get(tenant_id, "llm_config")

        model_source = "library"
        llm_library_id = None

        if llm_config and isinstance(llm_config, dict):
            model_source = llm_config.get("model_source", "library")
            llm_library_id = llm_config.get("llm_library_id")

        if model_source == "byollm":
            return await self._resolve_byollm_adapter(tenant_id)

        # Library mode — use platform Azure OpenAI
        return await self._resolve_library_adapter(llm_library_id)

    async def _resolve_library_adapter(
        self, llm_library_id: Optional[str]
    ) -> tuple[LLMProvider, str, str]:
        """Resolve adapter for library mode."""
        from app.core.llm.azure_openai import AzureOpenAIProvider

        primary_model = os.environ.get("PRIMARY_MODEL", "").strip()
        if not primary_model:
            raise ValueError(
                "PRIMARY_MODEL environment variable is required. Set it in .env."
            )

        # If a library entry is specified, try to read its model_name
        if llm_library_id:
            try:
                from app.core.session import async_session_factory
                from sqlalchemy import text

                async with async_session_factory() as session:
                    result = await session.execute(
                        text(
                            "SELECT model_name FROM llm_library "
                            "WHERE id = :id AND status = 'Published'"
                        ),
                        {"id": llm_library_id},
                    )
                    row = result.fetchone()
                    if row:
                        primary_model = row[0]
            except Exception as exc:
                logger.warning(
                    "instrumented_client_library_lookup_failed",
                    llm_library_id=llm_library_id,
                    error=str(exc),
                )

        adapter = AzureOpenAIProvider()
        return adapter, primary_model, "library"

    async def _resolve_byollm_adapter(
        self, tenant_id: str
    ) -> tuple[LLMProvider, str, str]:
        """Resolve adapter for BYOLLM mode — decrypt key in-memory only."""
        byollm_config = await self._config_svc.get(tenant_id, "byollm_key_ref")
        if not byollm_config or not isinstance(byollm_config, dict):
            raise ValueError(
                f"BYOLLM is configured but no key ref found for tenant {tenant_id!r}. "
                "Use PATCH /admin/llm-config/byollm to set credentials."
            )

        encrypted_key_ref = byollm_config.get("encrypted_key_ref")
        if not encrypted_key_ref:
            raise ValueError(f"BYOLLM key ref is empty for tenant {tenant_id!r}.")

        provider = byollm_config.get("provider", "openai_direct")
        endpoint = byollm_config.get("endpoint")

        # Decrypt in-memory — key never stored in any attribute
        from app.modules.har.crypto import get_fernet

        fernet = get_fernet()
        plaintext_key = fernet.decrypt(encrypted_key_ref.encode("ascii")).decode(
            "utf-8"
        )

        model = os.environ.get("PRIMARY_MODEL", "").strip() or "gpt-4o"

        if provider == "azure_openai":
            from openai import AsyncAzureOpenAI

            if not endpoint:
                raise ValueError(
                    f"BYOLLM azure_openai requires endpoint for tenant {tenant_id!r}."
                )
            api_version = os.environ.get(
                "AZURE_PLATFORM_OPENAI_API_VERSION", "2024-02-01"
            )
            client = AsyncAzureOpenAI(
                api_key=plaintext_key,
                azure_endpoint=endpoint,
                api_version=api_version,
            )
            # plaintext_key will be GC'd after this scope
            from app.core.llm.azure_openai import AzureOpenAIProvider
            import time

            class _ByoAzureAdapter(LLMProvider):
                def __init__(self, _client):
                    self._client = _client

                async def complete(self, messages, model, **kwargs):
                    start = time.time()
                    resp = await self._client.chat.completions.create(
                        model=model, messages=messages, **kwargs
                    )
                    latency_ms = int((time.time() - start) * 1000)
                    content = resp.choices[0].message.content or ""
                    tokens_in = resp.usage.prompt_tokens if resp.usage else 0
                    tokens_out = resp.usage.completion_tokens if resp.usage else 0
                    return CompletionResponse(
                        content=content,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        model=model,
                        provider="azure_openai",
                        latency_ms=latency_ms,
                    )

            return _ByoAzureAdapter(client), model, "byollm"

        else:
            # openai_direct
            from app.core.llm.openai_direct import OpenAIDirectProvider

            adapter = OpenAIDirectProvider(api_key=plaintext_key)
            # plaintext_key will be GC'd after this scope
            return adapter, model, "byollm"

    async def _write_usage_event(
        self,
        tenant_id: str,
        user_id: Optional[str],
        conversation_id: Optional[str],
        response: CompletionResponse,
        model_source: str,
    ) -> None:
        """
        Write a usage_event row to PostgreSQL.

        Non-blocking (called via create_task). Never raises to caller.
        Cost is calculated from llm_library pricing when available.
        """
        try:
            cost_usd = await self._calculate_cost(
                model_source=model_source,
                model=response.model,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
            )

            from app.core.session import async_session_factory
            from sqlalchemy import text

            async with async_session_factory() as session:
                await session.execute(
                    text(
                        "INSERT INTO usage_events ("
                        "  id, tenant_id, user_id, conversation_id, "
                        "  provider, model, tokens_in, tokens_out, "
                        "  model_source, cost_usd, latency_ms"
                        ") VALUES ("
                        "  :id, :tenant_id, :user_id, :conversation_id, "
                        "  :provider, :model, :tokens_in, :tokens_out, "
                        "  :model_source, :cost_usd, :latency_ms"
                        ")"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "provider": response.provider,
                        "model": response.model,
                        "tokens_in": response.tokens_in,
                        "tokens_out": response.tokens_out,
                        "model_source": model_source,
                        "cost_usd": str(cost_usd) if cost_usd is not None else None,
                        "latency_ms": response.latency_ms,
                    },
                )
                await session.commit()

            logger.debug(
                "usage_event_written",
                tenant_id=tenant_id,
                model=response.model,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                cost_usd=cost_usd,
            )
        except Exception as exc:
            # Non-blocking — log and swallow
            logger.warning(
                "usage_event_write_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )

    async def _calculate_cost(
        self,
        model_source: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
    ) -> Optional[float]:
        """
        Calculate cost_usd from pricing data.

        For library source: look up from llm_library table (Redis-cached, TTL 3600s).
        For BYOLLM or lookup failure: use BYOLLM_COST_PER_1K_IN_USD env var.
        Returns None if cost cannot be calculated.
        """
        try:
            price_in: Optional[float] = None
            price_out: Optional[float] = None

            if model_source == "library":
                pricing = await self._get_library_pricing(model)
                if pricing:
                    price_in = pricing.get("price_in")
                    price_out = pricing.get("price_out")

            if price_in is None:
                byollm_in = os.environ.get("BYOLLM_COST_PER_1K_IN_USD", "0.0")
                byollm_out = os.environ.get("BYOLLM_COST_PER_1K_OUT_USD", "0.0")
                try:
                    price_in = float(byollm_in)
                    price_out = float(byollm_out)
                except (ValueError, TypeError):
                    return None

            if price_in is None or price_out is None:
                return None

            cost = (tokens_in / 1000.0 * price_in) + (tokens_out / 1000.0 * price_out)
            return round(cost, 8)

        except Exception as exc:
            logger.warning(
                "cost_calculation_failed",
                model=model,
                error=str(exc),
            )
            return None

    async def _get_library_pricing(self, model: str) -> Optional[dict]:
        """
        Get pricing from llm_library table, Redis-cached for 3600s.

        Returns dict with keys 'price_in', 'price_out' or None.
        """
        # Raw Redis key (not tenant-scoped — library pricing is global)
        cache_key = f"mingai:platform:pricing:{model}"
        try:
            from app.core.redis_client import get_redis

            redis = get_redis()
            raw = await redis.get(cache_key)
            if raw is not None:
                return json.loads(raw)
        except Exception:
            pass

        try:
            from app.core.session import async_session_factory
            from sqlalchemy import text

            async with async_session_factory() as session:
                result = await session.execute(
                    text(
                        "SELECT pricing_per_1k_tokens_in, pricing_per_1k_tokens_out "
                        "FROM llm_library "
                        "WHERE model_name = :model AND status = 'Published' "
                        "LIMIT 1"
                    ),
                    {"model": model},
                )
                row = result.fetchone()
                if row and row[0] is not None and row[1] is not None:
                    pricing = {
                        "price_in": float(row[0]),
                        "price_out": float(row[1]),
                    }
                    # Cache for 1 hour
                    try:
                        from app.core.redis_client import get_redis

                        redis = get_redis()
                        await redis.setex(
                            cache_key,
                            _PRICING_CACHE_TTL,
                            json.dumps(pricing),
                        )
                    except Exception:
                        pass
                    return pricing
        except Exception as exc:
            logger.warning(
                "library_pricing_lookup_failed",
                model=model,
                error=str(exc),
            )

        return None
