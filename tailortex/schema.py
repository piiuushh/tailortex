"""Structured output contract between the engine and the LLM.

Kept deliberately simple (no Optional / dict / defaults) so it converts cleanly
into a Gemini ``response_schema``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BulletEdit(BaseModel):
    id: str = Field(description="Bullet id exactly as given, e.g. 'u07'.")
    title: str = Field(description="Rewritten bold label. Empty string if the bullet has no title.")
    text: str = Field(description="Rewritten bullet body as a LaTeX fragment.")
    relevance: int = Field(description="0-10: how relevant this bullet is to the job description.")
    keep: bool = Field(description="false only for bullets that are clearly irrelevant to this role.")


class Keyword(BaseModel):
    term: str = Field(description="Term spelled exactly as in the JD, e.g. 'Power BI', 'ETL', 'stakeholder management'.")
    kind: str = Field(description="One of: 'tool' (named technology, language, platform, library, certification), "
                                  "'skill' (method or practice, e.g. ETL, A/B testing), 'domain' (industry, e.g. lending), "
                                  "'soft' (e.g. communication).")


class GroupOrder(BaseModel):
    group: str = Field(description="Group id exactly as given, e.g. 'g3'.")
    order: list[str] = Field(description="All bullet ids of this group, most relevant first.")


class TailorPlan(BaseModel):
    company: str = Field(description="Hiring company name from the JD, or 'Unknown'.")
    role: str = Field(description="Job title from the JD.")
    jd_keywords: list[Keyword] = Field(
        description="15-30 tools, skills, methods and domain terms from the JD, most important first."
    )
    section_order: list[str] = Field(description="All section names exactly as given, in the recommended order.")
    bullets: list[BulletEdit]
    group_orders: list[GroupOrder]
    gaps: list[str] = Field(description="JD requirements the resume gives no evidence for (do NOT paper over these).")
    change_summary: list[str] = Field(description="3-6 short lines describing what was changed and why.")
