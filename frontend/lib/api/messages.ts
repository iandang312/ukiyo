import { API_BASE_URL, ApiError } from "./client";
import { parseSseStream } from "./sse";
import type {
  DeltaEvent,
  DoneEvent,
  MetaEvent,
  StreamErrorEvent,
} from "./types";

export interface StreamHandlers {
  onMeta?: (meta: MetaEvent) => void;
  onDelta?: (delta: DeltaEvent) => void;
  onDone?: (done: DoneEvent) => void;
  onStreamError?: (event: StreamErrorEvent) => void;
  onError?: (error: unknown) => void;
}

// Phase 13: canvas-surface turns add `surface` and (for scoped edits)
// `edit_scope_uid`. Defaults preserve the chat-only call sites — passing
// no options behaves identically to the pre-canvas version of this fn.
export interface StreamMessageOptions {
  surface?: "chat" | "canvas";
  editScopeUid?: number;
}

export async function streamMessage(
  conversationId: string,
  content: string,
  handlers: StreamHandlers,
  options: StreamMessageOptions = {},
  signal?: AbortSignal,
): Promise<void> {
  const body: Record<string, unknown> = { content };
  if (options.surface) body.surface = options.surface;
  if (options.editScopeUid !== undefined) {
    body.edit_scope_uid = options.editScopeUid;
  }

  try {
    const response = await fetch(
      `${API_BASE_URL}/conversations/${conversationId}/messages`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        credentials: "include",
        signal,
      },
    );
    if (!response.ok) {
      let parsed: unknown = null;
      try {
        parsed = await response.json();
      } catch {
        parsed = await response.text().catch(() => null);
      }
      throw new ApiError(response.status, parsed);
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
        case "error":
          handlers.onStreamError?.(data as StreamErrorEvent);
          break;
        default:
          break;
      }
    });
  } catch (err) {
    if ((err as { name?: string })?.name === "AbortError") return;
    handlers.onError?.(err);
  }
}
