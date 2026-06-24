"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth/auth-provider";
import { useToast } from "@/stores/toast";
import { getErrorMessage } from "@/types/errors";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Eye,
  Target,
  FileText,
  Send,
  ChevronDown,
  Loader2,
  Zap,
  BarChart3,
  Users,
  PenLine,
  ArrowRight,
  Activity,
  CheckCircle2,
  Circle,
} from "lucide-react";
import { apiRequest, type Opportunity, type Project } from "@/lib/api";
import { sourceLabel } from "@/lib/opportunity";
import { setStoredProjectId, withProjectId } from "@/lib/project";
import { useSelectedProjectId } from "@/hooks/use-selected-project";
import { PageHeader } from "@/components/shared/page-header";
import { KPIGrid } from "@/components/shared/kpi-card";
import { StatusBadge } from "@/components/shared/status-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { redditUrl } from "@/lib/reddit";

/* -------------------------------------------------------------------------- */
/*  Types                                                                     */
/* -------------------------------------------------------------------------- */

interface SetupStatus {
  brand_configured: boolean;
  personas_count: number;
  subreddits_count: number;
}

interface Subscription {
  plan_code: string;
  status: string;
  current_period_end?: string;
}

interface DashData {
  projects: {
    id: number;
    name: string;
    description?: string | null;
  }[];
  top_opportunities: Opportunity[];
  subscription: Subscription;
  setup_status?: SetupStatus;
  drafts_count?: number;
  published_count?: number;
}

interface DraftCounts {
  drafting: number;
  published: number;
  total: number;
}

interface UsageData {
  metrics?: {
    projects?: { used: number; limit: number };
    keywords?: { used: number; limit: number };
    subreddits?: { used: number; limit: number };
  };
}

interface VisibilitySummary {
  share_of_voice?: number;
  total_citations?: number;
  total_runs?: number;
  brand_mentioned?: number;
}

interface ActivityItem {
  id: number;
  action: string;
  created_at?: string;
}

interface WizardStep {
  label: string;
  title: string;
  description: string;
  actionLabel: string;
  done: boolean;
  href?: string;
  actionKind: "route" | "modal";
}

/* -------------------------------------------------------------------------- */
/*  Wizard step definitions                                                   */
/* -------------------------------------------------------------------------- */

const WIZARD_STEPS: {
  label: string;
  title: string;
  description: string;
  actionLabel: string;
  href?: string;
  actionKind: "route" | "modal";
}[] = [
  {
    label: "Set Brand Profile",
    title: "Review your brand profile",
    description:
      "Add your website, product summary, audience, and voice so the rest of the workflow has solid context.",
    actionLabel: "Open Brand",
    href: "/app/brand",
    actionKind: "route",
  },
  {
    label: "Add Audience Signals",
    title: "Add your first audience",
    description:
      "Create a customer type so discovery can generate stronger signals and surface more relevant conversations.",
    actionLabel: "Open Audience",
    href: "/app/persona",
    actionKind: "route",
  },
  {
    label: "Discover Communities",
    title: "Discover matching communities",
    description:
      "Turn audience signals into monitored Reddit communities and prepare the engagement queue.",
    actionLabel: "Open Radar",
    href: "/app/discovery",
    actionKind: "route",
  },
  {
    label: "Run First Scan",
    title: "Run your first visibility check",
    description:
      "Create or run a prompt set so the dashboard can start tracking AI share of voice and citations.",
    actionLabel: "Open AI Visibility",
    href: "/app/visibility",
    actionKind: "route",
  },
];

/* -------------------------------------------------------------------------- */
/*  Quick-action links                                                        */
/* -------------------------------------------------------------------------- */

const QUICK_ACTIONS = [
  {
    label: "AI Visibility",
    icon: Eye,
    href: "/app/visibility",
  },
  {
    label: "Communities",
    icon: Users,
    href: "/app/discovery",
  },
  {
    label: "Content Studio",
    icon: PenLine,
    href: "/app/content",
  },
  {
    label: "Analytics",
    icon: BarChart3,
    href: "/app/analytics",
  },
];

/* -------------------------------------------------------------------------- */
/*  Helpers                                                                   */
/* -------------------------------------------------------------------------- */

function relativeTime(dateStr?: string): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatAction(action: string): string {
  return action.replace(/_/g, " ").replace(/\./g, " \u2192 ");
}

/* -------------------------------------------------------------------------- */
/*  Component                                                                 */
/* -------------------------------------------------------------------------- */

export default function DashboardPage() {
  const router = useRouter();
  const { token } = useAuth();
  const toast = useToast();
  const selectedProjectId = useSelectedProjectId();

  /* ---- state ---- */
  const [loading, setLoading] = useState(true);
  const [dash, setDash] = useState<DashData | null>(null);
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [visibility, setVisibility] = useState<VisibilitySummary | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [draftCounts, setDraftCounts] = useState<DraftCounts | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [bizName, setBizName] = useState("");
  const [bizDesc, setBizDesc] = useState("");
  const [creating, setCreating] = useState(false);
  const [autoPipelineUrl, setAutoPipelineUrl] = useState("");

  // Wizard state
  const [wizardOpen, setWizardOpen] = useState(true);
  const [wizardDismissed, setWizardDismissed] = useState(false);

  /* ---- initial load ---- */
  useEffect(() => {
    if (!token) return;
    const storageKey = `wizard-dismissed-${selectedProjectId}`;
    const dismissed = localStorage.getItem(storageKey) === "true";
    // Migration: if new key doesn't exist but old one does, migrate
    if (!dismissed && !localStorage.getItem(storageKey)) {
      const oldDismissed = localStorage.getItem("wizard-dismissed") === "true";
      if (oldDismissed) {
        localStorage.setItem(storageKey, "true");
      }
      setWizardDismissed(oldDismissed);
    } else {
      setWizardDismissed(dismissed);
    }
    void loadAll();
  }, [token, selectedProjectId]);

  /* ---- data fetching (unchanged) ---- */
  async function loadAll() {
    setLoading(true);
    try {
      let dashData: DashData | null = null;
      let usageData: UsageData | null = null;
      let visData: VisibilitySummary | null = null;
      let actData: ActivityItem[] = [];
      let draftCountsData: DraftCounts | null = null;

      try {
        dashData = await apiRequest<DashData>(
          withProjectId("/v1/dashboard", selectedProjectId),
          {},
          token,
        );
      } catch (err: unknown) {
        console.warn("Failed to load dashboard:", err);
      }

      try {
        usageData = await apiRequest<UsageData>(
          withProjectId("/v1/usage", selectedProjectId),
          {},
          token,
        );
      } catch (err: unknown) {
        console.warn("Failed to load usage:", err);
      }

      try {
        visData = await apiRequest<VisibilitySummary>(
          withProjectId("/v1/visibility/summary", selectedProjectId),
          {},
          token,
        );
      } catch (err: unknown) {
        console.warn("Failed to load visibility:", err);
      }

      try {
        draftCountsData = await apiRequest<DraftCounts>(
          withProjectId("/v1/drafts/count", selectedProjectId),
          {},
          token,
        );
      } catch (err: unknown) {
        console.warn("Failed to load draft counts:", err);
      }

      try {
        const res = await apiRequest<{ items: ActivityItem[] }>("/v1/activity", {}, token);
        actData = res.items || [];
      } catch (err: unknown) {
        console.warn("Failed to load activity:", err);
      }

      setDash(dashData);
      setUsage(usageData);
      setVisibility(visData);
      setActivity(actData);
      setDraftCounts(draftCountsData);
    } finally {
      setLoading(false);
    }
  }

  /* ---- create project (unchanged) ---- */
  async function handleCreate() {
    if (!bizName.trim()) {
      toast.warning("Please enter a business name.");
      return;
    }
    setCreating(true);
    try {
      const createdProject = await apiRequest<Project>(
        "/v1/projects",
        {
          method: "POST",
          body: JSON.stringify({
            name: bizName.trim(),
            description: bizDesc.trim() || null,
          }),
        },
        token,
      );
      setStoredProjectId(createdProject.id);
      toast.success("Project created", "Next: add your first audience.");
      setBizName("");
      setBizDesc("");
      setShowCreate(false);
      router.push("/app/persona");
    } catch (error: unknown) {
      toast.error("Could not create project", getErrorMessage(error));
    }
    setCreating(false);
  }

  /* ---- auto-pipeline (unchanged) ---- */
  function handleAutoPipeline() {
    if (!autoPipelineUrl.trim()) {
      toast.warning("Please enter a URL");
      return;
    }
    router.push(
      `/app/auto-pipeline?url=${encodeURIComponent(autoPipelineUrl)}`,
    );
  }

  /* ---- wizard dismiss ---- */
  function dismissWizard() {
    localStorage.setItem(`wizard-dismissed-${selectedProjectId}`, "true");
    setWizardDismissed(true);
  }

  /* ---- derived data ---- */
  const hasProject = (dash?.projects?.length || 0) > 0;
  const focusProject =
    dash?.projects?.find((p) => p.id === selectedProjectId) ??
    dash?.projects?.[0] ??
    null;
  const topOpps = dash?.top_opportunities || [];
  const setupStatus = dash?.setup_status;

  // Build the wizard steps with live done-state
  const steps: WizardStep[] = [
    {
      label: "Create Project",
      title: "Create your first project",
      description:
        "Start a project to connect brand setup, audience signals, community mapping, and visibility tracking.",
      actionLabel: "Create Project",
      done: hasProject,
      actionKind: "modal",
    },
    {
      label: "Define Brand",
      title: "Review your brand profile",
      description:
        "Add your website, product summary, audience, and voice so the rest of the workflow has solid context.",
      actionLabel: "Open Brand",
      done: setupStatus?.brand_configured || false,
      href: "/app/brand",
      actionKind: "route",
    },
    {
      label: "Add Audience",
      title: "Add your first audience",
      description:
        "Create a customer type so discovery can generate stronger signals and surface more relevant conversations.",
      actionLabel: "Open Audience",
      done: (setupStatus?.personas_count || 0) > 0,
      href: "/app/persona",
      actionKind: "route",
    },
    {
      label: "Map Communities",
      title: "Discover matching communities",
      description:
        "Turn audience signals into monitored Reddit communities and prepare the engagement queue.",
      actionLabel: "Open Radar",
      done: (setupStatus?.subreddits_count || 0) > 0,
      href: "/app/discovery",
      actionKind: "route",
    },
    {
      label: "Track Visibility",
      title: "Run your first visibility check",
      description:
        "Create or run a prompt set so the dashboard can start tracking AI share of voice and citations.",
      actionLabel: "Open AI Visibility",
      done: (visibility?.total_runs || 0) > 0,
      href: "/app/visibility",
      actionKind: "route",
    },
  ];

  const currentStepIdx = steps.findIndex((s) => !s.done);
  const completedCount = steps.filter((s) => s.done).length;
  const allDone = completedCount === steps.length;
  const nextStep = steps.find((s) => !s.done) ?? null;
  const showWizard =
    !wizardDismissed && hasProject && !allDone;

  // Usage quota warning
  const projectUsage = usage?.metrics?.projects;
  const keywordUsage = usage?.metrics?.keywords;
  const subredditUsage = usage?.metrics?.subreddits;
  const nearQuota =
    (projectUsage &&
      projectUsage.used / projectUsage.limit >= 0.8) ||
    (keywordUsage &&
      keywordUsage.used / keywordUsage.limit >= 0.8) ||
    (subredditUsage &&
      subredditUsage.used / subredditUsage.limit >= 0.8);

  /* ---- loading skeleton ---- */
  if (loading) {
    return (
      <div className="grid gap-8">
        <div className="flex items-center justify-between">
          <Skeleton className="h-8 w-36" />
          <Skeleton className="h-8 w-28" />
        </div>
        <div className="grid grid-cols-2 gap-5 md:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          <Skeleton className="h-96 rounded-xl" />
          <div className="grid gap-4">
            <Skeleton className="h-48 rounded-xl" />
            <Skeleton className="h-48 rounded-xl" />
          </div>
        </div>
      </div>
    );
  }

  /* =================================================================       */
  /*  RENDER                                                                  */
  /* =================================================================       */
  return (
    <div className="grid gap-8">
      {/* ---- Page Header ---- */}
      <PageHeader
        title="Dashboard"
        description={
          focusProject
            ? `Managing: ${focusProject.name}`
            : undefined
        }
        actions={
          <Button onClick={() => setShowCreate(true)}>
            New Project
          </Button>
        }
      />

      {/* ---- Quota Warning Banner ---- */}
      {nearQuota && (
        <div className="flex items-center gap-3 rounded-xl border border-warning bg-warning/10 px-4 py-3">
          <Zap className="h-4 w-4 text-warning" />
          <span className="text-sm text-warning-foreground">
            Your project footprint is approaching its limit. Visit Settings to
            review usage.
          </span>
        </div>
      )}

      {/* ---- Collapsible Setup Wizard ---- */}
      {showWizard && (
        <Collapsible open={wizardOpen} onOpenChange={setWizardOpen}>
          <Card>
            <CollapsibleTrigger className="w-full cursor-pointer">
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle>
                    Complete Setup
                    <Badge variant="secondary" className="ml-2">
                      {completedCount}/{steps.length}
                    </Badge>
                  </CardTitle>
                </div>
                <ChevronDown
                  className={`h-5 w-5 text-muted-foreground transition-transform ${
                    wizardOpen ? "rotate-180" : ""
                  }`}
                />
              </CardHeader>
            </CollapsibleTrigger>

            <CollapsibleContent>
              <CardContent>
                {/* Horizontal Stepper */}
                <div className="mb-6 flex items-center gap-1 overflow-x-auto">
                  {steps.map((step, idx) => (
                    <div
                      key={step.label}
                      className="flex items-center gap-1"
                    >
                      <div className="flex items-center gap-1.5 whitespace-nowrap">
                        {step.done ? (
                          <CheckCircle2 className="h-4 w-4 text-success" />
                        ) : idx === currentStepIdx ? (
                          <Circle className="h-4 w-4 text-primary" />
                        ) : (
                          <Circle className="h-4 w-4 text-muted-foreground/40" />
                        )}
                        <span
                          className={`text-xs font-medium ${
                            step.done
                              ? "text-success"
                              : idx === currentStepIdx
                                ? "text-foreground"
                                : "text-muted-foreground/60"
                          }`}
                        >
                          {step.label}
                        </span>
                      </div>
                      {idx < steps.length - 1 && (
                        <div
                          className={`mx-1 h-px w-4 sm:w-8 ${
                            step.done ? "bg-success" : "bg-border"
                          }`}
                        />
                      )}
                    </div>
                  ))}
                </div>

                {/* Next-step card */}
                {nextStep && (
                  <div className="rounded-xl border bg-muted/50 p-5">
                    <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      Next Step
                    </div>
                    <h3 className="mt-1 text-sm font-semibold text-foreground">
                      {nextStep.title}
                    </h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {nextStep.description}
                    </p>
                    <div className="mt-3">
                      {nextStep.actionKind === "modal" ? (
                        <Button onClick={() => setShowCreate(true)}>
                          {nextStep.actionLabel}
                        </Button>
                      ) : (
                        <Button
                          onClick={() =>
                            nextStep.href && router.push(nextStep.href)
                          }
                        >
                          {nextStep.actionLabel}
                        </Button>
                      )}
                    </div>
                  </div>
                )}
              </CardContent>
            </CollapsibleContent>
          </Card>
        </Collapsible>
      )}

      {/* ---- Compact Pipeline Card ---- */}
      <Card size="sm">
        <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10">
              <Zap className="h-4 w-4 text-primary" />
            </div>
            <div>
              <div className="text-sm font-semibold text-foreground">
                Try Auto Pipeline
              </div>
              <div className="text-xs text-muted-foreground">
                Enter a URL to automatically generate your entire Reddit
                strategy
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Input
              type="url"
              value={autoPipelineUrl}
              onChange={(e) => setAutoPipelineUrl(e.target.value)}
              placeholder="https://example.com"
              className="h-8 w-full text-sm sm:w-64"
              onKeyDown={(e) =>
                e.key === "Enter" && handleAutoPipeline()
              }
            />
            <Button size="sm" onClick={handleAutoPipeline}>
              Launch
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* ---- KPI Grid ---- */}
      <KPIGrid
        columns={4}
        cards={[
          {
            label: "Visibility Score",
            value: visibility?.share_of_voice
              ? `${visibility.share_of_voice}%`
              : "\u2014",
            icon: Eye,
          },
          {
            label: "Opportunities",
            value: topOpps.length,
            icon: Target,
          },
          {
            label: "Drafts Ready",
            value: draftCounts?.drafting ?? dash?.drafts_count ?? topOpps.filter((o: Opportunity) => o.status === "drafting").length,
            icon: FileText,
          },
          {
            label: "Published",
            value: draftCounts?.published ?? dash?.published_count ?? topOpps.filter((o: Opportunity) => o.status === "posted").length,
            icon: Send,
          },
        ]}
      />

      {/* ---- Main Content: Priority Queue + Sidebar ---- */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
        {/* ---- Priority Queue ---- */}
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="flex items-center gap-2">
                Priority Queue
                {topOpps.length > 0 && (
                  <Badge variant="secondary">{topOpps.length}</Badge>
                )}
              </CardTitle>
            </div>
          </CardHeader>

          {topOpps.length === 0 ? (
            <CardContent>
              <EmptyState
                icon={Target}
                title="No opportunities yet"
                description="Run your first community scan after adding audience signals and monitored communities."
              />
            </CardContent>
          ) : (
            <CardContent>
              <div className="space-y-3">
                {topOpps.slice(0, 6).map((opp) => (
                  <div
                    key={opp.id}
                    className="flex items-start justify-between gap-3 rounded-xl border bg-card p-5"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex h-5 w-5 items-center justify-center rounded text-xs font-bold text-orange-500">
                          R
                        </span>
                        <Badge variant="outline" className="text-xs">
                          {sourceLabel(opp)}
                        </Badge>
                      </div>
                      <a
                        href={redditUrl(opp.permalink)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-1.5 block truncate text-sm font-semibold text-foreground hover:underline"
                      >
                        {opp.title}
                      </a>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        {(opp.score_reasons || [])
                          .slice(0, 2)
                          .map((reason: string) => (
                            <Badge
                              key={reason}
                              variant="secondary"
                              className="text-xs"
                            >
                              {reason}
                            </Badge>
                          ))}
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <StatusBadge score={opp.score || 0} />
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          router.push(
                            withProjectId(`/app/content?opportunity=${opp.id}`, focusProject?.id ?? selectedProjectId),
                          )
                        }
                      >
                        Draft Reply
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-4 flex justify-end">
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground"
                  onClick={() => router.push("/app/discovery")}
                >
                  View all in Opportunity Radar
                  <ArrowRight className="ml-1 h-3 w-3" />
                </Button>
              </div>
            </CardContent>
          )}
        </Card>

        {/* ---- Sidebar ---- */}
        <div className="grid gap-8">
          {/* Quick Actions Strip */}
          <Card size="sm">
            <CardContent className="flex gap-2 overflow-x-auto py-2">
              {QUICK_ACTIONS.map((qa) => {
                const Icon = qa.icon;
                return (
                  <Button
                    key={qa.label}
                    variant="outline"
                    size="sm"
                    className="shrink-0 gap-1.5"
                    onClick={() => router.push(qa.href)}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {qa.label}
                  </Button>
                );
              })}
            </CardContent>
          </Card>

          {/* Recent Activity */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Activity className="h-4 w-4" />
                Recent Activity
              </CardTitle>
            </CardHeader>
            <CardContent>
              {activity.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No activity yet. Start with brand setup or a visibility run.
                </p>
              ) : (
                <div className="space-y-2">
                  {activity.slice(0, 5).map((item) => (
                    <div
                      key={item.id}
                      className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-muted/50"
                    >
                      <span className="truncate text-sm font-medium text-foreground">
                        {formatAction(item.action)}
                      </span>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {relativeTime(item.created_at)}
                      </span>
                    </div>
                  ))}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-2 w-full text-muted-foreground"
                    onClick={() => router.push("/app/analytics")}
                  >
                    View all
                    <ArrowRight className="ml-1 h-3 w-3" />
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* ---- Create Project Dialog ---- */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Create New Project</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="biz-name">Business Name</Label>
              <Input
                id="biz-name"
                type="text"
                value={bizName}
                onChange={(e) => setBizName(e.target.value)}
                placeholder="Your company or product name"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="biz-desc">Description</Label>
              <Textarea
                id="biz-desc"
                rows={3}
                value={bizDesc}
                onChange={(e) => setBizDesc(e.target.value)}
                placeholder="What category, workflow, or audience does this project represent?"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowCreate(false)}
            >
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={creating}>
              {creating && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Create Project
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
