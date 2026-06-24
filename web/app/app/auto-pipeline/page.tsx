"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, ChevronDown, ChevronRight, Check, Zap } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { useToast } from "@/stores/toast";
import { getErrorMessage } from "@/types/errors";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { useSelectedProjectId } from "@/hooks/use-selected-project";
import { PageHeader } from "@/components/shared/page-header";
import { setStoredProjectId } from "@/lib/project";
import {
  executePipelineRun,
  getPipelineRun,
  listPipelineRuns,
  startPipelineRun,
  type PipelineRun,
} from "@/lib/api/pipeline";

// Step definitions
const PIPELINE_STEPS = [
  { key: "analyzing", label: "Analyzing website" },
  { key: "generating_personas", label: "Generating personas" },
  { key: "discovering_keywords", label: "Discovering keywords" },
  { key: "scanning_all", label: "Scanning Social Media" },
  { key: "checking_opportunities", label: "Checking opportunities" },
  { key: "analyzing_competitors", label: "Analyzing competitor mentions" },
  { key: "generating_drafts", label: "Generating drafts" },
];

function isFailureStatus(status: PipelineRun["status"]) {
  return status === "failed";
}

function isResultStatus(status: PipelineRun["status"]) {
  return status === "ready" || status === "executed";
}

function isTerminalStatus(status: PipelineRun["status"]) {
  return isFailureStatus(status) || isResultStatus(status);
}

function isLlmSetupError(message?: string | null) {
  const normalized = message?.toLowerCase() ?? "";
  return normalized.includes("no llm provider available") || normalized.includes("backend .env.local");
}

function isRedditDiscoveryError(message?: string | null) {
  const normalized = message?.toLowerCase() ?? "";
  return (
    normalized.includes("all subreddit discovery requests failed") ||
    normalized.includes("public reddit feeds") ||
    normalized.includes("reddit discovery methods failed") ||
    normalized.includes("no subreddits could be discovered") ||
    normalized.includes("apify") ||
    normalized.includes("add monitored subreddits before scanning")
  );
}

/** Map raw backend error strings to user-friendly messages. */
function friendlyPipelineError(message?: string | null): string {
  if (!message) return "Something went wrong while running the pipeline. Please try again.";
  const m = message.toLowerCase();
  if (m.includes("add monitored subreddits before scanning"))
    return "No communities are being monitored yet. The pipeline will discover relevant subreddits automatically — please try again.";
  if (m.includes("429") || m.includes("too many requests") || m.includes("rate limit"))
    return "Reddit is temporarily rate-limiting requests. Please wait a few minutes and try again.";
  if (m.includes("no llm provider"))
    return "The AI provider is not configured. Please set up your API key in Settings.";
  if (m.includes("connection") || m.includes("timeout") || m.includes("timed out"))
    return "Could not connect to an external service. Please check your internet connection and try again.";
  if (m.includes("could not access reddit") || m.includes("reddit discovery"))
    return "Reddit is temporarily unavailable. Please retry in a few minutes.";
  // Strip HTTP status codes from the message for cleaner display
  const cleaned = message.replace(/^\d{3}:\s*/, "");
  return cleaned || "An unexpected error occurred. Please try again.";
}

function openContentStudioForProject(router: ReturnType<typeof useRouter>, projectId: number) {
  setStoredProjectId(projectId);
  router.push(`/app/content?project_id=${projectId}`);
}

export default function AutoPipelinePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { token } = useAuth();
  const toast = useToast();
  const selectedProjectId = useSelectedProjectId();

  // State
  const [urlInput, setUrlInput] = useState("");
  const [timeFilter, setTimeFilter] = useState("week");
  const [activeRun, setActiveRun] = useState<PipelineRun | null>(null);
  const [previousRuns, setPreviousRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [expanding, setExpanding] = useState<Record<string, boolean>>({});
  const resultHydrationRetryRef = useRef<string | null>(null);

  // Pre-populate URL from query string if present
  useEffect(() => {
    const urlParam = searchParams.get("url");
    if (urlParam) {
      setUrlInput(urlParam);
    }
  }, [searchParams]);

  // Load previous runs on mount
  useEffect(() => {
    if (!token) return;
    loadPreviousRuns();
  }, [token, selectedProjectId]);

  // Poll active run
  useEffect(() => {
    if (!activeRun || isTerminalStatus(activeRun.status)) return;
    if (!token) return;

    const interval = setInterval(() => {
      void pollRun();
    }, 2000);

    return () => clearInterval(interval);
  }, [activeRun, token]);

  useEffect(() => {
    if (!activeRun || !token || !isResultStatus(activeRun.status) || activeRun.results) {
      resultHydrationRetryRef.current = null;
      return;
    }
    if (resultHydrationRetryRef.current === activeRun.id) {
      return;
    }
    resultHydrationRetryRef.current = activeRun.id;
    const timeout = window.setTimeout(() => {
      void openRun(activeRun.id);
    }, 2000);
    return () => window.clearTimeout(timeout);
  }, [activeRun, token]);

  async function loadPreviousRuns() {
    setLoading(true);
    try {
      const runs = await listPipelineRuns(token, selectedProjectId);
      setPreviousRuns(runs.items || []);
    } catch (err: unknown) {
      toast.error("Failed to load pipeline runs", getErrorMessage(err));
    }
    setLoading(false);
  }

  async function pollRun() {
    if (!activeRun || !token) return;
    try {
      const updated = await getPipelineRun(token, activeRun.id);
      setActiveRun(updated);
    } catch (err: unknown) {
      toast.error("Failed to refresh pipeline status", getErrorMessage(err));
    }
  }

  async function openRun(runId: string) {
    if (!token) {
      toast.error("Please log in first.");
      return;
    }

    try {
      const run = await getPipelineRun(token, runId);
      setActiveRun(run);
    } catch (error: unknown) {
      toast.error("Failed to open pipeline run", getErrorMessage(error));
    }
  }

  async function handleLaunch() {
    if (!urlInput.trim()) {
      toast.warning("Please enter a website URL.");
      return;
    }

    if (!token) {
      toast.error("Please log in first.");
      return;
    }

    setLaunching(true);
    try {
      // Ensure URL has a scheme so the backend fetch doesn't choke.
      let url = urlInput.trim();
      if (!/^https?:\/\//i.test(url)) {
        url = `https://${url}`;
      }
      // project_id is optional — the backend will resolve or create a
      // default project when it is omitted or null.
      const run = await startPipelineRun(token, url, selectedProjectId, timeFilter);
      setActiveRun(run);
      setUrlInput("");
    } catch (error: unknown) {
      const message = getErrorMessage(error) || "Unknown error";
      toast.error(
        isLlmSetupError(message) ? "Backend LLM is not configured" : "Failed to launch pipeline",
        message,
      );
    }
    setLaunching(false);
  }

  async function handleExecuteAll() {
    if (!activeRun || activeRun.status !== "ready" || !token) return;

    try {
      await executePipelineRun(token, activeRun.id);
      toast.success("Drafts marked as ready! Copy each draft and post manually.");
      setActiveRun(null);
      void loadPreviousRuns();
    } catch (error: unknown) {
      toast.error("Failed to execute", getErrorMessage(error));
    }
  }

  const toggleExpand = (section: string) => {
    setExpanding((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  // State 1: Input State
  if (!activeRun) {
    return (
      <div className="grid gap-8 max-w-[1000px] mx-auto">
        <PageHeader
          title="Auto Pipeline"
          description="Enter any website URL and we'll build your complete engagement strategy"
        />

        {/* Hero Input Section */}
        <div className="py-12 px-8 bg-gradient-to-br from-muted/50 to-card rounded-xl border">
          <div className="flex items-center gap-3 mb-6 justify-center">
            <div className="h-10 w-10 rounded-full bg-primary/10 flex items-center justify-center">
              <Zap className="h-5 w-5 text-primary" />
            </div>
            <h2 className="text-lg font-semibold">Launch a new pipeline</h2>
          </div>

          <div className="grid gap-3 max-w-lg mx-auto">
            <Input
              type="text"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleLaunch()}
              placeholder="https://example.com"
              className="h-12 px-5 text-base rounded-xl"
            />
            <div className="grid gap-1.5">
              <label htmlFor="scan-period" className="text-xs font-medium text-muted-foreground">
                Scan period
              </label>
              <select
                id="scan-period"
                value={timeFilter}
                onChange={(e) => setTimeFilter(e.target.value)}
                className="h-10 w-full rounded-xl border border-input bg-background px-4 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="day">Last 24 hours</option>
                <option value="week">Last 7 days</option>
                <option value="month">Last 30 days</option>
                <option value="all">All time</option>
              </select>
            </div>
            <Button
              disabled={launching}
              onClick={handleLaunch}
              size="lg"
              className="w-full h-12 text-[15px] font-semibold"
            >
              {launching && <Loader2 className="h-4 w-4 animate-spin" />}
              Launch Pipeline
            </Button>
          </div>
        </div>

        {/* Previous Runs */}
        {!loading && previousRuns.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold mb-3 text-muted-foreground uppercase tracking-wide">
              Previous Pipeline Runs
            </h3>
            <div className="grid gap-2.5">
              {previousRuns.map((run) => (
                <div
                  key={run.id}
                  onClick={() => void openRun(run.id)}
                  className="p-4 border rounded-xl bg-card cursor-pointer transition-all grid grid-cols-[1fr_auto_auto] items-center gap-4 hover:bg-muted hover:border-primary/30"
                >
                  <div>
                    <div className="font-semibold text-foreground text-sm mb-1">
                      {run.website_url}
                    </div>
                    <div className="text-[13px] text-muted-foreground">
                      {new Date(run.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-[13px] font-semibold text-primary">
                      {run.drafts_count} drafts
                    </div>
                  </div>
                  <Badge
                    variant={
                      isResultStatus(run.status)
                        ? "default"
                        : isFailureStatus(run.status)
                          ? "destructive"
                          : "secondary"
                    }
                    className="capitalize"
                  >
                    {run.status.replace(/_/g, " ")}
                  </Badge>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    );
  }

  // State 2: Running State
  if (activeRun && !isTerminalStatus(activeRun.status)) {
    const progressPercent = activeRun.progress || 0;
    const currentStepIndex = PIPELINE_STEPS.findIndex((s) => s.key === activeRun.status);
    const completedSteps = currentStepIndex >= 0 ? currentStepIndex : 0;

    return (
      <div className="max-w-[800px] mx-auto py-6 px-5">
        {/* Header */}
        <div className="mb-8">
          <PageHeader title="Building Your Sales Package" />
          <p className="text-sm text-muted-foreground mt-2">{activeRun.website_url}</p>
        </div>

        {/* Progress Bar */}
        <div className="mb-8">
          <div className="flex justify-between mb-2">
            <div className="text-xs font-semibold text-muted-foreground">Progress</div>
            <div className="text-xs font-semibold text-primary">{progressPercent}%</div>
          </div>
          <Progress value={progressPercent} />
        </div>

        {/* Steps Checklist */}
        <Card className="mb-6">
          <CardContent className="p-5">
            <div className="text-xs font-bold text-muted-foreground uppercase mb-4">
              Pipeline Steps
            </div>
            <div className="grid gap-3">
              {PIPELINE_STEPS.map((step, idx) => {
                const isDone = idx < completedSteps;
                const isCurrent = idx === completedSteps;

                return (
                  <div
                    key={step.key}
                    className="flex items-center gap-3 transition-opacity"
                    style={{ opacity: isDone || isCurrent ? 1 : 0.4 }}
                  >
                    <div
                      className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                        isDone
                          ? "bg-primary text-primary-foreground"
                          : isCurrent
                            ? "bg-primary/10 text-primary border-2 border-primary"
                            : "bg-border text-muted-foreground"
                      }`}
                    >
                      {isDone ? <Check className="h-3.5 w-3.5" /> : isCurrent ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : idx + 1}
                    </div>
                    <div className={`text-sm ${isDone || isCurrent ? "font-semibold" : "font-normal"} text-foreground`}>
                      {step.label}
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>

        {/* Live Counters */}
        <div className="grid grid-cols-2 md:grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-3 mb-8">
          <CounterCard label="Personas" value={activeRun.personas_count} />
          <CounterCard label="Keywords" value={activeRun.keywords_count} />
          <CounterCard label="Opportunities" value={activeRun.opportunities_count} />
          <CounterCard label="Drafts" value={activeRun.drafts_count} />
        </div>

        {/* Cancel Button */}
        <div className="text-center">
          <Button
            variant="outline"
            onClick={() => {
              setActiveRun(null);
              loadPreviousRuns();
            }}
          >
            Cancel Pipeline
          </Button>
        </div>
      </div>
    );
  }

  // State 3: Results State
  if (activeRun && isResultStatus(activeRun.status) && !activeRun.results) {
    return (
      <div className="max-w-[600px] mx-auto py-10 px-5 text-center">
        <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4 text-primary" />
        <h2 className="text-xl font-semibold mb-2">Loading Pipeline Results</h2>
        <p className="text-sm text-muted-foreground">
          Fetching the completed run details now.
        </p>
        <Button className="mt-4" variant="outline" onClick={() => void openRun(activeRun.id)}>
          Retry
        </Button>
      </div>
    );
  }

  if (activeRun && isResultStatus(activeRun.status) && activeRun.results) {
    const results = activeRun.results;

    return (
      <div className="max-w-[1000px] mx-auto py-6 px-5">
        {/* Success Banner */}
        <div className="p-5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl mb-8 text-center">
          <div className="text-base font-bold text-emerald-600 mb-1">
            <Check className="inline h-4 w-4 mr-1" />
            Your Sales Package is Ready!
          </div>
          <p className="text-[13px] text-muted-foreground mb-0">
            {activeRun.website_url}
          </p>
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3 mb-8">
          <SummaryCard label="Personas" value={results.personas.length} />
          <SummaryCard label="Keywords" value={results.keywords.length} />
          <SummaryCard label="Opportunities" value={results.opportunities.length} />
          <SummaryCard label="Drafts" value={results.drafts.length} />
        </div>

        {/* Expandable Sections */}
        <div className="grid gap-4 mb-8">
          {/* Brand Summary */}
          <ExpandableSection
            title="Brand Summary"
            isExpanded={expanding["brand_summary"]}
            onToggle={() => toggleExpand("brand_summary")}
          >
            <p className="text-sm leading-relaxed text-foreground m-0">
              {results.brand_summary}
            </p>
          </ExpandableSection>

          {/* Personas */}
          <ExpandableSection
            title={`Personas (${results.personas.length})`}
            isExpanded={expanding["personas"]}
            onToggle={() => toggleExpand("personas")}
          >
            <div className="grid gap-3">
              {results.personas.map((persona, idx) => (
                <div
                  key={idx}
                  className="p-4 bg-card rounded-xl border"
                >
                  <div className="font-semibold mb-1 text-sm">
                    {persona.name} {persona.role && `(${persona.role})`}
                  </div>
                  <div className="text-[13px] text-muted-foreground mb-2">
                    {persona.summary}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    <div className="mb-1">
                      <strong>Pain points:</strong> {persona.pain_points.join(", ")}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </ExpandableSection>

          {/* Keywords */}
          <ExpandableSection
            title={`Keywords (${results.keywords.length})`}
            isExpanded={expanding["keywords"]}
            onToggle={() => toggleExpand("keywords")}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-[13px] border-collapse">
                <thead>
                  <tr className="border-b">
                    <th className="p-2 text-left font-semibold text-muted-foreground">Keyword</th>
                    <th className="p-2 text-left font-semibold text-muted-foreground">Score</th>
                    <th className="p-2 text-left font-semibold text-muted-foreground">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {results.keywords.map((kw, idx) => (
                    <tr key={idx} className="border-b">
                      <td className="p-2 text-foreground">{kw.keyword}</td>
                      <td className="p-2 text-primary font-semibold">{kw.score}</td>
                      <td className="p-2 text-muted-foreground">{kw.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </ExpandableSection>


          {/* Top Opportunities */}
          <ExpandableSection
            title={`Top Opportunities (${results.opportunities.length})`}
            isExpanded={expanding["opportunities"]}
            onToggle={() => toggleExpand("opportunities")}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-[13px] border-collapse">
                <thead>
                  <tr className="border-b">
                    <th className="p-2 text-left font-semibold text-muted-foreground">Title</th>
                    <th className="p-2 text-left font-semibold text-muted-foreground">Platform</th>
                    <th className="p-2 text-left font-semibold text-muted-foreground">Source</th>
                    <th className="p-2 text-left font-semibold text-muted-foreground">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {results.opportunities.slice(0, 10).map((opp, idx) => (
                    <tr key={idx} className="border-b">
                      <td className="p-2 text-foreground">
                        <div className="max-w-[400px] overflow-hidden text-ellipsis whitespace-nowrap">
                          {opp.title}
                        </div>
                      </td>
                      <td className="p-2 text-muted-foreground capitalize">{opp.platform || "reddit"}</td>
                      <td className="p-2 text-muted-foreground">{opp.platform === "reddit" ? `r/${opp.subreddit}` : opp.subreddit}</td>
                      <td className="p-2 text-primary font-semibold">{opp.score}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </ExpandableSection>

          {/* Draft Replies */}
          <ExpandableSection
            title={`Draft Replies (${results.drafts.length})`}
            isExpanded={expanding["drafts"]}
            onToggle={() => toggleExpand("drafts")}
          >
            <div className="grid gap-3">
              {results.drafts.slice(0, 5).map((draft, idx) => (
                <div
                  key={idx}
                  className="p-4 bg-card rounded-xl border"
                >
                  <div className="text-xs text-muted-foreground mb-1.5">
                    Response to: <strong>{draft.opportunity_title}</strong>
                  </div>
                  <div className="text-[13px] leading-relaxed text-foreground mb-2">
                    {draft.content}
                  </div>
                </div>
              ))}
              {results.drafts.length > 5 && (
                <p className="text-[13px] text-muted-foreground m-0">
                  +{results.drafts.length - 5} more drafts...
                </p>
              )}
            </div>
          </ExpandableSection>
        </div>

        {/* Action Buttons */}
        <div className="grid grid-cols-2 gap-4 p-6 border-t mt-8">
          <Button
            variant="outline"
            onClick={() => openContentStudioForProject(router, activeRun.project_id)}
          >
            Review Individually
          </Button>
          <Button onClick={handleExecuteAll} disabled={activeRun.status === "executed"}>
            {activeRun.status === "executed" ? "Already Marked Ready" : "Mark All as Ready"}
          </Button>
        </div>
      </div>
    );
  }

  // Error State
  if (activeRun && isFailureStatus(activeRun.status)) {
    const llmSetupRequired = isLlmSetupError(activeRun.error_message);
    const redditDiscoveryFailed = isRedditDiscoveryError(activeRun.error_message);

    return (
      <div className="max-w-[600px] mx-auto py-10 px-5 text-center">
        <div className="text-5xl mb-4">&#x26A0;&#xFE0F;</div>
        <h2 className="text-2xl font-bold mb-2">Pipeline Failed</h2>
        <p className="text-sm text-muted-foreground mb-4">
          {friendlyPipelineError(activeRun.error_message)}
        </p>
        {llmSetupRequired ? (
          <div className="mb-6 rounded-xl border bg-muted/40 p-4 text-left">
            <p className="mb-2 text-sm font-semibold text-foreground">Backend setup required</p>
            <p className="mb-2 text-[13px] text-muted-foreground">
              Add <code>GEMINI_API_KEY</code> to the repo root <code>.env.local</code>, or switch{" "}
              <code>LLM_PROVIDER</code> to <code>openai</code>, <code>perplexity</code>, or <code>claude</code> and
              set the matching API key there instead.
            </p>
            <p className="m-0 text-[13px] text-muted-foreground">
              Then restart <code>uv run uvicorn app.main:app --reload</code> and launch the pipeline again.
            </p>
          </div>
        ) : redditDiscoveryFailed ? (
          <div className="mb-6 rounded-xl border bg-muted/40 p-4 text-left">
            <p className="mb-2 text-sm font-semibold text-foreground">Reddit discovery is temporarily unavailable</p>
            <p className="mb-2 text-[13px] text-muted-foreground">
              SignalFlow now runs without <code>REDDIT_CLIENT_ID</code> or <code>REDDIT_CLIENT_SECRET</code>. This
              failure means the public Reddit feeds and external search fallback were both unavailable from this
              machine.
            </p>
            <p className="m-0 text-[13px] text-muted-foreground">
              Retry the pipeline shortly. For a more stable external search source, you can optionally set{" "}
              <code>SERPAPI_API_KEY</code> or <code>BING_SEARCH_API_KEY</code> in the repo root <code>.env</code> and
              restart <code>uv run uvicorn app.main:app --reload</code>.
            </p>
          </div>
        ) : (
          <p className="text-[13px] text-muted-foreground mb-6 opacity-70">
            Tip: Make sure the URL is publicly accessible and includes the full address (e.g. https://example.com).
          </p>
        )}
        <Button onClick={() => setActiveRun(null)}>Try Again</Button>
      </div>
    );
  }

  return null;
}

// Helper Components

function CounterCard({ label, value }: { label: string; value: number }) {
  return (
    <Card className="p-4 text-center">
      <div className="text-2xl font-bold text-primary mb-1">
        {value}
      </div>
      <div className="text-xs text-muted-foreground font-medium">
        {label}
      </div>
    </Card>
  );
}

function SummaryCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="p-5 bg-card border rounded-xl text-center">
      <div className="text-[28px] font-bold text-primary mb-1.5">
        {value}
      </div>
      <div className="text-[13px] text-muted-foreground font-medium">
        {label}
      </div>
    </div>
  );
}

interface ExpandableSectionProps {
  title: string;
  isExpanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

function ExpandableSection({ title, isExpanded, onToggle, children }: ExpandableSectionProps) {
  return (
    <Card className="overflow-hidden">
      <button
        onClick={onToggle}
        aria-expanded={isExpanded}
        className="w-full px-4 py-4 bg-transparent border-none text-left text-sm font-semibold text-foreground cursor-pointer flex justify-between items-center transition-colors hover:bg-muted"
      >
        {title}
        <span className="text-xs text-muted-foreground">
          {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </span>
      </button>
      {isExpanded && (
        <div className="px-4 py-4 border-t bg-muted/50">
          {children}
        </div>
      )}
    </Card>
  );
}
