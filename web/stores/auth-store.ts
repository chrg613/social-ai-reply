import { create } from "zustand";
import type { AuthPayload } from "@/lib/api";

interface AuthState {
  token: string | null;
  user: AuthPayload["user"] | null;
  workspace: AuthPayload["workspace"] | null;
  loading: boolean;
  error: string | null;
  persist: (payload: AuthPayload) => void;
  clearAuth: () => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setToken: (token: string | null) => void;
}

export const STORAGE_KEY = "signalflow-auth";
export const LEGACY_STORAGE_KEY = "reply-radar-auth";

/**
 * One-time migration: if the legacy key exists and the current key does not,
 * copy the data over and delete the legacy key. Called once on store init
 * (browser-side only) so existing users are not logged out after the rename.
 */
function migrateLegacyStorage(): void {
  if (typeof window === "undefined") return;
  const legacyRaw = window.localStorage.getItem(LEGACY_STORAGE_KEY);
  if (!legacyRaw) return;
  const currentRaw = window.localStorage.getItem(STORAGE_KEY);
  if (!currentRaw) {
    // Migrate: copy legacy data to the new key before deleting the old one.
    window.localStorage.setItem(STORAGE_KEY, legacyRaw);
  }
  window.localStorage.removeItem(LEGACY_STORAGE_KEY);
}

// Run migration eagerly at module load time (runs once per page load).
migrateLegacyStorage();

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  user: null,
  workspace: null,
  loading: true,
  error: null,

  persist(payload) {
    set({
      token: payload.access_token,
      user: payload.user,
      workspace: payload.workspace,
    });
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      window.localStorage.removeItem(LEGACY_STORAGE_KEY);
    }
  },

  clearAuth() {
    set({ token: null, user: null, workspace: null, error: null, loading: true });
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_KEY);
      window.localStorage.removeItem(LEGACY_STORAGE_KEY);
      // Clear selected project ID on logout (Issue #55).
      window.localStorage.removeItem("rf-selected-project");
      // Reset transient UI state (Issue #58).
      window.localStorage.removeItem("rf-sidebar-open");
      window.localStorage.removeItem("rf-notif-panel-open");
    }
  },

  setLoading(loading) {
    set({ loading });
  },

  setError(error) {
    set({ error });
  },

  setToken(token) {
    set({ token });
    if (typeof window !== "undefined" && token) {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        try {
          const stored = JSON.parse(raw) as AuthPayload;
          stored.access_token = token;
          window.localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
        } catch {
          // ignore
        }
      }
    }
  },
}));
