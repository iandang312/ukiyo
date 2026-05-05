"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useChatLayout } from "./context";
import { cn } from "@/lib/utils";

interface ConversationListProps {
  collapsed: boolean;
}

const SKELETON_WIDTHS = ["w-11/12", "w-9/12", "w-7/12"];

export function ConversationList({ collapsed }: ConversationListProps) {
  const { conversations, conversationsLoading } = useChatLayout();
  const params = useParams<{ id?: string }>();
  const activeId = params?.id;

  if (collapsed) return null;

  if (conversationsLoading && conversations.length === 0) {
    return (
      <div
        role="status"
        aria-label="Loading conversations"
        className="flex flex-col gap-1 px-2"
      >
        {SKELETON_WIDTHS.map((width, i) => (
          <div
            key={i}
            className={cn(
              "h-9 animate-pulse rounded-md bg-zinc-900",
              width,
            )}
          />
        ))}
      </div>
    );
  }

  if (conversations.length === 0) {
    return (
      <div
        role="status"
        className="px-3 py-2 text-xs text-zinc-600"
      >
        No conversations yet
      </div>
    );
  }

  return (
    <nav aria-label="Conversations">
      <ul className="flex flex-col gap-0.5 px-2">
        {conversations.map((c) => {
          const isActive = c.id === activeId;
          return (
            <li key={c.id}>
              <Link
                href={`/c/${c.id}`}
                aria-current={isActive ? "page" : undefined}
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
    </nav>
  );
}
