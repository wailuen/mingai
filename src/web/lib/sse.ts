import { getStoredToken } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

export interface Source {
  document_id: string;
  title: string;
  score: number;
  source_url: string | null;
  content: string;
}

export type SSEEvent =
  | { type: "status"; data: { stage: string } }
  | { type: "sources"; data: { sources: Source[] } }
  | { type: "response_chunk"; data: { chunk: string } }
  | {
      type: "metadata";
      data: {
        retrieval_confidence: number;
        tokens_used: number;
        glossary_expansions: string[];
        glossary_expansions_applied?: Array<{
          term: string;
          expansion: string;
        }>;
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

/** Maximum number of automatic reconnection attempts on stream drop */
const MAX_RECONNECT_ATTEMPTS = 3;
/** Base delay (ms) between reconnection attempts — doubles each time */
const RECONNECT_BASE_DELAY = 2000;

/**
 * Internal event emitted to signal reconnection status to consumers.
 * Not part of the backend SSE protocol.
 */
export type SSEControlEvent =
  | { type: "__reconnecting"; data: { attempt: number; maxAttempts: number } }
  | { type: "__reconnect_failed"; data: { message: string } };

/**
 * Stream chat via SSE from POST /api/v1/chat/stream.
 * Yields typed SSE events as they arrive.
 *
 * On mid-stream disconnection the generator will automatically attempt to
 * reconnect up to MAX_RECONNECT_ATTEMPTS times with exponential back-off,
 * sending the last received event ID so the backend can resume.
 * Control events (__reconnecting, __reconnect_failed) are yielded so the UI
 * can show appropriate indicators.
 */
export async function* streamChat(
  query: string,
  conversationId: string | null,
  agentId: string,
): AsyncGenerator<SSEEvent | SSEControlEvent> {
  const token = getStoredToken();
  let lastEventId: string | null = null;
  let reconnectAttempts = 0;
  let shouldReconnect = true;

  while (shouldReconnect) {
    shouldReconnect = false; // reset — only set back to true on recoverable disconnect

    const headers: Record<string, string> = {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    };
    if (lastEventId) {
      headers["Last-Event-ID"] = lastEventId;
    }

    // fetch() used directly: SSE streaming requires ReadableStream access which
    // apiRequest() in @/lib/api cannot provide (it always resolves .json())
    let response: Response;
    try {
      response = await fetch(`${API_URL}/api/v1/chat/stream`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          query,
          conversation_id: conversationId,
          agent_id: agentId,
        }),
      });
    } catch (fetchErr) {
      // Network-level failure (offline, DNS, CORS)
      if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++;
        yield {
          type: "__reconnecting" as const,
          data: {
            attempt: reconnectAttempts,
            maxAttempts: MAX_RECONNECT_ATTEMPTS,
          },
        };
        await delay(RECONNECT_BASE_DELAY * 2 ** (reconnectAttempts - 1));
        shouldReconnect = true;
        continue;
      }
      yield {
        type: "__reconnect_failed" as const,
        data: { message: "Connection lost after multiple attempts" },
      };
      throw fetchErr instanceof Error
        ? fetchErr
        : new Error("Network request failed");
    }

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
    let streamCompleted = false;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          streamCompleted = true;
          break;
        }

        // Successful read resets the reconnect counter
        reconnectAttempts = 0;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        let currentEvent: string | null = null;

        for (const line of lines) {
          if (line.startsWith("id: ")) {
            lastEventId = line.slice(4).trim();
          } else if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ") && currentEvent) {
            try {
              const data = JSON.parse(line.slice(6));
              const event = { type: currentEvent, data } as SSEEvent;
              yield event;
              // If we received "done", stream is fully complete — stop reading
              if (currentEvent === "done") {
                streamCompleted = true;
              }
            } catch {
              // Skip malformed JSON lines
            }
            currentEvent = null;
          } else if (line.trim() === "") {
            currentEvent = null;
          }
        }
        // Exit inner loop as soon as done event is processed
        if (streamCompleted) break;
      }
    } catch (readErr) {
      // Stream interrupted mid-read (network drop, server crash)
      if (!streamCompleted && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++;
        yield {
          type: "__reconnecting" as const,
          data: {
            attempt: reconnectAttempts,
            maxAttempts: MAX_RECONNECT_ATTEMPTS,
          },
        };
        await delay(RECONNECT_BASE_DELAY * 2 ** (reconnectAttempts - 1));
        shouldReconnect = true;
        continue;
      }
      if (!streamCompleted) {
        yield {
          type: "__reconnect_failed" as const,
          data: { message: "Connection lost after multiple attempts" },
        };
      }
      throw readErr instanceof Error
        ? readErr
        : new Error("Stream read failed");
    }

    // If stream completed normally via "done" event, we exit the loop
    if (streamCompleted) break;

    // Stream ended without "done" — treat as unexpected disconnect
    if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      reconnectAttempts++;
      yield {
        type: "__reconnecting" as const,
        data: {
          attempt: reconnectAttempts,
          maxAttempts: MAX_RECONNECT_ATTEMPTS,
        },
      };
      await delay(RECONNECT_BASE_DELAY * 2 ** (reconnectAttempts - 1));
      shouldReconnect = true;
    } else {
      yield {
        type: "__reconnect_failed" as const,
        data: { message: "Connection lost after multiple attempts" },
      };
    }
  }
}

/** Promise-based delay helper */
function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
