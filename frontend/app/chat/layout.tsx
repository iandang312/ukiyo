"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  ChatLayoutContext,
  type DesignStatus,
} from "@/components/chat/context";
import type { ChatMessage } from "@/components/chat/message";
import { Sidebar } from "@/components/chat/sidebar";
import { TopStrip } from "@/components/chat/top-strip";
import { Toaster } from "@/components/ui/sonner";
import { ApiError } from "@/lib/api/client";
import {
  createConversation,
  getMessages as fetchMessages,
  listConversations,
  listModels,
  patchConversation as patchConversationApi,
} from "@/lib/api/conversations";
import {
  getConversationDesign,
  patchDesign,
} from "@/lib/api/designs";
import { streamMessage } from "@/lib/api/messages";
import type {
  Conversation,
  ConversationPatch,
  Design,
  ModelsResponse,
} from "@/lib/api/types";

// Used when GET /models fails. Mirrors today's BUCKET_MODEL_MAP defaults so
// the picker still renders something sane offline.
const FALLBACK_MODELS: ModelsResponse = {
  generalist: "claude-sonnet-4-6",
  buckets: {
    coding: "claude-sonnet-4-6",
    design: "gpt-4o",
    research: "gemini-2.5-flash",
  },
};

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const params = useParams<{ id?: string }>();
  const currentId =
    typeof params?.id === "string" ? params.id : null;

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(true);
  const [currentModel, setCurrentModel] = useState<string | null>(null);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [messagesByConv, setMessagesByConv] = useState<
    Record<string, ChatMessage[]>
  >({});
  const [streamingByConv, setStreamingByConv] = useState<
    Record<string, boolean>
  >({});

  // Phase 13: design state per conversation. `designsByConv` is the loaded
  // payload; `designStatusByConv` distinguishes loading/empty/error/ready
  // so the drawer can show the right placeholder without inferring it
  // from `design === null`. Keyed by conv id so switching threads keeps
  // the cached design — re-hydration is one network call away when needed.
  const [designsByConv, setDesignsByConv] = useState<Record<string, Design>>(
    {},
  );
  const [designStatusByConv, setDesignStatusByConv] = useState<
    Record<string, DesignStatus>
  >({});

  const inflightHistoryRef = useRef<Set<string>>(new Set());
  const inflightDesignRef = useRef<Set<string>>(new Set());
  const conversationsRef = useRef<Conversation[]>([]);
  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  const refreshConversations = useCallback(async () => {
    try {
      const data = await listConversations();
      setConversations(data);
    } catch (err) {
      console.error("Failed to load conversations", err);
    } finally {
      setConversationsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  useEffect(() => {
    let cancelled = false;
    listModels()
      .then((data) => {
        if (!cancelled) setModels(data);
      })
      .catch((err) => {
        console.warn("Failed to load /models, using fallback", err);
        if (!cancelled) setModels(FALLBACK_MODELS);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const setMessages = useCallback(
    (
      id: string,
      updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[]),
    ) => {
      setMessagesByConv((prev) => {
        const current = prev[id] ?? [];
        const next =
          typeof updater === "function" ? updater(current) : updater;
        return { ...prev, [id]: next };
      });
    },
    [],
  );

  const loadHistory = useCallback(
    async (id: string) => {
      if (messagesByConv[id] !== undefined) return;
      if (inflightHistoryRef.current.has(id)) return;
      inflightHistoryRef.current.add(id);
      try {
        const msgs = await fetchMessages(id);
        let sawCanvasRow = false;
        const chatMsgs: ChatMessage[] = msgs.map((m) => {
          // Phase 13: assistant rows with a design_version_id were
          // produced by canvas turns. Tagging them lets the Message
          // component render a thumbnail card instead of dumping the
          // multi-kilobyte HTML in chat.
          const isCanvas = Boolean(m.design_version_id);
          if (isCanvas) sawCanvasRow = true;
          return {
            id: m.id,
            role: m.role,
            content: m.content,
            model: m.model_used,
            surface: isCanvas ? "canvas" : "chat",
            designVersionId: m.design_version_id ?? null,
          };
        });
        setMessages(id, chatMsgs);
        // Lazy-load the design when historical canvas rows exist so the
        // thumbnails can render. The drawer would re-fetch on its own
        // mount; this just makes the chat-only route show full thumbnails
        // immediately. Fire-and-forget — Message renders a placeholder
        // until hydration lands.
        if (sawCanvasRow) {
          void refreshDesignRef.current?.(id);
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          router.replace("/chat");
        } else {
          console.error("Failed to load conversation history", err);
        }
      } finally {
        inflightHistoryRef.current.delete(id);
      }
    },
    [messagesByConv, router, setMessages],
  );

  const sendMessage = useCallback(
    async (
      content: string,
      idOrNull: string | null,
      options?: { surface?: "chat" | "canvas"; editScopeUid?: number },
    ) => {
      let convId = idOrNull;
      const userMsg: ChatMessage = {
        id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        role: "user",
        content,
      };

      if (!convId) {
        try {
          const conv = await createConversation();
          convId = conv.id;
          setConversations((prev) => [
            conv,
            ...prev.filter((c) => c.id !== conv.id),
          ]);
          setMessages(convId, [userMsg]);
          router.replace(`/chat/${convId}`);
        } catch (err) {
          console.error("Failed to create conversation", err);
          return;
        }
      } else {
        setMessages(convId, (prev) => [...prev, userMsg]);
      }

      const id = convId;
      const tempAssistantId = `assistant-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      const surface: "chat" | "canvas" = options?.surface ?? "chat";
      const assistantMsg: ChatMessage = {
        id: tempAssistantId,
        role: "assistant",
        content: "",
        model: null,
        isStreaming: true,
        surface,
      };
      setMessages(id, (prev) => [...prev, assistantMsg]);
      setStreamingByConv((prev) => ({ ...prev, [id]: true }));

      const dropAssistantRow = () => {
        setMessages(id, (prev) =>
          prev.filter((m) => m.id !== tempAssistantId),
        );
        setStreamingByConv((prev) => ({ ...prev, [id]: false }));
      };

      await streamMessage(
        id,
        content,
        {
          onMeta: (meta) => {
            setCurrentModel(meta.model);
            setMessages(id, (prev) =>
              prev.map((m) => {
                if (m.id !== tempAssistantId) return m;
                // Phase 13: chat-mode meta with `promote_to_canvas: true`
                // surfaces the "Open in design canvas" button below this
                // row. The user prompt is captured at this layer (not
                // recovered later from the message list) because the
                // user-message id is brittle when streaming concurrently.
                const promote =
                  meta.surface === "chat" && meta.promote_to_canvas === true
                    ? { promoteToCanvas: { prompt: content } }
                    : {};
                return { ...m, model: meta.model, ...promote };
              }),
            );
          },
          onDelta: (delta) => {
            setMessages(id, (prev) =>
              prev.map((m) =>
                m.id === tempAssistantId
                  ? { ...m, content: m.content + delta.content }
                  : m,
              ),
            );
          },
          onDone: (done) => {
            setMessages(id, (prev) =>
              prev.map((m) =>
                m.id === tempAssistantId
                  ? {
                      ...m,
                      id: done.message_id,
                      isStreaming: false,
                      // Stamp design_version_id from the done payload
                      // so the row immediately upgrades to a thumbnail
                      // (assuming design state is already / soon hydrated).
                      designVersionId: done.version_id ?? null,
                    }
                  : m,
              ),
            );
            setStreamingByConv((prev) => ({ ...prev, [id]: false }));
            refreshConversations();
            // Canvas turns ship a `version_id` on the done event; on
            // success refresh the design so the drawer's iframe + timeline
            // pick up the new version. Fire-and-forget — the drawer
            // tolerates a brief stale state.
            if (options?.surface === "canvas" && done.version_id) {
              void refreshDesignRef.current?.(id);
            }
          },
          onStreamError: (event) => {
            console.error("Provider error", event.provider, event.code);
            dropAssistantRow();
            toast.error(event.user_message);
          },
          onError: (err) => {
            console.error("Stream failed", err);
            dropAssistantRow();
            toast.error("Connection failed. Try again.");
          },
        },
        {
          surface: options?.surface,
          editScopeUid: options?.editScopeUid,
        },
      );
    },
    [refreshConversations, router, setMessages],
  );

  // refreshDesign is referenced inside sendMessage above for the canvas
  // post-stream refresh. Holding it in a ref breaks the would-be cycle
  // (sendMessage -> refreshDesign -> setDesignsByConv -> re-render -> new
  // sendMessage) without a hook-rule violation.
  const refreshDesignRef = useRef<((id: string) => Promise<void>) | null>(
    null,
  );

  const refreshDesign = useCallback(
    async (id: string) => {
      if (inflightDesignRef.current.has(id)) return;
      inflightDesignRef.current.add(id);
      setDesignStatusByConv((prev) => ({ ...prev, [id]: "loading" }));
      try {
        const design = await getConversationDesign(id);
        setDesignsByConv((prev) => ({ ...prev, [id]: design }));
        setDesignStatusByConv((prev) => ({ ...prev, [id]: "ready" }));
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          // No canvas turn has run yet — drawer renders "empty" state.
          setDesignsByConv((prev) => {
            const next = { ...prev };
            delete next[id];
            return next;
          });
          setDesignStatusByConv((prev) => ({ ...prev, [id]: "empty" }));
        } else {
          console.error("Failed to load design", err);
          setDesignStatusByConv((prev) => ({ ...prev, [id]: "error" }));
        }
      } finally {
        inflightDesignRef.current.delete(id);
      }
    },
    [],
  );

  useEffect(() => {
    refreshDesignRef.current = refreshDesign;
  }, [refreshDesign]);

  const revertDesignVersion = useCallback(
    async (conversationId: string, versionId: string) => {
      // Race: revert may be triggered before hydration completes
      // (e.g. an inline message thumbnail clicked from chat-only
      // mode where the drawer hasn't mounted yet). Hydrate first so
      // we have the design id to PATCH against.
      let design = designsByConv[conversationId];
      if (!design) {
        await refreshDesign(conversationId);
        // setState batching means designsByConv hasn't updated in this
        // closure yet — fetch directly to get a fresh value.
        try {
          design = await getConversationDesign(conversationId);
          setDesignsByConv((prev) => ({
            ...prev,
            [conversationId]: design as Design,
          }));
          setDesignStatusByConv((prev) => ({
            ...prev,
            [conversationId]: "ready",
          }));
        } catch (err) {
          console.error("Failed to load design before revert", err);
          toast.error("Couldn't load the design. Try again.");
          return;
        }
      }
      const previous = design;
      // Optimistic flip: show the target version immediately so the iframe
      // doesn't lag behind the click. Revert the optimism on failure.
      setDesignsByConv((prev) => ({
        ...prev,
        [conversationId]: { ...previous, current_version_id: versionId },
      }));
      try {
        const updated = await patchDesign(design.id, {
          current_version_id: versionId,
        });
        setDesignsByConv((prev) => ({ ...prev, [conversationId]: updated }));
      } catch (err) {
        console.error("Failed to revert version", err);
        setDesignsByConv((prev) => ({ ...prev, [conversationId]: previous }));
        toast.error("Couldn't switch versions. Try again.");
      }
    },
    [designsByConv, refreshDesign],
  );

  const dispatchCanvasFromPromotion = useCallback(
    async (conversationId: string, prompt: string) => {
      // Open the drawer first so the user sees the canvas surface come
      // up alongside the streaming response. sendMessage is fire-and-
      // forget here (no await before navigation) so the route swap
      // doesn't wait on the SSE stream to start.
      router.push(`/chat/${conversationId}/canvas`);
      void sendMessage(prompt, conversationId, { surface: "canvas" });
    },
    [router, sendMessage],
  );

  const dispatchCanvasFromVersion = useCallback(
    async (conversationId: string, versionId: string) => {
      // Pin to the requested version, then navigate. Order matters:
      // PATCH-then-navigate means the drawer mounts to the correct
      // current_version_id without flashing the stale one.
      await revertDesignVersion(conversationId, versionId);
      router.push(`/chat/${conversationId}/canvas`);
    },
    [revertDesignVersion, router],
  );

  const patchConversation = useCallback(
    async (
      id: string,
      patch: ConversationPatch,
    ): Promise<Conversation> => {
      const prev = conversationsRef.current.find((c) => c.id === id);
      if (prev) {
        const optimistic: Conversation = {
          ...prev,
          ...("pinned_model" in patch
            ? { pinned_model: patch.pinned_model ?? null }
            : {}),
          ...("auto_route_enabled" in patch &&
          patch.auto_route_enabled !== undefined
            ? { auto_route_enabled: patch.auto_route_enabled }
            : {}),
        };
        setConversations((curr) =>
          curr.map((c) => (c.id === id ? optimistic : c)),
        );
      }
      try {
        const updated = await patchConversationApi(id, patch);
        setConversations((curr) =>
          curr.map((c) => (c.id === id ? updated : c)),
        );
        return updated;
      } catch (err) {
        if (prev) {
          const snapshot = prev;
          setConversations((curr) =>
            curr.map((c) => (c.id === id ? snapshot : c)),
          );
        }
        console.error("Failed to patch conversation", err);
        throw err;
      }
    },
    [],
  );

  const getMessages = useCallback(
    (id: string | null) => (id ? messagesByConv[id] : []),
    [messagesByConv],
  );

  const isStreaming = useCallback(
    (id: string | null) => (id ? Boolean(streamingByConv[id]) : false),
    [streamingByConv],
  );

  const getDesign = useCallback(
    (id: string | null) => (id ? designsByConv[id] ?? null : null),
    [designsByConv],
  );

  const getDesignStatus = useCallback(
    (id: string | null): DesignStatus =>
      id ? designStatusByConv[id] ?? "idle" : "idle",
    [designStatusByConv],
  );

  const currentConversation = useMemo(
    () =>
      currentId
        ? (conversations.find((c) => c.id === currentId) ?? null)
        : null,
    [conversations, currentId],
  );

  return (
    <ChatLayoutContext.Provider
      value={{
        conversations,
        conversationsLoading,
        refreshConversations,
        currentConversation,
        currentModel,
        setCurrentModel,
        models,
        patchConversation,
        getMessages,
        isStreaming,
        sendMessage,
        loadHistory,
        getDesign,
        getDesignStatus,
        refreshDesign,
        revertDesignVersion,
        dispatchCanvasFromPromotion,
        dispatchCanvasFromVersion,
      }}
    >
      <div className="flex h-screen w-screen overflow-hidden bg-black font-sans text-white antialiased">
        <Sidebar />
        <main className="flex min-w-0 flex-1 flex-col">
          <TopStrip />
          {children}
        </main>
      </div>
      <Toaster />
    </ChatLayoutContext.Provider>
  );
}
