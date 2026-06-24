"use client";

import { useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { cn } from "@/lib/utils";

const PLATFORMS = [
  { id: "reddit", label: "Reddit" },
  { id: "twitter", label: "Twitter / X" },
  { id: "linkedin", label: "LinkedIn" },
  { id: "instagram", label: "Instagram" },
] as const;

interface ScanPlatformPickerProps {
  onScan: (platforms: string[]) => void;
  disabled?: boolean;
  scanning?: boolean;
}

export function ScanPlatformPicker({ onScan, disabled, scanning }: ScanPlatformPickerProps) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(["reddit"]));

  const allSelected = selected.size === PLATFORMS.length;
  const noneSelected = selected.size === 0;

  function togglePlatform(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(PLATFORMS.map((p) => p.id)));
    }
  }

  function handleStartScan() {
    const platforms = Array.from(selected);
    setOpen(false);
    onScan(platforms);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        disabled={disabled || scanning}
        className={cn(
          "inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm",
          "hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          "disabled:pointer-events-none disabled:opacity-50"
        )}
      >
        {scanning ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        Run Scan
        <ChevronDown className="h-4 w-4" />
      </PopoverTrigger>

      <PopoverContent align="end" className="w-64 p-0">
        {/* All Platforms toggle */}
        <label
          className={cn(
            "flex cursor-pointer items-center gap-3 border-b px-4 py-2.5 text-sm font-medium",
            "hover:bg-muted/50 transition-colors"
          )}
        >
          <input
            type="checkbox"
            checked={allSelected}
            ref={(el) => {
              if (el) el.indeterminate = !allSelected && !noneSelected;
            }}
            onChange={toggleAll}
            className="h-4 w-4 rounded border-border accent-primary"
          />
          All Platforms
        </label>

        {/* Individual platform rows */}
        <div className="py-1">
          {PLATFORMS.map((platform) => (
            <label
              key={platform.id}
              className={cn(
                "flex cursor-pointer items-center gap-3 px-4 py-2 text-sm",
                "hover:bg-muted/50 transition-colors"
              )}
            >
              <input
                type="checkbox"
                checked={selected.has(platform.id)}
                onChange={() => togglePlatform(platform.id)}
                className="h-4 w-4 rounded border-border accent-primary"
              />
              <PlatformIcon platform={platform.id} className="shrink-0" />
              <span>{platform.label}</span>
            </label>
          ))}
        </div>

        {/* Start Scan button */}
        <div className="border-t px-4 py-3">
          <Button
            size="sm"
            className="w-full"
            disabled={noneSelected}
            onClick={handleStartScan}
          >
            Start Scan
            {selected.size > 0 && (
              <span className="ml-1.5 text-xs opacity-80">
                ({selected.size} platform{selected.size !== 1 ? "s" : ""})
              </span>
            )}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
