"""
Endpoints publics pour les liens de partage Flutter.
"""

import os
from html import escape
from typing import List
from uuid import UUID

from fastapi import APIRouter, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from features.share.share_service import ShareService

router = APIRouter(tags=["Share links"])
_service = ShareService()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _csv_env(name: str) -> List[str]:
    raw = _env(name)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _share_base_url() -> str:
    return _env("SHARE_BASE_URL", "http://localhost:8000").rstrip("/")


def _app_scheme() -> str:
    return _env("SHARE_APP_SCHEME", "emall")


def _download_buttons() -> str:
    links = []
    play_store = _env("SHARE_PLAY_STORE_URL")
    app_store = _env("SHARE_APP_STORE_URL")
    if play_store:
        links.append(f'<a class="button secondary" href="{escape(play_store, quote=True)}">Google Play</a>')
    if app_store:
        links.append(f'<a class="button secondary" href="{escape(app_store, quote=True)}">App Store</a>')
    return "\n".join(links)


def _page_shell(title: str, body: str, *, description: str = "", image_url: str = "", url: str = "") -> str:
    safe_title = escape(title)
    safe_description = escape(description)
    safe_image = escape(image_url, quote=True)
    safe_url = escape(url, quote=True)
    image_meta = f'<meta property="og:image" content="{safe_image}" />' if safe_image else ""
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
  <meta name="description" content="{safe_description}" />
  <meta property="og:title" content="{safe_title}" />
  <meta property="og:description" content="{safe_description}" />
  {image_meta}
  <meta property="og:url" content="{safe_url}" />
  <meta property="og:type" content="product" />
  <meta name="twitter:card" content="summary_large_image" />
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; color: #171717; background: #f7f7f4; }}
    main {{ max-width: 720px; margin: 0 auto; padding: 40px 20px; }}
    img {{ width: 100%; max-height: 420px; object-fit: cover; border-radius: 8px; background: #e8e8e2; }}
    h1 {{ margin: 24px 0 8px; font-size: 32px; line-height: 1.15; }}
    p {{ color: #555; font-size: 17px; line-height: 1.5; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 24px; }}
    .button {{ display: inline-flex; align-items: center; min-height: 44px; padding: 0 18px; border-radius: 6px; text-decoration: none; font-weight: 700; color: white; background: #148f65; }}
    .secondary {{ color: #148f65; background: white; border: 1px solid #cfd8d1; }}
  </style>
</head>
<body>
  <main>
    {body}
  </main>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
def share_home() -> HTMLResponse:
    body = f"""
    <h1>e-Mall</h1>
    <p>Decouvrez les articles et les offres des boutiques dans l'application e-Mall.</p>
    <div class="actions">
      <a class="button" href="{escape(_app_scheme(), quote=True)}://">Ouvrir l'application</a>
      {_download_buttons()}
    </div>
    """
    html = _page_shell(
        "e-Mall",
        body,
        description="Decouvrez les articles et les offres des boutiques dans l'application e-Mall.",
        url=f"{_share_base_url()}/",
    )
    return HTMLResponse(html)


@router.get("/new/{article_id}", response_class=HTMLResponse)
def share_new(article_id: UUID) -> Response:
    data = _service.get_share_article(str(article_id))
    if data is None:
        return RedirectResponse(url=f"{_share_base_url()}/", status_code=status.HTTP_302_FOUND)

    title = str(data.get("name") or "Article e-Mall")
    price = str(data.get("formatted_price") or "")
    org = str(data.get("organization_name") or "e-Mall")
    caption = ""
    if data.get("first_post"):
        caption = str(data["first_post"].get("caption") or "")

    description_parts = [part for part in [caption, f"Prix : {price}" if price else "", org] if part]
    description = " - ".join(description_parts)
    public_url = f"{_share_base_url()}/new/{article_id}"
    deep_link = f"{_app_scheme()}://new/{article_id}"
    image_url = str(data.get("image_url") or data.get("media_url") or "")
    image_html = f'<img src="{escape(image_url, quote=True)}" alt="{escape(title, quote=True)}" />' if image_url else ""

    body = f"""
    {image_html}
    <h1>{escape(title)}</h1>
    <p>{escape(description)}</p>
    <div class="actions">
      <a class="button" href="{escape(deep_link, quote=True)}">Ouvrir dans l'application</a>
      {_download_buttons()}
    </div>
    """
    html = _page_shell(
        f"{title} - e-Mall",
        body,
        description=description,
        image_url=image_url,
        url=public_url,
    )
    return HTMLResponse(html)


@router.get("/.well-known/assetlinks.json")
def assetlinks() -> JSONResponse:
    package_name = _env("SHARE_ANDROID_PACKAGE_NAME")
    fingerprints = _csv_env("SHARE_ANDROID_SHA256_CERT_FINGERPRINTS")
    if not package_name or not fingerprints:
        return JSONResponse([])

    return JSONResponse(
        [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": package_name,
                    "sha256_cert_fingerprints": fingerprints,
                },
            }
        ]
    )


@router.get("/.well-known/apple-app-site-association")
def apple_app_site_association() -> JSONResponse:
    app_id = _env("SHARE_IOS_APP_ID")
    details = [{"appID": app_id, "paths": ["/new/*"]}] if app_id else []
    return JSONResponse(
        {
            "applinks": {
                "apps": [],
                "details": details,
            }
        },
        media_type="application/json",
    )
