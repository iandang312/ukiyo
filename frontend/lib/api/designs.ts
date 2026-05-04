import { apiJson } from "./client";
import type {
  Design,
  DesignPatch,
  IssueHandoffOut,
  RedeemHandoffOut,
} from "./types";

// v1's 1:1 design-per-conversation invariant means hydration is keyed on
// the conversation, not a separate design id. The backend 404s when no
// canvas turn has run yet — callers should treat that as "drawer empty".
export function getConversationDesign(
  conversationId: string,
): Promise<Design> {
  return apiJson<Design>(`/conversations/${conversationId}/design`);
}

// Sets `design.current_version_id`. Used by the version-timeline revert
// click. The backend preserves the DAG (no version is deleted or
// re-parented); the next edit appends at the end of the linear timeline.
export function patchDesign(
  designId: string,
  patch: DesignPatch,
): Promise<Design> {
  return apiJson<Design>(`/designs/${designId}`, {
    method: "PATCH",
    body: patch,
  });
}

export function issueHandoff(
  designId: string,
  versionId: string,
): Promise<IssueHandoffOut> {
  return apiJson<IssueHandoffOut>(
    `/designs/${designId}/versions/${versionId}/handoffs`,
    { method: "POST", body: {} },
  );
}

// Note: redemption is plugin-only in Phase 14 — included here for
// completeness so a future devtool can call it. The web app should never
// invoke this; it would consume the user's own code.
export function redeemHandoff(code: string): Promise<RedeemHandoffOut> {
  return apiJson<RedeemHandoffOut>("/handoffs/redeem", {
    method: "POST",
    body: { code },
  });
}
