"use client";

import { Streamdown } from "streamdown";
import { SparklesIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useChatLayout } from "./context";
import { cn } from "@/lib/utils";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  model?: string | null;
  isStreaming?: boolean;
  // Phase 13: which surface produced this row. Loaded history infers
  // this from `design_version_id` on the API row; in-flight rows pull
  // it from the streamMessage `surface` option. Defaulting absent
  // → "chat" preserves prior behavior for any code path that doesn't
  // set it explicitly.
  surface?: "chat" | "canvas";
  // Set on canvas-surface assistant rows. Used by the inline thumbnail
  // to look up the version HTML in the loaded design.
  designVersionId?: string | null;
  // Set on chat-surface assistant rows when the meta event included
  // `promote_to_canvas: true`. Carries the user prompt that triggered
  // the suggestion so the promotion button knows what to dispatch.
  promoteToCanvas?: { prompt: string };
}

interface MessageProps {
  message: ChatMessage;
  conversationId: string | null;
}

export function Message({ message, conversationId }: MessageProps) {
  const isUser = message.role === "user";

  // Canvas-surface assistant rows render as a "design vN generated"
  // card with a small iframe thumbnail rather than raw HTML in chat.
  // This avoids dumping multi-kilobyte HTML in the chat transcript and
  // matches the brief's inline-message-rows shape.
  if (
    !isUser &&
    message.surface === "canvas" &&
    !message.isStreaming &&
    message.designVersionId &&
    conversationId
  ) {
    return (
      <DesignVersionRow
        conversationId={conversationId}
        designVersionId={message.designVersionId}
      />
    );
  }

  // Streaming canvas turn — show a compact "generating design…" card so
  // the chat doesn't fill with raw streaming HTML. The drawer is the
  // surface the user actually watches; the chat row is just a marker.
  if (!isUser && message.surface === "canvas" && message.isStreaming) {
    return <DesignGeneratingRow />;
  }

  const label = isUser ? "You" : (message.model ?? "assistant");

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
      {message.promoteToCanvas && conversationId && !message.isStreaming && (
        <PromotionButton
          conversationId={conversationId}
          prompt={message.promoteToCanvas.prompt}
        />
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

function PromotionButton({
  conversationId,
  prompt,
}: {
  conversationId: string;
  prompt: string;
}) {
  const { dispatchCanvasFromPromotion } = useChatLayout();
  return (
    <div className="mt-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => dispatchCanvasFromPromotion(conversationId, prompt)}
        className="gap-2 text-xs"
      >
        <SparklesIcon size={12} />
        Open this in the design canvas
      </Button>
    </div>
  );
}

function DesignGeneratingRow() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-3 rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-xs text-zinc-400"
    >
      <SparklesIcon size={14} className="animate-pulse text-blue-400" />
      Generating design…
    </div>
  );
}

function DesignVersionRow({
  conversationId,
  designVersionId,
}: {
  conversationId: string;
  designVersionId: string;
}) {
  const { getDesign, dispatchCanvasFromVersion } = useChatLayout();
  const design = getDesign(conversationId);
  const version = design?.versions.find((v) => v.id === designVersionId);

  if (!version) {
    // Design not yet hydrated. Render a lightweight placeholder rather
    // than blocking the message list; the row will upgrade to a
    // thumbnail once the layout's design hydration completes.
    return (
      <button
        type="button"
        onClick={() => dispatchCanvasFromVersion(conversationId, designVersionId)}
        className="flex items-center gap-3 rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-xs text-zinc-400 transition-colors hover:bg-zinc-900 hover:text-zinc-200"
      >
        <SparklesIcon size={14} className="text-blue-400" />
        Design generated · open in canvas
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={() => dispatchCanvasFromVersion(conversationId, version.id)}
      aria-label={`Open design v${version.version_number} in canvas`}
      className="group flex w-full max-w-md flex-col overflow-hidden rounded-md border border-zinc-800 bg-zinc-950 transition-colors hover:border-zinc-700"
    >
      <DesignThumbnail html={version.html} />
      <div className="flex items-center justify-between border-t border-zinc-900 px-3 py-2 text-xs">
        <span className="text-zinc-300">
          Design v{version.version_number} generated
        </span>
        <span className="text-zinc-500 group-hover:text-zinc-300">
          Open →
        </span>
      </div>
    </button>
  );
}

function DesignThumbnail({ html }: { html: string }) {
  // Scaled-iframe thumbnail per CONTEXT.md decision #16 — the live HTML
  // doubles as the screenshot. Render the iframe at desktop dimensions
  // and scale it down with CSS so the layout looks like the real thing
  // rather than a mobile-collapsed version.
  //
  // pointer-events-none on the iframe so clicks pass through to the
  // parent button (and so the iframe's helper script's click handler
  // doesn't fire spurious `ukiyo:select` events when the drawer is open).
  return (
    <div className="pointer-events-none relative h-32 w-full overflow-hidden bg-white">
      <iframe
        title="Design thumbnail"
        sandbox="allow-scripts"
        srcDoc={html}
        aria-hidden="true"
        className="absolute left-0 top-0 h-[480px] w-[1200px] origin-top-left scale-[0.27] border-0"
      />
    </div>
  );
}
