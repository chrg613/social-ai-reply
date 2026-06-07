"use client";

import { useEffect, useState, useCallback } from "react";
import { Loader2, RotateCw, RefreshCw } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { useToast } from "@/stores/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { StatusBadge } from "@/components/shared/status-badge";
import {
  getAgentRuns,
  runAgent,
  runAllAgents,
  type AgentRun,
} from "@/lib/api/agents";
import { getCompanies } from "@/lib/api/company";

const AGENT_NAMES = ["reddit_scanner", "quora_watcher", "linkedin_monitor", "seo_auditor"];

export default function AgentRunsPage() {
  const { token } = useAuth();
  const { success, error } = useToast();
  const [loading, setLoading] = useState(true);
  const [autoRefreshing, setAutoRefreshing] = useState(false);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [running, setRunning] = useState<Set<string>>(new Set());

  const loadRuns = useCallback(async (silent = false) => {
    if (!token || !companyId) return;
    if (!silent) setLoading(true);
    try {
      const data = await getAgentRuns(token, companyId);
      setRuns(data);
    } catch (err) {
      error("Failed to load runs", err instanceof Error ? err.message : "Unknown error");
    }
    if (!silent) setLoading(false);
  }, [token, companyId, error]);

  useEffect(() => {
    if (!token) return;
    async function init() {
      try {
        const companies = await getCompanies(token!);
        const active = companies.find((c) => c.is_active) ?? companies[0] ?? null;
        if (active) setCompanyId(active.id);
      } catch (err) {
        error("Failed to load company", err instanceof Error ? err.message : "Unknown error");
      }
    }
    void init();
  }, [token, error]);

  useEffect(() => {
    if (companyId) {
      void loadRuns(false);
    }
  }, [companyId, loadRuns]);

  useEffect(() => {
    if (!companyId) return;
    const hasRunning = runs.some((r) => r.status === "running");
    if (!hasRunning) {
      setAutoRefreshing(false);
      return;
    }
    setAutoRefreshing(true);
    const interval = setInterval(() => {
      void loadRuns(true);
    }, 30000);
    return () => {
      clearInterval(interval);
      setAutoRefreshing(false);
    };
  }, [companyId, runs, loadRuns]);

  async function handleRunAll() {
    if (!token || !companyId) return;
    setRunning((prev) => new Set(prev).add("all"));
    try {
      await runAllAgents(token, companyId);
      success("All agents started");
      void loadRuns(false);
    } catch (err) {
      error("Failed to start agents", err instanceof Error ? err.message : "Unknown error");
    }
    setRunning((prev) => {
      const next = new Set(prev);
      next.delete("all");
      return next;
    });
  }

  async function handleRunAgent(agentName: string) {
    if (!token || !companyId) return;
    setRunning((prev) => new Set(prev).add(agentName));
    try {
      await runAgent(token, companyId, agentName);
      success(`${agentName} started`);
      void loadRuns(false);
    } catch (err) {
      error("Failed to start agent", err instanceof Error ? err.message : "Unknown error");
    }
    setRunning((prev) => {
      const next = new Set(prev);
      next.delete(agentName);
      return next;
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agent Runs"
        description="Monitor and trigger agent executions."
        actions={
          <div className="flex items-center gap-2">
            {autoRefreshing && (
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" />
                Auto-refreshing every 30s
              </span>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => void loadRuns(false)}
              disabled={loading}
            >
              {loading && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />}
              <RefreshCw className="h-3.5 w-3.5 mr-1" />
              Refresh
            </Button>
            <Button size="sm" onClick={() => void handleRunAll()} disabled={running.has("all")}>
              {running.has("all") && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              Run All
            </Button>
          </div>
        }
      />

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-xl" />
          ))}
        </div>
      ) : runs.length === 0 ? (
        <EmptyState
          icon={RotateCw}
          title="No agent runs yet"
          description="Run an agent to see execution history here."
        />
      ) : (
        <div className="space-y-3">
          {runs.map((run) => (
            <Card key={run.id}>
              <CardContent className="p-4">
                <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant="outline" className="text-xs">{run.agent_name}</Badge>
                    <StatusBadge
                      variant={run.status === "completed" ? "success" : run.status === "failed" ? "error" : run.status === "running" ? "primary" : "neutral"}
                    >
                      {run.status}
                    </StatusBadge>
                  </div>
                  <div className="flex-1 text-sm">
                    <span className="text-muted-foreground">Started:</span>{" "}
                    {new Date(run.started_at).toLocaleString()}
                  </div>
                  <div className="flex items-center gap-4 text-xs text-muted-foreground shrink-0">
                    <span>Fetched: {run.items_fetched}</span>
                    <span>Kept: {run.items_kept}</span>
                    <span>Rejected: {run.items_rejected}</span>
                  </div>
                </div>
                {run.error_message && (
                  <div className="mt-2 text-xs text-destructive bg-destructive/10 rounded p-2">
                    {run.error_message}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
