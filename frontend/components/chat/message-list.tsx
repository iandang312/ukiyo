"use client";

import { StickToBottom } from "use-stick-to-bottom";
import { Message, type ChatMessage } from "./message";

interface MessageListProps {
  messages: ChatMessage[];
  conversationId: string | null;
}

export function MessageList({ messages, conversationId }: MessageListProps) {
  return (
    <StickToBottom
      className="relative min-h-0 flex-1 overflow-hidden"
      resize="smooth"
      initial="instant"
    >
      <StickToBottom.Content className="flex flex-col gap-12 px-6 py-8">
        <div
          role="log"
          aria-label="Conversation"
          aria-live="off"
          className="mx-auto flex w-full max-w-3xl flex-col gap-12"
        >
          {messages.map((m) => (
            <div
              key={m.id}
              className="animate-in fade-in slide-in-from-bottom-1 duration-300"
            >
              <Message message={m} conversationId={conversationId} />
            </div>
          ))}
        </div>
      </StickToBottom.Content>
    </StickToBottom>
  );
}
