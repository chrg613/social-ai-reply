import { apiRequest } from "../api";

import type { Keyword, SubredditAnalysis, MonitoredSubreddit, Opportunity } from "../api";

export type { Keyword, SubredditAnalysis, MonitoredSubreddit, Opportunity };

/** A scan run record. POST /v1/scans returns immediately with a "running" run
 *  that can be polled via GET /v1/scans/{id} until it reaches a terminal status. */
export type ScanRun = {
  id: string;
  project_id?: number;
  status: string;
  posts_scanned: number;
  opportunities_found: number;
  subreddits_scanned?: number;
  error_message: string | null;
  started_at?: string;
  finished_at?: string | null;
};

export async function getKeywords(token: string, projectId: number) {
  return apiRequest<Keyword[]>(
    `/v1/discovery/keywords?project_id=${projectId}`, { headers: { Authorization: `Bearer ${token}` } }
  );
}

export async function createKeyword(token: string, projectId: number, data: { keyword: string; rationale?: string; priority_score?: number }) {
  return apiRequest<Keyword>(
    `/v1/discovery/keywords?project_id=${projectId}`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }
  );
}

export async function deleteKeyword(token: string, projectId: number, keywordId: number) {
  return apiRequest<void>(
    `/v1/discovery/keywords/${keywordId}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }
  );
}

export async function getSubreddits(token: string, projectId: number) {
  return apiRequest<MonitoredSubreddit[]>(
    `/v1/discovery/subreddits?project_id=${projectId}`, { headers: { Authorization: `Bearer ${token}` } }
  );
}

export async function addSubreddit(token: string, projectId: number, data: { name: string }) {
  return apiRequest<MonitoredSubreddit>(
    `/v1/discovery/subreddits?project_id=${projectId}`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }
  );
}

export async function removeSubreddit(token: string, projectId: number, subredditId: number) {
  return apiRequest<void>(
    `/v1/discovery/subreddits/${subredditId}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }
  );
}

export async function triggerScan(
  token: string,
  projectId: number,
  options?: { search_window_hours?: number; max_posts_per_subreddit?: number; platforms?: string[] }
) {
  return apiRequest<ScanRun>(
    `/v1/scans?project_id=${projectId}`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ project_id: projectId, ...options }),
    }
  );
}

export async function getScanStatus(token: string, scanId: string) {
  return apiRequest<ScanRun>(
    `/v1/scans/${scanId}`, { headers: { Authorization: `Bearer ${token}` } }
  );
}

export async function getOpportunities(token: string, projectId: number, status?: string, limit?: number) {
  const params = new URLSearchParams({ project_id: String(projectId) });
  if (status) params.set("status", status);
  if (limit) params.set("limit", String(limit));
  return apiRequest<Opportunity[]>(
    `/v1/opportunities?${params.toString()}`, { headers: { Authorization: `Bearer ${token}` } }
  );
}

export async function updateOpportunityStatus(token: string, opportunityId: number, status: string) {
  return apiRequest<unknown>(
    `/v1/opportunities/${opportunityId}/status`,
    { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ status }) }
  );
}
