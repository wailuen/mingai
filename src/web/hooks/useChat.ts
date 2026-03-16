"use client";

import { useState, useCallback, useRef } from "react";
import {
  streamChat,
  type SSEEvent,
  type SSEControlEvent,
  type Source,
  type StreamChatOptions,
} from "@/lib/sse";
import { apiGet } from "@/lib/api";
import type { GlossaryExpansionApplied } from "@/components/chat/TermsInterpreted";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  sources?: Source[];
  retrievalConfidence?: number;
  glossaryExpansions?: string[];
  glossaryExpansionsApplied?: GlossaryExpansionApplied[];
  profileContextUsed?: boolean;
  layersActive?: string[];
  feedbackValue?: 1 | -1 | null;
}

interface ConversationDetailMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

interface ConversationDetail {
  id: string;
  title: string;
  created_at: string;
  messages: ConversationDetailMessage[];
}

interface UseChatState {
  messages: ChatMessage[];
  streaming: boolean;
  sources: Source[];
  retrievalConfidence: number | null;
  glossaryExpansions: string[];
  glossaryExpansionsApplied: GlossaryExpansionApplied[];
  profileContextUsed: boolean;
  layersActive: string[];
  conversationId: string | null;
  statusMessage: string | null;
  error: string | null;
  currentMode: string;
  /** True while SSE stream is attempting to reconnect after a drop */
  reconnecting: boolean;
  /** Non-null when all reconnect attempts have been exhausted */
  reconnectFailed: string | null;
  /** CACHE-018: Whether the last response was a cache hit */
  cacheHit: boolean | null;
  /** CACHE-018: Age in seconds of the cached response */
  cacheAgeSeconds: number | null;
}

export function useChat(agentId: string) {
  const [state, setState] = useState<UseChatState>({
    messages: [],
    streaming: false,
    sources: [],
    retrievalConfidence: null,
    glossaryExpansions: [],
    glossaryExpansionsApplied: [],
    profileContextUsed: false,
    layersActive: [],
    conversationId: null,
    statusMessage: null,
    error: null,
    currentMode: "auto",
    reconnecting: false,
    reconnectFailed: null,
    cacheHit: null,
    cacheAgeSeconds: null,
  });

  const abortControllerRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(
    async (query: string, mode?: string, bypassCache?: boolean) => {
      // Add user message
      const userMessage: ChatMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: query,
        timestamp: new Date().toISOString(),
      };

      // Add empty assistant message placeholder
      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
      };

      setState((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage, assistantMessage],
        streaming: true,
        currentMode: mode ?? "auto",
        error: null,
        statusMessage: null,
        sources: [],
        retrievalConfidence: null,
        glossaryExpansions: [],
        glossaryExpansionsApplied: [],
        reconnecting: false,
        reconnectFailed: null,
        cacheHit: null,
        cacheAgeSeconds: null,
      }));

      let currentSources: Source[] = [];
      let currentConfidence: number | null = null;
      let currentExpansions: string[] = [];
      let currentExpansionsApplied: GlossaryExpansionApplied[] = [];
      let currentLayers: string[] = [];
      let profileUsed = false;

      try {
        const streamOpts: StreamChatOptions | undefined = bypassCache
          ? { extraHeaders: { "X-Cache-Bypass": "true" } }
          : undefined;

        for await (const event of streamChat(
          query,
          state.conversationId,
          agentId,
          streamOpts,
        )) {
          switch (event.type) {
            case "__reconnecting":
              setState((prev) => ({
                ...prev,
                reconnecting: true,
                statusMessage: `Reconnecting... (attempt ${event.data.attempt}/${event.data.maxAttempts})`,
              }));
              break;

            case "__reconnect_failed":
              setState((prev) => ({
                ...prev,
                reconnecting: false,
                reconnectFailed: event.data.message,
                streaming: false,
                statusMessage: null,
                error:
                  "Connection lost \u2014 click retry to try again",
              }));
              break;

            case "status": {
              const stageLabels: Record<string, string> = {
                glossary_expansion: "Expanding glossary terms...",
                intent_detection: "Detecting intent...",
                embedding: "Generating embeddings...",
                vector_search: "Searching knowledge base...",
                context_assembly: "Assembling context...",
                prompt_build: "Building prompt...",
                llm_streaming: "Generating response...",
                post_processing: "Processing response...",
                memory_save: "Saving to memory...",
              };
              setState((prev) => ({
                ...prev,
                reconnecting: false,
                statusMessage:
                  stageLabels[event.data.stage] ?? event.data.stage,
              }));
              break;
            }

            case "sources":
              currentSources = event.data.sources;
              setState((prev) => ({
                ...prev,
                sources: event.data.sources,
              }));
              break;

            case "response_chunk":
              setState((prev) => {
                const msgs = [...prev.messages];
                const lastMsg = msgs[msgs.length - 1];
                if (lastMsg.role === "assistant") {
                  msgs[msgs.length - 1] = {
                    ...lastMsg,
                    content: lastMsg.content + event.data.chunk,
                  };
                }
                return {
                  ...prev,
                  messages: msgs,
                  statusMessage: null,
                  reconnecting: false,
                };
              });
              break;

            case "metadata":
              currentConfidence = event.data.retrieval_confidence;
              currentExpansions = event.data.glossary_expansions ?? [];
              currentExpansionsApplied =
                event.data.glossary_expansions_applied ?? [];
              profileUsed = event.data.profile_context_used;
              currentLayers = event.data.layers_active ?? [];
              setState((prev) => ({
                ...prev,
                retrievalConfidence: currentConfidence,
                glossaryExpansions: currentExpansions,
                glossaryExpansionsApplied: currentExpansionsApplied,
                profileContextUsed: profileUsed,
                layersActive: currentLayers,
              }));
              break;

            case "memory_saved":
              // Trigger toast notification in parent component
              if (typeof window !== "undefined") {
                window.dispatchEvent(
                  new CustomEvent("mingai:memory_saved", {
                    detail: event.data,
                  }),
                );
              }
              break;

            case "profile_context_used":
              currentLayers = event.data.layers_active;
              setState((prev) => ({
                ...prev,
                profileContextUsed: true,
                layersActive: event.data.layers_active,
              }));
              break;

            case "cache_state":
              setState((prev) => ({
                ...prev,
                cacheHit: event.data.hit,
                cacheAgeSeconds: event.data.age_seconds,
              }));
              break;

            case "done":
              setState((prev) => {
                const msgs = [...prev.messages];
                const lastMsg = msgs[msgs.length - 1];
                if (lastMsg.role === "assistant") {
                  msgs[msgs.length - 1] = {
                    ...lastMsg,
                    id: event.data.message_id,
                    sources: currentSources,
                    retrievalConfidence: currentConfidence ?? undefined,
                    glossaryExpansions:
                      currentExpansions.length > 0
                        ? currentExpansions
                        : undefined,
                    glossaryExpansionsApplied:
                      currentExpansionsApplied.length > 0
                        ? currentExpansionsApplied
                        : undefined,
                    profileContextUsed: profileUsed || undefined,
                    layersActive:
                      currentLayers.length > 0 ? currentLayers : undefined,
                  };
                }
                return {
                  ...prev,
                  messages: msgs,
                  conversationId: event.data.conversation_id,
                  streaming: false,
                  statusMessage: null,
                  reconnecting: false,
                  reconnectFailed: null,
                };
              });
              break;

            case "error":
              setState((prev) => ({
                ...prev,
                error: event.data.message,
                streaming: false,
                statusMessage: null,
              }));
              break;
          }
        }
      } catch (err) {
        setState((prev) => ({
          ...prev,
          error:
            err instanceof Error ? err.message : "An unexpected error occurred",
          streaming: false,
          statusMessage: null,
          reconnecting: false,
        }));
      }
    },
    [agentId, state.conversationId],
  );

  const resetChat = useCallback(() => {
    setState({
      messages: [],
      streaming: false,
      sources: [],
      retrievalConfidence: null,
      glossaryExpansions: [],
      glossaryExpansionsApplied: [],
      profileContextUsed: false,
      layersActive: [],
      conversationId: null,
      statusMessage: null,
      error: null,
      currentMode: "auto",
      reconnecting: false,
      reconnectFailed: null,
      cacheHit: null,
      cacheAgeSeconds: null,
    });
  }, []);

  const loadConversation = useCallback(async (conversationId: string) => {
    try {
      const data = await apiGet<ConversationDetail>(
        `/api/v1/conversations/${conversationId}`,
      );
      const loadedMessages: ChatMessage[] = data.messages.map((msg) => ({
        id: msg.id,
        role: msg.role as "user" | "assistant",
        content: msg.content,
        timestamp: msg.created_at,
      }));
      setState({
        messages: loadedMessages,
        streaming: false,
        sources: [],
        retrievalConfidence: null,
        glossaryExpansions: [],
        glossaryExpansionsApplied: [],
        profileContextUsed: false,
        layersActive: [],
        conversationId: data.id,
        statusMessage: null,
        error: null,
        currentMode: "auto",
        reconnecting: false,
        reconnectFailed: null,
        cacheHit: null,
        cacheAgeSeconds: null,
      });
    } catch (err) {
      setState((prev) => ({
        ...prev,
        error:
          err instanceof Error ? err.message : "Failed to load conversation",
      }));
    }
  }, []);

  /** CACHE-018: Re-send the last user message with X-Cache-Bypass: true */
  const bypassCacheAndResend = useCallback(() => {
    const lastUserMsg = [...state.messages]
      .reverse()
      .find((m) => m.role === "user");
    if (!lastUserMsg) return;

    // Remove the cached assistant response + user message; sendMessage will re-add them
    setState((prev) => {
      const msgs = [...prev.messages];
      if (msgs.length > 0 && msgs[msgs.length - 1].role === "assistant") {
        msgs.pop();
      }
      if (msgs.length > 0 && msgs[msgs.length - 1].role === "user") {
        msgs.pop();
      }
      return { ...prev, messages: msgs, error: null };
    });

    sendMessage(lastUserMsg.content, state.currentMode, true);
  }, [state.messages, state.currentMode, sendMessage]);

  const retryLastMessage = useCallback(() => {
    // Find the last user message and re-send it
    const lastUserMsg = [...state.messages]
      .reverse()
      .find((m) => m.role === "user");
    if (!lastUserMsg) return;

    // Remove the failed assistant message (last message) before retrying
    setState((prev) => {
      const msgs = [...prev.messages];
      if (msgs.length > 0 && msgs[msgs.length - 1].role === "assistant") {
        msgs.pop();
      }
      // Also remove the last user message — sendMessage will re-add it
      if (msgs.length > 0 && msgs[msgs.length - 1].role === "user") {
        msgs.pop();
      }
      return {
        ...prev,
        messages: msgs,
        error: null,
        reconnecting: false,
        reconnectFailed: null,
      };
    });

    sendMessage(lastUserMsg.content, state.currentMode);
  }, [state.messages, state.currentMode, sendMessage]);

  return {
    ...state,
    sendMessage,
    resetChat,
    loadConversation,
    retryLastMessage,
    bypassCacheAndResend,
    hasMessages: state.messages.length > 0,
  };
}
