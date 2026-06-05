"""Modeles API pour l'agent IA Performance."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from features.performance.performance_models import FinancialPeriod


class PerformanceAgentTask(str, Enum):
    executive_summary = "executive_summary"
    monthly_report = "monthly_report"
    financial_diagnosis = "financial_diagnosis"
    trend_analysis = "trend_analysis"
    stock_recommendations = "stock_recommendations"
    sales_actions = "sales_actions"


class PerformanceAgentRequest(BaseModel):
    task: PerformanceAgentTask
    period: FinancialPeriod = FinancialPeriod.month
    language: str = Field("fr", min_length=2, max_length=8)
    extra_instructions: Optional[str] = Field(None, max_length=2000)
    max_tokens: int = Field(900, ge=200, le=2500)


class PerformanceAgentAttempt(BaseModel):
    provider: str
    model: str
    key_index: Optional[int] = None
    status: str
    error: Optional[str] = None


class PerformanceAgentResponse(BaseModel):
    generated_at: datetime
    organization_id: UUID
    task: PerformanceAgentTask
    period_key: FinancialPeriod
    provider: str
    model: str
    key_index: Optional[int] = None
    fallback_used: bool
    attempts: List[PerformanceAgentAttempt]
    output: str
    context: Dict[str, Any]


class PerformanceAgentTaskCapability(BaseModel):
    task: PerformanceAgentTask
    description: str
    preferred_route: str
    fallback_route: str


class PerformanceAgentCapabilities(BaseModel):
    free_models: List[str]
    openrouter_keys_configured: int
    premium_providers_configured: List[str]
    tasks: List[PerformanceAgentTaskCapability]
