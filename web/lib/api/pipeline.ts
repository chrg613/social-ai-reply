import { apiRequest } from "../api";

export interface PipelineRun {
  id: string;
  project_id: number;
  website_url: string;
  status:
    | "pending"
    | "analyzing"
    | "generating_personas"
    | "discovering_keywords"
    | "finding_subreddits"
    | "scanning_opportunities"
    | "scanning_platforms"
    | "scanning_all"
    | "checking_opportunities"
    | "generating_drafts"
    | "ready"
    | "executed"
    | "failed";
  progress: number;
  personas_count: number;
  keywords_count: number;
  subreddits_count: number;
  opportunities_count: number;
  drafts_count: number;
  current_step: string | null;
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
  results?: PipelineResults;
}

export interface PipelineResults {
  brand_summary: string;
  personas: PipelinePersona[];
  keywords: PipelineKeyword[];
  subreddits: PipelineSubreddit[];
  opportunities: PipelineOpportunity[];
  drafts: PipelineDraft[];
}

export interface PipelinePersona {
  name: string;
  role: string;
  summary: string;
  pain_points: string[];
}

export interface PipelineKeyword {
  keyword: string;
  score: number;
  source: string;
}

export interface PipelineSubreddit {
  name: string;
  fit_score: number;
  subscribers: number;
  description: string;
}

export interface PipelineOpportunity {
  title: string;
  subreddit: string;
  platform: string;
  score: number;
  author: string;
}

export interface PipelineDraft {
  title: string;
  content: string;
  opportunity_title: string;
}

export async function listPipelineRuns(token: string | null, projectId?: number | null): Promise<{ items: PipelineRun[] }> {
  const qs = projectId ? `?project_id=${projectId}` : "";
  return apiRequest<{ items: PipelineRun[] }>(`/v1/auto-pipeline${qs}`, {}, token);
}

export async function getPipelineRun(token: string | null, pipelineId: string): Promise<PipelineRun> {
  return apiRequest<PipelineRun>(`/v1/auto-pipeline/${pipelineId}`, {}, token);
}

export async function startPipelineRun(
  token: string | null,
  websiteUrl: string,
  projectId?: number | null,
  timeFilter?: string,
): Promise<PipelineRun> {
  const body: Record<string, unknown> = { website_url: websiteUrl };
  if (projectId) body.project_id = projectId;
  if (timeFilter) body.time_filter = timeFilter;
  return apiRequest<PipelineRun>(
    "/v1/auto-pipeline/run",
    { method: "POST", body: JSON.stringify(body) },
    token,
  );
}

export async function executePipelineRun(token: string | null, pipelineId: string): Promise<{ id: string; status: string; drafted_replies: number; message: string }> {
  return apiRequest<{ id: string; status: string; drafted_replies: number; message: string }>(
    `/v1/auto-pipeline/${pipelineId}/execute`,
    { method: "POST" },
    token,
  );
}
