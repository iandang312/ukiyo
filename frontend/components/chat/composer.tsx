"use client";

import { ArrowUpIcon } from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { cn } from "@/lib/utils";

interface ComposerProps {
  onSubmit: (content: string) => void;
  disabled?: boolean;
  autoFocus?: boolean;
  placeholder?: string;
}

const LINE_HEIGHT_PX = 24;
const MAX_LINES = 10;
const MAX_HEIGHT_PX = LINE_HEIGHT_PX * MAX_LINES;

export function Composer({
  onSubmit,
  disabled = false,
  autoFocus = false,
  placeholder = "Send a message",
}: ComposerProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const prevDisabledRef = useRef(disabled);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
    el.style.overflowY = el.scrollHeight > MAX_HEIGHT_PX ? "auto" : "hidden";
  }, [text]);

  useEffect(() => {
    if (prevDisabledRef.current && !disabled) {
      textareaRef.current?.focus();
    }
    prevDisabledRef.current = disabled;
  }, [disabled]);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setText("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
      return;
    }
    if (e.key === "Escape" && text.length > 0) {
      e.preventDefault();
      setText("");
    }
  };

  const handleFormSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    submit();
  };

  const canSubmit = text.trim().length > 0 && !disabled;

  return (
    <div className="px-6 pb-6">
      <form
        onSubmit={handleFormSubmit}
        aria-busy={disabled || undefined}
        className="mx-auto w-full max-w-3xl"
      >
        <div
          className={cn(
            "flex items-end gap-2 rounded-2xl border border-zinc-800 bg-zinc-950 px-4 py-3",
            "focus-within:border-zinc-700",
          )}
        >
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            autoFocus={autoFocus}
            rows={1}
            aria-label="Message"
            placeholder={placeholder}
            className={cn(
              "flex-1 resize-none border-0 bg-transparent text-[15px] leading-6 text-white placeholder:text-zinc-600",
              "focus:outline-none disabled:cursor-not-allowed disabled:opacity-60",
            )}
            style={{ maxHeight: MAX_HEIGHT_PX }}
          />
          <button
            type="submit"
            aria-label="Send message"
            disabled={!canSubmit}
            className={cn(
              "flex size-8 shrink-0 items-center justify-center rounded-full transition-colors",
              canSubmit
                ? "bg-white text-black hover:bg-zinc-200"
                : "bg-zinc-800 text-zinc-600",
            )}
          >
            <ArrowUpIcon size={16} />
          </button>
        </div>
      </form>
    </div>
  );
}
