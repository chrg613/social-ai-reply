import type { Project } from "./api";

const STORAGE_KEY = "signalflow-project-id";
export const PROJECT_CHANGE_EVENT = "signalflow-project-change";

export function getStoredProjectId(): number | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function setStoredProjectId(projectId: number): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, String(projectId));
  window.dispatchEvent(new CustomEvent(PROJECT_CHANGE_EVENT, { detail: { projectId } }));
}

export function withProjectId(path: string, projectId: number | null | undefined): string {
  if (!projectId) {
    return path;
  }
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}project_id=${projectId}`;
}

export function resolveProjectId(projects: Project[]): number | null {
  const stored = getStoredProjectId();
  if (stored && projects.some((project) => project.id === stored)) {
    return stored;
  }
  return projects[0]?.id ?? null;
}
