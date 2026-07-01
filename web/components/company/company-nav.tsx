"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

export function CompanyNav() {
  const pathname = usePathname();

  const links = [
    { href: "/app/company", label: "Profile" },
    { href: "/app/persona", label: "Target Personas" },
    { href: "/app/brand-brain", label: "Brand Brain" },
    { href: "/app/competitors", label: "Competitor Intel" },
    { href: "/app/seo-geo", label: "SEO & Geo Audit" },
    { href: "/app/sources", label: "Sources" },
    { href: "/app/agent-runs", label: "Agent Runs" },
    { href: "/app/pipeline-runs", label: "Run History" },
  ];

  return (
    <div className="flex space-x-2 border-b border-border mb-6 overflow-x-auto">
      {links.map((link) => {
        const isActive = pathname === link.href;
        return (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "px-4 py-2 text-sm font-medium border-b-2 transition-colors whitespace-nowrap",
              isActive 
                ? "border-primary text-primary" 
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
            )}
          >
            {link.label}
          </Link>
        );
      })}
    </div>
  );
}
