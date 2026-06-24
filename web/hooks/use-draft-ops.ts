"use client";

/**
 * Shared draft operations used by both the Discovery (Opportunity Radar)
 * and Content Studio pages.
 *
 * Wraps the API helpers in `lib/api/content` / `lib/api/discovery` with
 * toast feedback and loading state. Callers handle their own post-success
 * state updates (closing panels, reloading lists, etc.) based on the
 * returned value (`null` / `false` indicates failure).
 */

import { useCallback, useState } from "react";

import {
  generateReply,
  updateReplyDraft,
  updatePostDraft,
  type ReplyDraft,
  type PostDraft,
} from "@/lib/api/content";
import { updateOpportunityStatus } from "@/lib/api/discovery";
import { copyText } from "@/lib/reddit";
import { useToast } from "@/stores/toast";
import { getErrorMessage } from "@/types/errors";

export function useDraftOps(token: string | null | undefined) {
  const { success, error } = useToast();
  const [generatingReplyId, setGeneratingReplyId] = useState<number | null>(null);
  const [savingReply, setSavingReply] = useState(false);
  const [savingPost, setSavingPost] = useState(false);

  /** Generate an AI reply draft for an opportunity. Returns the draft, or null on failure. */
  const generateReplyDraft = useCallback(
    async (
      opportunityId: number,
      projectId?: number | null,
      options?: { voiceProfileId?: number | null; platform?: string | null }
    ): Promise<ReplyDraft | null> => {
      if (!token) {
        return null;
      }
      setGeneratingReplyId(opportunityId);
      try {
        const draft = await generateReply(token, opportunityId, projectId, null, {
          voice_profile_id: options?.voiceProfileId ?? undefined,
          platform: options?.platform ?? undefined,
        });
        success("Response drafted");
        return draft;
      } catch (err: unknown) {
        error("Could not generate response", getErrorMessage(err));
        return null;
      } finally {
        setGeneratingReplyId(null);
      }
    },
    [token, success, error]
  );

  /** Copy text to the clipboard with toast feedback. */
  const copyToClipboard = useCallback(
    async (text: string): Promise<boolean> => {
      try {
        await copyText(text);
        success("Copied to clipboard");
        return true;
      } catch {
        error("Failed to copy", "Clipboard access was denied.");
        return false;
      }
    },
    [success, error]
  );

  /** Copy text to the clipboard and open the source post in a new tab. */
  const copyAndOpen = useCallback(
    async (text: string, permalink: string, platform?: string): Promise<boolean> => {
      try {
        await copyText(text);
      } catch {
        error("Failed to copy", "Clipboard access was denied.");
        return false;
      }
      const { platformUrl } = await import("@/lib/reddit");
      window.open(platformUrl(permalink, platform), "_blank");
      const platformName = platform && platform !== "reddit"
        ? platform.charAt(0).toUpperCase() + platform.slice(1)
        : "Reddit";
      success(`Draft copied. ${platformName} is opening so you can review and paste.`);
      return true;
    },
    [success, error]
  );

  /** Mark an opportunity as posted. Returns true on success. */
  const markAsPosted = useCallback(
    async (opportunityId: number): Promise<boolean> => {
      if (!token) {
        return false;
      }
      try {
        await updateOpportunityStatus(token, opportunityId, "posted");
        success("Marked as posted");
        return true;
      } catch (err: unknown) {
        error("Could not update status", getErrorMessage(err));
        return false;
      }
    },
    [token, success, error]
  );

  /** Persist edits to a reply draft. Returns the updated draft, or null on failure. */
  const saveReplyDraft = useCallback(
    async (draftId: number, data: { content: string; rationale?: string | null }): Promise<ReplyDraft | null> => {
      if (!token) {
        return null;
      }
      setSavingReply(true);
      try {
        const updated = await updateReplyDraft(token, draftId, data);
        success("Reply draft saved");
        return updated;
      } catch (err: unknown) {
        error("Could not save reply draft", getErrorMessage(err));
        return null;
      } finally {
        setSavingReply(false);
      }
    },
    [token, success, error]
  );

  /** Persist edits to an original post draft. Returns the updated draft, or null on failure. */
  const savePostDraft = useCallback(
    async (
      draftId: number,
      data: { title: string; body: string; rationale?: string | null }
    ): Promise<PostDraft | null> => {
      if (!token) {
        return null;
      }
      setSavingPost(true);
      try {
        const updated = await updatePostDraft(token, draftId, data);
        success("Post draft saved");
        return updated;
      } catch (err: unknown) {
        error("Could not save post draft", getErrorMessage(err));
        return null;
      } finally {
        setSavingPost(false);
      }
    },
    [token, success, error]
  );

  return {
    generatingReplyId,
    savingReply,
    savingPost,
    generateReplyDraft,
    copyToClipboard,
    copyAndOpen,
    markAsPosted,
    saveReplyDraft,
    savePostDraft,
  };
}
