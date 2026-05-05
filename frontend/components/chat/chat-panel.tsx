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
    return <HistorySkeleton />;
  }

  const list = messages ?? [];
  const isEmpty = list.length === 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {isEmpty ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-6">
          <h1 className="text-2xl font-light tracking-tight text-foreground">
            What are we building today?
          </h1>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            {STARTER_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                disabled={streaming}
                onClick={() => sendMessage(prompt, conversationId)}
                className="rounded-full border border-border px-4 py-2 text-sm text-foreground transition hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <MessageList messages={list} conversationId={conversationId} />
      )}
      <Composer
        key={conversationId ?? "new"}
        onSubmit={(content) => sendMessage(content, conversationId)}
        disabled={streaming}
        autoFocus
      />
    </div>
  );
}

const STARTER_PROMPTS = [
  "Design a pricing page",
  "Build a landing hero",
  "Refactor a Python function",
  "Explain how OAuth works",
];

function HistorySkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading conversation"
      className="min-h-0 flex-1 overflow-hidden px-6 py-8"
    >
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-10">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex flex-col gap-2">
            <div className="h-3 w-16 animate-pulse rounded bg-muted" />
            <div className="flex flex-col gap-2">
              <div className="h-4 w-full animate-pulse rounded bg-muted" />
              <div className="h-4 w-11/12 animate-pulse rounded bg-muted/70" />
              <div className="h-4 w-8/12 animate-pulse rounded bg-muted" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
