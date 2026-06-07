"""Brand Brain — builds complete intelligence profiles from company websites or manual input."""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from app.db.tables.company import update_company
from app.services.infrastructure.llm.service import LLMService
from app.services.product.brand_brain_crawler import BrandBrainCrawler
from app.services.product.copilot.analyzer import WebsiteAnalyzer
from app.services.product.copilot.inference import infer_business_domain
from app.services.product.keyword_expansion import KeywordExpansionService

logger = logging.getLogger(__name__)

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he", "in",
    "is", "it", "its", "of", "on", "that", "the", "to", "was", "will", "with", "you",
    "your", "we", "our", "us", "this", "these", "those", "they", "them", "their", "or",
    "but", "not", "can", "could", "would", "should", "may", "might", "must", "shall",
    "have", "had", "been", "being", "do", "does", "did", "done", "get", "got", "go",
    "going", "went", "about", "above", "across", "after", "against", "along", "among",
    "around", "before", "behind", "below", "beneath", "beside", "between", "beyond",
    "down", "during", "except", "inside", "into", "near", "off", "onto", "outside",
    "over", "since", "through", "throughout", "till", "toward", "under", "until", "up",
    "upon", "within", "without",
}

_TONE_WORDS = {
    "professional": {"professional", "enterprise", "business", "corporate", "official", "trusted", "reliable"},
    "casual": {"casual", "simple", "easy", "fun", "friendly", "relaxed", "laid-back"},
    "technical": {"technical", "advanced", "api", "integration", "infrastructure", "scalable", "robust", "developer"},
    "friendly": {"friendly", "welcome", "happy", "helpful", "warm", "personal", "human"},
    "luxury": {"luxury", "premium", "exclusive", "elite", "high-end", "sophisticated"},
    "playful": {"playful", "fun", "creative", "colorful", "bold", "exciting"},
}


class BrandBrain:
    """Analyzes a company and builds a complete intelligence profile."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm = llm_service or LLMService()
        self.crawler = BrandBrainCrawler(rate_limit_seconds=1.0)
        self.analyzer = WebsiteAnalyzer()
        self.keyword_service = KeywordExpansionService()

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 15]

    @staticmethod
    def _extract_meaningful_keywords(text: str, top_n: int = 15) -> list[str]:
        """Extract most frequent meaningful keywords from text."""
        words = re.findall(r'\b[a-z]{3,}\b', text.lower())
        filtered = [w for w in words if w not in _STOP_WORDS and not w.isdigit()]
        counts = Counter(filtered)
        # Prefer longer, more specific terms; bigrams boost score
        scored: dict[str, float] = {}
        for word, count in counts.most_common(top_n * 3):
            score = count
            if len(word) >= 6:
                score += 1
            scored[word] = score
        sorted_words = sorted(scored.items(), key=lambda x: x[1], reverse=True)
        return [word for word, _ in sorted_words[:top_n]]

    @staticmethod
    def _detect_tone(text: str) -> str:
        """Detect tone of voice from word choice."""
        words = set(re.findall(r'\b[a-z]+\b', text.lower()))
        scores: dict[str, int] = {}
        for tone, markers in _TONE_WORDS.items():
            scores[tone] = len(words & markers)
        best = max(scores, key=lambda k: scores[k])
        if scores[best] > 0:
            return best
        # Default heuristic
        if any(w in words for w in {"api", "developer", "technical", "integration", "sdk"}):
            return "technical"
        if any(w in words for w in {"simple", "easy", "casual", "fun"}):
            return "casual"
        return "professional"

    def _heuristic_extraction(self, corpus: str) -> dict[str, Any]:
        """Extract structured intelligence without LLM."""
        sentences = self._split_sentences(corpus)

        # product_summary: first substantial paragraph
        product_summary = sentences[0] if sentences else corpus[:300]
        if len(product_summary) > 280:
            product_summary = product_summary[:277] + "..."

        # icp: sentences mentioning "for" or "target" or audience
        icp_phrases: list[str] = []
        for s in sentences:
            lowered = s.lower()
            if any(k in lowered for k in (" for ", "target audience", "ideal for", "designed for", "perfect for")):
                icp_phrases.append(s)
        icp = " ".join(icp_phrases[:2]) if icp_phrases else "Business professionals and teams"
        if len(icp) > 280:
            icp = icp[:277] + "..."

        # key_benefits
        benefit_keywords = {"helps", "enable", "enables", "allows", "saves", "improve", "improves", "boost", "boosts", "increase", "increases", "reduce", "reduces"}
        benefits: list[str] = []
        for s in sentences:
            if any(kw in s.lower() for kw in benefit_keywords):
                clean = s.strip()
                if clean and clean not in benefits:
                    benefits.append(clean)
        key_benefits = benefits[:5] or ["Saves time and resources", "Improves efficiency", "Easy to use"]

        # pain_points_solved
        pain_keywords = {"without", "no more", "eliminate", "eliminates", "reduce", "reduces", "avoid", "avoiding", "prevent", "prevents", "stop", "stops"}
        pain_points: list[str] = []
        for s in sentences:
            if any(kw in s.lower() for kw in pain_keywords):
                clean = s.strip()
                if clean and clean not in pain_points:
                    pain_points.append(clean)
        pain_points_solved = pain_points[:5] or ["Reduces manual work", "Prevents common errors", "Eliminates bottlenecks"]

        # competitors
        competitor_keywords = {"alternative to", "vs", "versus", "compared to", "unlike", "better than"}
        competitors: list[str] = []
        for s in sentences:
            lowered = s.lower()
            if any(kw in lowered for kw in competitor_keywords):
                # Try to extract capitalized words after comparison terms
                match = re.search(r'(?:alternative to|vs\.?|versus|compared to|unlike|better than)\s+([A-Z][A-Za-z0-9]+)', s)
                if match:
                    competitors.append(match.group(1))
        competitors = list(dict.fromkeys(competitors))[:5]

        # industry
        industry = infer_business_domain(corpus[:1000], product_summary)

        # common_keywords
        common_keywords = self._extract_meaningful_keywords(corpus, top_n=15)

        # tone_of_voice
        tone_of_voice = self._detect_tone(corpus)

        return {
            "product_summary": product_summary,
            "icp": icp,
            "key_benefits": key_benefits,
            "pain_points_solved": pain_points_solved,
            "competitors": competitors,
            "industry": industry,
            "common_keywords": common_keywords,
            "tone_of_voice": tone_of_voice,
        }

    def _llm_extraction(self, corpus: str, brand_name: str) -> dict[str, Any] | None:
        """Use LLM to extract structured intelligence from website corpus."""
        system_prompt = (
            "You are a market intelligence analyst. Extract structured data about a company from its website text. "
            "Return ONLY valid JSON with these keys:\n"
            "  product_summary: 2-3 sentence summary of what the product does\n"
            "  icp: ideal customer profile (who uses this product)\n"
            "  key_benefits: list of 3-5 top benefits\n"
            "  pain_points_solved: list of 3-5 pain points the product addresses\n"
            "  competitors: list of competitor names mentioned\n"
            "  industry: detected industry/category\n"
            "  common_keywords: 10-15 most frequent meaningful keywords\n"
            "  tone_of_voice: detected tone (professional, casual, technical, friendly, luxury, playful)\n"
            "Be concise and factual."
        )
        try:
            result = self.llm.call_json(system_prompt, corpus[:12000], temperature=0.2)
            if not result or not isinstance(result, dict):
                return None
            return {
                "product_summary": result.get("product_summary", ""),
                "icp": result.get("icp", result.get("target_audience", "")),
                "key_benefits": _to_list(result.get("key_benefits")),
                "pain_points_solved": _to_list(result.get("pain_points_solved")),
                "competitors": _to_list(result.get("competitors")),
                "industry": result.get("industry", result.get("business_domain", "")),
                "common_keywords": _to_list(result.get("common_keywords")),
                "tone_of_voice": result.get("tone_of_voice", ""),
            }
        except Exception:
            logger.exception("LLM extraction failed")
            return None

    def analyze_website(self, website_url: str, company_profile: dict[str, Any], db: Any) -> dict[str, Any]:
        """Crawl website and extract complete intelligence profile.

        Args:
            website_url: The company website URL.
            company_profile: Existing company profile dict from DB.
            db: Supabase client.

        Returns:
            Updated company profile dict.
        """
        company_id = company_profile.get("id")
        if not company_id:
            raise ValueError("company_profile must contain 'id'")

        # Step 1: Use existing WebsiteAnalyzer for homepage
        logger.info("Analyzing homepage for %s", website_url)
        try:
            homepage_analysis = self.analyzer.analyze_website(website_url)
        except Exception:
            logger.exception("Homepage analysis failed for %s", website_url)
            homepage_analysis = None

        # Step 2: Crawl additional pages
        logger.info("Crawling additional pages for %s", website_url)
        pages = self.crawler.crawl_site(website_url)
        corpus = self.crawler.build_corpus(pages)

        # Merge homepage analysis text into corpus
        homepage_text = ""
        if homepage_analysis:
            homepage_text = " ".join(
                str(v) for v in [
                    homepage_analysis.brand_name,
                    homepage_analysis.summary,
                    homepage_analysis.product_summary,
                    homepage_analysis.target_audience,
                    homepage_analysis.voice_notes,
                    homepage_analysis.business_domain,
                ] if v
            )
        full_corpus = f"{homepage_text} {corpus}".strip()
        if not full_corpus:
            logger.warning("Empty corpus for %s; cannot extract intelligence.", website_url)
            return company_profile

        # Step 3: Extract structured data
        brand_name = company_profile.get("name") or (
            homepage_analysis.brand_name if homepage_analysis else ""
        )

        is_llm = self.llm.provider_name != "template"
        extracted = self._llm_extraction(full_corpus, brand_name) if is_llm else None

        if not extracted:
            logger.info("Using heuristic extraction for %s (LLM=%s)", website_url, is_llm)
            extracted = self._heuristic_extraction(full_corpus)

        # Step 4: Update company profile in DB
        update_data: dict[str, Any] = {
            "extracted_summary": extracted.get("product_summary", "")[:4000],
            "extracted_keywords": ", ".join(extracted.get("common_keywords", []))[:4000],
            "extracted_pain_points": ", ".join(extracted.get("pain_points_solved", []))[:4000],
            "extracted_competitors": ", ".join(extracted.get("competitors", []))[:4000],
        }

        # Update fields if empty in current profile
        for field_name, extracted_value in [
            ("category", extracted.get("industry", "")),
            ("target_audience", extracted.get("icp", "")),
            ("brand_voice", extracted.get("tone_of_voice", "")),
        ]:
            if not company_profile.get(field_name) and extracted_value:
                update_data[field_name] = str(extracted_value)[:4000] if isinstance(extracted_value, str) else str(extracted_value)[:4000]

        # Update benefits/pain_points/features if empty
        if not company_profile.get("benefits") and extracted.get("key_benefits"):
            update_data["benefits"] = ", ".join(extracted["key_benefits"])[:4000]
        if not company_profile.get("pain_points") and extracted.get("pain_points_solved"):
            update_data["pain_points"] = ", ".join(extracted["pain_points_solved"])[:4000]
        if not company_profile.get("competitors") and extracted.get("competitors"):
            update_data["competitors"] = ", ".join(extracted["competitors"])[:4000]

        # Merge into profile dict
        merged_profile = {**company_profile, **update_data}
        for k, v in update_data.items():
            company_profile[k] = v

        # Persist to DB
        try:
            updated = update_company(db, company_id, update_data)
            if updated:
                merged_profile = updated
                logger.info("Updated company profile %s with extracted intelligence", company_id)
        except Exception:
            logger.exception("Failed to update company profile %s", company_id)

        # Step 5: Auto-expand keywords
        try:
            self._auto_expand_keywords(merged_profile, db)
        except Exception:
            logger.exception("Keyword expansion failed for company %s", company_id)

        return merged_profile

    def build_profile_from_input(self, data: dict[str, Any], db: Any | None = None) -> dict[str, Any]:
        """Create a company profile from manual input without website crawling.

        Args:
            data: Dict with keys: name, website_url, description, category,
                  target_audience, features, benefits, pain_points,
                  competitors, geography, brand_voice, language.
            db: Optional Supabase client to store the record.

        Returns:
            The created or updated company profile dict.
        """
        required = {"name"}
        missing = required - set(data.keys())
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        profile_data = {
            "name": data["name"],
            "website_url": data.get("website_url"),
            "description": data.get("description"),
            "category": data.get("category"),
            "target_audience": data.get("target_audience"),
            "features": data.get("features"),
            "benefits": data.get("benefits"),
            "pain_points": data.get("pain_points"),
            "competitors": data.get("competitors"),
            "geography": data.get("geography"),
            "brand_voice": data.get("brand_voice"),
            "language": data.get("language", "en"),
        }

        # Clean up empty strings to None
        for k, v in list(profile_data.items()):
            if isinstance(v, str) and not v.strip():
                profile_data[k] = None
            elif isinstance(v, list):
                profile_data[k] = ", ".join(str(i) for i in v)

        if db is not None:
            from app.db.tables.company import create_company
            created = create_company(db, profile_data)
            profile_data = created
            logger.info("Created company profile %s from manual input", created.get("id"))

            # Auto-expand keywords
            try:
                self._auto_expand_keywords(profile_data, db)
            except Exception:
                logger.exception("Keyword expansion failed for new company %s", created.get("id"))

        return profile_data

    def _auto_expand_keywords(self, company_profile: dict[str, Any], db: Any) -> None:
        """Run keyword expansion and store results."""
        company_id = company_profile.get("id")
        if not company_id:
            return

        keywords = self.keyword_service.expand(company_profile)
        if not keywords:
            return

        try:
            self.keyword_service.store_keywords(db, company_id, keywords)
            logger.info("Stored %s keywords for company %s", len(keywords), company_id)
        except Exception:
            logger.exception("Failed to store keywords for company %s", company_id)


def _to_list(value: Any) -> list[str]:
    """Coerce a value to a list of strings."""
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(value)]
