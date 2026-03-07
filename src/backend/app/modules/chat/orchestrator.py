"""
ChatOrchestrationService (AI-056) - The 8-stage RAG pipeline orchestrator.

Wires all AI services into a streaming SSE response pipeline:
  Stage 1: Glossary expansion (query pre-translation)
  Stage 2: Intent detection (reserved for future routing)
  Stage 3: Embedding generation (uses ORIGINAL query, NOT expanded)
  Stage 4: Vector search (tenant-scoped, agent-scoped)
  Stage 5: Context assembly (profile, working memory, org context, team memory)
  Stage 6: System prompt build (6-layer with token budgets)
  Stage 7: LLM streaming (response generation)
  Stage 8: Post-processing (persistence, memory update, profile learning)

Memory fast path: "Remember that..." / "Remember:..." / "Please remember..." /
"Note that..." / "Save this:..." queries bypass RAG and save directly to memory notes.
"""
import os
import re
from typing import AsyncGenerator

import structlog

logger = structlog.get_logger()

# Memory command patterns that trigger the fast path (AI-024)
# Each pattern uses ^ to match only at the start of the query.
# Note: "please remember" intentionally does not require "that" (colon-less short form);
# bare "remember" without "that" or ":" does NOT trigger the fast path by design.
_MEMORY_COMMAND_PATTERNS = [
    re.compile(r"^remember\s+that\s+", re.IGNORECASE),
    re.compile(r"^remember\s*:\s*", re.IGNORECASE),
    re.compile(r"^please\s+remember\s+", re.IGNORECASE),
    re.compile(r"^note\s+that\s+", re.IGNORECASE),
    re.compile(r"^save\s+this\s*:\s*", re.IGNORECASE),
]

# Maximum length for memory note content
MAX_MEMORY_NOTE_LENGTH = 200


class ChatOrchestrationService:
    """
    Orchestrates the 8-stage RAG pipeline for chat responses.

    All services are injected via constructor. This service coordinates
    them into a streaming SSE event sequence.
    """

    def __init__(
        self,
        *,
        embedding_service,
        vector_search_service,
        profile_service,
        working_memory_service,
        org_context_service,
        glossary_expander,
        prompt_builder,
        persistence_service,
        confidence_calculator,
        team_memory_service=None,
        llm_service=None,
    ):
        self._embedding = embedding_service
        self._vector_search = vector_search_service
        self._profile = profile_service
        self._working_memory = working_memory_service
        self._org_context = org_context_service
        self._glossary = glossary_expander
        self._prompt_builder = prompt_builder
        self._persistence = persistence_service
        self._confidence = confidence_calculator
        self._team_memory = team_memory_service
        self._llm_service = llm_service

    async def stream_response(
        self,
        *,
        query: str,
        user_id: str,
        tenant_id: str,
        agent_id: str,
        conversation_id: str | None,
        active_team_id: str | None,
        jwt_claims: dict,
    ) -> AsyncGenerator[dict, None]:
        """
        Execute the 8-stage RAG pipeline and yield SSE events.

        Args:
            query: The user's query text.
            user_id: Authenticated user ID.
            tenant_id: Tenant ID for multi-tenant isolation.
            agent_id: Agent ID for agent-specific behavior.
            conversation_id: Existing conversation ID, or None for new.
            active_team_id: Team ID if team context applies, or None.
            jwt_claims: JWT claims dict for org context extraction.

        Yields:
            SSE event dicts with "event" and "data" keys.
        """
        if not query or not query.strip():
            raise ValueError("query is required and cannot be empty.")
        if not user_id:
            raise ValueError("user_id is required for chat orchestration.")
        if not tenant_id:
            raise ValueError("tenant_id is required for chat orchestration.")
        if not agent_id:
            raise ValueError("agent_id is required for chat orchestration.")

        # Check for memory fast path before entering RAG pipeline
        memory_content = self._extract_memory_command(query)
        if memory_content is not None:
            async for event in self._handle_memory_fast_path(
                content=memory_content,
                user_id=user_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                conversation_id=conversation_id,
            ):
                yield event
            return

        # --- Stage 1: Glossary Expansion ---
        yield {"event": "status", "data": {"stage": "glossary_expansion"}}

        expanded_query, glossary_expansions = await self._glossary.expand(
            query, tenant_id=tenant_id
        )

        logger.info(
            "stage_1_glossary",
            original_query=query,
            expanded_query=expanded_query,
            expansions_count=len(glossary_expansions),
            tenant_id=tenant_id,
        )

        # --- Stage 3: Embedding (uses ORIGINAL query, NOT expanded) ---
        yield {"event": "status", "data": {"stage": "embedding"}}

        query_vector = await self._embedding.embed(query)

        logger.info(
            "stage_3_embedding",
            query=query,
            vector_dim=len(query_vector),
            tenant_id=tenant_id,
        )

        # --- Stage 4: Vector Search ---
        yield {"event": "status", "data": {"stage": "vector_search"}}

        search_results = await self._vector_search.search(
            query_vector=query_vector,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )

        # Calculate retrieval confidence
        retrieval_confidence = self._confidence.calculate(search_results)

        # Emit sources event
        sources_data = [
            r.to_dict() if hasattr(r, "to_dict") else r for r in search_results
        ]
        yield {
            "event": "sources",
            "data": {"sources": sources_data},
        }

        logger.info(
            "stage_4_search",
            result_count=len(search_results),
            confidence=retrieval_confidence,
            tenant_id=tenant_id,
        )

        # --- Stage 5: Context Assembly ---
        yield {"event": "status", "data": {"stage": "context_assembly"}}

        profile_context = await self._profile.get_profile_context(
            user_id=user_id, tenant_id=tenant_id
        )

        working_memory_context = await self._working_memory.get_for_prompt(
            user_id=user_id, tenant_id=tenant_id, agent_id=agent_id
        )

        org_context_data = await self._org_context.get(user_id, tenant_id, jwt_claims)
        org_context_dict = org_context_data.to_dict() if org_context_data else {}

        # Team memory: only fetch if active_team_id is set and service exists
        team_memory_context = None
        if active_team_id is not None and self._team_memory is not None:
            team_memory_context = await self._team_memory.get_context(
                team_id=active_team_id, tenant_id=tenant_id
            )

        logger.info(
            "stage_5_context",
            has_profile=bool(profile_context),
            has_working_memory=bool(working_memory_context),
            has_org_context=bool(org_context_dict),
            has_team_memory=team_memory_context is not None,
            tenant_id=tenant_id,
        )

        # --- Stage 6: System Prompt Build ---
        yield {"event": "status", "data": {"stage": "prompt_build"}}

        system_prompt, layers_active = await self._prompt_builder.build(
            agent_id=agent_id,
            tenant_id=tenant_id,
            org_context=org_context_dict,
            profile_context=profile_context,
            working_memory=working_memory_context,
            team_memory=team_memory_context,
            rag_context=search_results,
        )

        logger.info(
            "stage_6_prompt",
            layers_active=layers_active,
            prompt_length=len(system_prompt),
            tenant_id=tenant_id,
        )

        # --- Stage 7: LLM Streaming (real call) ---
        yield {"event": "status", "data": {"stage": "llm_streaming"}}

        response_chunks = []
        async for chunk in self._stream_llm(
            system_prompt=system_prompt,
            query=expanded_query,
            tenant_id=tenant_id,
        ):
            response_chunks.append(chunk)
            yield {"event": "response_chunk", "data": {"chunk": chunk}}
        response_text = "".join(response_chunks)

        # --- Stage 8: Post-processing ---
        yield {"event": "status", "data": {"stage": "post_processing"}}

        # Persist the exchange
        message_id, final_conversation_id = await self._persistence.save_exchange(
            user_id=user_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            query=query,
            response=response_text,
            sources=search_results,
        )

        # Update working memory with this query
        await self._working_memory.update(
            user_id=user_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            query=query,
            response=response_text,
        )

        # Update team working memory (anonymized, no user_id stored)
        if active_team_id and self._team_memory is not None:
            await self._team_memory.update(
                team_id=active_team_id,
                tenant_id=tenant_id,
                query=query,
                response=response_text,
            )

        # Trigger profile learning
        await self._profile.on_query_completed(
            user_id=user_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )

        logger.info(
            "stage_8_postprocessing",
            message_id=message_id,
            conversation_id=final_conversation_id,
            tenant_id=tenant_id,
        )

        # AI-034: profile_context_used — true when any personalisation layer contributed
        _PROFILE_LAYERS = {"profile", "working_memory", "org_context", "team_memory"}
        profile_context_used = bool(_PROFILE_LAYERS.intersection(layers_active))

        # Emit metadata event
        yield {
            "event": "metadata",
            "data": {
                "retrieval_confidence": retrieval_confidence,
                "glossary_expansions": glossary_expansions,
                "profile_context_used": profile_context_used,
                "layers_active": layers_active,
            },
        }

        # Emit done event (always last)
        yield {
            "event": "done",
            "data": {
                "conversation_id": final_conversation_id,
                "message_id": message_id,
            },
        }

    def _extract_memory_command(self, query: str) -> str | None:
        """
        Check if query is a memory command and extract content.

        Returns the memory content string if it matches a memory pattern,
        or None if it's a normal query.
        """
        for pattern in _MEMORY_COMMAND_PATTERNS:
            match = pattern.search(query)
            if match:
                content = query[match.end() :].strip()
                return content
        return None

    async def _handle_memory_fast_path(
        self,
        *,
        content: str,
        user_id: str,
        tenant_id: str,
        agent_id: str,
        conversation_id: str | None,
    ) -> AsyncGenerator[dict, None]:
        """
        Handle memory command fast path -- bypasses RAG stages 2-7.

        Saves the memory note and emits memory_saved + done events.
        """
        logger.info(
            "memory_fast_path",
            content_length=len(content),
            user_id=user_id,
            tenant_id=tenant_id,
        )

        # AI-024: If content exceeds 200 chars, return error SSE — do NOT truncate silently
        if len(content) > MAX_MEMORY_NOTE_LENGTH:
            yield {
                "event": "error",
                "data": {
                    "code": "memory_note_too_long",
                    "message": (
                        f"Memory note too long ({len(content)} chars). "
                        f"Maximum is {MAX_MEMORY_NOTE_LENGTH} characters."
                    ),
                },
            }
            yield {
                "event": "done",
                "data": {"conversation_id": conversation_id, "message_id": None},
            }
            return

        yield {"event": "status", "data": {"stage": "memory_save"}}

        note = await self._working_memory.add_note(
            user_id=user_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            content=content,
        )

        yield {
            "event": "memory_saved",
            "data": {
                "note_id": note.id,
                "content": note.content,
            },
        }

        yield {
            "event": "done",
            "data": {
                "conversation_id": conversation_id,
                "message_id": None,
                "memory_saved": True,
            },
        }

    async def _stream_llm(
        self,
        *,
        system_prompt: str,
        query: str,
        tenant_id: str,
    ) -> AsyncGenerator[str, None]:
        """
        Stream LLM response chunks from the configured provider.

        If an llm_service was injected (has a `stream` async generator method),
        delegates to it. Otherwise, reads PRIMARY_MODEL from env (raises
        ValueError if not set) and selects client based on CLOUD_PROVIDER:
          - 'azure': AsyncAzureOpenAI with AZURE_PLATFORM_OPENAI_API_KEY/ENDPOINT
          - otherwise: AsyncOpenAI (reads OPENAI_API_KEY from env)

        Yields:
            String chunks of the LLM response.
        """
        # If an LLM service was injected (e.g., for testing), delegate to it
        if self._llm_service is not None:
            async for chunk in self._llm_service.stream(
                system_prompt=system_prompt,
                query=query,
                tenant_id=tenant_id,
            ):
                yield chunk
            return

        model = os.environ.get("PRIMARY_MODEL", "").strip()
        if not model:
            raise ValueError(
                "PRIMARY_MODEL environment variable is required for LLM streaming. "
                "Set it in .env to the deployment/model name."
            )

        cloud_provider = os.environ.get("CLOUD_PROVIDER", "local").strip()

        if cloud_provider == "azure":
            from openai import AsyncAzureOpenAI

            api_key = os.environ.get("AZURE_PLATFORM_OPENAI_API_KEY", "").strip()
            endpoint = os.environ.get("AZURE_PLATFORM_OPENAI_ENDPOINT", "").strip()
            if not api_key:
                raise ValueError(
                    "AZURE_PLATFORM_OPENAI_API_KEY is required when CLOUD_PROVIDER=azure."
                )
            if not endpoint:
                raise ValueError(
                    "AZURE_PLATFORM_OPENAI_ENDPOINT is required when CLOUD_PROVIDER=azure."
                )
            client = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=endpoint,
                api_version="2024-02-01",
            )
        else:
            from openai import AsyncOpenAI

            client = AsyncOpenAI()

        logger.info(
            "llm_stream_start",
            model=model,
            cloud_provider=cloud_provider,
            tenant_id=tenant_id,
        )

        stream = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
