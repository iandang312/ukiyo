import { apiJson } from "./client";
import type {
  Conversation,
  ConversationPatch,
  Message,
  ModelsResponse,
  User,
} from "./types";

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

export function patchConversation(
  conversationId: string,
  patch: ConversationPatch,
): Promise<Conversation> {
  return apiJson<Conversation>(`/conversations/${conversationId}`, {
    method: "PATCH",
    body: patch,
  });
}

export function listModels(): Promise<ModelsResponse> {
  return apiJson<ModelsResponse>("/models");
}

export function getMe(): Promise<User> {
  return apiJson<User>("/me");
}
