import { apiRequest } from "../api";
import type { Opportunity } from "../api";

export type { Opportunity };

export async function getFeed(
  token: string,
  params: {
    company_id: number;
    platform?: string;
    status?: string;
    min_score?: number;
    intent?: string;
    keyword?: string;
    agent_name?: string;
    sort?: string;
    limit?: number;
    offset?: number;
    debug?: boolean;
  }
) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      query.set(key, String(value));
    }
  });
  return apiRequest<{ opportunities: Opportunity[]; total: number }>(`/v1/feed?${query.toString()}`, { headers: { Authorization: `Bearer ${token}` } });
}

export async function getOpportunityDetail(token: string, id: number) {
  return apiRequest<Opportunity>(`/v1/opportunities/${id}`, { headers: { Authorization: `Bearer ${token}` } });
}

export async function getDebugInfo(token: string, companyId: number) {
  return apiRequest<any>(`/v1/feed/debug?company_id=${companyId}`, { headers: { Authorization: `Bearer ${token}` } });
}

export async function approveOpportunity(token: string, id: number) {
  return apiRequest<Opportunity>(`/v1/opportunities/${id}/approve`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export async function rejectOpportunity(token: string, id: number) {
  return apiRequest<Opportunity>(`/v1/opportunities/${id}/reject`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export async function copyOpportunity(token: string, id: number) {
  return apiRequest<Opportunity>(`/v1/opportunities/${id}/copy`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export async function markIrrelevant(token: string, id: number, reason?: string) {
  return apiRequest<Opportunity>(`/v1/opportunities/${id}/irrelevant`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ reason }) });
}
