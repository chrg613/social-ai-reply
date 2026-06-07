"""SEO Agent — audits website and stores SEO opportunities."""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.db.tables.agent_runs import create_agent_run, update_agent_run
from app.db.tables.brand_keywords import list_brand_keywords_for_company
from app.db.tables.company import get_company_by_id
from app.db.tables.discovery import bulk_create_opportunities
from app.db.tables.projects import list_projects_for_workspace

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_DEFAULT_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class AgentRunResult:
    items_fetched: int = 0
    items_kept: int = 0
    items_rejected: int = 0
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


@dataclass
class SEOAuditPage:
    url: str
    title: str = ""
    meta_description: str = ""
    h1_list: list[str] = field(default_factory=list)
    h2_list: list[str] = field(default_factory=list)
    word_count: int = 0
    canonical: str = ""
    og_tags: dict[str, str] = field(default_factory=dict)
    schema_org: list[dict] = field(default_factory=list)
    image_alts: list[str] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    load_time_ms: float = 0.0
    status_code: int | None = None
    error: str | None = None


class SEOAgent:
    """SEO audit agent that crawls a website and stores SEO opportunities."""

    def __init__(self, rate_limit_seconds: float = 1.0) -> None:
        self.rate_limit = rate_limit_seconds
        self._last_request_time: float | None = None

    def _sleep_if_needed(self) -> None:
        if self._last_request_time is not None:
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self.rate_limit:
                time.sleep(self.rate_limit - elapsed)
        self._last_request_time = time.monotonic()

    @staticmethod
    def _normalize_url(url: str) -> str:
        url = url.strip()
        if not url:
            raise ValueError("Empty URL")
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        return url

    def _fetch_html(self, url: str) -> tuple[str, float]:
        """Fetch HTML with retries and timing. Returns (text, load_time_ms)."""
        last_err: Exception | None = None
        candidate_urls = [url]
        if url.startswith("https://"):
            candidate_urls.append(f"http://{url.removeprefix('https://')}")

        for candidate_url in candidate_urls:
            for verify_ssl in (True, False):
                try:
                    self._sleep_if_needed()
                    start = time.monotonic()
                    with httpx.Client(
                        timeout=25.0,
                        follow_redirects=True,
                        verify=verify_ssl,
                    ) as client:
                        resp = client.get(candidate_url, headers=_DEFAULT_HEADERS)
                        resp.raise_for_status()
                        load_time_ms = (time.monotonic() - start) * 1000
                        return resp.text, load_time_ms
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "HTTP %s for %s (ssl_verify=%s)",
                        exc.response.status_code,
                        candidate_url,
                        verify_ssl,
                    )
                    last_err = exc
                    break
                except httpx.HTTPError as exc:
                    logger.warning(
                        "Fetch failed for %s (ssl_verify=%s): %s",
                        candidate_url,
                        verify_ssl,
                        exc,
                    )
                    last_err = exc
                    if verify_ssl:
                        continue
                    break

        raise RuntimeError(f"Could not fetch {url}: {last_err}") from last_err

    def crawl_page(self, url: str) -> SEOAuditPage:
        """Crawl a single page and extract SEO data."""
        page = SEOAuditPage(url=url)
        try:
            html, load_time_ms = self._fetch_html(url)
            page.load_time_ms = load_time_ms
            page.status_code = 200
            soup = BeautifulSoup(html, "html.parser")

            # Title
            if soup.title and soup.title.string:
                page.title = soup.title.string.strip()

            # Meta description
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                page.meta_description = meta_desc.get("content").strip()

            # Canonical
            canonical = soup.find("link", rel="canonical")
            if canonical and canonical.get("href"):
                page.canonical = canonical.get("href").strip()

            # OG tags
            for tag in soup.find_all("meta", property=lambda x: x and x.startswith("og:")):
                prop = tag.get("property", "")
                content = tag.get("content", "")
                if prop and content:
                    page.og_tags[prop] = content

            # Schema.org
            import json

            for script in soup.find_all("script", type="application/ld+json"):
                if script.string:
                    try:
                        page.schema_org.append(json.loads(script.string))
                    except json.JSONDecodeError:
                        continue

            # Headings
            page.h1_list = [
                h.get_text(" ", strip=True)
                for h in soup.find_all("h1")
                if h.get_text(strip=True)
            ]
            page.h2_list = [
                h.get_text(" ", strip=True)
                for h in soup.find_all("h2")
                if h.get_text(strip=True)
            ]

            # Word count
            text = soup.get_text(separator=" ", strip=True)
            page.word_count = len(text.split())

            # Image alt texts
            for img in soup.find_all("img"):
                alt = img.get("alt", "")
                page.image_alts.append(alt)

            # Internal links
            parsed_base = urlparse(url)
            base_domain = parsed_base.netloc
            for a in soup.find_all("a", href=True):
                href = a["href"]
                full = urljoin(url, href)
                parsed = urlparse(full)
                if parsed.netloc == base_domain or not parsed.netloc:
                    page.internal_links.append(full)

        except httpx.HTTPStatusError as exc:
            page.status_code = exc.response.status_code
            page.error = f"HTTP {exc.response.status_code}"
            logger.warning("HTTP %s for %s", exc.response.status_code, url)
        except httpx.HTTPError as exc:
            page.error = str(exc)
            logger.warning("Fetch error for %s: %s", url, exc)
        except Exception as exc:
            page.error = str(exc)
            logger.warning("Error parsing %s: %s", url, exc)

        return page

    def run(self, company_id: int, db: Client, config: dict[str, Any]) -> AgentRunResult:
        """Execute a full SEO audit run."""
        result = AgentRunResult()
        started_at = datetime.now(UTC)

        project_id = _get_project_id_for_company(db, company_id, config)
        if not project_id:
            result.logs.append(f"ERROR: No project found for company {company_id}")
            return result

        company = get_company_by_id(db, company_id)
        if not company:
            result.logs.append(f"ERROR: Company {company_id} not found")
            return result

        website_url = company.get("website_url")
        if not website_url:
            result.logs.append(f"ERROR: No website_url for company {company_id}")
            return result

        brand_keywords = list_brand_keywords_for_company(db, company_id, enabled_only=True)

        run = create_agent_run(
            db,
            {
                "company_id": company_id,
                "agent_name": "seo",
                "status": "running",
                "started_at": started_at.isoformat(),
            },
        )
        run_id = run["id"]

        try:
            base_url = self._normalize_url(website_url)
            parsed = urlparse(base_url)

            # Crawl standard pages
            paths = ["/", "/pricing", "/features", "/about", "/blog", "/docs", "/sitemap.xml"]
            pages: dict[str, SEOAuditPage] = {}
            for path in paths:
                full_url = urljoin(base_url, path)
                page = self.crawl_page(full_url)
                pages[path] = page
                result.items_fetched += 1

            # Fetch robots.txt
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            robots_exists = False
            try:
                self._sleep_if_needed()
                with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                    resp = client.get(robots_url, headers=_DEFAULT_HEADERS)
                    robots_exists = resp.status_code == 200
            except Exception:
                robots_exists = False

            # Fetch sitemap.xml
            sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
            sitemap_exists = False
            sitemap_urls: list[str] = []
            try:
                self._sleep_if_needed()
                with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                    resp = client.get(sitemap_url, headers=_DEFAULT_HEADERS)
                    if resp.status_code == 200:
                        sitemap_exists = True
                        try:
                            root = ET.fromstring(resp.text)
                            for elem in root.iter():
                                if elem.tag.endswith("loc") and elem.text:
                                    sitemap_urls.append(elem.text)
                        except ET.ParseError:
                            pass
            except Exception:
                sitemap_exists = False

            # Crawl additional sitemap URLs (up to 10)
            extra_pages: list[SEOAuditPage] = []
            for s_url in sitemap_urls[:10]:
                if s_url not in {p.url for p in pages.values()}:
                    extra_page = self.crawl_page(s_url)
                    extra_pages.append(extra_page)
                    result.items_fetched += 1

            all_pages = list(pages.values()) + extra_pages

            # Run checks
            issues: list[dict] = []
            all_titles: list[str] = []
            for page in all_pages:
                if page.error:
                    continue
                all_titles.append(page.title.lower())

            for page in all_pages:
                if page.error:
                    if page.status_code == 404:
                        issues.append(
                            {
                                "check": "broken_internal_link",
                                "severity": "high",
                                "url": page.url,
                                "detail": f"Page returned HTTP {page.status_code}",
                            }
                        )
                    continue

                # Missing title
                if not page.title:
                    issues.append(
                        {
                            "check": "missing_title",
                            "severity": "high",
                            "url": page.url,
                            "detail": "Title tag is missing or empty",
                        }
                    )

                # Missing meta description
                if not page.meta_description:
                    issues.append(
                        {
                            "check": "missing_meta_description",
                            "severity": "medium",
                            "url": page.url,
                            "detail": "Meta description is missing",
                        }
                    )

                # Duplicate H1
                if len(page.h1_list) > 1:
                    issues.append(
                        {
                            "check": "duplicate_h1",
                            "severity": "medium",
                            "url": page.url,
                            "detail": f"Page has {len(page.h1_list)} H1 tags",
                        }
                    )

                # Missing H1
                if not page.h1_list:
                    issues.append(
                        {
                            "check": "missing_h1",
                            "severity": "high",
                            "url": page.url,
                            "detail": "H1 tag is missing",
                        }
                    )

                # Thin content
                if page.word_count < 300:
                    issues.append(
                        {
                            "check": "thin_content",
                            "severity": "medium",
                            "url": page.url,
                            "detail": f"Page has only {page.word_count} words",
                        }
                    )

                # Missing canonical
                if not page.canonical:
                    issues.append(
                        {
                            "check": "missing_canonical",
                            "severity": "low",
                            "url": page.url,
                            "detail": "Canonical tag is missing",
                        }
                    )

                # Missing alt text
                missing_alts = sum(1 for alt in page.image_alts if not alt.strip())
                if missing_alts > 0:
                    issues.append(
                        {
                            "check": "missing_alt_text",
                            "severity": "low",
                            "url": page.url,
                            "detail": f"{missing_alts} images missing alt text",
                        }
                    )

                # Missing OG tags
                if not page.og_tags:
                    issues.append(
                        {
                            "check": "missing_og_tags",
                            "severity": "low",
                            "url": page.url,
                            "detail": "Open Graph tags are missing",
                        }
                    )

                # Missing schema.org
                if not page.schema_org:
                    issues.append(
                        {
                            "check": "missing_schema_org",
                            "severity": "medium",
                            "url": page.url,
                            "detail": "Schema.org structured data is missing",
                        }
                    )

                # Slow page
                if page.load_time_ms > 3000:
                    issues.append(
                        {
                            "check": "slow_page",
                            "severity": "low",
                            "url": page.url,
                            "detail": f"Page load time is {page.load_time_ms:.0f}ms (>3000ms)",
                        }
                    )

                # Missing internal links
                if len(page.internal_links) < 2:
                    issues.append(
                        {
                            "check": "missing_internal_links",
                            "severity": "low",
                            "url": page.url,
                            "detail": f"Page has only {len(page.internal_links)} internal links",
                        }
                    )

            # Duplicate titles
            title_counts: dict[str, int] = {}
            for t in all_titles:
                if t:
                    title_counts[t] = title_counts.get(t, 0) + 1
            for title, count in title_counts.items():
                if count > 1:
                    affected = [p.url for p in all_pages if p.title and p.title.lower() == title]
                    issues.append(
                        {
                            "check": "duplicate_title",
                            "severity": "medium",
                            "url": affected[0],
                            "detail": f"Title '{title[:80]}' duplicated across {count} pages: {', '.join(affected)}",
                        }
                    )

            # Missing robots.txt
            if not robots_exists:
                issues.append(
                    {
                        "check": "missing_robots_txt",
                        "severity": "medium",
                        "url": robots_url,
                        "detail": "robots.txt is missing",
                    }
                )

            # Missing sitemap.xml
            if not sitemap_exists:
                issues.append(
                    {
                        "check": "missing_sitemap_xml",
                        "severity": "medium",
                        "url": sitemap_url,
                        "detail": "sitemap.xml is missing",
                    }
                )

            # Build corpus for keyword gap
            corpus = " ".join(
                f"{p.title} {p.meta_description} {' '.join(p.h1_list)} {' '.join(p.h2_list)}"
                for p in all_pages
                if not p.error
            ).lower()

            # Keyword gap analysis
            keyword_gaps: list[dict] = []
            for kw in brand_keywords:
                term = str(kw.get("keyword", "")).strip().lower()
                if term and term not in corpus:
                    keyword_gaps.append(
                        {
                            "keyword": term,
                            "suggested_topic": f"Create content about {term}",
                        }
                    )

            # Build opportunities
            opportunities: list[dict] = []
            for issue in issues:
                priority = _severity_to_priority(issue["severity"], issue["url"] == base_url)
                opportunities.append(
                    {
                        "project_id": project_id,
                        "platform": "seo",
                        "agent_name": "seo",
                        "title": _issue_title(issue),
                        "body": f"URL: {issue['url']}\n\n{issue['detail']}",
                        "opportunity_type": "seo_issue",
                        "severity": issue["severity"],
                        "score": priority,
                        "status": "new",
                    }
                )

            for gap in keyword_gaps:
                opportunities.append(
                    {
                        "project_id": project_id,
                        "platform": "seo",
                        "agent_name": "seo",
                        "title": f"Missing content for keyword: {gap['keyword']}",
                        "body": f"Suggested topic: {gap['suggested_topic']}",
                        "opportunity_type": "keyword_gap",
                        "severity": "medium",
                        "score": 60,
                        "status": "new",
                    }
                )

            result.items_kept = len(opportunities)
            result.logs.append(f"SEO audit: {len(issues)} issues found, {len(keyword_gaps)} keyword gaps")

            if opportunities:
                stored = bulk_create_opportunities(db, opportunities)
                result.opportunities = stored
                result.logs.append(f"Stored {len(stored)} opportunities")

            update_agent_run(
                db,
                run_id,
                {
                    "status": "completed",
                    "items_fetched": result.items_fetched,
                    "items_kept": result.items_kept,
                    "items_rejected": 0,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "logs_json": result.logs,
                },
            )
        except Exception as exc:
            logger.exception("SEOAgent run failed")
            result.logs.append(f"FATAL ERROR: {type(exc).__name__}: {exc}")
            update_agent_run(
                db,
                run_id,
                {
                    "status": "error",
                    "error_message": str(exc)[:500],
                    "finished_at": datetime.now(UTC).isoformat(),
                    "logs_json": result.logs,
                },
            )

        return result


def _get_project_id_for_company(db: Client, company_id: int, config: dict[str, Any]) -> int | None:
    project_id = config.get("project_id")
    if project_id:
        return int(project_id)
    company = get_company_by_id(db, company_id)
    if not company:
        return None
    workspace_id = company.get("workspace_id")
    if not workspace_id:
        return None
    projects = list_projects_for_workspace(db, workspace_id)
    if projects:
        return projects[0]["id"]
    return None


def _severity_to_priority(severity: str, is_homepage: bool) -> int:
    base = {"high": 85, "medium": 60, "low": 35}.get(severity, 35)
    if is_homepage:
        base += 15
    return min(base, 100)


def _issue_title(issue: dict) -> str:
    mapping = {
        "missing_title": "Missing title tag",
        "missing_meta_description": "Missing meta description",
        "duplicate_title": "Duplicate page titles",
        "missing_h1": "Missing H1 tag",
        "duplicate_h1": "Duplicate H1 tags",
        "thin_content": "Thin content",
        "missing_canonical": "Missing canonical tag",
        "missing_robots_txt": "Missing robots.txt",
        "missing_sitemap_xml": "Missing sitemap.xml",
        "missing_alt_text": "Images missing alt text",
        "missing_og_tags": "Missing Open Graph tags",
        "missing_schema_org": "Missing schema.org markup",
        "broken_internal_link": "Broken internal link",
        "slow_page": "Slow page load",
        "missing_internal_links": "Missing internal links",
    }
    return mapping.get(issue["check"], issue["check"])
