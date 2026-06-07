"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Loader2,
  Check,
  X,
  Copy,
  Flag,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Search,
  Filter,
} from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { useToast } from "@/stores/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { ScoreBadge } from "@/components/shared/score-badge";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { StatusBadge } from "@/components/shared/status-badge";
import { cn } from "@/lib/utils";
import {
  getFeed,
  approveOpportunity,
  rejectOpportunity,
  copyOpportunity,
  markIrrelevant,
  type Opportunity,
} from "@/lib/api/feed";
import { getCompanies } from "@/lib/api/company";

interface FeedFilters {
  platform: string;
  status: string;
  min_score: number;
  intent: string;
  keyword: string;
  agent_name: string;
  sort: string;
}

export default function AgentsPage() {
  const { token } = useAuth();
  const { success, error } = useToast();
  const [loading, setLoading] = useState(true);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [total, setTotal] = useState(0);
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [debug, setDebug] = useState(false);
  const [filters, setFilters] = useState<FeedFilters>({
    platform: "",
    status: "",
    min_score: 0,
    intent: "",
    keyword: "",
    agent_name: "",
    sort: "relevance",
  });
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [acting, setActing] = useState<Set<number>>(new Set());

  const loadFeed = useCallback(async () => {
    if (!token || !companyId) return;
    setLoading(true);
    try {
      const res = await getFeed(token, {
        company_id: companyId,
        platform: filters.platform || undefined,
        status: filters.status || undefined,
        min_score: filters.min_score || undefined,
        intent: filters.intent || undefined,
        keyword: filters.keyword || undefined,
        agent_name: filters.agent_name || undefined,
        sort: filters.sort || undefined,
        limit: 50,
        offset: 0,
        debug,
      });
      setOpportunities(res.opportunities);
      setTotal(res.total);
    } catch (err) {
      error("Failed to load feed", err instanceof Error ? err.message : "Unknown error");
    }
    setLoading(false);
  }, [token, companyId, filters, debug, error]);

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
      void loadFeed();
    }
  }, [companyId, loadFeed]);

  async function handleAction(action: string, id: number, reason?: string) {
    if (!token) return;
    setActing((prev) => new Set(prev).add(id));
    try {
      let updated: Opportunity;
      switch (action) {
        case "approve":
          updated = await approveOpportunity(token, id);
          break;
        case "reject":
          updated = await rejectOpportunity(token, id);
          break;
        case "copy":
          updated = await copyOpportunity(token, id);
          break;
        case "irrelevant":
          updated = await markIrrelevant(token, id, reason);
          break;
        default:
          return;
      }
      setOpportunities((prev) =>
        prev.map((o) => (o.id === id ? updated : o))
      );
      success("Action completed", action);
    } catch (err) {
      error("Action failed", err instanceof Error ? err.message : "Unknown error");
    }
    setActing((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }

  function toggleExpanded(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const sortOptions = [
    { label: "Relevance", value: "relevance" },
    { label: "Newest", value: "newest" },
    { label: "Engagement", value: "engagement" },
    { label: "Priority", value: "priority" },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agents Feed"
        description="Central opportunity feed from all agents."
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setDebug((d) => !d)}>
              <Filter className="h-4 w-4 mr-1" />
              {debug ? "Hide Debug" : "Debug"}
            </Button>
          </div>
        }
      />

      <Card>
        <CardContent className="p-4">
          <div className="flex flex-wrap gap-3 items-end">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Platform</Label>
              <Select value={filters.platform} onValueChange={(v) => setFilters((f) => ({ ...f, platform: v ?? "" }))}>
                <SelectTrigger className="h-8 w-[140px] text-xs">
                  <SelectValue placeholder="All" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All</SelectItem>
                  <SelectItem value="reddit">Reddit</SelectItem>
                  <SelectItem value="quora">Quora</SelectItem>
                  <SelectItem value="linkedin">LinkedIn</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Status</Label>
              <Select value={filters.status} onValueChange={(v) => setFilters((f) => ({ ...f, status: v ?? "" }))}>
                <SelectTrigger className="h-8 w-[140px] text-xs">
                  <SelectValue placeholder="All" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All</SelectItem>
                  <SelectItem value="new">New</SelectItem>
                  <SelectItem value="approved">Approved</SelectItem>
                  <SelectItem value="rejected">Rejected</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Min Score</Label>
              <Input
                type="number"
                min={0}
                max={100}
                value={filters.min_score}
                onChange={(e) => setFilters((f) => ({ ...f, min_score: Number(e.target.value) }))}
                className="h-8 w-[80px] text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Intent</Label>
              <Select value={filters.intent} onValueChange={(v) => setFilters((f) => ({ ...f, intent: v ?? "" }))}>
                <SelectTrigger className="h-8 w-[140px] text-xs">
                  <SelectValue placeholder="All" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All</SelectItem>
                  <SelectItem value="buy">Buy</SelectItem>
                  <SelectItem value="compare">Compare</SelectItem>
                  <SelectItem value="question">Question</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Sort</Label>
              <Select value={filters.sort} onValueChange={(v) => setFilters((f) => ({ ...f, sort: v ?? "" }))}>
                <SelectTrigger className="h-8 w-[140px] text-xs">
                  <SelectValue placeholder="Sort" />
                </SelectTrigger>
                <SelectContent>
                  {sortOptions.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1 min-w-[180px] space-y-1">
              <Label className="text-xs text-muted-foreground">Keyword</Label>
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Search keywords..."
                  value={filters.keyword}
                  onChange={(e) => setFilters((f) => ({ ...f, keyword: e.target.value }))}
                  className="h-8 pl-7 text-xs"
                />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      ) : opportunities.length === 0 ? (
        <EmptyState
          icon={Filter}
          title="No opportunities found"
          description="Adjust your filters or run an agent to populate the feed."
        />
      ) : (
        <div className="space-y-3">
          {opportunities.map((opp) => (
            <Card key={opp.id} className={cn("overflow-hidden", debug && "border-dashed")}>
              <CardContent className="p-4">
                <div className="flex flex-col sm:flex-row sm:items-start gap-3">
                  <div className="flex items-center gap-2 shrink-0">
                    <PlatformIcon platform="reddit" />
                    <Badge variant="outline" className="text-xs">r/{opp.subreddit_name}</Badge>
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-semibold truncate">{opp.title}</h3>
                    <div className="mt-1 flex flex-wrap gap-1">
                      <ScoreBadge score={opp.score} />
                      <StatusBadge variant="info">{opp.status}</StatusBadge>
                      {(opp.keyword_hits || []).slice(0, 3).map((k) => (
                        <Badge key={k} variant="secondary" className="text-[11px] px-1.5 py-0">
                          {k}
                        </Badge>
                      ))}
                    </div>
                    {debug && (
                      <div className="mt-2 text-xs text-muted-foreground bg-muted p-2 rounded">
                        <div>Score reasons: {(opp.score_reasons || []).join(", ") || "N/A"}</div>
                        <div>Rule risk: {(opp.rule_risk || []).join(", ") || "N/A"}</div>
                      </div>
                    )}
                    {expanded.has(opp.id) && opp.body_excerpt && (
                      <p className="mt-2 text-xs text-muted-foreground leading-snug">{opp.body_excerpt}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => void handleAction("approve", opp.id)} disabled={acting.has(opp.id)}>
                      <Check className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => void handleAction("reject", opp.id)} disabled={acting.has(opp.id)}>
                      <X className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => void handleAction("copy", opp.id)} disabled={acting.has(opp.id)}>
                      <Copy className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => void handleAction("irrelevant", opp.id, "Not relevant")} disabled={acting.has(opp.id)}>
                      <Flag className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => toggleExpanded(opp.id)}>
                      {expanded.has(opp.id) ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                    </Button>
                    <a href={opp.permalink || "#"} target="_blank" rel="noopener noreferrer">
                      <Button size="icon" variant="ghost" className="h-7 w-7">
                        <ExternalLink className="h-3.5 w-3.5" />
                      </Button>
                    </a>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
