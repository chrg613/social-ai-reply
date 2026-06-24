"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";

interface SheetPanelProps {
  title: ReactNode;
  description?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  width?: "sm" | "md" | "lg";
}

const widthClasses = {
  sm: "!sm:max-w-sm",
  md: "!sm:max-w-md",
  lg: "!sm:max-w-lg",
} as const;

export function SheetPanel({
  title,
  description,
  open,
  onOpenChange,
  children,
  footer,
  className,
  width = "md",
}: SheetPanelProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        showCloseButton
        className={cn(
          "w-full flex flex-col h-full",
          widthClasses[width],
          className
        )}
      >
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          {description && <SheetDescription>{description}</SheetDescription>}
        </SheetHeader>

        <div className="flex-1 overflow-y-auto p-6">{children}</div>

        {footer && (
          <div className="border-t border-border p-5 flex flex-row items-center justify-end gap-2">
            {footer}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
