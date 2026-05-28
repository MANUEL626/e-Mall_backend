from pathlib import Path

from fastapi import FastAPI, Request
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
)
from features.organization_article_orders.article_orders_route import (
    router as organization_article_orders_router,
)
from features.organization_articles.organization_articles_route import (
    router as organization_articles_router,
)
from features.share.share_route import router as share_router
from features.members.members_route import router as members_router
from features.organizations.organizations_route import router as organizations_router
from features.organization_subscriptions.organization_subscriptions_route import (
    router as organization_subscriptions_router,
)
from features.performance.performance_route import router as performance_router
from features.users.users_route import router as users_router


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


# Inclusion des routes
app.include_router(share_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(admin_router)
app.include_router(player_router)
app.include_router(organizations_router)
app.include_router(organization_subscriptions_router)
app.include_router(members_router)
app.include_router(organization_articles_router)
app.include_router(organization_article_orders_router)
app.include_router(performance_router)
app.include_router(messaging_router)
app.include_router(customer_sales_delivery_router)
app.include_router(customer_sales_customer_router)
app.include_router(customer_sales_org_router)
