"""Pydantic v2 models for SignalFlow database tables.

These models provide type-safe representations of database records
and are used with ConfigDict(from_attributes=True) for validation.
"""

from app.models.analytics import AnalyticsSnapshot, AuditEvent, AutoPipeline, VisibilitySnapshot
from app.models.content import PostDraft, ReplyDraft
from app.models.discovery import DiscoveryKeyword, MonitoredSubreddit, Opportunity, Persona, ScanRun
from app.models.other import (
    ActivityLog,
    Campaign,
    IntegrationSecret,
    Notification,
    PublishedPost,
    RedditAccount,
    UsageMetric,
    WebhookEndpoint,
)
from app.models.project import BrandProfile, Project, PromptTemplate
from app.models.user import AccountUser
from app.models.visibility import AIResponse, BrandMention, Citation, PromptRun, PromptSet, SourceDomain, SourceGap
from app.models.workspace import Invitation, Membership, PlanEntitlement, Redemption, Subscription, Workspace

__all__ = [
    # User
    "AccountUser",
    # Workspace
    "Workspace",
    "Membership",
    "Invitation",
    "Subscription",
    "PlanEntitlement",
    "Redemption",
    # Project
    "Project",
    "BrandProfile",
    "PromptTemplate",
    # Discovery
    "Persona",
    "DiscoveryKeyword",
    "MonitoredSubreddit",
    "Opportunity",
    "ScanRun",
    # Content
    "ReplyDraft",
    "PostDraft",
    # Visibility
    "PromptSet",
    "PromptRun",
    "AIResponse",
    "BrandMention",
    "Citation",
    "SourceDomain",
    "SourceGap",
    # Analytics
    "AnalyticsSnapshot",
    "AuditEvent",
    "AutoPipeline",
    "VisibilitySnapshot",
    # Other
    "Campaign",
    "PublishedPost",
    "WebhookEndpoint",
    "IntegrationSecret",
    "RedditAccount",
    "Notification",
    "ActivityLog",
    "UsageMetric",
]
