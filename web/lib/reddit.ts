/**
 * Shared URL utility helpers for multi-platform link resolution.
 * Both functions were previously duplicated in content/page.tsx and discovery/page.tsx.
 */

/**
 * Returns a full Reddit URL from a permalink that may or may not already be absolute.
 * @deprecated Use `platformUrl()` for multi-platform support.
 */
export function redditUrl(permalink: string): string {
  if (permalink.startsWith("http")) {
    return permalink;
  }
  return `https://www.reddit.com${permalink}`;
}

/**
 * Returns the correct absolute URL for a post on any platform.
 * - Reddit: prepends `https://www.reddit.com` to relative paths.
 * - Other platforms (Twitter, LinkedIn, Instagram): returns the permalink as-is
 *   (their URLs are already absolute).
 */
export function platformUrl(permalink: string, platform?: string): string {
  if (!platform || platform.toLowerCase() === "reddit") {
    return redditUrl(permalink);
  }
  // Twitter, LinkedIn, Instagram URLs are already absolute.
  return permalink;
}

/**
 * Copies `text` to the clipboard.
 * The caller is responsible for showing user feedback after the call.
 * Errors propagate so callers can show failure toasts.
 */
export async function copyText(text: string): Promise<void> {
  await navigator.clipboard.writeText(text);
}
