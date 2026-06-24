"use client";

import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { ScanRun } from "@/lib/api/discovery";

interface ScanProgressBannerProps {
  scanRun: ScanRun | null;
  onRefresh?: () => void;
}

/**
 * Live banner for an in-flight scan run. The page polls GET /v1/scans/{id}
 * while the run is "running" and feeds the latest snapshot in here.
 */
export function ScanProgressBanner({ scanRun, onRefresh }: ScanProgressBannerProps) {
  if (!scanRun) {
    return null;
  }

  if (scanRun.status === "running") {
    return (
      <Card className="border-primary/30 bg-primary/5">
        <CardContent className="flex flex-col sm:flex-row sm:items-center gap-3 py-3">
          <div className="flex items-center gap-2 min-w-0">
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
            <p className="text-sm font-medium truncate">Scan in progress…</p>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground sm:ml-auto">
            {typeof scanRun.subreddits_scanned === "number" && (
              <span>{scanRun.subreddits_scanned} communities scanned</span>
            )}
            <span>{scanRun.posts_scanned ?? 0} posts scanned</span>
            <span>{scanRun.opportunities_found ?? 0} opportunities found</span>
            {onRefresh && (
              <Button variant="ghost" size="sm" onClick={onRefresh}>
                <RefreshCw className="h-3.5 w-3.5" />
                Refresh
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (scanRun.status === "failed" || scanRun.error_message) {
    return (
      <Card className="border-destructive/30 bg-destructive/5">
        <CardContent className="flex items-start gap-2 py-3">
          <AlertTriangle className="h-4 w-4 shrink-0 text-destructive mt-0.5" />
          <div className="min-w-0">
            <p className="text-sm font-medium">Scan finished with issues</p>
            <p className="text-xs text-muted-foreground">
              {(scanRun.error_message || "The scan did not complete successfully.")
                .replace(/^\d{3}:\s*/, "")}
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return null;
}
