"use client";

import { createContext, useContext } from "react";
import type { Conversation } from "@/lib/api/types";
import type { ChatMessage } from "./message";

export interface ChatLayoutContextValue {
  conversations: Conversation[];
  conversationsLoading: boolean;
  refreshConversations: () => Promise<void>;
  currentModel: string | null;
  setCurrentModel: (model: string | null) => void;
  getMessages: (conversationId: string | null) => ChatMessage[] | undefined;
  isStreaming: (conversationId: string | null) => boolean;
  sendMessage: (content: string, conversationId: string | null) => Promise<void>;
  loadHistory: (conversationId: string) => Promise<void>;
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
