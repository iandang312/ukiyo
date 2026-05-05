"use client";

import { createContext, useContext } from "react";
import type {
  Conversation,
  ConversationPatch,
  Design,
  ModelsResponse,
} from "@/lib/api/types";
import type { ChatMessage } from "./message";

// Phase 13: design state lives at the layout level so:
//  - the chat-panel can render "design vN" inline rows + the promotion
//    button without re-hydrating per-render
//  - the canvas page (a separate route) can read drawer state without
//    its own fetch
//  - state survives route swaps between /c/{id} and /c/{id}/canvas
//
// `designStatusByConv` distinguishes "no canvas turn yet → drawer is
// empty" (`empty`) from "fetch failed → show retry" (`error`) and
// "still fetching" (`loading`). Indexed by conversation id so switching
// conversations doesn't drop the cache.
export type DesignStatus = "idle" | "loading" | "empty" | "error" | "ready";

export interface ChatLayoutContextValue {
  conversations: Conversation[];
  conversationsLoading: boolean;
  refreshConversations: () => Promise<void>;
  currentConversation: Conversation | null;
  currentModel: string | null;
  setCurrentModel: (model: string | null) => void;
  models: ModelsResponse | null;
  patchConversation: (
    id: string,
    patch: ConversationPatch,
  ) => Promise<Conversation>;
  getMessages: (conversationId: string | null) => ChatMessage[] | undefined;
  isStreaming: (conversationId: string | null) => boolean;
  sendMessage: (
    content: string,
    conversationId: string | null,
    options?: { surface?: "chat" | "canvas"; editScopeUid?: number },
  ) => Promise<void>;
  loadHistory: (conversationId: string) => Promise<void>;

  // Phase 13 canvas state
  getDesign: (conversationId: string | null) => Design | null;
  getDesignStatus: (conversationId: string | null) => DesignStatus;
  refreshDesign: (conversationId: string) => Promise<void>;
  revertDesignVersion: (
    conversationId: string,
    versionId: string,
  ) => Promise<void>;

  // Phase 13 promotion + version-thumbnail handlers. These wrap
  // sendMessage / revertDesignVersion + a navigation, expressed as
  // single methods so call sites don't have to thread next/router and
  // sequence the two calls themselves.
  dispatchCanvasFromPromotion: (
    conversationId: string,
    prompt: string,
  ) => Promise<void>;
  dispatchCanvasFromVersion: (
    conversationId: string,
    versionId: string,
  ) => Promise<void>;
}

export const ChatLayoutContext = createContext<ChatLayoutContextValue | null>(
  null,
);

export function useChatLayout(): ChatLayoutContextValue {
  const ctx = useContext(ChatLayoutContext);
  if (!ctx) {
    throw new Error("useChatLayout must be used inside <ChatLayout>");
  }
  return ctx;
}
