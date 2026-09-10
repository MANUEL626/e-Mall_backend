import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# Import des routeurs pour les utilisateurs
from features.admin.admins_route import router as admin_router
from features.customers.customers_route import router as player_router
from features.auth.auth_route import router as auth_router
from features.messaging.messaging_route import router as messaging_router
from features.messaging.messaging_service import MessagingNotConfiguredError
from features.customer_sales.customer_sales_route import (
    customer_router as customer_sales_customer_router,
    delivery_router as customer_sales_delivery_router,
    org_router as customer_sales_org_router,
    shop_org_router as customer_sales_shop_org_router,
)
from features.organization_article_orders.article_orders_route import (
    router as organization_article_orders_router,
    shop_router as organization_shop_article_orders_router,
)
from features.organization_articles.organization_articles_route import (
    router as organization_articles_router,
    shop_articles_router,
    shop_stock_resources_router,
)
from features.share.share_route import router as share_router
from features.members.members_route import router as members_router
from features.organizations.organizations_route import router as organizations_router
from features.organization_subscriptions.organization_subscriptions_route import (
    router as organization_subscriptions_router,
    stripe_router,
)
from features.performance.performance_route import router as performance_router
from features.users.users_route import router as users_router
from features.organization_repairs.organization_repairs_route import (
    router as organization_repairs_router,
)
from features.organization_rentals.organization_rentals_route import (
    router as organization_rentals_router,
)
from features.delivery_realtime.delivery_realtime_route import (
    router as delivery_realtime_router,
)
from infra.redis_client import init_redis, close_redis


app = FastAPI(
    title="e-Mall Backend API",
    version="1.0.0",
    description="API pour la gestion d'un e-Market (achat et livraison de produit).",
    openapi_tags=[
        {"name": "Auth", "description": "Authentification et inscription"},
        {"name": "Users", "description": "Gestion des utilisateurs"},
        {"name": "Admins", "description": "Gestion des administrateurs"},
        {
            "name": "Customers",
            "description": "Gestion des clients (catalogue, favoris, paniers, abonnements marchands)",
        },
        {"name": "Organizations", "description": "Organisations et membres"},
        {
            "name": "Organization subscriptions",
            "description": "Plans, abonnements et droits des organisations",
        },
        {
            "name": "Members",
            "description": "Espace membre d'organisation (profil, abonnés de la boutique)",
        },
        {
            "name": "Organization articles",
            "description": "Articles, stock et images par organisation",
        },
        {
            "name": "Organization article posts",
            "description": "Posts promotionnels (image/vidéo) par article",
        },
        {
            "name": "Organization article orders",
            "description": "Commandes fournisseur / réception et impact sur le stock",
        },
        {
            "name": "Messaging",
            "description": "Conversations directes et messages temps réel (Supabase RLS)",
        },
        {
            "name": "Customer sales",
            "description": "Commandes client, retrait, livraison, vente hors système",
        },
        {
            "name": "Performance",
            "description": "Rapports mensuels, financiers et analytics par organisation",
        },
        {
            "name": "Customer analytics",
            "description": "Tracking customer pour tendances et recommandations",
        },
        {
            "name": "Customer params",
            "description": "Langue et coordonnées par défaut du client",
        },
    ]
)


# Événements application: initialisation et fermeture de Redis (désactivables en DEV)
USE_REDIS = os.getenv("APP_ENV", "dev").strip().lower() == "prod"

if USE_REDIS:
    @app.on_event("startup")
    async def _on_startup() -> None:
        await init_redis(app)

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:
        await close_redis(app)
else:
    @app.on_event("startup")
    async def _on_startup() -> None:
        # Redis désactivé en DEV
        return None

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:
        # Redis désactivé en DEV
        return None


# Configuration CORS
# Autoriser les requêtes depuis les applications Angular (local et production)
origins = [
    "http://localhost:4200",  # Admin

    # Domaines Vercel (production et previews)
    "https://*.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.vercel\.app",  # Autoriser tous les domaines Vercel (previews, branches, etc.)
    allow_credentials=True,
    allow_methods=["*"],  # Autoriser toutes les méthodes (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Autoriser tous les headers
)


@app.exception_handler(MessagingNotConfiguredError)
async def messaging_schema_missing_handler(
    _request: Request, exc: MessagingNotConfiguredError
) -> JSONResponse:
    """Migration messagerie absente sur le projet Supabase lié (PGRST205)."""
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc)},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    def field_path(location: tuple[object, ...]) -> str:
        parts = [part for part in location if part not in ("body", "query", "path")]
        if not parts:
            return "requete"
        result = ""
        for part in parts:
            if isinstance(part, int):
                result += f"[{part}]"
            else:
                result += f".{part}" if result else str(part)
        return result

    def clear_message(error: dict) -> str:
        error_type = str(error.get("type") or "")
        context = error.get("ctx") or {}
        messages = {
            "missing": "Ce champ est obligatoire.",
            "uuid_parsing": "La valeur doit etre un UUID valide.",
            "uuid_type": "La valeur doit etre un UUID valide.",
            "datetime_parsing": "La valeur doit etre une date ISO 8601 valide.",
            "datetime_from_date_parsing": "La valeur doit etre une date ISO 8601 valide.",
            "decimal_parsing": "La valeur doit etre un nombre valide.",
            "decimal_type": "La valeur doit etre un nombre valide.",
            "int_parsing": "La valeur doit etre un entier valide.",
            "int_type": "La valeur doit etre un entier valide.",
            "list_type": "La valeur doit etre une liste.",
            "enum": "La valeur ne fait pas partie des choix autorises.",
        }
        if error_type == "greater_than_equal":
            return f"La valeur doit etre superieure ou egale a {context.get('ge')}."
        if error_type == "less_than_equal":
            return f"La valeur doit etre inferieure ou egale a {context.get('le')}."
        if error_type in {"too_short", "list_too_short"}:
            minimum = context.get("min_length")
            return f"La liste doit contenir au moins {minimum or 1} element(s)."
        if error_type in {"string_too_long", "too_long"}:
            maximum = context.get("max_length")
            return f"La valeur depasse la longueur maximale autorisee ({maximum})."
        if error_type == "value_error":
            message = str(error.get("msg") or "Valeur invalide.")
            return message.removeprefix("Value error, ")
        return messages.get(error_type, str(error.get("msg") or "Valeur invalide."))

    errors = []
    for raw_error in exc.errors():
        error = dict(raw_error)
        error["field"] = field_path(tuple(error.get("loc") or ()))
        error["message"] = clear_message(error)
        errors.append(error)

    if len(errors) == 1:
        summary = f"{errors[0]['field']}: {errors[0]['message']}"
    else:
        summary = (
            f"La requete contient {len(errors)} erreurs de validation. "
            "Consultez detail.errors pour les corriger."
        )
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "validation_error",
                "message": summary,
                "method": request.method,
                "path": request.url.path,
                "errors": jsonable_encoder(errors),
            }
        },
    )


# Inclusion des routes
app.include_router(share_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(admin_router)
app.include_router(player_router)
app.include_router(organizations_router)
app.include_router(organization_subscriptions_router)
app.include_router(stripe_router)
app.include_router(members_router)
app.include_router(organization_articles_router)
app.include_router(shop_articles_router)
app.include_router(shop_stock_resources_router)
app.include_router(organization_article_orders_router)
app.include_router(organization_shop_article_orders_router)
app.include_router(performance_router)
app.include_router(messaging_router)
app.include_router(customer_sales_delivery_router)
app.include_router(customer_sales_customer_router)
app.include_router(customer_sales_org_router)
app.include_router(customer_sales_shop_org_router)
app.include_router(organization_repairs_router)
app.include_router(organization_rentals_router)
app.include_router(delivery_realtime_router)
