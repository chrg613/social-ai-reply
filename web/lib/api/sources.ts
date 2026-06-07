import { apiRequest } from "../api";
import type { Source } from "../api";

export type { Source };

export async function getSources(token: string, companyId: number) {
  return apiRequest<Source[]>(`/v1/companies/${companyId}/sources`, { headers: { Authorization: `Bearer ${token}` } });
}

export async function createSource(token: string, data: Partial<Source>) {
  return apiRequest<Source>("/v1/sources", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) });
}

export async function updateSource(token: string, id: number, data: Partial<Source>) {
  return apiRequest<Source>(`/v1/sources/${id}`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) });
}

export async function deleteSource(token: string, id: number) {
  return apiRequest<void>(`/v1/sources/${id}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
}
