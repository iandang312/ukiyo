"use client";

import { ChevronDownIcon } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useChatLayout } from "./context";

const BUCKET_LABELS: Record<string, string> = {
  coding: "Coding",
  design: "Design",
  research: "Research",
};

export function ModelPicker() {
  const { currentConversation, currentModel, models, patchConversation } =
    useChatLayout();

  if (!currentConversation || !models) {
    return <span aria-hidden="true" />;
  }

  const conv = currentConversation;
  const pinnedModel = conv.pinned_model;
  const autoRouteOn = conv.auto_route_enabled && pinnedModel === null;
  const triggerLabel = pinnedModel ?? currentModel ?? models.generalist;

  const onSelectAutoRoute = async () => {
    if (autoRouteOn) return;
    try {
      await patchConversation(conv.id, {
        pinned_model: null,
        auto_route_enabled: true,
      });
    } catch {
      // patchConversation already console.errors and reverts the optimistic
      // update; no toast until Phase 10.
    }
  };

  const onSelectModel = async (model: string) => {
    if (pinnedModel === model) return;
    try {
      await patchConversation(conv.id, {
        pinned_model: model,
        auto_route_enabled: false,
      });
    } catch {
      // see above
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="Change model"
        className="flex items-center gap-1 font-mono text-xs tracking-tight text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:text-foreground"
      >
        <span>{triggerLabel}</span>
        <ChevronDownIcon size={12} aria-hidden="true" />
        <span className="sr-only">{`Answering with ${triggerLabel}`}</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="min-w-56 border-border bg-popover text-popover-foreground"
      >
        <DropdownMenuCheckboxItem
          checked={autoRouteOn}
          onCheckedChange={() => onSelectAutoRoute()}
          className="focus:bg-accent focus:text-accent-foreground"
        >
          <span>Auto-route</span>
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator className="bg-border" />
        {Object.entries(models.buckets).map(([bucket, model]) => (
          <DropdownMenuCheckboxItem
            key={bucket}
            checked={pinnedModel === model}
            onCheckedChange={() => onSelectModel(model)}
            className="focus:bg-accent focus:text-accent-foreground"
          >
            <div className="flex flex-col">
              <span>{BUCKET_LABELS[bucket] ?? bucket}</span>
              <span className="font-mono text-xs text-muted-foreground">
                {model}
              </span>
            </div>
          </DropdownMenuCheckboxItem>
        ))}
        <DropdownMenuSeparator className="bg-border" />
        <DropdownMenuCheckboxItem
          checked={pinnedModel === models.generalist}
          onCheckedChange={() => onSelectModel(models.generalist)}
          className="focus:bg-accent focus:text-accent-foreground"
        >
          <div className="flex flex-col">
            <span>Generalist</span>
            <span className="font-mono text-xs text-muted-foreground">
              {models.generalist}
            </span>
          </div>
        </DropdownMenuCheckboxItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
