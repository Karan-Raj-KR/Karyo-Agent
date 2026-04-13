from __future__ import annotations

from typing import Optional, Literal
from pydantic import BaseModel


class WebsiteHealth(BaseModel):
    status: Literal["alive", "dead", "slow", "none"]
    response_time_ms: Optional[int] = None
    has_ssl: Optional[bool] = None
    last_modified: Optional[str] = None
    mobile_meta_tag: Optional[bool] = None


class BusinessDossier(BaseModel):
    name: str
    place_id: str
    address: str
    phone: Optional[str] = None
    website: Optional[str] = None
    website_status: Literal["alive", "dead", "slow", "none"] = "none"
    has_ssl: Optional[bool] = None
    domain_age_years: Optional[float] = None
    google_rating: Optional[float] = None
    review_count: int = 0
    instagram_handle: Optional[str] = None
    instagram_last_post_days: Optional[int] = None
    research_notes: list[str] = []


class LeadScore(BaseModel):
    business_name: str
    presence_gap_score: int    # 1-10
    conversion_likelihood: int  # 1-10
    combined_score: int         # sum of above
    reasoning: str
    primary_gap: str
    flag: Literal["approve", "reject", "borderline"] = "borderline"


class ManagerDecision(BaseModel):
    business_name: str
    action: Literal["approve", "reject", "reroute"]
    reason: str
    follow_up_query: Optional[str] = None  # only for reroute


class FinalLead(BaseModel):
    dossier: BusinessDossier
    score: LeadScore
    manager_reason: str
