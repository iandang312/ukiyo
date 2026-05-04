"use client";

import { Streamdown } from "streamdown";
import { cn } from "@/lib/utils";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  model?: string | null;
  isStreaming?: boolean;
}

interface MessageProps {
  message: ChatMessage;
}

export function Message({ message }: MessageProps) {
  const isUser = message.role === "user";
  const label = isUser ? "You" : message.model ?? "assistant";

  return (
    <div className="flex flex-col gap-2">
      <div
        aria-hidden="true"
        className="text-xs uppercase tracking-wide text-zinc-500"
      >
        {label}
      </div>
      {isUser ? (
        <div className="text-[15px] leading-[1.7] text-white">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
      ) : message.isStreaming ? (
        <div
          role="status"
          aria-live="polite"
          aria-atomic="false"
          aria-label={`${label} response`}
          className="text-[15px] leading-[1.7] text-white"
        >
          <Streamdown>{message.content}</Streamdown>
          <StreamingCursor />
        </div>
      ) : (
        <div className="text-[15px] leading-[1.7] text-white">
          <Streamdown>{message.content}</Streamdown>
        </div>
      )}
    </div>
  );
}

function StreamingCursor() {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "ml-0.5 inline-block h-[1em] w-[2px] translate-y-0.5 bg-zinc-300 align-middle",
        "animate-pulse",
      )}
    />
  );
}
