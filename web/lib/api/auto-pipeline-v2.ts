import { apiRequest } from "../api";

export interface AutoPipelineV2Request {
  website_url: string;
  name?: string;
}

export interface AutoPipelineV2Response {
  company_id: number;
  status: string;
  message: string;
}

export interface AutoPipelineV2Status {
  company_id: number;
  company_name: string;
  has_extracted_summary: boolean;
  keywords_count: number;
  agents_total: number;
  agents_completed: number;
  agents_failed: number;
  agents_running: number;
  runs: Array<{
    agent_name: string;
    status: string;
    items_fetched: number;
    items_kept: number;
    started_at: string;
    completed_at: string | null;
  }>;
}

export async function startAutoPipelineV2(
  token: string,
  data: AutoPipelineV2Request,
): Promise<AutoPipelineV2Response> {
  return apiRequest<AutoPipelineV2Response>("/v1/auto-pipeline/v2/run", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(data),
  });
}

export async function getAutoPipelineV2Status(
  token: string,
  companyId: number,
): Promise<AutoPipelineV2Status> {
  return apiRequest<AutoPipelineV2Status>(`/v1/auto-pipeline/v2/status/${companyId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}
