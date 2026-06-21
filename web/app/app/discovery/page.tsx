"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { MessageSquare, Plus, Target, Users } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import type { Opportunity } from "@/lib/api";
import { sourceLabel } from "@/lib/opportunity";
import { useSelectedProjectId } from "@/hooks/use-selected-project";
import { useDiscoveryData } from "@/hooks/use-discovery-data";
import { useDraftOps } from "@/hooks/use-draft-ops";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";
import { useScanRunner } from "@/hooks/use-scan-runner";
import { PageHeader } from "@/components/shared/page-header";
import { KPIGrid } from "@/components/shared/kpi-card";
import { VoiceProfileSelect } from "@/components/shared/voice-profile-select";
import { CampaignDialog } from "@/components/discovery/campaign-dialog";
import { CommunitiesSection } from "@/components/discovery/communities-section";
import { DiscoverySkeleton } from "@/components/discovery/discovery-skeleton";
import { InboxSection } from "@/components/discovery/inbox-section";
import { OpportunityDetailPanel } from "@/components/discovery/opportunity-detail-panel";
import { ScanPlatformPicker } from "@/components/discovery/scan-platform-picker";
import { ScanProgressBanner } from "@/components/discovery/scan-progress-banner";
import { SignalsSection } from "@/components/discovery/signals-section";
import { WorkflowStrip } from "@/components/discovery/workflow-strip";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { cn } from "@/lib/utils";

function lastSeenKey(projectId: number): string {
  return `rf-inbox-last-seen-${projectId}`;
}

export default function DiscoveryPage() {
  const { token } = useAuth();
  const selectedProjectId = useSelectedProjectId();

  const data = useDiscoveryData(token, selectedProjectId);
  const { project, keywords, subreddits, opportunities, campaigns, loading } = data;
  const scan = useScanRunner(token, project?.id, () => void data.loadAll());
  const draftOps = useDraftOps(token);

  const [newKeyword, setNewKeyword] = useState("");
  const [voiceProfileId, setVoiceProfileId] = useState<number | null>(null);
  const [draftingOpp, setDraftingOpp] = useState<Opportunity | null>(null);
  const [draftContent, setDraftContent] = useState("");
  const [draftRationale, setDraftRationale] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<{ type: string; id: number; name: string } | null>(null);

  const [statusFilter, setStatusFilter] = useState("");
  const [stageFilter, setStageFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [campaignFilter, setCampaignFilter] = useState("");
  const [showCampaignModal, setShowCampaignModal] = useState(false);
  const [platformFilter, setPlatformFilter] = useState<string>("all");

  // Inbox state: explicit row selection, bulk checkboxes, last-visit marker.
  const [selectedOppId, setSelectedOppId] = useState<number | null>(null);
  const [checkedIds, setCheckedIds] = useState<Set<number>>(new Set());
  const [lastSeenAt, setLastSeenAt] = useState<string | null>(null);

  const signalsRef = useRef<HTMLDivElement>(null);
  const communitiesRef = useRef<HTMLDivElement>(null);
  const queueRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (token) {
      void data.loadAll();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, selectedProjectId]);

  // "New since last visit": read the previous visit timestamp once per project,
  // then stamp the current visit after 5s on page (and again on unmount).
  useEffect(() => {
    const projectId = project?.id;
    if (!projectId) {
      return;
    }
    const key = lastSeenKey(projectId);
    setLastSeenAt(window.localStorage.getItem(key));
    const stamp = () => window.localStorage.setItem(key, new Date().toISOString());
    const timer = window.setTimeout(stamp, 5000);
    return () => {
      window.clearTimeout(timer);
      stamp();
    };
  }, [project?.id]);

  async function handleAddKeyword() {
    if (await data.addKeyword(newKeyword)) {
      setNewKeyword("");
    }
  }

  async function handleGenerateReply(opp: Opportunity) {
    const draft = await draftOps.generateReplyDraft(opp.id, undefined, { voiceProfileId });
    if (!draft) {
      return;
    }
    setDraftContent(draft.content || "");
    setDraftRationale(draft.rationale || "");
    setDraftingOpp(opp);
  }

  async function handleMarkPosted(oppId: number) {
    if (await draftOps.markAsPosted(oppId)) {
      setDraftingOpp(null);
      await data.loadAll();
    }
  }

  async function handleDelete() {
    if (deleteTarget && (await data.deleteDiscoveryItem(deleteTarget.type, deleteTarget.id, deleteTarget.name))) {
      setDeleteTarget(null);
    }
  }

  async function handleCreateCampaign(name: string, description: string): Promise<boolean> {
    const created = await data.createCampaign(name, description);
    if (created) {
      setShowCampaignModal(false);
    }
    return created;
  }

  // "All" means the active funnel and excludes "rejected" so the default
  // view isn't polluted by low-fit posts the scoring pipeline filtered out.
  const search = searchQuery.trim().toLowerCase();
  const filteredOpps = useMemo(
    () =>
      opportunities
        .filter((opp) => (statusFilter ? opp.status === statusFilter : opp.status !== "rejected"))
        .filter(
          (opp) =>
            !search ||
            opp.title.toLowerCase().includes(search) ||
            (opp.body_excerpt ?? "").toLowerCase().includes(search) ||
            sourceLabel(opp).toLowerCase().includes(search)
        )
        .filter((opp) => {
          if (platformFilter === "all") return true;
          const oppPlatform = ((opp as Record<string, unknown>).platform as string || "reddit").toLowerCase();
          return oppPlatform === platformFilter;
        })
        .sort((a, b) => (b.score || 0) - (a.score || 0)),
    [opportunities, statusFilter, search, platformFilter]
  );
  // Note: campaignFilter is UI-ready but opportunities don't have campaign_id yet.

  // Stage chips show counts over the status/search-filtered list; the inbox
  // then narrows further by the active stage (client-side).
  const stageCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const opp of filteredOpps) {
      if (opp.buying_stage) {
        counts[opp.buying_stage] = (counts[opp.buying_stage] || 0) + 1;
      }
    }
    return counts;
  }, [filteredOpps]);

  const inboxOpps = useMemo(
    () => (stageFilter ? filteredOpps.filter((opp) => opp.buying_stage === stageFilter) : filteredOpps),
    [filteredOpps, stageFilter]
  );

  // Selection falls back to the top row whenever the explicit pick is filtered out.
  const selectedOpp = inboxOpps.find((opp) => opp.id === selectedOppId) ?? inboxOpps[0] ?? null;

  function moveSelection(delta: number) {
    if (inboxOpps.length === 0) {
      return;
    }
    const currentIndex = selectedOpp ? inboxOpps.findIndex((opp) => opp.id === selectedOpp.id) : -1;
    const nextIndex = Math.min(Math.max(currentIndex + delta, 0), inboxOpps.length - 1);
    setSelectedOppId(inboxOpps[nextIndex].id);
  }

  async function handleApprove(opp: Opportunity) {
    await data.setOpportunityStatus(opp, "saved");
  }

  async function handleIgnore(opp: Opportunity) {
    await data.setOpportunityStatus(opp, "ignored");
  }

  function toggleChecked(oppId: number) {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (next.has(oppId)) {
        next.delete(oppId);
      } else {
        next.add(oppId);
      }
      return next;
    });
  }

  function toggleAllVisible() {
    setCheckedIds((prev) => {
      const allChecked = inboxOpps.length > 0 && inboxOpps.every((opp) => prev.has(opp.id));
      return allChecked ? new Set<number>() : new Set(inboxOpps.map((opp) => opp.id));
    });
  }

  async function handleBulk(status: "saved" | "ignored") {
    const targets = inboxOpps.filter((opp) => checkedIds.has(opp.id));
    if (targets.length === 0) {
      return;
    }
    await data.bulkUpdateStatus(targets, status);
    setCheckedIds(new Set());
  }

  // Inbox keyboard shortcuts — paused while any dialog/sheet is open.
  const shortcutsEnabled = !draftingOpp && !deleteTarget && !showCampaignModal;
  useKeyboardShortcuts(
    {
      j: () => moveSelection(1),
      k: () => moveSelection(-1),
      a: () => selectedOpp && void handleApprove(selectedOpp),
      s: () => selectedOpp && void handleApprove(selectedOpp),
      i: () => selectedOpp && void handleIgnore(selectedOpp),
      Enter: () => selectedOpp && void handleGenerateReply(selectedOpp),
    },
    shortcutsEnabled
  );

  if (loading) {
    return <DiscoverySkeleton />;
  }

  if (!project) {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-center">
        <div className="text-4xl">PRJ</div>
        <h3 className="mt-4 text-lg font-medium">No project selected</h3>
        <p className="mt-2 text-sm text-muted-foreground">
          Go to Command Center first and create a project before building an engagement workflow.
        </p>
      </div>
    );
  }

  const scanBusy = scan.scanning || scan.scanRunning;

  return (
    <div className="grid gap-8">
      <PageHeader
        title="Social Radar"
        description="Discover conversations across Reddit, Twitter/X, LinkedIn, and Instagram — find high-intent opportunities and draft replies."
        actions={
          <div className="flex items-center gap-2">
            <VoiceProfileSelect
              token={token}
              projectId={project?.id ?? null}
              value={voiceProfileId}
              onChange={setVoiceProfileId}
            />
            {campaigns.length > 0 && (
              <Button variant="ghost" size="sm" onClick={() => setShowCampaignModal(true)}>
                <Plus className="h-4 w-4" />
                Campaign
              </Button>
            )}
            <ScanPlatformPicker
              onScan={(platforms) => void scan.runScan(platforms)}
              disabled={scanBusy || subreddits.length === 0}
              scanning={scanBusy}
            />
          </div>
        }
      />

      {/* ── Platform Tabs ──────────────────────────────────────────── */}
      <div className="flex items-center gap-1 rounded-lg bg-muted/50 p-1 w-fit">
        {[
          { id: "all", label: "All Platforms", icon: null },
          { id: "reddit", label: "Reddit", icon: "reddit" },
          { id: "twitter", label: "Twitter/X", icon: "twitter" },
          { id: "linkedin", label: "LinkedIn", icon: "linkedin" },
          { id: "instagram", label: "Instagram", icon: "instagram" },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setPlatformFilter(tab.id)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all",
              platformFilter === tab.id
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-background/50"
            )}
          >
            {tab.icon && <PlatformIcon platform={tab.icon} className="[&_svg]:h-3.5 [&_svg]:w-3.5" />}
            {tab.label}
            {tab.id !== "all" && (
              <span className="text-[10px] tabular-nums opacity-60">
                {opportunities.filter((o) => {
                  const p = ((o as Record<string, unknown>).platform as string || "reddit").toLowerCase();
                  return p === tab.id;
                }).length}
              </span>
            )}
          </button>
        ))}
      </div>

      {campaigns.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">Campaigns:</span>
          {campaigns.map((campaign) => (
            <Badge key={campaign.id} variant="secondary">
              {campaign.name}
              {campaign.status && <span className="text-[11px] opacity-70">({campaign.status})</span>}
            </Badge>
          ))}
        </div>
      )}

      <KPIGrid
        columns={3}
        cards={[
          { label: "Signals", value: keywords.length, icon: Target },
          { label: "Communities", value: subreddits.length, icon: Users },
          { label: "Queue", value: inboxOpps.length, icon: MessageSquare },
        ]}
      />

      <WorkflowStrip
        steps={[
          { label: "Signals", count: keywords.length, done: keywords.length > 0, ref: signalsRef },
          { label: "Communities", count: subreddits.length, done: subreddits.length > 0, ref: communitiesRef },
          { label: "Queue", count: opportunities.length, done: opportunities.length > 0, ref: queueRef },
        ]}
      />

      <ScanProgressBanner scanRun={scan.scanRun} onRefresh={() => void data.loadAll()} />

      <div ref={signalsRef}>
        <SignalsSection
          keywords={keywords}
          newKeyword={newKeyword}
          onNewKeywordChange={setNewKeyword}
          onAddKeyword={() => void handleAddKeyword()}
          addingKeyword={data.addingKeyword}
          onGenerateKeywords={() => void data.generateKeywords()}
          generatingKeywords={data.generatingKeywords}
          onDeleteKeyword={(keyword) => setDeleteTarget({ type: "keywords", id: keyword.id, name: keyword.keyword })}
        />
      </div>

      <div ref={communitiesRef}>
        <CommunitiesSection
          communities={subreddits}
          onDiscover={() => void data.discoverCommunities()}
          discovering={data.discoveringCommunities}
          canDiscover={keywords.length > 0}
          onDeleteCommunity={(community) =>
            setDeleteTarget({ type: "subreddits", id: community.id, name: `r/${community.name}` })
          }
        />
      </div>

      <div ref={queueRef}>
        <InboxSection
          opportunities={inboxOpps}
          totalCount={opportunities.length}
          statusFilter={statusFilter}
          onStatusFilterChange={setStatusFilter}
          stageCounts={stageCounts}
          stageTotal={filteredOpps.length}
          stageFilter={stageFilter}
          onStageFilterChange={setStageFilter}
          search={{ value: searchQuery, onChange: setSearchQuery }}
          filters={
            campaigns.length > 0
              ? [
                  {
                    id: "campaign",
                    placeholder: "All Campaigns",
                    options: campaigns.map((c) => ({ label: c.name, value: String(c.id) })),
                    value: campaignFilter,
                    onChange: setCampaignFilter,
                  },
                ]
              : []
          }
          selectedOpportunity={selectedOpp}
          onSelect={setSelectedOppId}
          checkedIds={checkedIds}
          onToggleChecked={toggleChecked}
          onToggleAllVisible={toggleAllVisible}
          onBulkApprove={() => void handleBulk("saved")}
          onBulkIgnore={() => void handleBulk("ignored")}
          bulkBusy={data.bulkUpdating}
          lastSeenAt={lastSeenAt}
          generatingReplyId={draftOps.generatingReplyId}
          updatingStatus={data.updatingStatus}
          onGenerateReply={(opp) => void handleGenerateReply(opp)}
          onApprove={(opp) => void handleApprove(opp)}
          onIgnore={(opp) => void handleIgnore(opp)}
          emptyAction={subreddits.length > 0 ? { label: "Run Scan", onClick: () => void scan.runScan() } : undefined}
        />
      </div>

      <OpportunityDetailPanel
        opportunity={draftingOpp}
        content={draftContent}
        onContentChange={setDraftContent}
        rationale={draftRationale}
        onClose={() => setDraftingOpp(null)}
        onCopy={(text) => void draftOps.copyToClipboard(text)}
        onCopyAndOpen={(text, permalink) => void draftOps.copyAndOpenReddit(text, permalink)}
        onMarkPosted={(oppId) => void handleMarkPosted(oppId)}
      />

      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deleteTarget?.name || ""}?</AlertDialogTitle>
            <AlertDialogDescription>This action cannot be undone. Are you sure?</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void handleDelete()} variant="destructive">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <CampaignDialog
        open={showCampaignModal}
        onOpenChange={setShowCampaignModal}
        creating={data.creatingCampaign}
        onCreate={handleCreateCampaign}
      />
    </div>
  );
}
