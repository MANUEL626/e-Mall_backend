"""
Configuration du client Supabase pour le projet
Ce fichier peut être importé dans n'importe quel module du projet
"""

import os

from dotenv import load_dotenv
from supabase import Client, ClientOptions, create_client

# Charger les variables d'environnement depuis un fichier .env
load_dotenv()

# Configuration Supabase depuis les variables d'environnement
SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "http://127.0.0.1:54321"  # URL par défaut pour Supabase local
)

SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    # Clé anon par défaut pour Supabase local (développement uniquement)
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
)

SUPABASE_SERVICE_KEY = os.getenv(
    "SUPABASE_SERVICE_KEY",
    # Clé service par défaut pour Supabase local (développement uniquement)
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU"
)

# Secret partagé mobile ↔ backend (Authorization: Bearer …). Ce n’est pas le JWT Supabase.
# En prod : définir INTERNAL_API_BEARER dans .env (valeur longue et aléatoire).
_INTERNAL_API_BEARER_RAW = os.getenv("INTERNAL_API_BEARER", "").strip()
INTERNAL_API_BEARER = (
    _INTERNAL_API_BEARER_RAW if _INTERNAL_API_BEARER_RAW else "dev-internal-bearer"
)


def get_supabase_client(use_service_key: bool = False) -> Client:
    """
    Crée et retourne une instance du client Supabase

    Args:
        use_service_key (bool): Si True, utilise la SERVICE_KEY (bypass RLS).
                                Si False, utilise la ANON_KEY (respecte RLS).
                                Par défaut: False

    Returns:
        Client: Instance du client Supabase

    Note:
        - ANON_KEY: Pour les opérations normales qui respectent les politiques RLS
        - SERVICE_KEY: Pour les opérations administratives qui bypassent RLS
                      ⚠️ À utiliser avec précaution, uniquement côté serveur !
    """
    key = SUPABASE_SERVICE_KEY if use_service_key else SUPABASE_ANON_KEY
    return create_client(SUPABASE_URL, key)


def get_supabase_client_with_token(access_token: str) -> Client:
    """
    Crée un client Supabase dont les requêtes PostgREST envoient le JWT utilisateur dans
    ``Authorization: Bearer <access_token>`` (RLS : ``auth.uid()`` = l’utilisateur du token).

    Important : on n’utilise pas ``auth.set_session()`` ici. ``set_session`` déclenche un appel
    ``GET /auth/v1/user`` sur GoTrue ; en cas d’erreur réseau / 520, le JWT n’était pas appliqué
    aux appels ``rest/v1``, donc la RLS masquait les lignes et ``.single()`` sur ``users`` renvoyait
    **406 Not Acceptable** (PostgREST : 0 ligne avec ``Accept: application/vnd.pgrst.object+json``).

    En passant le Bearer via ``ClientOptions``, ``create_client`` n’essaie pas de résoudre la session
    GoTrue et PostgREST reçoit directement le bon en-tête.
    """
    token = access_token.replace("Bearer ", "").strip() if access_token else ""

    if not token:
        return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

    options = ClientOptions(
        persist_session=False,
        auto_refresh_token=False,
    )
    options.headers = {**options.headers, "Authorization": f"Bearer {token}"}
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options)


# Instance globale du client avec ANON_KEY (par défaut, respecte RLS)
# Pour les opérations normales de l'application
supabase: Client = get_supabase_client(use_service_key=False)

# Instance globale du client avec SERVICE_KEY (bypass RLS)
# ⚠️ À utiliser uniquement pour les opérations administratives côté serveur
supabase_admin: Client = get_supabase_client(use_service_key=True)

