"use client";

import { StickToBottom } from "use-stick-to-bottom";
import { Message, type ChatMessage } from "./message";

interface MessageListProps {
  messages: ChatMessage[];
}

export function MessageList({ messages }: MessageListProps) {
  return (
    <StickToBottom
      className="relative min-h-0 flex-1 overflow-hidden"
      resize="smooth"
      initial="instant"
    >
      <StickToBottom.Content className="flex flex-col gap-10 px-6 py-8">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-10">
          {messages.map((m) => (
            <Message key={m.id} message={m} />
          ))}
        </div>
      </StickToBottom.Content>
    </StickToBottom>
  );
}
