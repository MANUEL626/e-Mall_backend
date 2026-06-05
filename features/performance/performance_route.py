"""
Routes Performance : rapports et analytics organisation.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_service import AuthService
from features.performance.performance_agent_models import (
    PerformanceAgentCapabilities,
    PerformanceAgentRequest,
    PerformanceAgentResponse,
)
from features.performance.performance_agent_service import PerformanceAgentService
from features.performance.performance_models import (
    AIContextResponse,
    FinancialPeriod,
    FinancialSummary,
    InventorySummary,
    MonthlyPerformanceSummary,
    PerformancePeriod,
    PerformanceDashboardSummary,
    SalesStatusSummary,
    TopProductsSummary,
    TrendingProductsSummary,
    WeeklySalesSummary,
    YearlyPerformanceSummary,
)
from features.performance.performance_service import PerformanceService

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/performance",
    tags=["Performance"],
)

security = HTTPBearer()
_auth = AuthService()
_service = PerformanceService()
_agent_service = PerformanceAgentService(_service)


def _current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    try:
        return _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


@router.get("/monthly-summary", response_model=MonthlyPerformanceSummary)
def get_monthly_performance_summary(
    organization_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Résumé du mois courant avec comparaison au mois précédent."""

    user_id = _current_user_id(credentials)
    try:
        payload = _service.get_monthly_summary(user_id, str(organization_id))
        return MonthlyPerformanceSummary.model_validate(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get("/dashboard-summary", response_model=PerformanceDashboardSummary)
def get_performance_dashboard_summary(
    organization_id: UUID,
    period: FinancialPeriod = Query(
        FinancialPeriod.month,
        description="PÃ©riode principale : month, 7d, 30d, 90d ou year.",
    ),
    limit: int = Query(
        10,
        ge=1,
        le=50,
        description="Nombre max de top/tendance produits Ã  retourner.",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Vue agrÃ©gÃ©e pour l'Ã©cran principal du dashboard Performance."""

    user_id = _current_user_id(credentials)
    try:
        payload = _service.get_dashboard_summary(
            user_id,
            str(organization_id),
            period,
            limit,
        )
        return PerformanceDashboardSummary.model_validate(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get("/agent/capabilities", response_model=PerformanceAgentCapabilities)
def get_performance_agent_capabilities(
    organization_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """TÃ¢ches IA disponibles et routage modÃ¨les configurÃ©."""

    user_id = _current_user_id(credentials)
    try:
        _service.assert_org_member(user_id, str(organization_id))
        _service.assert_feature_enabled(str(organization_id), "ai_performance_agent")
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    return _agent_service.capabilities()


@router.post("/agent", response_model=PerformanceAgentResponse)
def run_performance_agent(
    organization_id: UUID,
    body: PerformanceAgentRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """ExÃ©cute une tÃ¢che d'agent IA Performance avec fallback provider/modÃ¨le."""

    user_id = _current_user_id(credentials)
    try:
        payload = _agent_service.run(
            user_id=user_id,
            organization_id=str(organization_id),
            body=body,
        )
        return PerformanceAgentResponse.model_validate(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        detail: object = str(exc)
        if len(exc.args) > 1:
            detail = {"message": exc.args[0], "attempts": exc.args[1]}
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        ) from exc


@router.get("/weekly-sales", response_model=WeeklySalesSummary)
def get_weekly_sales_summary(
    organization_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Ventes de la semaine courante, avec répartition par produit."""

    user_id = _current_user_id(credentials)
    try:
        payload = _service.get_weekly_sales(user_id, str(organization_id))
        return WeeklySalesSummary.model_validate(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get("/yearly-summary", response_model=YearlyPerformanceSummary)
def get_yearly_performance_summary(
    organization_id: UUID,
    year: int | None = Query(
        None,
        ge=2000,
        le=2100,
        description="Année à analyser. Si omise, l'année courante est utilisée.",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Résumé annuel mois par mois."""

    user_id = _current_user_id(credentials)
    try:
        payload = _service.get_yearly_summary(user_id, str(organization_id), year)
        return YearlyPerformanceSummary.model_validate(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get("/inventory-summary", response_model=InventorySummary)
def get_inventory_summary(
    organization_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """État du catalogue et du stock."""

    user_id = _current_user_id(credentials)
    try:
        payload = _service.get_inventory_summary(user_id, str(organization_id))
        return InventorySummary.model_validate(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get("/top-products", response_model=TopProductsSummary)
def get_top_products(
    organization_id: UUID,
    period: PerformancePeriod = Query(
        PerformancePeriod.d30,
        description="Période à analyser : 7d, 30d, 90d ou year.",
    ),
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Nombre maximum de produits à retourner.",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Produits les plus vendus sur une période."""

    user_id = _current_user_id(credentials)
    try:
        payload = _service.get_top_products(
            user_id,
            str(organization_id),
            period,
            limit,
        )
        return TopProductsSummary.model_validate(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get("/trending-products", response_model=TrendingProductsSummary)
def get_trending_products(
    organization_id: UUID,
    period: PerformancePeriod = Query(
        PerformancePeriod.d30,
        description="PÃ©riode Ã  analyser : 7d, 30d, 90d ou year.",
    ),
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Nombre maximum de produits tendance Ã  retourner.",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Produits tendance selon les signaux customer et les ventes complÃ©tÃ©es."""

    user_id = _current_user_id(credentials)
    try:
        payload = _service.get_trending_products(
            user_id,
            str(organization_id),
            period,
            limit,
        )
        return TrendingProductsSummary.model_validate(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get("/financial-summary", response_model=FinancialSummary)
def get_financial_summary(
    organization_id: UUID,
    period: FinancialPeriod = Query(
        FinancialPeriod.month,
        description="Période à analyser : month, 7d, 30d, 90d ou year.",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Résumé financier : revenu, coût fournisseur, panier moyen et marge estimée."""

    user_id = _current_user_id(credentials)
    try:
        payload = _service.get_financial_summary(user_id, str(organization_id), period)
        return FinancialSummary.model_validate(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get("/sales-status", response_model=SalesStatusSummary)
def get_sales_status(
    organization_id: UUID,
    period: FinancialPeriod = Query(
        FinancialPeriod.month,
        description="Période à analyser : month, 7d, 30d, 90d ou year.",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """État des ventes par statut et type de fulfillment."""

    user_id = _current_user_id(credentials)
    try:
        payload = _service.get_sales_status(user_id, str(organization_id), period)
        return SalesStatusSummary.model_validate(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get("/ai-context", response_model=AIContextResponse)
def get_ai_context(
    organization_id: UUID,
    period: FinancialPeriod = Query(
        FinancialPeriod.month,
        description="PÃ©riode Ã  analyser : month, 7d, 30d, 90d ou year.",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Contexte structurÃ© pour alimenter un agent IA sans lui faire inventer les chiffres."""

    user_id = _current_user_id(credentials)
    try:
        payload = _service.get_ai_context(user_id, str(organization_id), period)
        return AIContextResponse.model_validate(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
