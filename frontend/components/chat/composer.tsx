"use client";

import { ArrowUpIcon, Square } from "lucide-react";
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
  onStop?: () => void;
  disabled?: boolean;
  autoFocus?: boolean;
  placeholder?: string;
}

const LINE_HEIGHT_PX = 24;
const MAX_LINES = 10;
const MAX_HEIGHT_PX = LINE_HEIGHT_PX * MAX_LINES;

export function Composer({
  onSubmit,
  onStop,
  disabled = false,
  autoFocus = false,
  placeholder = "Reply to Ukiyo…",
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
  const showStop = disabled && !!onStop;

  return (
    <div className="px-6 pb-6">
      <form
        onSubmit={handleFormSubmit}
        aria-busy={disabled || undefined}
        className="mx-auto w-full max-w-3xl"
      >
        <div
          className={cn(
            "flex items-end gap-2 rounded-2xl border border-border bg-muted/40 px-4 py-3",
            "focus-within:border-ring",
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
              "flex-1 resize-none border-0 bg-transparent text-[15px] leading-6 text-foreground placeholder:text-muted-foreground",
              "focus:outline-none disabled:cursor-not-allowed disabled:opacity-60",
            )}
            style={{ maxHeight: MAX_HEIGHT_PX }}
          />
          {showStop ? (
            <button
              type="button"
              aria-label="Stop generating"
              onClick={() => onStop?.()}
              className={cn(
                "flex size-8 shrink-0 items-center justify-center rounded-full transition-colors",
                "bg-primary text-primary-foreground hover:bg-primary/90",
              )}
            >
              <Square size={14} className="fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              aria-label="Send message"
              disabled={!canSubmit}
              className={cn(
                "flex size-8 shrink-0 items-center justify-center rounded-full transition-colors",
                canSubmit
                  ? "bg-primary text-primary-foreground hover:bg-primary/90"
                  : "bg-muted text-muted-foreground",
              )}
            >
              <ArrowUpIcon size={16} />
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
