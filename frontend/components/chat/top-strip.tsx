"use client";

import { useChatLayout } from "./context";
import { ModelPicker } from "./model-picker";

export function TopStrip() {
  const { currentConversation } = useChatLayout();
  return (
    <div className="flex h-10 shrink-0 items-center border-b border-zinc-900 px-4 text-xs text-zinc-500">
      {currentConversation ? (
        <ModelPicker />
      ) : (
        <span aria-hidden="true" />
      )}
    </div>
  );
}
