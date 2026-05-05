"use client";

import Link from "next/link";
import { PanelLeftIcon, PanelRightIcon, PlusIcon } from "lucide-react";
import { useState } from "react";
import { ConversationList } from "./conversation-list";
import { cn } from "@/lib/utils";

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={cn(
        "flex shrink-0 flex-col border-r border-border bg-background transition-[width] duration-200 ease-out",
        collapsed ? "w-16" : "w-72",
      )}
    >
      <div
        className={cn(
          "flex items-center px-3 py-3",
          collapsed ? "justify-center" : "justify-between",
        )}
      >
        {!collapsed && (
          <span className="px-1 text-sm font-medium tracking-tight text-foreground">
            ukiyo
          </span>
        )}
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          {collapsed ? (
            <PanelRightIcon size={16} />
          ) : (
            <PanelLeftIcon size={16} />
          )}
        </button>
      </div>

      <div className="px-3 pb-3">
        <Link
          href="/chat"
          className={cn(
            "flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground transition-colors hover:bg-accent",
            collapsed && "justify-center px-0",
          )}
          aria-label="New chat"
        >
          <PlusIcon size={16} className="shrink-0" />
          {!collapsed && <span>New chat</span>}
        </Link>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pb-4">
        <ConversationList collapsed={collapsed} />
      </div>
    </aside>
  );
}
