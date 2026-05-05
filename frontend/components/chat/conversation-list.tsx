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
              "h-9 animate-pulse rounded-md bg-muted",
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
        className="px-3 py-2 text-xs text-muted-foreground"
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
                href={`/chat/${c.id}`}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "block truncate rounded-md px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground",
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
