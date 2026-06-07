"""Technical SEO Agent — scans website code and suggests actual code changes."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.db.tables.agent_runs import create_agent_run, update_agent_run
from app.db.tables.company import get_company_by_id
from app.db.tables.discovery import bulk_create_opportunities
from app.db.tables.projects import list_projects_for_workspace
from app.services.product.brand_brain_crawler import BrandBrainCrawler

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)


@dataclass
class AgentRunResult:
    items_fetched: int = 0
    items_kept: int = 0
    items_rejected: int = 0
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


@dataclass
class TechnicalIssue:
    check: str
    severity: str
    page: str
    detail: str
    current_code_snippet: str = ""
    suggested_fix: str = ""
    code_snippet: str = ""
    priority_score: int = 0


class TechnicalSEOAgent:
    """Technical SEO agent that scans website code and suggests fixes."""

    def __init__(self, rate_limit_seconds: float = 1.0) -> None:
        self.crawler = BrandBrainCrawler(rate_limit_seconds=rate_limit_seconds)

    def run(self, company_id: int, db: Client, config: dict[str, Any]) -> AgentRunResult:
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

        run = create_agent_run(
            db,
            {
                "company_id": company_id,
                "agent_name": "technical_seo",
                "status": "running",
                "started_at": started_at.isoformat(),
            },
        )
        run_id = run["id"]

        try:
            base_url = self.crawler._normalize_url(website_url)

            # Crawl standard pages
            paths = ["/", "/pricing", "/features", "/about", "/blog", "/docs", "/contact"]
            pages: dict[str, Any] = {}
            for path in paths:
                from urllib.parse import urljoin
                full_url = urljoin(base_url, path)
                try:
                    page = self.crawler.crawl_page(full_url)
                    pages[full_url] = page
                    result.items_fetched += 1
                except Exception as exc:
                    logger.warning("Crawl failed for %s: %s", full_url, exc)
                    result.logs.append(f"Crawl failed for {full_url}: {exc}")

            # Run technical checks on each page
            all_issues: list[TechnicalIssue] = []
            for page_url, page in pages.items():
                if page.error:
                    result.logs.append(f"Page error {page_url}: {page.error}")
                    continue

                try:
                    issues = self.check_html(page, page_url, base_url)
                    all_issues.extend(issues)
                except Exception as exc:
                    logger.warning("Check failed for %s: %s", page_url, exc)
                    result.logs.append(f"Check failed for {page_url}: {exc}")

            # Build opportunities
            opportunities: list[dict] = []
            for issue in all_issues:
                issue_json = json.dumps(
                    {
                        "check": issue.check,
                        "severity": issue.severity,
                        "page": issue.page,
                        "detail": issue.detail,
                        "current_code_snippet": issue.current_code_snippet,
                        "suggested_fix": issue.suggested_fix,
                        "code_snippet": issue.code_snippet,
                        "priority_score": issue.priority_score,
                    },
                    indent=2,
                )
                opportunities.append(
                    {
                        "project_id": project_id,
                        "platform": "technical_seo",
                        "agent_name": "technical_seo",
                        "title": _issue_title(issue),
                        "body": f"{issue.detail}\n\nCurrent:\n```html\n{issue.current_code_snippet}\n```\n\nSuggested fix:\n```html\n{issue.suggested_fix}\n```\n\nFull snippet:\n```html\n{issue.code_snippet}\n```"[:4000],
                        "opportunity_type": "code_issue",
                        "severity": issue.severity,
                        "score": issue.priority_score,
                        "status": "new",
                        "draft_article": issue_json,
                    }
                )

            result.items_kept = len(opportunities)
            result.logs.append(f"Technical SEO audit: {len(all_issues)} issues found on {len(pages)} pages")

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
            logger.exception("TechnicalSEOAgent run failed")
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

    def check_html(self, page: Any, page_url: str, base_url: str) -> list[TechnicalIssue]:
        """Parse HTML and return list of technical issue dicts."""
        issues: list[TechnicalIssue] = []
        if not hasattr(page, "title"):
            return issues

        html_text = ""
        try:
            html_text = self._fetch_raw_html(page_url)
        except Exception as exc:
            logger.warning("Could not fetch raw HTML for %s: %s", page_url, exc)
            return issues

        soup = BeautifulSoup(html_text, "html.parser")
        brand_name = "Brand Name"
        value_prop = "Value Prop"

        # --- Title tag checks ---
        title_tag = soup.find("title")
        if not title_tag or not title_tag.string:
            issues.append(
                TechnicalIssue(
                    check="missing_title",
                    severity="critical",
                    page=page_url,
                    detail="Missing <title> tag",
                    current_code_snippet="<head>\n  <!-- no title -->\n</head>",
                    suggested_fix=f"<title>{brand_name} | {value_prop}</title>",
                    code_snippet=f"<head>\n  <title>{brand_name} | {value_prop}</title>\n</head>",
                    priority_score=95,
                )
            )
        else:
            title_text = title_tag.string.strip()
            if len(title_text) > 60:
                shorter = title_text[:57] + "..."
                issues.append(
                    TechnicalIssue(
                        check="title_too_long",
                        severity="medium",
                        page=page_url,
                        detail=f"Title is {len(title_text)} chars (>60)",
                        current_code_snippet=f"<title>{title_text}</title>",
                        suggested_fix=f"<title>{shorter}</title>",
                        code_snippet=f"<head>\n  <title>{shorter}</title>\n</head>",
                        priority_score=60,
                    )
                )

        # --- Meta description checks ---
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if not meta_desc or not meta_desc.get("content"):
            issues.append(
                TechnicalIssue(
                    check="missing_meta_description",
                    severity="high",
                    page=page_url,
                    detail="Missing <meta name=\"description\">",
                    current_code_snippet="<head>\n  <!-- no meta description -->\n</head>",
                    suggested_fix='<meta name="description" content=" compelling description here " />',
                    code_snippet='<head>\n  <meta name="description" content="Compelling description here" />\n</head>',
                    priority_score=80,
                )
            )
        else:
            desc_text = meta_desc.get("content", "").strip()
            if len(desc_text) > 160:
                issues.append(
                    TechnicalIssue(
                        check="meta_description_too_long",
                        severity="low",
                        page=page_url,
                        detail=f"Meta description is {len(desc_text)} chars (>160)",
                        current_code_snippet=f'<meta name="description" content="{desc_text}" />',
                        suggested_fix=f'<meta name="description" content="{desc_text[:157]}..." />',
                        code_snippet="<head>\n  ...\n</head>",
                        priority_score=40,
                    )
                )

        # --- H1 checks ---
        h1_tags = soup.find_all("h1")
        if not h1_tags:
            issues.append(
                TechnicalIssue(
                    check="missing_h1",
                    severity="critical",
                    page=page_url,
                    detail="Missing H1 tag",
                    current_code_snippet="<body>\n  <!-- no h1 -->\n</body>",
                    suggested_fix="<h1>Primary Page Heading</h1>",
                    code_snippet="<body>\n  <h1>Primary Page Heading</h1>\n</body>",
                    priority_score=95,
                )
            )
        elif len(h1_tags) > 1:
            issues.append(
                TechnicalIssue(
                    check="multiple_h1",
                    severity="medium",
                    page=page_url,
                    detail=f"Multiple H1 tags ({len(h1_tags)})",
                    current_code_snippet="\n".join(str(h) for h in h1_tags[:2]),
                    suggested_fix="Use only one <h1> per page; convert extras to <h2>",
                    code_snippet="<body>\n  <h1>Primary Heading</h1>\n  <h2>Secondary Heading</h2>\n</body>",
                    priority_score=60,
                )
            )

        # --- Alt attributes ---
        imgs = soup.find_all("img")
        missing_alt = [str(img) for img in imgs if not img.get("alt")]
        if missing_alt:
            issues.append(
                TechnicalIssue(
                    check="missing_alt_text",
                    severity="medium",
                    page=page_url,
                    detail=f"{len(missing_alt)} images missing alt attributes",
                    current_code_snippet=missing_alt[0],
                    suggested_fix='<img src="..." alt="descriptive text" />',
                    code_snippet="<img src=\"image.jpg\" alt=\"Descriptive text about the image\" />",
                    priority_score=60,
                )
            )

        # --- Canonical checks ---
        canonical = soup.find("link", rel="canonical")
        if not canonical or not canonical.get("href"):
            issues.append(
                TechnicalIssue(
                    check="missing_canonical",
                    severity="medium",
                    page=page_url,
                    detail="Missing canonical link",
                    current_code_snippet="<head>\n  <!-- no canonical -->\n</head>",
                    suggested_fix=f'<link rel="canonical" href="{page_url}" />',
                    code_snippet=f'<head>\n  <link rel="canonical" href="{page_url}" />\n</head>',
                    priority_score=60,
                )
            )
        else:
            canonical_url = canonical.get("href", "").strip()
            parsed_canonical = urlparse(canonical_url)
            parsed_base = urlparse(base_url)
            if parsed_canonical.netloc and parsed_canonical.netloc != parsed_base.netloc:
                issues.append(
                    TechnicalIssue(
                        check="bad_canonical",
                        severity="high",
                        page=page_url,
                        detail=f"Canonical points to different domain: {canonical_url}",
                        current_code_snippet=f'<link rel="canonical" href="{canonical_url}" />',
                        suggested_fix=f'<link rel="canonical" href="{page_url}" />',
                        code_snippet=f'<head>\n  <link rel="canonical" href="{page_url}" />\n</head>',
                        priority_score=80,
                    )
                )

        # --- Open Graph tags ---
        og_tags = {
            tag.get("property", "").strip(): tag.get("content", "").strip()
            for tag in soup.find_all("meta", property=lambda x: x and x.startswith("og:"))
        }
        if not og_tags:
            issues.append(
                TechnicalIssue(
                    check="missing_og_tags",
                    severity="low",
                    page=page_url,
                    detail="Missing Open Graph tags",
                    current_code_snippet="<head>\n  <!-- no OG tags -->\n</head>",
                    suggested_fix='<meta property="og:title" content="..." />\n<meta property="og:description" content="..." />\n<meta property="og:image" content="..." />',
                    code_snippet='<head>\n  <meta property="og:title" content="Page Title" />\n  <meta property="og:description" content="Description" />\n  <meta property="og:image" content="https://example.com/image.jpg" />\n</head>',
                    priority_score=40,
                )
            )

        # --- Twitter Card tags ---
        twitter_tags = [
            tag for tag in soup.find_all("meta", attrs={"name": lambda x: x and x.startswith("twitter:")})
        ]
        if not twitter_tags:
            issues.append(
                TechnicalIssue(
                    check="missing_twitter_cards",
                    severity="low",
                    page=page_url,
                    detail="Missing Twitter Card tags",
                    current_code_snippet="<head>\n  <!-- no Twitter Cards -->\n</head>",
                    suggested_fix='<meta name="twitter:card" content="summary_large_image" />\n<meta name="twitter:title" content="..." />',
                    code_snippet='<head>\n  <meta name="twitter:card" content="summary_large_image" />\n  <meta name="twitter:title" content="Page Title" />\n</head>',
                    priority_score=40,
                )
            )

        # --- Viewport meta ---
        viewport = soup.find("meta", attrs={"name": "viewport"})
        if not viewport:
            issues.append(
                TechnicalIssue(
                    check="missing_viewport",
                    severity="medium",
                    page=page_url,
                    detail="Missing viewport meta tag (mobile SEO)",
                    current_code_snippet="<head>\n  <!-- no viewport -->\n</head>",
                    suggested_fix='<meta name="viewport" content="width=device-width, initial-scale=1" />',
                    code_snippet='<head>\n  <meta name="viewport" content="width=device-width, initial-scale=1" />\n</head>',
                    priority_score=60,
                )
            )

        # --- Lang attribute ---
        html_tag = soup.find("html")
        if html_tag and not html_tag.get("lang"):
            issues.append(
                TechnicalIssue(
                    check="missing_lang",
                    severity="low",
                    page=page_url,
                    detail="Missing lang attribute on <html>",
                    current_code_snippet="<html>\n  ...\n</html>",
                    suggested_fix='<html lang="en">',
                    code_snippet='<html lang="en">\n  ...\n</html>',
                    priority_score=40,
                )
            )

        # --- Inline CSS/JS blocking rendering ---
        inline_styles = soup.find_all("style")
        if inline_styles:
            issues.append(
                TechnicalIssue(
                    check="inline_css",
                    severity="medium",
                    page=page_url,
                    detail="Inline <style> blocks may block rendering",
                    current_code_snippet="<style>\n  /* inline styles */\n</style>",
                    suggested_fix='<link rel="stylesheet" href="/styles.css" />',
                    code_snippet='<head>\n  <link rel="stylesheet" href="/styles.css" />\n</head>',
                    priority_score=60,
                )
            )

        # --- HTTPS / Mixed content ---
        if page_url.startswith("http://"):
            issues.append(
                TechnicalIssue(
                    check="no_https",
                    severity="high",
                    page=page_url,
                    detail="Page served over HTTP, no HTTPS redirect",
                    current_code_snippet="http://example.com/",
                    suggested_fix="Redirect HTTP to HTTPS via server config or HSTS",
                    code_snippet="https://example.com/",
                    priority_score=80,
                )
            )

        if page_url.startswith("https://"):
            http_resources = soup.find_all(
                src=lambda x: x and x.startswith("http://")
            ) + soup.find_all(href=lambda x: x and x.startswith("http://"))
            if http_resources:
                issues.append(
                    TechnicalIssue(
                        check="mixed_content",
                        severity="high",
                        page=page_url,
                        detail="Mixed content: HTTP resources on HTTPS page",
                        current_code_snippet=str(http_resources[0]),
                        suggested_fix='Change src/href to "https://..." or relative path',
                        code_snippet='<img src="https://example.com/image.jpg" />',
                        priority_score=80,
                    )
                )

        # --- Robots meta ---
        robots_meta = soup.find("meta", attrs={"name": "robots"})
        if not robots_meta:
            issues.append(
                TechnicalIssue(
                    check="missing_robots_meta",
                    severity="low",
                    page=page_url,
                    detail="Missing robots meta tag",
                    current_code_snippet="<head>\n  <!-- no robots meta -->\n</head>",
                    suggested_fix='<meta name="robots" content="index, follow" />',
                    code_snippet='<head>\n  <meta name="robots" content="index, follow" />\n</head>',
                    priority_score=40,
                )
            )
        else:
            content = robots_meta.get("content", "").lower()
            if "noindex" in content:
                issues.append(
                    TechnicalIssue(
                        check="noindex_on_important",
                        severity="high",
                        page=page_url,
                        detail="noindex on important page",
                        current_code_snippet=f'<meta name="robots" content="{robots_meta.get("content", "")}" />',
                        suggested_fix='<meta name="robots" content="index, follow" />',
                        code_snippet='<head>\n  <meta name="robots" content="index, follow" />\n</head>',
                        priority_score=80,
                    )
                )

        # --- Structured data ---
        scripts = soup.find_all("script", type="application/ld+json")
        if not scripts:
            issues.append(
                TechnicalIssue(
                    check="missing_structured_data",
                    severity="medium",
                    page=page_url,
                    detail="Missing structured data (schema.org JSON-LD)",
                    current_code_snippet="<head>\n  <!-- no JSON-LD -->\n</head>",
                    suggested_fix='<script type="application/ld+json">\n{\n  "@context": "https://schema.org",\n  "@type": "Organization",\n  "name": "..."\n}\n</script>',
                    code_snippet='<script type="application/ld+json">\n{\n  "@context": "https://schema.org",\n  "@type": "Organization",\n  "name": "Brand"\n}\n</script>',
                    priority_score=60,
                )
            )
        else:
            for script in scripts:
                if script.string:
                    try:
                        json.loads(script.string)
                    except json.JSONDecodeError:
                        issues.append(
                            TechnicalIssue(
                                check="bad_json_ld",
                                severity="medium",
                                page=page_url,
                                detail="Bad JSON-LD structured data",
                                current_code_snippet=script.string[:200],
                                suggested_fix='Validate JSON-LD at https://validator.schema.org/',
                                code_snippet='<script type="application/ld+json">\n{ valid json }\n</script>',
                                priority_score=60,
                            )
                        )
                        break

        # --- hreflang (if multilingual hints) ---
        hreflang_links = soup.find_all("link", rel="alternate", hreflang=True)
        if not hreflang_links and ("/en/" in page_url or "/fr/" in page_url or "/es/" in page_url):
                issues.append(
                    TechnicalIssue(
                        check="missing_hreflang",
                        severity="low",
                        page=page_url,
                        detail="Missing hreflang tags for multilingual page",
                        current_code_snippet="<head>\n  <!-- no hreflang -->\n</head>",
                        suggested_fix='<link rel="alternate" hreflang="en" href="..." />',
                        code_snippet='<head>\n  <link rel="alternate" hreflang="en" href="https://example.com/en/" />\n</head>',
                        priority_score=40,
                    )
                )

        return issues

    def _fetch_raw_html(self, url: str) -> str:
        """Fetch raw HTML for technical analysis."""
        return self.crawler._fetch_html(url)


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


def _issue_title(issue: TechnicalIssue) -> str:
    mapping = {
        "missing_title": "Missing <title> tag",
        "title_too_long": "Title too long",
        "missing_meta_description": "Missing meta description",
        "meta_description_too_long": "Meta description too long",
        "missing_h1": "Missing H1 tag",
        "multiple_h1": "Multiple H1 tags",
        "missing_alt_text": "Images missing alt text",
        "missing_canonical": "Missing canonical link",
        "bad_canonical": "Bad canonical URL",
        "missing_og_tags": "Missing Open Graph tags",
        "missing_twitter_cards": "Missing Twitter Card tags",
        "missing_viewport": "Missing viewport meta (mobile)",
        "missing_lang": "Missing lang attribute",
        "inline_css": "Inline CSS/JS blocking rendering",
        "no_https": "No HTTPS redirect",
        "mixed_content": "Mixed content (HTTP on HTTPS)",
        "missing_robots_meta": "Missing robots meta",
        "noindex_on_important": "Noindex on important page",
        "missing_structured_data": "Missing structured data",
        "bad_json_ld": "Bad JSON-LD structured data",
        "missing_hreflang": "Missing hreflang tags",
    }
    return mapping.get(issue.check, issue.check)
