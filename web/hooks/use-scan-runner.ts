"use client";

/**
 * Scan orchestration for the Discovery page.
 *
 * POST /v1/scans returns immediately with a "running" scan_run; this hook
 * polls GET /v1/scans/{id} every 2s while the run is in progress (clearing
 * the interval on unmount or status change), surfaces the result via toasts,
 * and invokes `onFinished` so the caller can reload its data.
 */

import { useEffect, useRef, useState } from "react";

import { getScanStatus, triggerScan, type ScanRun } from "@/lib/api/discovery";
import { useToast } from "@/stores/toast";
import { getErrorMessage } from "@/types/errors";

const POLL_INTERVAL_MS = 2000;

export function useScanRunner(
  token: string | null | undefined,
  projectId: number | null | undefined,
  onFinished?: () => void
) {
  const { success, error, warning } = useToast();
  const [scanning, setScanning] = useState(false);
  const [scanRun, setScanRun] = useState<ScanRun | null>(null);
  const prevStatusRef = useRef<string | null>(null);
  const onFinishedRef = useRef(onFinished);
  onFinishedRef.current = onFinished;

  const scanRunning = scanRun?.status === "running";

  function notifyScanResult(run: ScanRun) {
    // Distinguish "nothing matched" from "Reddit refused the request".
    if (run.status === "failed" || run.error_message) {
      warning("Scan finished with issues", run.error_message ?? "The scan did not complete successfully.");
    } else if (run.opportunities_found > 0) {
      success(
        "Scan complete",
        `Scanned ${run.posts_scanned} post(s) — found ${run.opportunities_found} opportunity(ies). Check the queue below.`
      );
    } else if (run.posts_scanned > 0) {
      warning(
        "Scan complete — no matches above the threshold",
        `Scanned ${run.posts_scanned} post(s), none cleared the relevance gate. Check the Rejected tab to see what Reddit returned, or broaden your keywords / subreddits.`
      );
    } else {
      warning(
        "Scan returned no posts",
        "Reddit returned zero posts for your keywords in the last 72 hours. Try broader keywords, higher-traffic subreddits, or a wider time window."
      );
    }
  }

  async function runScan(platforms?: string[]) {
    if (!token || !projectId) {
      return;
    }
    setScanning(true);
    try {
      const run = await triggerScan(token, projectId, {
        search_window_hours: 72,
        max_posts_per_subreddit: 10,
        platforms: platforms?.length ? platforms : undefined,
      });
      setScanRun(run);
      if (run.status !== "running") {
        // Backward compatible: the backend ran the scan synchronously.
        notifyScanResult(run);
        onFinishedRef.current?.();
      }
    } catch (err: unknown) {
      error("Scan failed", getErrorMessage(err));
    }
    setScanning(false);
  }

  // Poll while the run is in progress.
  useEffect(() => {
    if (!token || !scanRun || scanRun.status !== "running") {
      return;
    }
    const scanId = scanRun.id;
    const interval = setInterval(() => {
      void getScanStatus(token, scanId)
        .then(setScanRun)
        .catch((err: unknown) => console.warn("Failed to poll scan status:", err));
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [token, scanRun?.id, scanRun?.status]);

  // Surface the result once a polled run transitions out of "running".
  useEffect(() => {
    const status = scanRun?.status ?? null;
    const previous = prevStatusRef.current;
    prevStatusRef.current = status;
    if (scanRun && previous === "running" && status !== "running") {
      notifyScanResult(scanRun);
      onFinishedRef.current?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanRun]);

  return { scanRun, scanning, scanRunning, runScan };
}
