"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ChatLayoutContext } from "@/components/chat/context";
import type { ChatMessage } from "@/components/chat/message";
import { Sidebar } from "@/components/chat/sidebar";
import { TopStrip } from "@/components/chat/top-strip";
import { ApiError } from "@/lib/api/client";
import {
  createConversation,
  getMessages as fetchMessages,
  listConversations,
} from "@/lib/api/conversations";
import { streamMessage } from "@/lib/api/messages";
import type { Conversation } from "@/lib/api/types";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(true);
  const [currentModel, setCurrentModel] = useState<string | null>(null);
  const [messagesByConv, setMessagesByConv] = useState<
    Record<string, ChatMessage[]>
  >({});
  const [streamingByConv, setStreamingByConv] = useState<
    Record<string, boolean>
  >({});

  const inflightHistoryRef = useRef<Set<string>>(new Set());

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
        onError: (err) => {
          console.error("Stream failed", err);
          setMessages(id, (prev) =>
            prev.map((m) =>
              m.id === tempAssistantId
                ? {
                    ...m,
                    isStreaming: false,
                    error: "Failed to load response. Try again.",
                  }
                : m,
            ),
          );
          setStreamingByConv((prev) => ({ ...prev, [id]: false }));
        },
      });
    },
    [refreshConversations, router, setMessages],
  );

  const getMessages = useCallback(
    (id: string | null) => (id ? messagesByConv[id] : []),
    [messagesByConv],
  );

  const isStreaming = useCallback(
    (id: string | null) => (id ? Boolean(streamingByConv[id]) : false),
    [streamingByConv],
  );

  return (
    <ChatLayoutContext.Provider
      value={{
        conversations,
        conversationsLoading,
        refreshConversations,
        currentModel,
        setCurrentModel,
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
    </ChatLayoutContext.Provider>
  );
}
