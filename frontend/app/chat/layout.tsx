"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { ChatLayoutContext } from "@/components/chat/context";
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
import { streamMessage } from "@/lib/api/messages";
import type {
  Conversation,
  ConversationPatch,
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

  const inflightHistoryRef = useRef<Set<string>>(new Set());
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
    async (content: string, idOrNull: string | null) => {
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

      await streamMessage(id, content, {
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
      });
    },
    [refreshConversations, router, setMessages],
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
