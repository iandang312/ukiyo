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
  // Phase 13: assistant rows produced by canvas turns carry the version
  // they generated. Used by inline "design vN generated" rows in the
  // chat panel.
  design_version_id?: string | null;
  created_at: string;
}

// Chat-surface meta carries `confidence`; canvas-surface meta carries
// canvas-specific fields. The two shapes are disjoint at runtime — the
// `surface` discriminant is what the frontend keys off. Modeling them as
// a union lets the type system stop callers from reading `design_id` on
// a chat meta and vice versa.
export interface ChatMetaEvent {
  surface: "chat";
  model: string;
  bucket: string | null;
  confidence: number | null;
  // Phase 12 build-request promotion: only present (and only `true`) when
  // both the design-bucket-confidence and verb+noun heuristics fire. The
  // backend omits the field otherwise so UI checks for *presence*, not
  // a `false` value.
  promote_to_canvas?: true;
}

export interface CanvasMetaEvent {
  surface: "canvas";
  model: string;
  bucket: "design";
  design_id: string;
  // null on the meta event — the version row doesn't exist yet at meta
  // time. The done event carries the persisted `version_id`.
  version_id: null;
  parent_version_id: string | null;
  version_number: number;
  is_scoped_edit: boolean;
}

export type MetaEvent = ChatMetaEvent | CanvasMetaEvent;

export interface DeltaEvent {
  content: string;
}

export interface DoneEvent {
  message_id: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: string;
  latency_ms: number;
  // Only present on canvas-surface done events (Phase 12 SSE shape).
  version_id?: string;
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

// --- Phase 13: design / canvas types -------------------------------------

export interface DesignVersion {
  id: string;
  version_number: number;
  html: string;
  prompt: string | null;
  edit_scope_selector: string | null;
  parent_version_id: string | null;
  model_used: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  created_at: string;
}

export interface Design {
  id: string;
  conversation_id: string;
  title: string | null;
  current_version_id: string | null;
  created_at: string;
  updated_at: string;
  versions: DesignVersion[];
}

export interface DesignPatch {
  current_version_id: string;
}

export interface IssueHandoffOut {
  code: string;
  expires_at: string;
}

export interface RedeemHandoffOut {
  html: string;
  version_number: number;
  design_title: string | null;
  design_id: string;
}

// Posted from the iframe helper script on click — the parent listens for
// this shape on `window.message`.
export interface CanvasSelectMessage {
  type: "ukiyo:select";
  uid: string;
  tag: string;
}

// Round-trip query the parent sends back into the iframe to position the
// edit overlay over the clicked element. Reply shape mirrors a
// `getBoundingClientRect()` payload.
export interface CanvasRectRequest {
  type: "ukiyo:rect_request";
  uid: string;
}

export interface CanvasRectReply {
  type: "ukiyo:rect_reply";
  uid: string;
  rect: { x: number; y: number; width: number; height: number };
}
