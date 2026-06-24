"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ExternalLink,
  Eye,
  Frown,
  Loader2,
  Meh,
  Search,
  Smile,
  Swords,
} from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useSelectedProjectId } from "@/hooks/use-selected-project";
import { PageHeader } from "@/components/shared/page-header";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { EmptyState } from "@/components/shared/empty-state";
import {
  fetchCompetitorMentions,
  fetchCompetitorStats,
  fetchCompetitorList,
  type CompetitorMention,
  type CompetitorStats,
} from "@/lib/api/competitors";

/* ── Sentiment helpers ──────────────────────────────────────────── */

const SENTIMENT_CONFIG: Record<
  string,
  { label: string; color: string; bg: string; icon: React.ElementType }
> = {
  negative: {
    label: "Negative",
    color: "text-red-500",
    bg: "bg-red-500/15 text-red-400 border-red-500/30",
    icon: Frown,
  },
  neutral: {
    label: "Neutral",
    color: "text-yellow-500",
    bg: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
    icon: Meh,
  },
  positive: {
    label: "Positive",
    color: "text-green-500",
    bg: "bg-green-500/15 text-green-400 border-green-500/30",
    icon: Smile,
  },
};

function SentimentBadge({ sentiment }: { sentiment: string }) {
  const cfg = SENTIMENT_CONFIG[sentiment] ?? SENTIMENT_CONFIG.neutral;
  const Icon = cfg.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        cfg.bg,
      )}
    >
      <Icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
}

/* ── Sentiment bar — small colored bars for stat cards ───────── */

function SentimentBar({
  negative,
  neutral,
  positive,
}: {
  negative: number;
  neutral: number;
  positive: number;
}) {
  const total = negative + neutral + positive;
  if (total === 0) return null;
  return (
    <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted">
      <div
        className="bg-red-500 transition-all"
        style={{ width: `${(negative / total) * 100}%` }}
      />
      <div
        className="bg-yellow-500 transition-all"
        style={{ width: `${(neutral / total) * 100}%` }}
      />
      <div
        className="bg-green-500 transition-all"
        style={{ width: `${(positive / total) * 100}%` }}
      />
    </div>
  );
}

/* ── Loading skeleton ───────────────────────────────────────────── */

function CompetitorsSkeleton() {
  return (
    <div className="space-y-6">
      {/* Stats row skeleton */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-5 w-28" />
            </CardHeader>
            <CardContent className="space-y-3">
              <Skeleton className="h-8 w-16" />
              <Skeleton className="h-1.5 w-full rounded-full" />
              <Skeleton className="h-4 w-32" />
            </CardContent>
          </Card>
        ))}
      </div>
      {/* Filter bar skeleton */}
      <div className="flex gap-3">
        <Skeleton className="h-8 w-[160px]" />
        <Skeleton className="h-8 w-[140px]" />
      </div>
      {/* Table skeleton */}
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-20 w-full rounded-xl" />
        ))}
      </div>
    </div>
  );
}

/* ── Main page ──────────────────────────────────────────────────── */

export default function CompetitorsPage() {
  const { token } = useAuth();
  const selectedProjectId = useSelectedProjectId();

  const [mentions, setMentions] = useState<CompetitorMention[]>([]);
  const [stats, setStats] = useState<CompetitorStats[]>([]);
  const [competitors, setCompetitors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [competitorFilter, setCompetitorFilter] = useState("");
  const [sentimentFilter, setSentimentFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  // Data loading
  useEffect(() => {
    if (!token || !selectedProjectId) return;
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [mentionsRes, statsRes, listRes] = await Promise.all([
          fetchCompetitorMentions(token!, selectedProjectId!),
          fetchCompetitorStats(token!, selectedProjectId!),
          fetchCompetitorList(token!, selectedProjectId!),
        ]);
        if (cancelled) return;
        setMentions(mentionsRes);
        setStats(statsRes);
        setCompetitors(listRes);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load data");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [token, selectedProjectId]);

  // Client-side filtering
  const search = searchQuery.trim().toLowerCase();
  const filteredMentions = useMemo(
    () =>
      mentions
        .filter((m) => !competitorFilter || m.competitor_name === competitorFilter)
        .filter((m) => !sentimentFilter || m.sentiment === sentimentFilter)
        .filter(
          (m) =>
            !search ||
            m.competitor_name.toLowerCase().includes(search) ||
            (m.post_title ?? "").toLowerCase().includes(search) ||
            (m.complaint_detail ?? "").toLowerCase().includes(search) ||
            (m.complaint_category ?? "").toLowerCase().includes(search),
        )
        .sort(
          (a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        ),
    [mentions, competitorFilter, sentimentFilter, search],
  );

  /* ── Renders ────────────────────────────────────────────────── */

  if (!selectedProjectId) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Competitor Intelligence"
          description="Track competitor mentions, sentiment, and complaints across platforms."
        />
        <EmptyState
          icon={Swords}
          title="Select a project"
          description="Choose a project from the sidebar to view competitor intelligence."
        />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Competitor Intelligence"
          description="Track competitor mentions, sentiment, and complaints across platforms."
        />
        <CompetitorsSkeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Competitor Intelligence"
          description="Track competitor mentions, sentiment, and complaints across platforms."
        />
        <Card>
          <CardContent className="py-10 text-center">
            <p className="text-sm text-destructive">{error}</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() => window.location.reload()}
            >
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (competitors.length === 0 && mentions.length === 0) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Competitor Intelligence"
          description="Track competitor mentions, sentiment, and complaints across platforms."
        />
        <EmptyState
          icon={Swords}
          title="No competitors configured"
          description="Add competitor names in your Company Setup page, then run the Auto Pipeline to detect competitor mentions across social platforms."
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Competitor Intelligence"
        description="Track competitor mentions, sentiment, and complaints across platforms."
        actions={
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Eye className="h-4 w-4" />
            {mentions.length} mention{mentions.length !== 1 && "s"} tracked
          </div>
        }
      />

      {/* ── Stats cards ──────────────────────────────────────── */}
      {stats.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {stats.map((s) => (
            <Card
              key={s.competitor_name}
              interactive
              className="relative overflow-hidden"
              onClick={() =>
                setCompetitorFilter(
                  competitorFilter === s.competitor_name ? "" : s.competitor_name,
                )
              }
            >
              {/* Subtle gradient accent on selected */}
              {competitorFilter === s.competitor_name && (
                <div className="pointer-events-none absolute inset-0 rounded-xl ring-2 ring-primary/40" />
              )}
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm font-semibold">
                  <Swords className="h-4 w-4 text-muted-foreground" />
                  {s.competitor_name}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="text-2xl font-bold tabular-nums tracking-tight">
                  {s.total_mentions}
                  <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                    mentions
                  </span>
                </div>

                <SentimentBar
                  negative={s.negative_count}
                  neutral={s.neutral_count}
                  positive={s.positive_count}
                />

                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
                    {s.negative_count}
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full bg-yellow-500" />
                    {s.neutral_count}
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
                    {s.positive_count}
                  </span>
                </div>

                {s.top_complaints.length > 0 && (
                  <div className="pt-1">
                    <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Top complaint
                    </span>
                    <p className="mt-0.5 truncate text-xs">{s.top_complaints[0]}</p>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* ── Filter bar ───────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search mentions…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-8 w-[200px] pl-8 text-xs"
          />
        </div>

        <Select
          value={competitorFilter}
          onValueChange={(v) => setCompetitorFilter(v ?? "")}
        >
          <SelectTrigger className="h-8 w-[160px] text-xs">
            <SelectValue placeholder="All competitors" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">All competitors</SelectItem>
            {competitors.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={sentimentFilter}
          onValueChange={(v) => setSentimentFilter(v ?? "")}
        >
          <SelectTrigger className="h-8 w-[140px] text-xs">
            <SelectValue placeholder="All sentiment" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">All sentiment</SelectItem>
            <SelectItem value="negative">Negative</SelectItem>
            <SelectItem value="neutral">Neutral</SelectItem>
            <SelectItem value="positive">Positive</SelectItem>
          </SelectContent>
        </Select>

        {(competitorFilter || sentimentFilter || searchQuery) && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-xs"
            onClick={() => {
              setCompetitorFilter("");
              setSentimentFilter("");
              setSearchQuery("");
            }}
          >
            Clear filters
          </Button>
        )}
      </div>

      {/* ── Mentions list ────────────────────────────────────── */}
      {filteredMentions.length === 0 ? (
        <EmptyState
          icon={Swords}
          title="No competitor mentions found"
          description={
            mentions.length > 0
              ? "Try adjusting your filters to see more results."
              : "Competitor mentions will appear here once they are detected by the scanning pipeline."
          }
        />
      ) : (
        <div className="space-y-2">
          {filteredMentions.map((m) => (
            <Card key={m.id} size="sm" className="group/mention transition-colors">
              <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-4">
                {/* Left: Platform + competitor */}
                <div className="flex shrink-0 items-center gap-3">
                  <PlatformIcon
                    platform={m.source_platform}
                    className="h-5 w-5"
                  />
                  <Badge variant="secondary" className="text-xs font-medium">
                    {m.competitor_name}
                  </Badge>
                  <SentimentBadge sentiment={m.sentiment} />
                </div>

                {/* Center: Content */}
                <div className="min-w-0 flex-1 space-y-1">
                  {m.post_title && (
                    <p className="truncate text-sm font-medium leading-snug">
                      {m.post_title}
                    </p>
                  )}
                  {m.complaint_detail && (
                    <p className="line-clamp-2 text-xs text-muted-foreground">
                      {m.complaint_detail}
                    </p>
                  )}
                  <div className="flex flex-wrap items-center gap-2 pt-0.5">
                    {m.complaint_category && (
                      <Badge variant="outline" className="text-[10px]">
                        {m.complaint_category}
                      </Badge>
                    )}
                    <span className="text-[10px] text-muted-foreground">
                      {new Date(m.created_at).toLocaleDateString("en-US", {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}
                    </span>
                  </div>
                </div>

                {/* Right: Source link */}
                {m.source_url && (
                  <a
                    href={m.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <ExternalLink className="h-3 w-3" />
                    Source
                  </a>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
