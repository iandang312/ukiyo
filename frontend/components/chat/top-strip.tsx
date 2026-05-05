"use client";

import { MoonIcon, SunIcon } from "lucide-react";
import { useChatLayout } from "./context";
import { ModelPicker } from "./model-picker";

export function TopStrip() {
  const { currentConversation, chatTheme, setChatTheme } = useChatLayout();
  const isDark = chatTheme === "dark";
  return (
    <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-4 text-xs text-muted-foreground">
      {currentConversation ? (
        <ModelPicker />
      ) : (
        <span aria-hidden="true" />
      )}
      <button
        type="button"
        onClick={() => setChatTheme(isDark ? "light" : "dark")}
        aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
        className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
      >
        {isDark ? <SunIcon size={14} /> : <MoonIcon size={14} />}
      </button>
    </div>
  );
}
