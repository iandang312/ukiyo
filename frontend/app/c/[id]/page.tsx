"use client";

import { use } from "react";
import { ChatPanel } from "@/components/chat/chat-panel";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function ChatConversationPage({ params }: PageProps) {
  const { id } = use(params);
  return <ChatPanel conversationId={id} />;
}
