from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from config.supabase_client import get_supabase_client_with_token
from features.auth.auth_service import AuthService
from features.customers.customer_analytics_models import (
    CustomerArticleTrendEventCreate,
    CustomerArticleTrendEventResponse,
)
from features.customers.customer_analytics_service import CustomerAnalyticsService
from features.customers.customer_catalog_models import (
    CustomerArticlePostFeedItem,
    CustomerArticlePostFeedPage,
    CustomerArticlePostPublic,
    CustomerCatalogPage,
    CustomerCatalogProduct,
    CustomerTrendingProduct,
    CustomerTrendingProductsPage,
)
from features.customers.customer_catalog_service import CustomerCatalogService
from features.customers.customer_i18n import CustomerI18nService
from features.customers.customer_wishlist_cart_models import (
    AddCartItemBody,
    AddWishlistItemBody,
    CustomerCartGroup,
    CustomerCartItemAddResponse,
    CustomerCartLineItem,
    CustomerCartsResponse,
    CustomerWishlistResponse,
    PatchCartLineBody,
)
from features.customers.customer_subscriptions_models import (
    CustomerOrganizationSummary,
    CustomerSubscribeResponse,
    CustomerSubscriptionsListResponse,
    CustomerSubscriptionItem,
    SubscribeOrganizationBody,
)
from features.customers.customer_subscriptions_service import CustomerSubscriptionsService
from features.customers.customer_wishlist_cart_service import CustomerWishlistCartService
from features.customer_sales.customer_sales_models import CustomerParamsOut, CustomerParamsPatch
from features.customer_sales.customer_sales_service import CustomerSalesService
from features.organization_articles.organization_articles_models import ArticleCategory
from features.performance.performance_models import PerformancePeriod

security = HTTPBearer()
_auth = AuthService()
_catalog = CustomerCatalogService()
_analytics = CustomerAnalyticsService()
_wish_cart = CustomerWishlistCartService()
_subscriptions = CustomerSubscriptionsService()
_customer_sales = CustomerSalesService()
_i18n = CustomerI18nService()

router = APIRouter(prefix="/api/v1/customers", tags=["Customers"])

_CATALOG_LIMIT_DEFAULT = 50
_CATALOG_LIMIT_MAX = 100


def _require_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    try:
        return _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def require_authenticated_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Valide le JWT Supabase (tout utilisateur connecté)."""
    return _require_user_id(credentials)


def require_customer_id(user_id: str = Depends(require_authenticated_user)) -> str:
    """JWT + ligne `customers` (profil client)."""
    cid = _wish_cart.get_customer_id_for_user(user_id)
    if not cid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_i18n.translate_for_user(user_id, "Profil client introuvable"),
        )
    return cid


def _customer_detail(customer_id: str, message: str) -> str:
    return _i18n.translate_for_customer(customer_id, message)


def _user_detail(user_id: str, message: str) -> str:
    return _i18n.translate_for_user(user_id, message)


class UpdateCustomerRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)


@router.get("/", response_model=List[Dict[str, Any]])
def list_players(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Liste les entrées de `public.customers`.
    La visibilité est gérée par les RLS.
    """
    client = get_supabase_client_with_token(credentials.credentials)
    res = client.table("customers").select("*").execute()
    return res.data or []


@router.get("/me", response_model=Dict[str, Any])
def get_my_player_profile(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Retourne l'entrée `customers` correspondant à l'utilisateur connecté (si player).
    """
    client = get_supabase_client_with_token(credentials.credentials)
    res = client.table("customers").select("*").limit(1).execute()
    data = res.data or []
    if not data:
        user_id = _require_user_id(credentials)
        raise HTTPException(
            status_code=404,
            detail=_user_detail(user_id, "Profil player introuvable"),
        )
    return data[0]


@router.get("/me/params", response_model=CustomerParamsOut, tags=["Customer params"])
def get_my_customer_params(customer_id: str = Depends(require_customer_id)):
    """
    Langue et coordonnées par défaut (livraison). Crée une ligne par défaut si absente.
    """
    row = _customer_sales.get_or_create_customer_params(customer_id)
    return CustomerParamsOut.model_validate(row)


@router.patch("/me/params", response_model=CustomerParamsOut, tags=["Customer params"])
def patch_my_customer_params(
    body: CustomerParamsPatch,
    customer_id: str = Depends(require_customer_id),
):
    """Mise à jour partielle des paramètres client."""
    row = _customer_sales.upsert_customer_params(
        customer_id,
        locale=body.locale,
        default_longitude=body.default_longitude,
        default_latitude=body.default_latitude,
        country=body.country,
        interests=body.interests,
        extra=body.extra,
    )
    return CustomerParamsOut.model_validate(row)


@router.patch("/me", response_model=Dict[str, Any])
def update_my_player_profile(
    body: UpdateCustomerRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Met à jour le `username` du joueur connecté.
    RLS: l'utilisateur peut mettre à jour uniquement sa propre ligne.
    """
    client = get_supabase_client_with_token(credentials.credentials)
    res = client.table("customers").update({"username": body.username}).execute()
    data = res.data or []
    if not data:
        user_id = _require_user_id(credentials)
        raise HTTPException(
            status_code=403,
            detail=_user_detail(user_id, "Action non autorisée"),
        )
    return data[0]


def _catalog_limit_offset(
    limit: int = Query(
        _CATALOG_LIMIT_DEFAULT,
        ge=1,
        le=_CATALOG_LIMIT_MAX,
        description="Nombre max d’articles par page.",
    ),
    offset: int = Query(0, ge=0, description="Décalage pour la pagination."),
) -> tuple[int, int]:
    return limit, offset


@router.get("/posts/feed", response_model=CustomerArticlePostFeedPage)
def list_customer_article_post_feed(
    customer_id: str = Depends(require_customer_id),
    pagination: tuple[int, int] = Depends(_catalog_limit_offset),
):
    """
    Feed paginé : posts promotionnels actifs avec le contexte produit (prix, stock, images catalogue, vendeur).
    Sans identifiant du post (seuls `organization_id` et `organization_article_id`).
    Requiert la migration `customer_article_post_feed` sur Supabase.
    """
    limit, offset = pagination
    rows, total = _catalog.list_article_post_feed_page(
        limit=limit,
        offset=offset,
        customer_id=customer_id,
    )
    return CustomerArticlePostFeedPage(
        items=[CustomerArticlePostFeedItem.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/analytics/article-events",
    response_model=CustomerArticleTrendEventResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Customer analytics"],
)
def create_customer_article_trend_event(
    body: CustomerArticleTrendEventCreate,
    customer_id: str = Depends(require_customer_id),
):
    """
    Enregistre un signal customer pour les futurs produits tendance.
    Les achats confirmÃ©s (`purchase`) seront crÃ©Ã©s automatiquement cÃ´tÃ© backend.
    """
    try:
        row = _analytics.create_article_event(customer_id=customer_id, body=body)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_customer_detail(customer_id, str(exc)),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_customer_detail(customer_id, str(exc)),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_customer_detail(customer_id, str(exc)),
        ) from exc
    return CustomerArticleTrendEventResponse.model_validate(row)


@router.get("/products", response_model=CustomerCatalogPage)
def list_customer_catalog_products(
    customer_id: str = Depends(require_customer_id),
    pagination: tuple[int, int] = Depends(_catalog_limit_offset),
):
    """
    Liste les articles actifs (catalogue) : nom, catégorie, prix, images, vendeur (organisation).
    JWT Supabase requis.
    """
    limit, offset = pagination
    rows, total = _catalog.list_catalog_page(
        limit=limit,
        offset=offset,
        customer_id=customer_id,
    )
    return CustomerCatalogPage(
        items=[CustomerCatalogProduct.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/trending-products", response_model=CustomerTrendingProductsPage)
def list_customer_trending_products(
    period: PerformancePeriod = Query(
        PerformancePeriod.d30,
        description="PÃ©riode Ã  analyser : 7d, 30d, 90d ou year.",
    ),
    country: Optional[str] = Query(
        None,
        min_length=2,
        max_length=2,
        description="Pays ISO alpha-2 optionnel. Si omis, customer_params est utilisÃ©.",
    ),
    category: Optional[ArticleCategory] = Query(
        None,
        description="CatÃ©gorie Ã  recommander en prioritÃ©.",
    ),
    limit: int = Query(20, ge=1, le=100),
    customer_id: str = Depends(require_customer_id),
):
    """Produits tendance recommandÃ©s au customer connectÃ©."""

    rows, total = _catalog.list_trending_products(
        customer_id=customer_id,
        period=period.value,
        limit=limit,
        country=country,
        category=category.value if category else None,
    )
    return CustomerTrendingProductsPage(
        items=[CustomerTrendingProduct.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        period_key=period.value,
        country=country.upper() if country else None,
        category=category,
    )


@router.get("/products/search", response_model=CustomerCatalogPage)
def search_customer_catalog_products(
    q: str = Query(..., min_length=1, description="Sous-chaîne recherchée dans le nom (insensible à la casse)."),
    customer_id: str = Depends(require_customer_id),
    pagination: tuple[int, int] = Depends(_catalog_limit_offset),
):
    """Recherche d’articles par nom (parmi les articles actifs)."""
    limit, offset = pagination
    rows, total = _catalog.list_catalog_page(
        limit=limit,
        offset=offset,
        customer_id=customer_id,
        name_ilike=q,
    )
    return CustomerCatalogPage(
        items=[CustomerCatalogProduct.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/products/{organization_article_id}/posts",
    response_model=List[CustomerArticlePostPublic],
)
def list_customer_article_posts(
    organization_article_id: UUID,
    customer_id: str = Depends(require_customer_id),
):
    """Posts promotionnels actifs d’un article actif (bucket `organization-article-posts`)."""
    try:
        rows = _catalog.list_public_article_posts(str(organization_article_id))
        return [CustomerArticlePostPublic.model_validate(r) for r in rows]
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_customer_detail(customer_id, str(exc)),
        ) from exc


@router.get("/products/filter", response_model=CustomerCatalogPage)
def filter_customer_catalog_products(
    name: Optional[str] = Query(
        None,
        description="Filtre sur le nom (contient, insensible à la casse).",
    ),
    category: Optional[List[ArticleCategory]] = Query(
        None,
        description="Une ou plusieurs catégories (répéter le paramètre).",
    ),
    min_price: Optional[Decimal] = Query(None, ge=0, description="Prix unitaire minimum."),
    max_price: Optional[Decimal] = Query(None, ge=0, description="Prix unitaire maximum."),
    customer_id: str = Depends(require_customer_id),
    pagination: tuple[int, int] = Depends(_catalog_limit_offset),
):
    """
    Filtres combinables : nom, catégorie(s), plage de prix. Au moins un critère doit être fourni.
    """
    cats = [c.value for c in category] if category else None
    has_name = name is not None and name.strip() != ""
    has_cat = bool(cats)
    has_min = min_price is not None
    has_max = max_price is not None
    if not (has_name or has_cat or has_min or has_max):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_customer_detail(
                customer_id,
                "Fournir au moins un filtre : name, category, min_price ou max_price.",
            ),
        )
    if has_min and has_max and min_price > max_price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_customer_detail(
                customer_id,
                "min_price doit être inférieur ou égal à max_price.",
            ),
        )
    limit, offset = pagination
    rows, total = _catalog.list_catalog_page(
        limit=limit,
        offset=offset,
        customer_id=customer_id,
        name_ilike=name.strip() if has_name else None,
        categories=cats,
        min_price=min_price,
        max_price=max_price,
    )
    return CustomerCatalogPage(
        items=[CustomerCatalogProduct.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/wishlist", response_model=CustomerWishlistResponse)
def get_customer_wishlist(customer_id: str = Depends(require_customer_id)):
    """Liste des produits en favoris (articles actifs uniquement)."""
    rows = _wish_cart.list_wishlist(customer_id)
    return CustomerWishlistResponse(
        items=[CustomerCatalogProduct.model_validate(r) for r in rows],
    )


@router.post("/wishlist/items", status_code=status.HTTP_204_NO_CONTENT)
def add_customer_wishlist_item(
    body: AddWishlistItemBody,
    customer_id: str = Depends(require_customer_id),
):
    try:
        _wish_cart.add_wishlist_item(customer_id, body.organization_article_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_customer_detail(customer_id, str(exc)),
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/wishlist/items/{organization_article_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_customer_wishlist_item(
    organization_article_id: UUID,
    customer_id: str = Depends(require_customer_id),
):
    _wish_cart.remove_wishlist_item(customer_id, organization_article_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/carts", response_model=CustomerCartsResponse)
def get_customer_carts(customer_id: str = Depends(require_customer_id)):
    """Paniers regroupés par organisation marchande (une entrée par vendeur)."""
    raw = _wish_cart.list_carts(customer_id)
    carts_out: List[CustomerCartGroup] = []
    for c in raw:
        items_out = [
            CustomerCartLineItem(
                line_id=item["line_id"],
                quantity=item["quantity"],
                product=CustomerCatalogProduct.model_validate(item["product"]),
            )
            for item in c["items"]
        ]
        carts_out.append(
            CustomerCartGroup(
                cart_id=c["cart_id"],
                organization_id=c["organization_id"],
                organization_name=c["organization_name"],
                updated_at=c["updated_at"],
                items=items_out,
            )
        )
    return CustomerCartsResponse(carts=carts_out)


@router.post("/carts/items", response_model=CustomerCartItemAddResponse)
def add_customer_cart_item(
    body: AddCartItemBody,
    customer_id: str = Depends(require_customer_id),
):
    try:
        cart_id, line_id = _wish_cart.add_cart_item(
            customer_id,
            body.organization_article_id,
            body.quantity,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_customer_detail(customer_id, str(exc)),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_customer_detail(customer_id, str(exc)),
        ) from exc
    return CustomerCartItemAddResponse(
        cart_id=UUID(cart_id),
        line_id=UUID(line_id),
    )


@router.patch("/carts/items/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def patch_customer_cart_line(
    line_id: UUID,
    body: PatchCartLineBody,
    customer_id: str = Depends(require_customer_id),
):
    try:
        _wish_cart.set_cart_line_quantity(customer_id, line_id, body.quantity)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_customer_detail(customer_id, str(exc)),
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/carts/items/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer_cart_line(
    line_id: UUID,
    customer_id: str = Depends(require_customer_id),
):
    ok = _wish_cart.remove_cart_line(customer_id, line_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_customer_detail(customer_id, "Ligne introuvable"),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/carts/{cart_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer_cart(
    cart_id: UUID,
    customer_id: str = Depends(require_customer_id),
):
    ok = _wish_cart.clear_cart(customer_id, cart_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_customer_detail(customer_id, "Panier introuvable"),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/organizations/{organization_id}",
    response_model=CustomerOrganizationSummary,
)
def get_customer_organization_summary(
    organization_id: UUID,
    customer_id: str = Depends(require_customer_id),
):
    """
    Informations minimales sur une organisation : nom et nombre d’abonnés actifs.
    """
    row = _subscriptions.get_organization_public_summary(str(organization_id))
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_customer_detail(customer_id, "Organisation introuvable"),
        )
    return CustomerOrganizationSummary.model_validate(row)


@router.get("/subscriptions", response_model=CustomerSubscriptionsListResponse)
def list_customer_subscriptions(customer_id: str = Depends(require_customer_id)):
    """Abonnements actifs à des marchands (organisations)."""
    rows = _subscriptions.list_active_for_customer(customer_id)
    return CustomerSubscriptionsListResponse(
        items=[CustomerSubscriptionItem.model_validate(r) for r in rows],
    )


@router.post("/subscriptions", response_model=CustomerSubscribeResponse)
def subscribe_customer_to_organization(
    body: SubscribeOrganizationBody,
    customer_id: str = Depends(require_customer_id),
):
    """S’abonner à une organisation (idempotent si déjà actif)."""
    try:
        row = _subscriptions.subscribe(customer_id, body.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_customer_detail(customer_id, str(exc)),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_customer_detail(customer_id, str(exc)),
        ) from exc
    return CustomerSubscribeResponse.model_validate(row)


@router.delete(
    "/subscriptions/{organization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unsubscribe_customer_from_organization(
    organization_id: UUID,
    customer_id: str = Depends(require_customer_id),
):
    """Résilier l’abonnement (statut passé à « cancelled », traçabilité conservée)."""
    ok = _subscriptions.unsubscribe(customer_id, organization_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_customer_detail(customer_id, "Abonnement actif introuvable"),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
