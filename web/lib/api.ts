export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type AuthPayload = {
  access_token: string;
  refresh_token?: string | null;
  token_type: string;
  user: {
    id: number;
    supabase_user_id: string;
    email: string;
    full_name: string;
    is_active: boolean;
  };
  workspace: {
    id: number;
    name: string;
    slug: string;
    role: string;
  };
};

// ── Shared types (used across multiple domain modules) ──────────

export type Project = {
  id: number;
  workspace_id: number;
  name: string;
  slug: string;
  description: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export type Opportunity = {
  id: number;
  project_id: number;
  scan_run_id: string | null;
  reddit_post_id: string;
  subreddit_name: string;
  author: string;
  title: string;
  permalink: string;
  body_excerpt: string | null;
  score: number;
  status: string;
  score_reasons: string[];
  keyword_hits: string[];
  rule_risk: string[];
  created_at: string;
  updated_at: string;
  posted_at: string | null;
};

export type ReplyDraft = {
  id: number;
  project_id: number;
  opportunity_id: number;
  content: string;
  rationale: string | null;
  source_prompt: string | null;
  version: number;
  created_at: string;
};

export type PostDraft = {
  id: number;
  project_id: number;
  title: string;
  body: string;
  rationale: string | null;
  source_prompt: string | null;
  version: number;
  created_at: string;
};

export type Dashboard = {
  projects: Project[];
  top_opportunities: Opportunity[];
};

export type BrandProfile = {
  id: number;
  project_id: number;
  brand_name: string;
  website_url: string | null;
  summary: string | null;
  voice_notes: string | null;
  product_summary: string | null;
  target_audience: string | null;
  call_to_action: string | null;
  reddit_username: string | null;
  linkedin_url: string | null;
  last_analyzed_at: string | null;
};

export type Persona = {
  id: number;
  project_id: number;
  name: string;
  role: string | null;
  summary: string;
  pain_points: string[];
  goals: string[];
  triggers: string[];
  preferred_subreddits: string[];
  source: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type Keyword = {
  id: number;
  project_id: number;
  keyword: string;
  rationale: string | null;
  priority_score: number;
  source: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type SubredditAnalysis = {
  id: number;
  top_post_types: string[];
  audience_signals: string[];
  posting_risk: string[];
  recommendation: string;
  analyzed_at: string;
};

export type MonitoredSubreddit = {
  id: number;
  project_id: number;
  name: string;
  title: string | null;
  description: string | null;
  subscribers: number;
  activity_score: number;
  fit_score: number;
  rules_summary: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  analyses: SubredditAnalysis[];
};

export type PromptTemplate = {
  id: number;
  project_id: number | null;
  prompt_type: string;
  name: string;
  system_prompt: string;
  instructions: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
};

export type Subscription = {
  plan_code: string;
  status: string;
  current_period_end: string | null;
  features: string[];
  limits: Record<string, number>;
};

export type WebhookEndpoint = {
  id: number;
  workspace_id: number;
  target_url: string;
  event_types: string[];
  is_active: boolean;
  last_tested_at: string | null;
  created_at: string;
};

export type SecretRecord = {
  id: number;
  workspace_id: number;
  provider: string;
  label: string;
  created_at: string;
  updated_at: string;
};

export interface CompanyProfile {
  id: number;
  workspace_id: number;
  name: string;
  website_url: string | null;
  description: string | null;
  category: string | null;
  target_audience: string | null;
  geography: string | null;
  language: string;
  features: string | null;
  benefits: string | null;
  pain_points: string | null;
  competitors: string | null;
  brand_voice: string | null;
  preferred_cta: string | null;
  extracted_summary: string | null;
  extracted_keywords: string | null;
  extracted_pain_points: string | null;
  extracted_competitors: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface BrandKeyword {
  id: number;
  company_id: number;
  keyword: string;
  type: string;
  weight: number;
  source: string | null;
  times_matched: number;
  times_approved: number;
  times_rejected: number;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface Source {
  id: number;
  company_id: number;
  platform: string;
  source_name: string;
  source_url: string | null;
  status: string;
  priority: number;
  config_json: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface AgentRun {
  id: number;
  company_id: number;
  agent_name: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  items_fetched: number;
  items_kept: number;
  items_rejected: number;
  error_message: string | null;
  created_at: string;
}

export interface Feedback {
  id: number;
  opportunity_id: number;
  company_id: number;
  action: string;
  reason: string | null;
  created_at: string;
}

// ── Base helpers ────────────────────────────────────────────────

export function isAuthError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  // Only treat genuine authentication failures as auth errors.
  // Do NOT include "no_local_account" (404 for OAuth setup) or
  // workspace/permission errors (403s).
  return [
    "Authentication required.",
    "Invalid token.",
    "User not found.",
    "Session expired. Please sign in again.",
    "account_deactivated",
  ].includes(error.message);
}

export function isSetupRequired(error: unknown): boolean {
  return error instanceof Error && error.message === "no_local_account";
}

export async function apiRequest<T>(path: string, options: RequestInit = {}, token?: string | null): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers, cache: "no-store" });
  if (!response.ok) {
    let detail = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail ?? payload.message ?? detail;
    } catch {
      // ignore JSON parse errors
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return undefined as unknown as T;
  }
  return response.json() as Promise<T>;
}

// ── Re-exports from domain modules ──────────────────────────────

export {
  forgotPassword,
  resetPassword,
} from "./api/auth";

export {
  getProjects,
  getProject,
  createProject,
  updateProject,
  deleteProject,
  getDashboard,
} from "./api/projects";

export {
  getKeywords,
  createKeyword,
  deleteKeyword,
  getSubreddits,
  addSubreddit,
  removeSubreddit,
  triggerScan,
  getScanStatus,
  getOpportunities,
} from "./api/discovery";

export {
  generateReply,
  getReplyDrafts,
  createPostDraft,
  getPostDrafts,
  getPrompts,
  createPrompt,
  updatePrompt,
  deletePrompt,
} from "./api/content";

export {
  getPromptSets,
  createPromptSet,
  runPromptSet,
  getVisibilitySummary,
  getVisibilityPrompts,
  getCitations,
  getSourceDomains,
  getSourceGaps,

  // Re-export interfaces that were previously on this module
  type PromptSetItem,
  type VisibilitySummary,
  type PromptRunResult,
  type CitationItem,
} from "./api/visibility";

export {
  getNotifications,
  type NotificationItem,
} from "./api/notifications";

export {
  getActivity,
  type ActivityItem,
} from "./api/analytics";

export {
  getWorkspace,
  updateWorkspace,
  getProfile,
  updateProfile,
  getUsage,
  downloadWorkspaceExport,
  type Workspace,
  type NotificationPreferences,
  type UserProfile,
  type UsageResponse,
} from "./api/workspace";
