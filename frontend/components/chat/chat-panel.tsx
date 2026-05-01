"use client";

import { useEffect } from "react";
import { Composer } from "./composer";
import { MessageList } from "./message-list";
import { useChatLayout } from "./context";

interface ChatPanelProps {
  conversationId: string | null;
}

export function ChatPanel({ conversationId }: ChatPanelProps) {
  const {
    getMessages,
    isStreaming,
    sendMessage,
    loadHistory,
    setCurrentModel,
  } = useChatLayout();

  useEffect(() => {
    if (conversationId) {
      loadHistory(conversationId);
    } else {
      setCurrentModel(null);
    }
  }, [conversationId, loadHistory, setCurrentModel]);

  const messages = getMessages(conversationId);
  const streaming = isStreaming(conversationId);

  useEffect(() => {
    if (!conversationId || !messages) return;
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role === "assistant" && m.model) {
        setCurrentModel(m.model);
        return;
      }
    }
    setCurrentModel(null);
  }, [conversationId, messages, setCurrentModel]);

  if (conversationId && messages === undefined) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-zinc-600">
        Loading…
      </div>
    );
  }

  const list = messages ?? [];
  const isEmpty = list.length === 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {isEmpty ? (
        <div className="flex min-h-0 flex-1 items-center justify-center px-6">
          <h1 className="text-2xl font-light tracking-tight text-zinc-400">
            What can I help with?
          </h1>
        </div>
      ) : (
        <MessageList messages={list} />
      )}
      <Composer
        onSubmit={(content) => sendMessage(content, conversationId)}
        disabled={streaming}
        autoFocus
      />
    </div>
  );
}
