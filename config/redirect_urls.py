"""
Configuration des URLs de redirection selon le type d'utilisateur.

IMPORTANT - Supabase : chaque URL ci-dessous doit être ajoutée dans
Supabase Dashboard → Authentication → URL Configuration → Redirect URLs.
Sinon Supabase ignore notre redirect et utilise la Site URL (souvent localhost:3000).
Voir docs/SUPABASE_REDIRECT_URLS.md.

Pour les tenants (app mobile Flutter) : deep link pour ouvrir l'app après
confirmation email ou OAuth. Doit correspondre à :
- Android (intent-filter) et iOS (CFBundleURLTypes)
- Supabase Dashboard → Redirect URLs (ex. com.example.eho://login-callback)
- Flutter _handleDeepLink (scheme + host)
"""

import os

# Deep link de l'app mobile (tenants). Même valeur que dans l'app Flutter et Supabase.
# Ex. com.example.eho://login-callback
TENANT_MOBILE_DEEP_LINK = os.getenv(
    "TENANT_REDIRECT_DEEP_LINK",
    "com.example.eho://login-callback",
).strip()

# Mapping direct des types d'utilisateurs vers leurs URLs de redirection (sans relais)
REDIRECT_URLS_BY_USER_TYPE = {
    "admin": "http://localhost:4300",
    "owner": "http://localhost:4200",
    "commercial": "http://localhost:4100",
    # Tenant = app Flutter : après confirmation email, redirection vers l'app via deep link
    "tenant": TENANT_MOBILE_DEEP_LINK,
}

# URL par défaut si le type n'est pas trouvé
DEFAULT_REDIRECT_URL = "http://localhost:3000"

# Mode relais : une seule origine à whitelister dans Supabase (comme en Nuxt).
# Si défini, toutes les redirections passent par {AUTH_CONFIRM_BASE_URL}/auth/confirm?target=<type>
# La page relais (static/auth_confirm.html) redirige ensuite vers la bonne URL (deep link ou web).
# Ex. http://localhost:8080 ou https://votredomaine.com
AUTH_CONFIRM_BASE_URL = os.getenv("AUTH_CONFIRM_BASE_URL", "").strip().rstrip("/")


def get_redirect_url_for_user_type(user_type: str) -> str:
    """
    Retourne l'URL de redirection pour un type d'utilisateur donné.

    Si AUTH_CONFIRM_BASE_URL est défini : utilise la page relais
    (une seule origine à ajouter dans Supabase Redirect URLs).
    Sinon : utilise l'URL directe (chaque URL doit être dans la whitelist Supabase).

    Args:
        user_type: Type d'utilisateur ('admin', 'owner', 'commercial', 'tenant')

    Returns:
        URL de redirection pour ce type d'utilisateur
    """
    ut = user_type.lower()
    if AUTH_CONFIRM_BASE_URL:
        return f"{AUTH_CONFIRM_BASE_URL}/auth/confirm?target={ut}"
    return REDIRECT_URLS_BY_USER_TYPE.get(ut, DEFAULT_REDIRECT_URL)













