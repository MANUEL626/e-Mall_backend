from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# Import des routeurs pour les utilisateurs
from features.admin.admins_route import router as admin_router
from features.customers.customers_route import router as player_router
from features.auth.auth_route import router as auth_router
from features.users.users_route import router as users_router


app = FastAPI(
    title="e-Mall Backend API",
    version="1.0.0",
    description="API pour la gestion d'un e-Market (achat et livraison de produit).",
    openapi_tags=[
        {"name": "Auth", "description": "Authentification et inscription"},
        {"name": "Users", "description": "Gestion des utilisateurs"},
        {"name": "Admins", "description": "Gestion des administrateurs"},
        {"name": "Customers", "description": "Gestion des clients"},
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



# Inclusion des routes
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(admin_router)
app.include_router(player_router)