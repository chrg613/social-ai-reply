"use client";

import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { ScoreBadge } from "@/components/shared/score-badge";
import type { Opportunity } from "@/lib/api";
import { sourceLabel, sourcePlatform } from "@/lib/opportunity";
import { platformUrl } from "@/lib/reddit";

interface OpportunityCardProps {
  opportunity: Opportunity;
  generating?: boolean;
  onGenerateReply: (opportunity: Opportunity) => void;
}

/** A single opportunity row: source badge, title, intent/stage signals, score, and actions. */
export function OpportunityCard({ opportunity, generating = false, onGenerateReply }: OpportunityCardProps) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-3 rounded-xl border bg-card p-5">
      {/* Left: Platform + source */}
      <div className="flex items-center gap-2 shrink-0">
        <PlatformIcon platform={sourcePlatform(opportunity)} />
        <Badge variant="outline" className="text-xs">
          {sourceLabel(opportunity)}
        </Badge>
      </div>

      {/* Center: Title + signal badges */}
      <div className="flex-1 min-w-0">
        <a
          href={platformUrl(opportunity.permalink, (opportunity as Record<string, unknown>).platform as string | undefined)}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm font-medium text-foreground hover:underline truncate block"
        >
          {opportunity.title}
        </a>
        {(opportunity.intent || opportunity.buying_stage || (opportunity.score_reasons || []).length > 0) && (
          <div className="mt-1 flex flex-wrap gap-1">
            {opportunity.intent && (
              <Badge variant="outline" className="text-[11px] px-1.5 py-0">
                {opportunity.intent}
                {typeof opportunity.intent_confidence === "number" &&
                  ` ${Math.round(opportunity.intent_confidence * 100)}%`}
              </Badge>
            )}
            {opportunity.buying_stage && (
              <Badge variant="outline" className="text-[11px] px-1.5 py-0">
                {opportunity.buying_stage}
              </Badge>
            )}
            {(opportunity.score_reasons || []).slice(0, 3).map((reason) => (
              <Badge key={reason} variant="secondary" className="text-[11px] px-1.5 py-0">
                {reason}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Right: Score + Action */}
      <div className="flex items-center gap-2 shrink-0">
        <ScoreBadge score={opportunity.score || 0} />
        <Button size="sm" onClick={() => onGenerateReply(opportunity)} disabled={generating}>
          {generating && <Loader2 className="h-4 w-4 animate-spin" />}
          Draft Reply
        </Button>
      </div>
    </div>
  );
}
