import { API_BASE, apiRequest } from "../api";

export interface Workspace {
  id: number;
  name: string;
  slug: string;
}

export interface NotificationPreferences {
  email_notifications: boolean;
  digest_email: boolean;
  slack_notifications: boolean;
}

export interface UserProfile {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  notification_preferences: NotificationPreferences;
  created_at: string | null;
}

export interface UsageResponse {
  plan: string;
  metrics: Record<string, { used: number; limit: number }>;
}

export async function getWorkspace(token: string): Promise<Workspace> {
  return apiRequest<Workspace>("/v1/workspace", {}, token);
}

export async function updateWorkspace(token: string, data: { name?: string }): Promise<Workspace> {
  return apiRequest<Workspace>(
    "/v1/workspace",
    { method: "PATCH", body: JSON.stringify(data) },
    token,
  );
}

export async function getProfile(token: string): Promise<UserProfile> {
  return apiRequest<UserProfile>("/v1/users/me", {}, token);
}

export async function updateProfile(
  token: string,
  data: { full_name?: string; notification_preferences?: Partial<NotificationPreferences> },
): Promise<UserProfile> {
  return apiRequest<UserProfile>(
    "/v1/users/me",
    { method: "PATCH", body: JSON.stringify(data) },
    token,
  );
}

export async function getUsage(token: string, projectId?: number): Promise<UsageResponse> {
  const query = projectId ? `?project_id=${projectId}` : "";
  return apiRequest<UsageResponse>(`/v1/usage${query}`, {}, token);
}

function sanitizeDownloadFilename(raw: string | null | undefined): string {
  const fallback = "signalflow-export.json";
  if (!raw) {
    return fallback;
  }
  const cleaned = raw
    .replace(/[\u0000-\u001F\u007F]+/g, "")
    .split(/[\\/]+/)
    .pop()
    ?.trim()
    .replace(/^\.+/, "");
  return cleaned || fallback;
}

function filenameFromDisposition(disposition: string): string {
  const encodedMatch = disposition.match(/filename\*\s*=\s*([^;]+)/i);
  if (encodedMatch) {
    const encodedValue = encodedMatch[1].trim().replace(/^"(.*)"$/, "$1");
    const parts = encodedValue.split("'");
    const encodedName = parts.length >= 3 ? parts.slice(2).join("'") : encodedValue;
    try {
      return sanitizeDownloadFilename(decodeURIComponent(encodedName));
    } catch {
      // Fall back to legacy filename parsing below.
    }
  }

  const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
  return sanitizeDownloadFilename(filenameMatch?.[1]);
}

/**
 * Triggers a browser download of the workspace JSON export. Streams the response
 * through a blob so the download dialog works even with Bearer auth.
 */
export async function downloadWorkspaceExport(token: string): Promise<void> {
  const response = await fetch(`${API_BASE}/v1/workspace/export`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = `Export failed: ${response.status}`;
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch {
      // ignore parse errors
    }
    throw new Error(detail);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = filenameFromDisposition(disposition);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Safari can interrupt an in-flight download if the blob URL is revoked
  // synchronously after click(). Defer so the browser has a chance to pick
  // up the file before the underlying blob is freed.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
