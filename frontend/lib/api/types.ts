export interface User {
  id: string;
  email: string;
}

export interface Conversation {
  id: string;
  title: string | null;
  auto_route_enabled: boolean;
  pinned_model: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  model_used: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: string | null;
  latency_ms: number | null;
  created_at: string;
}

export interface MetaEvent {
  surface: "chat" | "canvas";
  model: string;
  bucket: string | null;
  confidence: number | null;
}

export interface DeltaEvent {
  content: string;
}

export interface DoneEvent {
  message_id: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: string;
  latency_ms: number;
}

export interface StreamErrorEvent {
  provider: "openai" | "anthropic" | "google";
  code: string;
  user_message: string;
}

export interface ModelsResponse {
  generalist: string;
  buckets: Record<string, string>;
}

export interface ConversationPatch {
  pinned_model?: string | null;
  auto_route_enabled?: boolean;
}
