"""Route aggregator for /v1 API.

Each domain router lives in its own module under this package.
"""

from fastapi import APIRouter

from app.api.v1.routes.agents import router as agents_router
from app.api.v1.routes.amplify import router as amplify_router
from app.api.v1.routes.analytics import router as analytics_router
from app.api.v1.routes.analytics_v2 import router as analytics_v2_router
from app.api.v1.routes.articles import router as articles_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.auto_pipeline import router as auto_pipeline_router
from app.api.v1.routes.auto_pipeline_v2 import router as auto_pipeline_v2_router
from app.api.v1.routes.billing import router as billing_router
from app.api.v1.routes.brands import router as brands_router
from app.api.v1.routes.campaigns import router as campaigns_router
from app.api.v1.routes.citations import router as citations_router
from app.api.v1.routes.company import router as company_router
from app.api.v1.routes.competitors import router as competitors_router
from app.api.v1.routes.discovery import router as discovery_router
from app.api.v1.routes.drafts import router as drafts_router
from app.api.v1.routes.feed import router as feed_router
from app.api.v1.routes.feedback import router as feedback_router
from app.api.v1.routes.geo import router as geo_router
from app.api.v1.routes.invitations import router as invitations_router
from app.api.v1.routes.links import public_router as links_public_router
from app.api.v1.routes.links import router as links_router
from app.api.v1.routes.manual_import import router as manual_import_router
from app.api.v1.routes.notifications import router as notifications_router
from app.api.v1.routes.opportunities import router as opportunities_router
from app.api.v1.routes.personas import router as personas_router
from app.api.v1.routes.projects import router as projects_router
from app.api.v1.routes.prompts import router as prompts_router
from app.api.v1.routes.reddit_posting import router as reddit_posting_router
from app.api.v1.routes.scans import router as scans_router
from app.api.v1.routes.secrets import router as secrets_router
from app.api.v1.routes.seo import router as seo_router
from app.api.v1.routes.sources import router as sources_router
from app.api.v1.routes.technical_seo import router as technical_seo_router
from app.api.v1.routes.ugc import router as ugc_router
from app.api.v1.routes.user_keys import router as user_keys_router
from app.api.v1.routes.visibility import router as visibility_router
from app.api.v1.routes.voice_profiles import router as voice_profiles_router
from app.api.v1.routes.webhooks import router as webhooks_router
from app.api.v1.routes.workspace import router as workspace_router

router = APIRouter()

router.include_router(agents_router)
router.include_router(amplify_router)
router.include_router(analytics_router)
router.include_router(analytics_v2_router)
router.include_router(articles_router)
router.include_router(auth_router)
router.include_router(auto_pipeline_router)
router.include_router(auto_pipeline_v2_router)
router.include_router(billing_router)
router.include_router(brands_router)
router.include_router(campaigns_router)
router.include_router(citations_router)
router.include_router(company_router)
router.include_router(competitors_router)
router.include_router(discovery_router)
router.include_router(drafts_router)
router.include_router(feed_router)
router.include_router(feedback_router)
router.include_router(geo_router)
router.include_router(invitations_router)
router.include_router(links_router)
# Public unauthenticated short-link redirect (/r/{code}) — no /v1 prefix.
router.include_router(links_public_router)
router.include_router(manual_import_router)
router.include_router(notifications_router)
router.include_router(opportunities_router)
router.include_router(personas_router)
router.include_router(projects_router)
router.include_router(prompts_router)
router.include_router(reddit_posting_router)
router.include_router(scans_router)
router.include_router(secrets_router)
router.include_router(seo_router)
router.include_router(sources_router)
router.include_router(technical_seo_router)
router.include_router(ugc_router)
router.include_router(user_keys_router)
router.include_router(visibility_router)
router.include_router(voice_profiles_router)
router.include_router(webhooks_router)
router.include_router(workspace_router)
