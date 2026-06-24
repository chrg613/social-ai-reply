"use client";

/**
 * Data layer for the Discovery (Opportunity Radar) page: loads the active
 * project plus its keywords, communities, opportunities, and campaigns, and
 * exposes the CRUD actions for each with toast feedback.
 */

import { useCallback, useRef, useState } from "react";

import type { CommunityItem } from "@/components/discovery/communities-section";
import type { SignalItem } from "@/components/discovery/signals-section";
import { apiRequest, type Opportunity } from "@/lib/api";
import { updateOpportunityStatus } from "@/lib/api/discovery";
import { sendOpportunityFeedback } from "@/lib/api/feedback";
import { withProjectId } from "@/lib/project";
import { useToast } from "@/stores/toast";
import { getErrorMessage } from "@/types/errors";

export interface ProjectContext {
  id: number;
  name: string;
}

export interface Campaign {
  id: number;
  name: string;
  description?: string;
  status?: string;
}

export function useDiscoveryData(token: string | null | undefined, selectedProjectId: number | null) {
  const { success, error, warning } = useToast();

  const [project, setProject] = useState<ProjectContext | null>(null);
  const [keywords, setKeywords] = useState<SignalItem[]>([]);
  const [subreddits, setSubreddits] = useState<CommunityItem[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [initialLoading, setInitialLoading] = useState(true);
  const hasLoadedOnceRef = useRef(false);

  const [addingKeyword, setAddingKeyword] = useState(false);
  const [generatingKeywords, setGeneratingKeywords] = useState(false);
  const [discoveringCommunities, setDiscoveringCommunities] = useState(false);
  const [creatingCampaign, setCreatingCampaign] = useState(false);
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [bulkUpdating, setBulkUpdating] = useState(false);

  const loadAll = useCallback(async () => {
    if (!token) {
      return;
    }
    setLoading(true);

    function settle<T>(result: PromiseSettledResult<T>, fallback: T, label: string): T {
      if (result.status === "fulfilled") {
        return result.value;
      }
      console.warn(`Failed to load ${label}:`, result.reason);
      error(`Failed to load ${label}`);
      return fallback;
    }

    try {
      const dashRes = await apiRequest<{ projects?: ProjectContext[] }>(
        withProjectId("/v1/dashboard", selectedProjectId),
        {},
        token
      );
      const currentProject =
        dashRes.projects?.find((item) => item.id === selectedProjectId) ?? dashRes.projects?.[0] ?? null;
      setProject(currentProject);
      if (!currentProject) {
        // No project found — clear loading flags so the UI can render
        // a "no project" empty state instead of an eternal spinner.
        setLoading(false);
        setInitialLoading(false);
        return;
      }

      const projectId = currentProject.id;
      const [kw, subs, opps, camps] = await Promise.allSettled([
        apiRequest<SignalItem[]>(`/v1/discovery/keywords?project_id=${projectId}`, {}, token),
        apiRequest<CommunityItem[]>(`/v1/discovery/subreddits?project_id=${projectId}`, {}, token),
        apiRequest<Opportunity[]>(`/v1/opportunities?project_id=${projectId}&status=all&limit=200`, {}, token),
        apiRequest<Campaign[]>(`/v1/campaigns?project_id=${projectId}`, {}, token),
      ]);
      setKeywords(settle(kw, [], "keywords"));
      setSubreddits(settle(subs, [], "subreddits"));
      setOpportunities(settle(opps, [], "opportunities"));
      setCampaigns(settle(camps, [], "campaigns"));
    } catch (err: unknown) {
      error("Failed to load data", getErrorMessage(err));
    } finally {
      setLoading(false);
      if (!hasLoadedOnceRef.current) {
        hasLoadedOnceRef.current = true;
        setInitialLoading(false);
      }
    }
  }, [token, selectedProjectId, error]);

  async function addKeyword(keyword: string): Promise<boolean> {
    if (!keyword.trim() || !project) {
      return false;
    }
    setAddingKeyword(true);
    try {
      await apiRequest(
        `/v1/discovery/keywords?project_id=${project.id}`,
        {
          method: "POST",
          body: JSON.stringify({ keyword: keyword.trim(), rationale: "Manual", priority_score: 5, is_active: true }),
        },
        token
      );
      success("Signal added");
      await loadAll();
      return true;
    } catch (err: unknown) {
      error("Failed to add keyword", getErrorMessage(err));
      return false;
    } finally {
      setAddingKeyword(false);
    }
  }

  async function generateKeywords() {
    if (!project) {
      return;
    }
    setGeneratingKeywords(true);
    try {
      await apiRequest(
        `/v1/discovery/keywords/generate?project_id=${project.id}`,
        { method: "POST", body: JSON.stringify({ count: 12 }) },
        token
      );
      success("Audience signals generated");
      await loadAll();
    } catch (err: unknown) {
      error("Failed to generate", getErrorMessage(err));
    }
    setGeneratingKeywords(false);
  }

  async function discoverCommunities() {
    if (!project) {
      return;
    }
    setDiscoveringCommunities(true);
    try {
      await apiRequest(
        `/v1/discovery/subreddits/discover?project_id=${project.id}`,
        { method: "POST", body: JSON.stringify({ max_subreddits: 8 }) },
        token
      );
      success("Communities discovered");
      await loadAll();
    } catch (err: unknown) {
      error("Failed to discover", getErrorMessage(err));
    }
    setDiscoveringCommunities(false);
  }

  /** Delete a discovery item ("keywords" | "subreddits"). Returns true on success. */
  async function deleteDiscoveryItem(type: string, id: number, name: string): Promise<boolean> {
    try {
      await apiRequest(`/v1/discovery/${type}/${id}`, { method: "DELETE" }, token);
      success(`${name} deleted`);
      await loadAll();
      return true;
    } catch (err: unknown) {
      error("Delete failed", getErrorMessage(err));
      return false;
    }
  }

  /**
   * Update an opportunity's status (inbox approve/ignore/save). Optimistically
   * updates the local list without a full reload. For "saved"/"ignored" also
   * fires a best-effort feedback signal so scoring can learn from triage.
   */
  async function setOpportunityStatus(
    opportunity: Opportunity,
    status: string,
    options?: { silent?: boolean }
  ): Promise<boolean> {
    if (!token) {
      return false;
    }
    if (!options?.silent) {
      setUpdatingStatus(true);
    }
    try {
      await updateOpportunityStatus(token, opportunity.id, status);
      setOpportunities((prev) => prev.map((opp) => (opp.id === opportunity.id ? { ...opp, status } : opp)));
      if (status === "saved" || status === "ignored") {
        void sendOpportunityFeedback(token, {
          opportunity_id: opportunity.id,
          action: status,
          original_score: opportunity.score || 0,
        });
      }
      if (!options?.silent) {
        success(status === "ignored" ? "Conversation ignored" : status === "saved" ? "Conversation approved" : "Status updated");
      }
      return true;
    } catch (err: unknown) {
      if (!options?.silent) {
        error("Could not update status", getErrorMessage(err));
      }
      return false;
    } finally {
      if (!options?.silent) {
        setUpdatingStatus(false);
      }
    }
  }

  /** Bulk approve/ignore: sequential status updates with a single summary toast. */
  async function bulkUpdateStatus(targets: Opportunity[], status: "saved" | "ignored"): Promise<void> {
    if (!token || targets.length === 0) {
      return;
    }
    setBulkUpdating(true);
    let updated = 0;
    let failed = 0;
    try {
      for (const opportunity of targets) {
        if (await setOpportunityStatus(opportunity, status, { silent: true })) {
          updated += 1;
        } else {
          failed += 1;
        }
      }
    } finally {
      setBulkUpdating(false);
    }
    const verb = status === "ignored" ? "ignored" : "approved";
    const noun = updated === 1 ? "conversation" : "conversations";
    if (failed === 0) {
      success(`${updated} ${noun} ${verb}`);
    } else if (updated === 0) {
      error(`Could not update ${failed} ${failed === 1 ? "conversation" : "conversations"}`);
    } else {
      warning(`${updated} ${noun} ${verb}, ${failed} failed`);
    }
  }

  async function createCampaign(name: string, description: string): Promise<boolean> {
    if (!project || !name.trim()) {
      warning("Please enter a campaign name");
      return false;
    }
    setCreatingCampaign(true);
    try {
      const campaign = await apiRequest<Campaign>(
        "/v1/campaigns",
        {
          method: "POST",
          body: JSON.stringify({ project_id: project.id, name: name.trim(), description: description.trim() || null }),
        },
        token
      );
      setCampaigns((prev) => [campaign, ...prev]);
      success("Campaign created");
      return true;
    } catch (err: unknown) {
      error("Failed to create campaign", getErrorMessage(err));
      return false;
    } finally {
      setCreatingCampaign(false);
    }
  }

  return {
    project,
    keywords,
    subreddits,
    opportunities,
    campaigns,
    loading,
    initialLoading,
    addingKeyword,
    generatingKeywords,
    discoveringCommunities,
    creatingCampaign,
    updatingStatus,
    bulkUpdating,
    loadAll,
    addKeyword,
    generateKeywords,
    discoverCommunities,
    deleteDiscoveryItem,
    createCampaign,
    setOpportunityStatus,
    bulkUpdateStatus,
  };
}
