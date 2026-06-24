"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp, ExternalLink } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { SheetPanel } from "@/components/shared/sheet-panel";
import { PlatformIcon } from "@/components/shared/platform-icon";
import type { Opportunity } from "@/lib/api";
import { platformUrl } from "@/lib/reddit";
import { cn } from "@/lib/utils";

const PLATFORM_LABELS: Record<string, string> = {
  reddit: "Reddit",
  twitter: "Twitter/X",
  x: "Twitter/X",
  linkedin: "LinkedIn",
  instagram: "Instagram",
};

const PLATFORM_CHAR_LIMITS: Record<string, number> = {
  twitter: 280,
  x: 280,
  linkedin: 1250,
  instagram: 2200,
};

const PLATFORM_TONE: Record<string, string> = {
  reddit: "Casual • Community-first",
  twitter: "Concise • Conversational",
  x: "Concise • Conversational",
  linkedin: "Professional • Thought-leadership",
  instagram: "Warm • Authentic",
};

interface OpportunityDetailPanelProps {
  opportunity: Opportunity | null;
  content: string;
  onContentChange: (value: string) => void;
  rationale: string;
  onClose: () => void;
  onCopy: (text: string) => void;
  onCopyAndOpen: (text: string, permalink: string) => void;
  onMarkPosted: (opportunityId: number) => void;
}

/** Side panel showing the original post and the generated reply draft. */
export function OpportunityDetailPanel({
  opportunity,
  content,
  onContentChange,
  rationale,
  onClose,
  onCopy,
  onCopyAndOpen,
  onMarkPosted,
}: OpportunityDetailPanelProps) {
  const [showOriginalThread, setShowOriginalThread] = useState(true);
  const [showRationale, setShowRationale] = useState(false);

  // Reset collapsible state whenever a new opportunity is opened.
  useEffect(() => {
    setShowOriginalThread(true);
    setShowRationale(false);
  }, [opportunity?.id]);

  const opp = opportunity as (Opportunity & Record<string, unknown>) | null;
  const platform = (opp?.platform as string || "reddit").toLowerCase();
  const platformLabel = PLATFORM_LABELS[platform] || platform;
  const charLimit = PLATFORM_CHAR_LIMITS[platform];
  const toneHint = PLATFORM_TONE[platform] || "";
  const isReddit = platform === "reddit";

  return (
    <SheetPanel
      title={
        <span className="inline-flex items-center gap-2">
          <PlatformIcon platform={platform} />
          Reply Draft — {platformLabel}
        </span>
      }
      description={opportunity?.title?.substring(0, 60) || ""}
      open={!!opportunity}
      onOpenChange={(open) => !open && onClose()}
      width="lg"
      footer={
        <div className="flex flex-wrap gap-2">
          <a href="/app/content">
            <Button variant="ghost" size="sm">Review in Studio</Button>
          </a>
          <Button variant="outline" size="sm" onClick={() => onCopy(content)}>
            Copy
          </Button>
          {opportunity?.permalink && (
            <Button size="sm" onClick={() => onCopyAndOpen(content, opportunity.permalink)}>
              Copy &amp; Open {platformLabel}
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => opportunity && onMarkPosted(opportunity.id)}>
            Mark as Posted
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Collapsible: Original Thread */}
        {opportunity?.permalink && (
          <div className="rounded-lg border">
            <button
              type="button"
              onClick={() => setShowOriginalThread(!showOriginalThread)}
              className="flex w-full items-center justify-between p-3 text-sm font-medium text-foreground hover:bg-muted/50 transition-colors"
            >
              <span>Original Thread</span>
              {showOriginalThread ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            {showOriginalThread && (
              <div className="border-t px-3 pb-3 pt-2">
                <a
                  href={platformUrl(opportunity.permalink, platform)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
                >
                  View on {platformLabel} <ExternalLink className="h-3 w-3" />
                </a>
                {opportunity.body_excerpt && (
                  <p className="mt-2 text-xs text-muted-foreground leading-snug">
                    {opportunity.body_excerpt.substring(0, 280)}...
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        {/* Draft Textarea */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>Generated Response</Label>
            {toneHint && (
              <Badge variant="outline" className="text-[10px] font-normal">
                {toneHint}
              </Badge>
            )}
          </div>
          <Textarea
            rows={10}
            value={content}
            onChange={(event) => onContentChange(event.target.value)}
            className="text-sm leading-relaxed"
          />
          <div className="flex items-center justify-between">
            <p className={cn(
              "text-xs",
              charLimit && content.length > charLimit
                ? "text-destructive font-medium"
                : "text-muted-foreground"
            )}>
              {content.length}{charLimit ? ` / ${charLimit}` : ""} characters
            </p>
            {charLimit && content.length > charLimit && (
              <p className="text-xs text-destructive">
                ⚠ Over {platformLabel} character limit by {content.length - charLimit}
              </p>
            )}
          </div>
        </div>

        {/* Collapsible: Rationale */}
        {rationale && (
          <div className="rounded-lg border">
            <button
              type="button"
              onClick={() => setShowRationale(!showRationale)}
              className="flex w-full items-center justify-between p-3 text-sm font-medium text-foreground hover:bg-muted/50 transition-colors"
            >
              <span>Why this response works</span>
              {showRationale ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            {showRationale && (
              <div className="border-t px-3 pb-3 pt-2">
                <p className="text-sm text-muted-foreground">{rationale}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </SheetPanel>
  );
}
