import { apiJson } from "./client";
import type { Conversation, Message, User } from "./types";

export function listConversations(): Promise<Conversation[]> {
  return apiJson<Conversation[]>("/conversations");
}

export function createConversation(): Promise<Conversation> {
  return apiJson<Conversation>("/conversations", {
    method: "POST",
    body: {},
  });
}

export function getMessages(conversationId: string): Promise<Message[]> {
  return apiJson<Message[]>(`/conversations/${conversationId}/messages`);
}

export function getMe(): Promise<User> {
  return apiJson<User>("/me");
}
