import { apiRequest } from "../api";

import type { ReplyDraft, PostDraft, PromptTemplate } from "../api";

export type { ReplyDraft, PostDraft, PromptTemplate };

export async function generateReply(
  token: string,
  opportunityId: number,
  projectId?: number | null,
  promptTemplateId?: number | null,
  options?: { voice_profile_id?: number | null; platform?: string | null; variants?: number }
) {
  const body: Record<string, unknown> = { opportunity_id: opportunityId };
  if (promptTemplateId) body.prompt_template_id = promptTemplateId;
  if (options?.voice_profile_id) body.voice_profile_id = options.voice_profile_id;
  if (options?.platform) body.platform = options.platform;
  if (options?.variants && options.variants > 1) body.variants = options.variants;
  const qs = projectId ? `?project_id=${projectId}` : "";
  return apiRequest<ReplyDraft>(
    `/v1/drafts/replies${qs}`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(body) }
  );
}

export async function getReplyDrafts(token: string, projectId?: number | null, status?: string) {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", String(projectId));
  if (status) params.set("status", status);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<ReplyDraft[]>(
    `/v1/drafts/replies${qs}`, { headers: { Authorization: `Bearer ${token}` } }
  );
}

export async function updateReplyDraft(
  token: string,
  draftId: number,
  data: { content: string; rationale?: string | null }
) {
  return apiRequest<ReplyDraft>(
    `/v1/drafts/replies/${draftId}`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }
  );
}

export async function updatePostDraft(
  token: string,
  draftId: number,
  data: { title: string; body: string; rationale?: string | null }
) {
  return apiRequest<PostDraft>(
    `/v1/drafts/posts/${draftId}`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }
  );
}

export async function createPostDraft(token: string, projectId: number, data?: { title?: string; body?: string; subreddit?: string }) {
  const payload = { project_id: projectId, ...data };
  return apiRequest<PostDraft>(
    `/v1/drafts/posts`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }
  );
}

export async function getPostDrafts(token: string, projectId?: number | null) {
  const qs = projectId ? `?project_id=${projectId}` : "";
  return apiRequest<PostDraft[]>(
    `/v1/drafts/posts${qs}`, { headers: { Authorization: `Bearer ${token}` } }
  );
}

export async function getPrompts(token: string, projectId?: number | null) {
  const suffix = projectId ? `?project_id=${projectId}` : "";
  return apiRequest<PromptTemplate[]>(
    `/v1/prompts${suffix}`, { headers: { Authorization: `Bearer ${token}` } }
  );
}

export async function createPrompt(token: string, data: { prompt_type: string; name: string; system_prompt: string; instructions: string; project_id?: number }) {
  return apiRequest<PromptTemplate>(
    `/v1/prompts`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }
  );
}

export async function updatePrompt(token: string, promptId: number, data: Partial<{ prompt_type: string; name: string; system_prompt: string; instructions: string }>) {
  return apiRequest<PromptTemplate>(
    `/v1/prompts/${promptId}`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }
  );
}

export async function deletePrompt(token: string, promptId: number) {
  return apiRequest<void>(
    `/v1/prompts/${promptId}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }
  );
}
