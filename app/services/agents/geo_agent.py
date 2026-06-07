"""GEO Agent — Generative Engine Optimization / AI Search Visibility."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

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
class CrawledPage:
    url: str
    title: str = ""
    meta_description: str = ""
    headings: list[str] = field(default_factory=list)
    content: str = ""
    has_schema: bool = False
    status_code: int | None = None
    error: str | None = None


class GEOAgent:
    """GEO (Generative Engine Optimization) agent."""

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

    def _fetch_page(self, url: str) -> CrawledPage:
        page = CrawledPage(url=url)
        try:
            self._sleep_if_needed()
            with httpx.Client(timeout=25.0, follow_redirects=True) as client:
                resp = client.get(url, headers=_DEFAULT_HEADERS)
                resp.raise_for_status()
                page.status_code = 200
                soup = BeautifulSoup(resp.text, "html.parser")

                if soup.title and soup.title.string:
                    page.title = soup.title.string.strip()

                meta_desc = soup.find("meta", attrs={"name": "description"})
                if meta_desc and meta_desc.get("content"):
                    page.meta_description = meta_desc.get("content").strip()

                page.headings = [
                    h.get_text(" ", strip=True)
                    for h in soup.find_all(["h1", "h2", "h3"])
                    if h.get_text(strip=True)
                ]

                page.content = soup.get_text(separator=" ", strip=True)
                page.has_schema = bool(soup.find("script", type="application/ld+json"))
        except httpx.HTTPStatusError as exc:
            page.status_code = exc.response.status_code
            page.error = f"HTTP {exc.response.status_code}"
        except httpx.HTTPError as exc:
            page.error = str(exc)
        except Exception as exc:
            page.error = str(exc)
        return page

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

        brand_keywords = list_brand_keywords_for_company(db, company_id, enabled_only=True)

        run = create_agent_run(
            db,
            {
                "company_id": company_id,
                "agent_name": "geo",
                "status": "running",
                "started_at": started_at.isoformat(),
            },
        )
        run_id = run["id"]

        try:
            website_url = company.get("website_url")
            base_url = self._normalize_url(website_url) if website_url else ""

            pages: list[CrawledPage] = []
            if base_url:
                paths = [
                    "/",
                    "/pricing",
                    "/features",
                    "/about",
                    "/blog",
                    "/docs",
                    "/compare",
                    "/alternatives",
                    "/faq",
                    "/use-cases",
                ]
                for path in paths:
                    full_url = urljoin(base_url, path)
                    page = self._fetch_page(full_url)
                    pages.append(page)
                    result.items_fetched += 1

            # Generate target questions
            questions = self._generate_target_questions(company, brand_keywords)
            result.logs.append(f"Generated {len(questions)} target questions")

            # Check website coverage
            coverage = self._check_coverage(questions, pages)

            # Check AI visibility readiness
            readiness = self._check_readiness(pages, company)

            # Build opportunities
            opportunities: list[dict] = []

            # Visibility gaps
            for q in questions:
                q_coverage = coverage["question_map"].get(q["question"], 0)
                if q_coverage < 50:
                    gap = 100 - q_coverage
                    opportunities.append(
                        {
                            "project_id": project_id,
                            "platform": "geo",
                            "agent_name": "geo",
                            "title": f"Visibility gap: {q['question']}",
                            "body": (
                                f"Target question: {q['question']}\n"
                                f"Coverage: {q_coverage}%\n"
                                f"Recommended: {q.get('recommended_page', 'Create a dedicated page')}"
                            ),
                            "opportunity_type": "visibility_gap",
                            "severity": "high" if gap > 70 else "medium",
                            "score": gap,
                            "status": "new",
                        }
                    )

            # Readiness gaps
            for check_name, check_data in readiness["checks"].items():
                if check_data["score"] < 60:
                    opportunities.append(
                        {
                            "project_id": project_id,
                            "platform": "geo",
                            "agent_name": "geo",
                            "title": f"AI readiness gap: {check_name}",
                            "body": f"Score: {check_data['score']}/100\nDetails: {check_data['detail']}",
                            "opportunity_type": "visibility_gap",
                            "severity": "medium",
                            "score": 100 - check_data["score"],
                            "status": "new",
                        }
                    )

            # Content suggestions
            suggestions = [
                ("comparison page", "Create a comparison page (e.g., 'vs competitors')"),
                ("alternatives page", "Create an alternatives page"),
                ("use-case landing page", "Create use-case landing pages"),
                ("FAQ section", "Add a comprehensive FAQ section"),
                ("glossary page", "Create a glossary page for industry terms"),
                ("customer problem page", "Create pages addressing specific customer problems"),
                ("integration page", "Create integration/pages showing ecosystem"),
                ("llms.txt", "Add an llms.txt file for AI crawlers"),
                ("structured data", "Enhance structured data for AI understanding"),
            ]
            for sug_type, sug_desc in suggestions:
                opportunities.append(
                    {
                        "project_id": project_id,
                        "platform": "geo",
                        "agent_name": "geo",
                        "title": f"GEO suggestion: {sug_type}",
                        "body": sug_desc,
                        "opportunity_type": "visibility_gap",
                        "severity": "medium",
                        "score": 55,
                        "status": "new",
                    }
                )

            result.items_kept = len(opportunities)
            result.logs.append(f"GEO audit: {len(opportunities)} opportunities generated")

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
            logger.exception("GEOAgent run failed")
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

    @staticmethod
    def _generate_target_questions(company: dict, brand_keywords: list[dict]) -> list[dict]:
        questions: list[dict] = []
        category = company.get("category", "")
        pain_points = _jsonb_to_list(company.get("pain_points"))
        competitors = _jsonb_to_list(company.get("competitors"))
        target_audience = company.get("target_audience", "")
        name = company.get("name", "")

        if category:
            questions.append({"question": f"best {category} tools", "recommended_page": "Comparison page"})
            questions.append(
                {"question": f"{category} software comparison", "recommended_page": "Comparison page"}
            )

        for pp in pain_points[:3]:
            questions.append({"question": f"how to solve {pp}", "recommended_page": "Problem/solution page"})

        for comp in competitors[:3]:
            questions.append({"question": f"alternatives to {comp}", "recommended_page": "Alternatives page"})

        if target_audience:
            questions.append({"question": f"tools for {target_audience}", "recommended_page": "Use-case page"})

        if name:
            questions.append({"question": f"what is {name}", "recommended_page": "About page"})

        for kw in brand_keywords[:5]:
            term = kw.get("keyword", "")
            if term:
                questions.append({"question": f"how to use {term}", "recommended_page": "Feature page"})

        return questions[:15]

    @staticmethod
    def _check_coverage(questions: list[dict], pages: list[CrawledPage]) -> dict:
        covered = 0
        question_map: dict[str, int] = {}
        for q in questions:
            question = q["question"].lower()
            key_phrases = question.split()
            best_match = 0
            for page in pages:
                if page.error:
                    continue
                text = f"{page.title} {page.meta_description} {page.content}".lower()
                matches = sum(1 for phrase in key_phrases if phrase in text)
                pct = int((matches / len(key_phrases)) * 100) if key_phrases else 0
                if pct > best_match:
                    best_match = pct
            question_map[q["question"]] = best_match
            if best_match >= 50:
                covered += 1

        total = len(questions) or 1
        score = int((covered / total) * 100)
        return {"score": score, "question_map": question_map}

    @staticmethod
    def _check_readiness(pages: list[CrawledPage], company: dict) -> dict:
        checks: dict[str, dict] = {}

        all_text = " ".join(
            f"{p.title} {p.meta_description} {' '.join(p.headings)} {p.content}"
            for p in pages
            if not p.error
        ).lower()

        # Homepage clarity
        homepage = next(
            (
                p
                for p in pages
                if p.url.rstrip("/").endswith("/") or p.url.endswith("/")
            ),
            None,
        )
        if homepage and homepage.title and company.get("name", "").lower() in homepage.title.lower():
            checks["homepage_clarity"] = {
                "score": 80,
                "detail": "Homepage includes brand name in title",
            }
        else:
            checks["homepage_clarity"] = {
                "score": 40,
                "detail": "Homepage may lack clear product positioning",
            }

        # Comparison pages
        if " vs " in all_text or "compare" in all_text or "alternative" in all_text:
            checks["comparison_pages"] = {"score": 75, "detail": "Comparison content found"}
        else:
            checks["comparison_pages"] = {"score": 20, "detail": "No comparison pages detected"}

        # FAQ pages
        if "faq" in all_text or "frequently asked" in all_text:
            checks["faq_pages"] = {"score": 80, "detail": "FAQ content found"}
        else:
            checks["faq_pages"] = {"score": 30, "detail": "No FAQ pages detected"}

        # Use-case pages
        if "use case" in all_text or " for " in all_text:
            checks["use_case_pages"] = {"score": 70, "detail": "Use-case content found"}
        else:
            checks["use_case_pages"] = {"score": 30, "detail": "No use-case pages detected"}

        # Schema markup
        schema_found = any(p.has_schema for p in pages if not p.error)
        if schema_found:
            checks["schema_markup"] = {"score": 80, "detail": "Schema markup detected"}
        else:
            checks["schema_markup"] = {"score": 20, "detail": "No schema markup detected"}

        # Credibility signals
        if "about" in all_text and "contact" in all_text:
            checks["credibility_signals"] = {
                "score": 80,
                "detail": "About and contact pages found",
            }
        else:
            checks["credibility_signals"] = {
                "score": 40,
                "detail": "Missing about or contact info",
            }

        # Pricing/features
        if "pricing" in all_text or "features" in all_text:
            checks["pricing_features"] = {
                "score": 80,
                "detail": "Pricing or features content found",
            }
        else:
            checks["pricing_features"] = {
                "score": 30,
                "detail": "No pricing/features pages detected",
            }

        # Docs/help
        if "docs" in all_text or "help" in all_text or "documentation" in all_text:
            checks["docs_help"] = {"score": 80, "detail": "Documentation/help content found"}
        else:
            checks["docs_help"] = {"score": 30, "detail": "No docs/help pages detected"}

        scores = [c["score"] for c in checks.values()]
        overall = int(sum(scores) / len(scores)) if scores else 0
        return {"overall_score": overall, "checks": checks}


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


def _jsonb_to_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []
