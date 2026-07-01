"""Project, brand profile, and prompt template table operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

PROJECTS_TABLE = "projects"
BRAND_PROFILES_TABLE = "brand_profiles"
PROMPT_TEMPLATES_TABLE = "prompt_templates"


# Project operations
def get_project_by_id(db: Client, project_id: int) -> dict[str, Any] | None:
    """Get a project by ID."""
    result = db.table(PROJECTS_TABLE).select("*").eq("id", project_id).execute()
    return result.data[0] if result.data else None


def get_project_by_slug(db: Client, workspace_id: int, slug: str) -> dict[str, Any] | None:
    """Get a project by workspace ID and slug."""
    result = (
        db.table(PROJECTS_TABLE).select("*").eq("workspace_id", workspace_id).eq("slug", slug).execute()
    )
    return result.data[0] if result.data else None


def get_project_by_company_id(db: Client, workspace_id: int, company_id: int) -> dict[str, Any] | None:
    """Get the most recently created project linked to a company profile.

    This is the preferred lookup for "find or create" flows (e.g. the
    auto-pipeline) since company_id is a stable foreign key — unlike a
    slug, which can drift if the generated slug format ever changes.
    Orders by id desc so a stray duplicate from a past bug doesn't shadow
    the project the user has actually been working in.
    """
    result = (
        db.table(PROJECTS_TABLE)
        .select("*")
        .eq("workspace_id", workspace_id)
        .eq("company_id", company_id)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def create_project(db: Client, project_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new project."""
    result = db.table(PROJECTS_TABLE).insert(project_data).execute()
    return result.data[0]


def update_project(db: Client, project_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a project."""
    result = db.table(PROJECTS_TABLE).update(update_data).eq("id", project_id).execute()
    return result.data[0] if result.data else None


def delete_project(db: Client, project_id: int) -> None:
    """Delete a project."""
    db.table(PROJECTS_TABLE).delete().eq("id", project_id).execute()


def list_projects_for_workspace(db: Client, workspace_id: int) -> list[dict[str, Any]]:
    """List all projects in a workspace."""
    result = db.table(PROJECTS_TABLE).select("*").eq("workspace_id", workspace_id).order("created_at", desc=True).execute()
    return list(result.data)


def get_projects_by_ids(db: Client, project_ids: list[int]) -> list[dict[str, Any]]:
    """Get multiple projects by IDs."""
    if not project_ids:
        return []
    result = db.table(PROJECTS_TABLE).select("*").in_("id", project_ids).execute()
    return list(result.data)


# Brand profile operations
def get_brand_profile_by_project(db: Client, project_id: int) -> dict[str, Any] | None:
    """Get a brand profile by project ID."""
    result = db.table(BRAND_PROFILES_TABLE).select("*").eq("project_id", project_id).execute()
    return result.data[0] if result.data else None


def get_brand_profile_by_id(db: Client, profile_id: int) -> dict[str, Any] | None:
    """Get a brand profile by ID."""
    result = db.table(BRAND_PROFILES_TABLE).select("*").eq("id", profile_id).execute()
    return result.data[0] if result.data else None


def create_brand_profile(db: Client, profile_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new brand profile."""
    result = db.table(BRAND_PROFILES_TABLE).insert(profile_data).execute()
    return result.data[0]


def resolve_brand_context(db: Client, workspace_id: int, project_id: int) -> dict[str, Any] | None:
    """Build a unified brand dict for AI generation (keywords, personas, replies).

    There are two brand data sources in this codebase that evolved separately:
      - ``brand_profiles``   (project-scoped — older flow)
      - ``company_profiles`` (workspace-scoped — the Company Setup workflow step)

    Routes that called ``project.get("brand_profile")`` were always silently
    getting ``None`` (the ``projects`` table has no such column), which made
    keyword/persona generation return an empty list with no visible error.
    This resolver fetches both real sources and merges them — company_profiles
    fields win when brand_profiles fields are blank, since that's the richer,
    more commonly-filled-in source for users going through the new workflow.

    Returns ``None`` only if neither source has any data at all.
    """
    from app.db.tables.company import get_company_by_id

    # Get the project to find its company_id
    project_result = db.table(PROJECTS_TABLE).select("company_id").eq("id", project_id).execute()
    project_company_id = project_result.data[0].get("company_id") if project_result.data else None

    bp = get_brand_profile_by_project(db, project_id) or {}
    cp = get_company_by_id(db, project_company_id) if project_company_id else {}

    if not bp and not cp:
        return None

    def _pick(*vals: Any) -> str:
        for v in vals:
            if v:
                return v
        return ""

    merged = {
        "brand_name": _pick(bp.get("brand_name"), cp.get("name")),
        "summary": _pick(bp.get("summary"), cp.get("extracted_summary"), cp.get("description")),
        "product_summary": _pick(bp.get("product_summary"), cp.get("description"), cp.get("extracted_summary")),
        "target_audience": _pick(bp.get("target_audience"), cp.get("target_audience")),
        "business_domain": _pick(bp.get("business_domain"), cp.get("category")),
        "geography": _pick(bp.get("geography"), cp.get("geography")),
        "brand_voice": _pick(bp.get("voice_notes"), bp.get("brand_voice"), cp.get("brand_voice")),
        "competitors": _pick(bp.get("competitors"), cp.get("competitors"), cp.get("extracted_competitors")),
        "pain_points": _pick(bp.get("pain_points"), cp.get("extracted_pain_points"), cp.get("pain_points")),
    }
    # If after merging everything is still blank, treat as no brand context
    if not any(merged.values()):
        return None
    return merged


def update_brand_profile(db: Client, profile_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a brand profile."""
    result = db.table(BRAND_PROFILES_TABLE).update(update_data).eq("id", profile_id).execute()
    return result.data[0] if result.data else None


def delete_brand_profile(db: Client, profile_id: int) -> None:
    """Delete a brand profile."""
    db.table(BRAND_PROFILES_TABLE).delete().eq("id", profile_id).execute()


# Prompt template operations
def get_prompt_template_by_id(db: Client, template_id: int) -> dict[str, Any] | None:
    """Get a prompt template by ID."""
    result = db.table(PROMPT_TEMPLATES_TABLE).select("*").eq("id", template_id).execute()
    return result.data[0] if result.data else None


def get_default_prompts(db: Client, project_id: int) -> list[dict[str, Any]]:
    """Get all default prompt templates for a project."""
    result = (
        db.table(PROMPT_TEMPLATES_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .eq("is_default", True)
        .execute()
    )
    return list(result.data)


def create_prompt_template(db: Client, template_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new prompt template."""
    result = db.table(PROMPT_TEMPLATES_TABLE).insert(template_data).execute()
    return result.data[0]


def update_prompt_template(db: Client, template_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a prompt template."""
    result = db.table(PROMPT_TEMPLATES_TABLE).update(update_data).eq("id", template_id).execute()
    return result.data[0] if result.data else None


def delete_prompt_template(db: Client, template_id: int) -> None:
    """Delete a prompt template."""
    db.table(PROMPT_TEMPLATES_TABLE).delete().eq("id", template_id).execute()


def list_prompt_templates_for_project(db: Client, project_id: int) -> list[dict[str, Any]]:
    """List all prompt templates for a project."""
    result = db.table(PROMPT_TEMPLATES_TABLE).select("*").eq("project_id", project_id).execute()
    return list(result.data)


def ensure_default_prompts_exist(db: Client, project_id: int, default_prompts: list[dict[str, Any]]) -> None:
    """Ensure default prompts exist for a project, creating them if needed."""
    existing = get_default_prompts(db, project_id)
    existing_types = {p["prompt_type"] for p in existing}

    for prompt in default_prompts:
        if prompt["prompt_type"] not in existing_types:
            prompt_data = {**prompt, "project_id": project_id, "is_default": True}
            create_prompt_template(db, prompt_data)
