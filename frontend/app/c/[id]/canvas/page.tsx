"use client";

import { use } from "react";
import { ChatPanel } from "@/components/chat/chat-panel";
import { CanvasDrawer } from "@/components/chat/canvas-drawer";

interface PageProps {
  params: Promise<{ id: string }>;
}

// Canvas mode renders the chat panel on the left (~35%) and the design
// drawer on the right (~65%). Mode is in the URL — refresh + back-button
// "preserve" naturally because the route swap drives the layout.
//
// Below the desktop breakpoint we still render the chat panel full-width
// and substitute the drawer with a placeholder (CanvasDrawer handles the
// breakpoint internally so the chat side stays usable on narrow viewports).
export default function CanvasConversationPage({ params }: PageProps) {
  const { id } = use(params);
  return (
    <div className="flex min-h-0 flex-1">
      <div className="hidden min-w-0 flex-col border-r border-zinc-900 md:flex md:w-[35%]">
        <ChatPanel conversationId={id} />
      </div>
      <div className="flex min-w-0 flex-1">
        <CanvasDrawer conversationId={id} />
      </div>
    </div>
  );
}
