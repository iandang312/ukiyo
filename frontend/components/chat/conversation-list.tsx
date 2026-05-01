"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useChatLayout } from "./context";
import { cn } from "@/lib/utils";

interface ConversationListProps {
  collapsed: boolean;
}

export function ConversationList({ collapsed }: ConversationListProps) {
  const { conversations, conversationsLoading } = useChatLayout();
  const params = useParams<{ id?: string }>();
  const activeId = params?.id;

  if (collapsed) return null;

  if (conversationsLoading && conversations.length === 0) {
    return (
      <div className="px-3 py-2 text-xs text-zinc-600">Loading…</div>
    );
  }

  if (conversations.length === 0) {
    return (
      <div className="px-3 py-2 text-xs text-zinc-600">No conversations yet</div>
    );
  }

  return (
    <ul className="flex flex-col gap-0.5 px-2">
      {conversations.map((c) => {
        const isActive = c.id === activeId;
        return (
          <li key={c.id}>
            <Link
              href={`/chat/${c.id}`}
              className={cn(
                "block truncate rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-zinc-800 text-white"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200",
              )}
            >
              {c.title ?? "Untitled"}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
