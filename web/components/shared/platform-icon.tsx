import { cn } from "@/lib/utils";
import { MessageCircle } from "lucide-react";

interface PlatformIconProps {
  platform: string;
  className?: string;
}

/** Reddit SVG logo */
function RedditLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.843.07 3.51.646 4.662 1.534a1.58 1.58 0 0 1 1.063-.413c.883 0 1.598.715 1.598 1.598 0 .65-.39 1.206-.948 1.451a3.3 3.3 0 0 1 .043.551c0 2.79-3.27 5.062-7.31 5.062-4.037 0-7.308-2.272-7.308-5.062 0-.183.015-.366.043-.547A1.748 1.748 0 0 1 3.45 11.65c0-.883.716-1.598 1.598-1.598.396 0 .753.147 1.031.39a8.9 8.9 0 0 1 4.72-1.535l.876-4.089a.346.346 0 0 1 .14-.208.346.346 0 0 1 .246-.041l2.907.637a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.608.608 1.806.649 2.147.649.342 0 1.536-.04 2.147-.649a.33.33 0 0 0 0-.463.33.33 0 0 0-.462 0c-.39.39-1.195.497-1.685.497-.49 0-1.296-.107-1.685-.497a.326.326 0 0 0-.231-.094z" />
    </svg>
  );
}

/** X (Twitter) logo */
function XLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

/** Instagram logo */
function InstagramLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z" />
    </svg>
  );
}

/** LinkedIn logo */
function LinkedInLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  );
}

/** TikTok logo */
function TikTokLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z" />
    </svg>
  );
}

/** Hacker News Y Combinator logo */
function HackerNewsLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M0 0v24h24V0H0zm12.8 13.4V19h-1.6v-5.6L7.3 5h1.8l3 5.2L15.1 5h1.7l-4 8.4z" />
    </svg>
  );
}

const ICON_MAP: Record<string, { icon: React.ElementType; color: string }> = {
  reddit: { icon: RedditLogo, color: "text-orange-500" },
  twitter: { icon: XLogo, color: "text-foreground" },
  x: { icon: XLogo, color: "text-foreground" },
  instagram: { icon: InstagramLogo, color: "text-pink-500" },
  linkedin: { icon: LinkedInLogo, color: "text-blue-600" },
  tiktok: { icon: TikTokLogo, color: "text-foreground" },
  hackernews: { icon: HackerNewsLogo, color: "text-orange-600" },
  quora: { icon: MessageCircle, color: "text-red-500" },
  facebook: { icon: MessageCircle, color: "text-blue-600" },
  default: { icon: MessageCircle, color: "text-muted-foreground" },
};

export function PlatformIcon({ platform, className }: PlatformIconProps) {
  const normalizedPlatform = platform.trim().toLowerCase();
  const { icon: Icon, color } = ICON_MAP[normalizedPlatform] ?? ICON_MAP.default;
  return (
    <span role="img" aria-label={normalizedPlatform} className={cn("inline-flex", color, className)}>
      <Icon className="h-4 w-4" />
    </span>
  );
}
