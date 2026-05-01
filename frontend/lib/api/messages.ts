import { API_BASE_URL, ApiError } from "./client";
import { parseSseStream } from "./sse";
import type { DeltaEvent, DoneEvent, MetaEvent } from "./types";

export interface StreamHandlers {
  onMeta?: (meta: MetaEvent) => void;
  onDelta?: (delta: DeltaEvent) => void;
  onDone?: (done: DoneEvent) => void;
  onError?: (error: unknown) => void;
}

export async function streamMessage(
  conversationId: string,
  content: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const response = await fetch(
      `${API_BASE_URL}/conversations/${conversationId}/messages`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ content }),
        credentials: "include",
        signal,
      },
    );
    if (!response.ok) {
      let body: unknown = null;
      try {
        body = await response.json();
      } catch {
        body = await response.text().catch(() => null);
      }
      throw new ApiError(response.status, body);
    }
    await parseSseStream(response, (eventName, data) => {
      switch (eventName) {
        case "meta":
          handlers.onMeta?.(data as MetaEvent);
          break;
        case "delta":
          handlers.onDelta?.(data as DeltaEvent);
          break;
        case "done":
          handlers.onDone?.(data as DoneEvent);
          break;
        default:
          // ignore unknown events; Phase 11 may add `error`
          break;
      }
    });
  } catch (err) {
    if ((err as { name?: string })?.name === "AbortError") return;
    handlers.onError?.(err);
  }
}
