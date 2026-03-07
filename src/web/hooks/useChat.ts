"use client";

import { useState, useCallback, useRef } from "react";
import { streamChat, type SSEEvent, type Source } from "@/lib/sse";
import { apiGet } from "@/lib/api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  sources?: Source[];
  retrievalConfidence?: number;
  glossaryExpansions?: string[];
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
  profileContextUsed: boolean;
  layersActive: string[];
  conversationId: string | null;
  statusMessage: string | null;
  error: string | null;
  currentMode: string;
}

export function useChat(agentId: string) {
  const [state, setState] = useState<UseChatState>({
    messages: [],
    streaming: false,
    sources: [],
    retrievalConfidence: null,
    glossaryExpansions: [],
    profileContextUsed: false,
    layersActive: [],
    conversationId: null,
    statusMessage: null,
    error: null,
    currentMode: "auto",
  });

  const abortControllerRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(
    async (query: string, mode?: string) => {
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
      }));

      let currentSources: Source[] = [];
      let currentConfidence: number | null = null;
      let currentExpansions: string[] = [];
      let currentLayers: string[] = [];
      let profileUsed = false;

      try {
        for await (const event of streamChat(
          query,
          state.conversationId,
          agentId,
        )) {
          switch (event.type) {
            case "status":
              setState((prev) => ({
                ...prev,
                statusMessage: event.data.message,
              }));
              break;

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
                    content: lastMsg.content + event.data.text,
                  };
                }
                return { ...prev, messages: msgs, statusMessage: null };
              });
              break;

            case "metadata":
              currentConfidence = event.data.retrieval_confidence;
              currentExpansions = event.data.glossary_expansions ?? [];
              profileUsed = event.data.profile_context_used;
              currentLayers = event.data.layers_active ?? [];
              setState((prev) => ({
                ...prev,
                retrievalConfidence: currentConfidence,
                glossaryExpansions: currentExpansions,
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
      profileContextUsed: false,
      layersActive: [],
      conversationId: null,
      statusMessage: null,
      error: null,
      currentMode: "auto",
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
        profileContextUsed: false,
        layersActive: [],
        conversationId: data.id,
        statusMessage: null,
        error: null,
        currentMode: "auto",
      });
    } catch (err) {
      setState((prev) => ({
        ...prev,
        error:
          err instanceof Error ? err.message : "Failed to load conversation",
      }));
    }
  }, []);

  return {
    ...state,
    sendMessage,
    resetChat,
    loadConversation,
    hasMessages: state.messages.length > 0,
  };
}
