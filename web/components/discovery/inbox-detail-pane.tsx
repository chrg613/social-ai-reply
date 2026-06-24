"use client";

import { Check, ExternalLink, Inbox, Loader2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { ScoreBadge } from "@/components/shared/score-badge";
import { cn } from "@/lib/utils";
import type { Opportunity } from "@/lib/api";
import { sourceLabel, sourcePlatform } from "@/lib/opportunity";
import { platformUrl } from "@/lib/reddit";

import { humanizeStage, stageBadgeClass } from "./buying-stage";

interface InboxDetailPaneProps {
  opportunity: Opportunity | null;
  generating: boolean;
  updating: boolean;
  onGenerateReply: (opportunity: Opportunity) => void;
  onApprove: (opportunity: Opportunity) => void;
  onIgnore: (opportunity: Opportunity) => void;
  className?: string;
}

/** Right-hand inbox pane: full details + actions for the selected opportunity. */
export function InboxDetailPane({
  opportunity,
  generating,
  updating,
  onGenerateReply,
  onApprove,
  onIgnore,
  className,
}: InboxDetailPaneProps) {
  if (!opportunity) {
    return (
      <div className={cn("flex h-full flex-col items-center justify-center p-8 text-center", className)}>
        <Inbox className="h-10 w-10 text-muted-foreground/40" />
        <p className="mt-3 text-sm text-muted-foreground">Select a conversation to review it here.</p>
        <p className="mt-1 text-xs text-muted-foreground/70">
          Tip: use <kbd className="rounded border bg-muted px-1">j</kbd> /{" "}
          <kbd className="rounded border bg-muted px-1">k</kbd> to move through the list.
        </p>
      </div>
    );
  }

  return (
    <div className={cn("flex h-full flex-col", className)}>
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {/* Source + score */}
        <div className="flex flex-wrap items-center gap-2">
          <PlatformIcon platform={sourcePlatform(opportunity)} />
          <Badge variant="outline" className="text-xs">
            {sourceLabel(opportunity)}
          </Badge>
          <ScoreBadge score={opportunity.score || 0} />
          <Badge variant="secondary" className="px-1.5 py-0 text-[11px] capitalize">
            {opportunity.status}
          </Badge>
        </div>

        {/* Title */}
        <a
          href={platformUrl(opportunity.permalink, (opportunity as Record<string, unknown>).platform as string | undefined)}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-base font-semibold leading-snug text-foreground hover:underline"
        >
          {opportunity.title}
          <ExternalLink className="ml-1.5 inline h-3.5 w-3.5 text-muted-foreground" />
        </a>

        {/* Intent / stage signals */}
        {(opportunity.intent || opportunity.buying_stage) && (
          <div className="flex flex-wrap gap-1.5">
            {opportunity.buying_stage && (
              <Badge
                variant="outline"
                className={cn("px-2 py-0.5 text-xs", stageBadgeClass(opportunity.buying_stage))}
              >
                {humanizeStage(opportunity.buying_stage)}
              </Badge>
            )}
            {opportunity.intent && (
              <Badge variant="outline" className="px-2 py-0.5 text-xs">
                {opportunity.intent}
                {typeof opportunity.intent_confidence === "number" &&
                  ` · ${Math.round(opportunity.intent_confidence * 100)}%`}
              </Badge>
            )}
          </div>
        )}

        {/* Body excerpt */}
        {opportunity.body_excerpt && (
          <p className="whitespace-pre-line rounded-lg border bg-muted/30 p-3 text-sm leading-relaxed text-muted-foreground">
            {opportunity.body_excerpt}
          </p>
        )}

        {/* Why it scored */}
        {(opportunity.score_reasons || []).length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">Why it scored</p>
            <div className="flex flex-wrap gap-1">
              {(opportunity.score_reasons || []).map((reason) => (
                <Badge key={reason} variant="secondary" className="px-1.5 py-0 text-[11px]">
                  {reason}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Keyword hits */}
        {(opportunity.keyword_hits || []).length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">Matched signals</p>
            <div className="flex flex-wrap gap-1">
              {(opportunity.keyword_hits || []).map((hit) => (
                <Badge key={hit} variant="outline" className="px-1.5 py-0 text-[11px]">
                  {hit}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2 border-t p-3">
        <Button size="sm" onClick={() => onGenerateReply(opportunity)} disabled={generating}>
          {generating && <Loader2 className="h-4 w-4 animate-spin" />}
          Draft Reply
        </Button>
        <Button variant="outline" size="sm" onClick={() => onApprove(opportunity)} disabled={updating}>
          <Check className="h-4 w-4" />
          Approve
        </Button>
        <Button variant="ghost" size="sm" onClick={() => onIgnore(opportunity)} disabled={updating}>
          <X className="h-4 w-4" />
          Ignore
        </Button>
        <span className="ml-auto hidden text-[11px] text-muted-foreground sm:block">
          <kbd className="rounded border bg-muted px-1">a</kbd> approve ·{" "}
          <kbd className="rounded border bg-muted px-1">i</kbd> ignore ·{" "}
          <kbd className="rounded border bg-muted px-1">↵</kbd> draft
        </span>
      </div>
    </div>
  );
}
