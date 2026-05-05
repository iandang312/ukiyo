"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowLeftIcon,
  RefreshCwIcon,
  SendHorizontalIcon,
  XIcon,
} from "lucide-react";
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

interface SelectionState {
  uid: string;
  tag: string;
  rect?: { x: number; y: number; width: number; height: number };
}

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
          conversationId={conversationId}
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
  conversationId: string;
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
  conversationId,
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
        <PreviewCodeTabs
          html={currentVersion.html}
          conversationId={conversationId}
        />
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

function PreviewCodeTabs({
  html,
  conversationId,
}: {
  html: string;
  conversationId: string;
}) {
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
        <CanvasIframe html={html} conversationId={conversationId} />
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

function CanvasIframe({
  html,
  conversationId,
}: {
  html: string;
  conversationId: string;
}) {
  // sandbox="allow-scripts" only — NOT allow-same-origin. The server-baked
  // CSP (connect-src 'none') + the lack of same-origin already neutralize
  // most of what an LLM-generated <script> can do; not granting
  // same-origin keeps it from poking at parent storage / cookies.
  //
  // The helper script in the baked HTML posts `ukiyo:select` on click and
  // replies to `ukiyo:rect_request` with the element's bounding rect (a
  // round-trip is required because we don't have allow-same-origin to
  // reach into the iframe's document directly).
  const { sendMessage, isStreaming } = useChatLayout();
  const streaming = isStreaming(conversationId);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [selection, setSelection] = useState<SelectionState | null>(null);
  const [instruction, setInstruction] = useState("");

  // Reset selection whenever the rendered HTML changes — a new version
  // arrived (or the user reverted) and the previously highlighted element
  // may no longer exist at the same uid.
  useEffect(() => {
    setSelection(null);
    setInstruction("");
  }, [html]);

  // Single global message listener — handles both `ukiyo:select` (user
  // clicked an element) and `ukiyo:rect_reply` (iframe answered our rect
  // request). Stale rect replies (uid drift between request and reply)
  // are dropped by matching against the current selection's uid.
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      const d = e.data as
        | { type?: string; uid?: string; tag?: string; rect?: SelectionState["rect"] }
        | null;
      if (!d || typeof d !== "object" || !d.type) return;

      if (d.type === "ukiyo:select" && d.uid) {
        const uid = String(d.uid);
        const tag = String(d.tag ?? "");
        setSelection({ uid, tag });
        // Fire the rect_request immediately. The reply will arrive on
        // the same listener and patch in the rect.
        const win = iframeRef.current?.contentWindow;
        if (win) {
          win.postMessage({ type: "ukiyo:rect_request", uid }, "*");
        }
      } else if (d.type === "ukiyo:rect_reply" && d.uid && d.rect) {
        const replyUid = String(d.uid);
        setSelection((prev) => {
          if (!prev || prev.uid !== replyUid) return prev;
          return { ...prev, rect: d.rect };
        });
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  const closeSelection = useCallback(() => {
    setSelection(null);
    setInstruction("");
  }, []);

  const submitEdit = useCallback(async () => {
    if (!selection || !instruction.trim() || streaming) return;
    const uidNum = parseInt(selection.uid, 10);
    if (Number.isNaN(uidNum)) return;
    const content = instruction.trim();
    // Optimistically dismiss the overlay — sendMessage is fire-and-forget
    // here, the streaming state is reflected by the chat panel and the
    // drawer's iframe re-renders on `done`.
    setSelection(null);
    setInstruction("");
    await sendMessage(content, conversationId, {
      surface: "canvas",
      editScopeUid: uidNum,
    });
  }, [selection, instruction, streaming, sendMessage, conversationId]);

  // Esc dismisses the overlay; works regardless of which surface inside
  // the drawer has focus.
  useEffect(() => {
    if (!selection) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeSelection();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selection, closeSelection]);

  return (
    <div className="relative h-full w-full overflow-hidden">
      <iframe
        ref={iframeRef}
        title="Design preview"
        sandbox="allow-scripts"
        srcDoc={html}
        className="h-full w-full border-0 bg-white"
      />
      {selection && (
        <SelectionOverlay
          selection={selection}
          instruction={instruction}
          onInstructionChange={setInstruction}
          onSubmit={submitEdit}
          onClose={closeSelection}
          disabled={streaming}
        />
      )}
    </div>
  );
}

function SelectionOverlay({
  selection,
  instruction,
  onInstructionChange,
  onSubmit,
  onClose,
  disabled,
}: {
  selection: SelectionState;
  instruction: string;
  onInstructionChange: (v: string) => void;
  onSubmit: () => void;
  onClose: () => void;
  disabled: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  // Autofocus the input as soon as the overlay mounts so the user can
  // start typing without an extra click.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // The highlight box (positioned over the selected element) is only
  // rendered once the rect_reply arrives. Pre-rect we still show the
  // input docked at bottom-center so the user can type immediately —
  // the rect arrives within ~one frame so this is rarely visible.
  const rect = selection.rect;

  return (
    <>
      {rect && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute rounded-sm ring-2 ring-blue-500/80"
          style={{
            top: rect.y,
            left: rect.x,
            width: rect.width,
            height: rect.height,
          }}
        />
      )}
      <div
        role="dialog"
        aria-label={`Edit ${selection.tag.toLowerCase()}`}
        className="absolute bottom-4 left-1/2 z-10 flex w-[min(36rem,90%)] -translate-x-1/2 items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950/95 p-2 shadow-2xl shadow-black/50 backdrop-blur"
      >
        <span className="px-1 text-xs uppercase tracking-wide text-zinc-500">
          {selection.tag.toLowerCase() || "element"}
        </span>
        <input
          ref={inputRef}
          type="text"
          value={instruction}
          disabled={disabled}
          onChange={(e) => onInstructionChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
            }
          }}
          placeholder="Describe the change…"
          aria-label="Edit instruction"
          className="min-w-0 flex-1 rounded-md bg-transparent px-2 py-1.5 text-sm text-white outline-none placeholder:text-zinc-600 disabled:opacity-50"
        />
        <Button
          type="button"
          size="sm"
          onClick={onSubmit}
          disabled={disabled || !instruction.trim()}
          aria-label="Send edit"
        >
          <SendHorizontalIcon size={14} />
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={onClose}
          aria-label="Cancel edit"
        >
          <XIcon size={14} />
        </Button>
      </div>
    </>
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
