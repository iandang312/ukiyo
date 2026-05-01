"use client";

import { useChatLayout } from "./context";

export function TopStrip() {
  const { currentModel } = useChatLayout();
  return (
    <div className="flex h-10 shrink-0 items-center border-b border-zinc-900 px-4 text-xs text-zinc-500">
      {currentModel ? (
        <span className="font-mono tracking-tight">{currentModel}</span>
      ) : null}
    </div>
  );
}
