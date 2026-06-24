import { apiRequest } from "../api";

export interface CompetitorMention {
  id: number;
  project_id: number;
  opportunity_id: number | null;
  competitor_name: string;
  sentiment: string;
  sentiment_score: number;
  complaint_category: string | null;
  complaint_detail: string | null;
  source_platform: string;
  source_url: string | null;
  post_title: string | null;
  post_body: string | null;
  detected_at: string | null;
  created_at: string;
}

export interface CompetitorStats {
  competitor_name: string;
  total_mentions: number;
  negative_count: number;
  neutral_count: number;
  positive_count: number;
  top_complaints: string[];
  avg_sentiment_score: number;
}

export async function fetchCompetitorMentions(
  token: string,
  projectId: number,
  opts?: { competitor_name?: string; sentiment?: string; limit?: number },
): Promise<CompetitorMention[]> {
  const params = new URLSearchParams();
  params.set("project_id", String(projectId));
  if (opts?.competitor_name) params.set("competitor_name", opts.competitor_name);
  if (opts?.sentiment) params.set("sentiment", opts.sentiment);
  if (opts?.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiRequest<CompetitorMention[]>(
    `/v1/competitors/mentions${qs ? `?${qs}` : ""}`,
    {},
    token,
  );
}

export async function fetchCompetitorStats(
  token: string,
  projectId: number,
): Promise<CompetitorStats[]> {
  return apiRequest<CompetitorStats[]>(
    `/v1/competitors/stats?project_id=${projectId}`,
    {},
    token,
  );
}

export async function fetchCompetitorList(
  token: string,
  projectId: number,
): Promise<string[]> {
  return apiRequest<string[]>(
    `/v1/competitors/list?project_id=${projectId}`,
    {},
    token,
  );
}
