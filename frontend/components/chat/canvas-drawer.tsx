"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeftIcon, RefreshCwIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { CodeBlock } from "@/components/ai-elements/code-block";
import { useChatLayout } from "./context";
import { cn } from "@/lib/utils";

interface CanvasDrawerProps {
  conversationId: string;
}

// Dimensions chosen to match brief: chat collapses to ~30-40% on the
// left, canvas takes ~60-70%. We render full-width here because the page
// route already splits the viewport — the drawer just fills its slot.
//
// Below the desktop breakpoint we render a placeholder. The chat side of
// the canvas page is hidden on mobile (so the chat panel doesn't squeeze
// into a narrow rail) — the drawer + placeholder combo means mobile users
// who deep-link to /c/{id}/canvas see a "switch to desktop" message
// rather than a broken layout.
export function CanvasDrawer({ conversationId }: CanvasDrawerProps) {
  const {
    getDesign,
    getDesignStatus,
    refreshDesign,
    revertDesignVersion,
  } = useChatLayout();

  const design = getDesign(conversationId);
  const status = getDesignStatus(conversationId);

  // Hydrate on mount + on conversationId change. The layout's
  // `inflightDesignRef` dedupes parallel requests.
  useEffect(() => {
    if (status === "idle") {
      void refreshDesign(conversationId);
    }
  }, [conversationId, status, refreshDesign]);

  const currentVersion = useMemo(() => {
    if (!design) return null;
    return (
      design.versions.find((v) => v.id === design.current_version_id) ??
      // Fallback: if current_version_id is null but we have versions,
      // show the latest. Should not happen in normal flow but keeps the
      // drawer non-blank if the DB invariant slips.
      design.versions[design.versions.length - 1] ??
      null
    );
  }, [design]);

  return (
    <>
      <DesktopOnlyPlaceholder conversationId={conversationId} />
      <div className="hidden min-w-0 flex-1 flex-col bg-zinc-950 md:flex">
        <DrawerHeader conversationId={conversationId} title={design?.title} />
        <DrawerBody
          status={status}
          currentVersion={currentVersion}
          versions={design?.versions ?? []}
          currentVersionId={design?.current_version_id ?? null}
          onRevert={(versionId) =>
            revertDesignVersion(conversationId, versionId)
          }
          onRetry={() => refreshDesign(conversationId)}
        />
      </div>
    </>
  );
}

function DesktopOnlyPlaceholder({
  conversationId,
}: {
  conversationId: string;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col items-center justify-center gap-3 bg-zinc-950 px-6 text-center md:hidden">
      <p className="text-sm text-zinc-300">
        The design canvas is desktop-only in v1.
      </p>
      <Link
        href={`/c/${conversationId}`}
        className="text-xs text-zinc-500 underline hover:text-zinc-300"
      >
        Back to chat
      </Link>
    </div>
  );
}

function DrawerHeader({
  conversationId,
  title,
}: {
  conversationId: string;
  title: string | null | undefined;
}) {
  return (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b border-zinc-900 bg-black/40 px-4 py-3">
      <div className="flex min-w-0 items-center gap-3">
        <Link
          href={`/c/${conversationId}`}
          aria-label="Close canvas"
          className="rounded-md p-1.5 text-zinc-400 transition-colors hover:bg-zinc-900 hover:text-zinc-200"
        >
          <ArrowLeftIcon size={16} />
        </Link>
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wide text-zinc-500">
            Canvas
          </div>
          <div className="truncate text-sm text-zinc-200">
            {title ?? "Untitled design"}
          </div>
        </div>
      </div>
      {/* Open in Figma button lands in commit 4. */}
    </header>
  );
}

interface DrawerBodyProps {
  status: ReturnType<ReturnType<typeof useChatLayout>["getDesignStatus"]>;
  currentVersion: {
    id: string;
    version_number: number;
    html: string;
  } | null;
  versions: Array<{
    id: string;
    version_number: number;
    edit_scope_selector: string | null;
    created_at: string;
  }>;
  currentVersionId: string | null;
  onRevert: (versionId: string) => void;
  onRetry: () => void;
}

function DrawerBody({
  status,
  currentVersion,
  versions,
  currentVersionId,
  onRevert,
  onRetry,
}: DrawerBodyProps) {
  if (status === "loading" || status === "idle") {
    return (
      <div
        role="status"
        aria-label="Loading canvas"
        className="flex min-h-0 flex-1 items-center justify-center px-6 text-sm text-zinc-500"
      >
        Loading canvas…
      </div>
    );
  }

  if (status === "empty") {
    return <EmptyState />;
  }

  if (status === "error" || !currentVersion) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
        <p className="text-sm text-zinc-300">Couldn't load the design.</p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCwIcon size={14} /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <PreviewCodeTabs html={currentVersion.html} />
      </div>
      <VersionTimeline
        versions={versions}
        currentVersionId={currentVersionId}
        onRevert={onRevert}
      />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
      <p className="text-sm text-zinc-300">No design here yet.</p>
      <p className="max-w-sm text-xs text-zinc-500">
        Ask in the chat for a page, card, layout, or any other UI — the
        first canvas-routed response will appear here.
      </p>
    </div>
  );
}

function PreviewCodeTabs({ html }: { html: string }) {
  return (
    <Tabs
      defaultValue="preview"
      className="flex min-h-0 flex-1 flex-col gap-0"
    >
      <div className="shrink-0 border-b border-zinc-900 px-4 py-2">
        <TabsList>
          <TabsTrigger value="preview">Preview</TabsTrigger>
          <TabsTrigger value="code">Code</TabsTrigger>
        </TabsList>
      </div>
      <TabsContent
        value="preview"
        className="min-h-0 flex-1 bg-white p-0 data-[state=inactive]:hidden"
      >
        <CanvasIframe html={html} />
      </TabsContent>
      <TabsContent
        value="code"
        className="min-h-0 flex-1 overflow-auto p-3 data-[state=inactive]:hidden"
      >
        <CodeBlock code={html} language="html" showLineNumbers />
      </TabsContent>
    </Tabs>
  );
}

function CanvasIframe({ html }: { html: string }) {
  // sandbox="allow-scripts" only — NOT allow-same-origin. The server-baked
  // CSP (connect-src 'none') + the lack of same-origin already neutralize
  // most of what an LLM-generated <script> can do; not granting
  // same-origin keeps it from poking at parent storage / cookies.
  //
  // The helper script in the baked HTML uses `parent.postMessage(..., '*')`
  // which works without same-origin; the click-to-edit listener (Seam 3)
  // hangs off `window.message` to receive it.
  return (
    <iframe
      title="Design preview"
      sandbox="allow-scripts"
      srcDoc={html}
      className="h-full w-full border-0 bg-white"
    />
  );
}

function VersionTimeline({
  versions,
  currentVersionId,
  onRevert,
}: {
  versions: DrawerBodyProps["versions"];
  currentVersionId: string | null;
  onRevert: (versionId: string) => void;
}) {
  // Sorted descending so the newest version is at the top — easier to
  // glance at "what's the latest" without scrolling.
  const ordered = useMemo(
    () => [...versions].sort((a, b) => b.version_number - a.version_number),
    [versions],
  );

  return (
    <aside
      aria-label="Design versions"
      className="flex w-44 shrink-0 flex-col border-l border-zinc-900 bg-black/30"
    >
      <div className="shrink-0 border-b border-zinc-900 px-3 py-2 text-xs uppercase tracking-wide text-zinc-500">
        Versions
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto p-2">
        {ordered.map((v) => {
          const isActive = v.id === currentVersionId;
          return (
            <li key={v.id}>
              <button
                type="button"
                onClick={() => {
                  if (!isActive) onRevert(v.id);
                }}
                aria-current={isActive ? "true" : undefined}
                className={cn(
                  "flex w-full flex-col items-start gap-0.5 rounded-md px-2.5 py-1.5 text-left text-xs transition-colors",
                  isActive
                    ? "bg-zinc-800 text-white"
                    : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200",
                )}
              >
                <span className="font-medium">v{v.version_number}</span>
                <span className="text-[10px] text-zinc-500">
                  {v.edit_scope_selector ? "scoped edit" : "full doc"}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
