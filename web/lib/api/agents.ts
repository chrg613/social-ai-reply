import { apiRequest } from "../api";
import type { AgentRun } from "../api";

export type { AgentRun };

export async function runAgent(token: string, companyId: number, agentName: string) {
  return apiRequest<{ run_id: number; status: string }>("/v1/agents/run", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ company_id: companyId, agent_name: agentName }) });
}

export async function runAllAgents(token: string, companyId: number) {
  return apiRequest<{ status: string; runs: any[] }>("/v1/agents/run-all", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ company_id: companyId }) });
}

export async function getAgentRuns(token: string, companyId: number, agentName?: string) {
  const params = new URLSearchParams({ company_id: String(companyId) });
  if (agentName) params.set("agent_name", agentName);
  return apiRequest<AgentRun[]>(`/v1/agents/runs?${params.toString()}`, { headers: { Authorization: `Bearer ${token}` } });
}

export async function getAgentRun(token: string, runId: string) {
  return apiRequest<AgentRun>(`/v1/agents/runs/${runId}`, { headers: { Authorization: `Bearer ${token}` } });
}

export async function getAgentStatus(token: string, companyId: number) {
  return apiRequest<any[]>(`/v1/agents/status?company_id=${companyId}`, { headers: { Authorization: `Bearer ${token}` } });
}
