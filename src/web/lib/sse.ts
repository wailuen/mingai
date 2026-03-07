import { getStoredToken } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

export interface Source {
  id: string;
  title: string;
  score: number;
  url: string;
  excerpt: string;
}

export type SSEEvent =
  | { type: "status"; data: { stage: string; message: string } }
  | { type: "sources"; data: { sources: Source[] } }
  | { type: "response_chunk"; data: { text: string } }
  | {
      type: "metadata";
      data: {
        retrieval_confidence: number;
        tokens_used: number;
        glossary_expansions: string[];
        profile_context_used: boolean;
        layers_active: string[];
      };
    }
  | { type: "memory_saved"; data: { note_id: string; content: string } }
  | { type: "profile_context_used"; data: { layers_active: string[] } }
  | {
      type: "done";
      data: { conversation_id: string; message_id: string };
    }
  | { type: "error"; data: { code: string; message: string } };

/**
 * Stream chat via SSE from POST /api/v1/chat/stream.
 * Yields typed SSE events as they arrive.
 */
export async function* streamChat(
  query: string,
  conversationId: string | null,
  agentId: string,
): AsyncGenerator<SSEEvent> {
  const token = getStoredToken();

  // fetch() used directly: SSE streaming requires ReadableStream access which
  // apiRequest() in @/lib/api cannot provide (it always resolves .json())
  const response = await fetch(`${API_URL}/api/v1/chat/stream`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      conversation_id: conversationId,
      agent_id: agentId,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Chat request failed: ${response.status} ${errorText}`);
  }

  if (!response.body) {
    throw new Error("Response body is null");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    let currentEvent: string | null = null;

    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ") && currentEvent) {
        try {
          const data = JSON.parse(line.slice(6));
          yield { type: currentEvent, data } as SSEEvent;
        } catch {
          // Skip malformed JSON lines
        }
        currentEvent = null;
      } else if (line.trim() === "") {
        currentEvent = null;
      }
    }
  }
}
