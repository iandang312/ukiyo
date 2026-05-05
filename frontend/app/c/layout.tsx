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
        const chatMsgs: ChatMessage[] = msgs.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          model: m.model_used,
        }));
        setMessages(id, chatMsgs);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          router.replace("/c");
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
          router.replace(`/c/${convId}`);
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
      const assistantMsg: ChatMessage = {
        id: tempAssistantId,
        role: "assistant",
        content: "",
        model: null,
        isStreaming: true,
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
              prev.map((m) =>
                m.id === tempAssistantId ? { ...m, model: meta.model } : m,
              ),
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
                  ? { ...m, id: done.message_id, isStreaming: false }
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
      const design = designsByConv[conversationId];
      if (!design) {
        // Race: revert clicked before hydration finished. Refetch first
        // so the user-visible failure is "drawer reloading", not "PATCH
        // 404 on a design we haven't seen yet".
        await refreshDesign(conversationId);
        return;
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
