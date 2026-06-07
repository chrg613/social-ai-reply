import { apiRequest } from "../api";
import type { CompanyProfile, BrandKeyword } from "../api";

export type { CompanyProfile, BrandKeyword };

export async function getCompanies(token: string) {
  return apiRequest<CompanyProfile[]>("/v1/companies", { headers: { Authorization: `Bearer ${token}` } });
}

export async function createCompany(token: string, data: Partial<CompanyProfile>) {
  return apiRequest<CompanyProfile>("/v1/companies", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) });
}

export async function getCompany(token: string, id: number) {
  return apiRequest<CompanyProfile>(`/v1/companies/${id}`, { headers: { Authorization: `Bearer ${token}` } });
}

export async function updateCompany(token: string, id: number, data: Partial<CompanyProfile>) {
  return apiRequest<CompanyProfile>(`/v1/companies/${id}`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) });
}

export async function deleteCompany(token: string, id: number) {
  return apiRequest<void>(`/v1/companies/${id}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
}

export async function analyzeCompanyWebsite(token: string, id: number) {
  return apiRequest<{ run_id: string; status: string }>(`/v1/companies/${id}/analyze`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export async function generateCompanyKeywords(token: string, id: number) {
  return apiRequest<{ run_id: string; status: string }>(`/v1/companies/${id}/keywords/generate`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export async function getCompanyKeywords(token: string, id: number) {
  return apiRequest<BrandKeyword[]>(`/v1/companies/${id}/keywords`, { headers: { Authorization: `Bearer ${token}` } });
}
