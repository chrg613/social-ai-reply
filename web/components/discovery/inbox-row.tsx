"use client";

import { Badge } from "@/components/ui/badge";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { ScoreBadge } from "@/components/shared/score-badge";
import { cn } from "@/lib/utils";
import type { Opportunity } from "@/lib/api";
import { sourceLabel, sourcePlatform } from "@/lib/opportunity";

import { humanizeStage, stageBadgeClass } from "./buying-stage";

interface InboxRowProps {
  opportunity: Opportunity;
  selected: boolean;
  checked: boolean;
  /** Created since the user's last visit — shows a "● new" marker. */
  isNew: boolean;
  onSelect: () => void;
  onToggleChecked: () => void;
}

/** Compact, selectable inbox row: checkbox, platform icon, source, title, stage badge, score. */
export function InboxRow({ opportunity, selected, checked, isNew, onSelect, onToggleChecked }: InboxRowProps) {
  const unread = opportunity.status === "new";
  const platform = sourcePlatform(opportunity);

  return (
    <div
      id={`inbox-opp-${opportunity.id}`}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      aria-selected={selected}
      className={cn(
        "flex w-full cursor-pointer items-start gap-2.5 border-b border-l-2 px-3 py-2.5 text-left transition-colors last:border-b-0",
        selected ? "border-l-primary bg-primary/5" : "border-l-transparent hover:bg-muted/50"
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        onClick={(event) => event.stopPropagation()}
        onChange={onToggleChecked}
        aria-label={`Select ${opportunity.title}`}
        className="mt-1 h-3.5 w-3.5 shrink-0 cursor-pointer accent-primary"
      />

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          {isNew && (
            <span
              className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
              title="New since last visit"
              aria-label="New since last visit"
            />
          )}
          <PlatformIcon platform={platform} className="h-3.5 w-3.5 shrink-0 opacity-60" />
          <span
            className={cn(
              "block truncate text-sm",
              unread ? "font-semibold text-foreground" : "font-normal text-foreground/80"
            )}
          >
            {opportunity.title}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground">{sourceLabel(opportunity)}</span>
          {opportunity.buying_stage && (
            <Badge variant="outline" className={cn("px-1.5 py-0 text-[11px]", stageBadgeClass(opportunity.buying_stage))}>
              {humanizeStage(opportunity.buying_stage)}
            </Badge>
          )}
          {!unread && opportunity.status !== "rejected" && (
            <span className="text-[11px] capitalize text-muted-foreground/70">{opportunity.status}</span>
          )}
        </div>
      </div>

      <ScoreBadge score={opportunity.score || 0} className="shrink-0" />
    </div>
  );
}
