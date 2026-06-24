/**
 * Platform-neutral helpers for rendering an opportunity's source.
 *
 * Opportunities historically came only from Reddit (`subreddit_name`), but the
 * platform is moving toward multi-source discovery (`platform` / `source_name`).
 */

export interface OpportunitySource {
  subreddit_name?: string | null;
  platform?: string | null;
  source_name?: string | null;
}

/** Human-readable label for where an opportunity came from. */
export function sourceLabel(source: OpportunitySource): string {
  const platform = (source.platform || "reddit").toLowerCase();

  // Reddit: always prefer subreddit_name with r/ prefix
  if (platform === "reddit") {
    return source.subreddit_name ? `r/${source.subreddit_name}` : (source.source_name || "Reddit");
  }

  // Twitter / X: use @ prefix
  if (platform === "twitter" || platform === "x") {
    return source.source_name ? `@${source.source_name}` : "Twitter/X";
  }

  // LinkedIn, Instagram, etc.: plain source name
  return source.source_name || source.platform || "Unknown source";
}

/** Platform key for icon rendering (defaults to "reddit" when platform is falsy). */
export function sourcePlatform(source: OpportunitySource): string {
  if (source.platform) {
    return source.platform;
  }
  return "reddit";
}
