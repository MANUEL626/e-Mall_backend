"""
Routes CRUD : articles / stock par organisation (JWT membre).
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_service import AuthService
from features.organization_articles.organization_articles_models import (
    OrganizationArticleCreate,
    OrganizationArticleResponse,
    OrganizationArticleUpdate,
)
from features.organization_article_posts.organization_article_posts_models import (
    OrganizationArticlePostResponse,
)
from features.organization_article_posts.organization_article_posts_route import (
    router as organization_article_posts_router,
)
from features.organization_article_posts.organization_article_posts_service import (
    OrganizationArticlePostsService,
)
from features.organization_articles.organization_articles_service import (
    OrganizationArticlesService,
)

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/articles",
    tags=["Organization articles"],
)

security = HTTPBearer()
_service = OrganizationArticlesService()
_posts_service = OrganizationArticlePostsService()
_auth = AuthService()

# Sous-ressource : `/articles/{article_id}/posts` — enregistré avant `GET /{article_id}` pour éviter
# tout conflit de matching avec le détail article.
router.include_router(
    organization_article_posts_router,
    prefix="/{article_id}/posts",
)


def _current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    try:
        return _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


@router.get("", response_model=List[OrganizationArticleResponse])
def list_organization_articles(
    organization_id: UUID,
    active_only: Optional[bool] = Query(
        None,
        description="Si true/false, filtre sur `active` ; si omis, tous les articles.",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Liste les articles de l'organisation (membre actif requis)."""
    uid = _current_user_id(credentials)
    try:
        rows = _service.list_articles(
            uid, str(organization_id), active_only=active_only
        )
        return [OrganizationArticleResponse.model_validate(r) for r in rows]
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get("/posts/batch", response_model=List[OrganizationArticlePostResponse])
def list_organization_article_posts_batch(
    organization_id: UUID,
    article_ids: List[UUID] = Query(
        ...,
        min_length=1,
        description="IDs d'articles a charger en une requete. Repeter article_ids=... pour chaque article.",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Liste les posts de plusieurs articles sans faire un appel par article."""
    uid = _current_user_id(credentials)
    try:
        rows = _posts_service.list_posts_for_articles(
            uid,
            str(organization_id),
            [str(article_id) for article_id in article_ids],
        )
        return [OrganizationArticlePostResponse.model_validate(row) for row in rows]
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/{article_id}", response_model=OrganizationArticleResponse)
def get_organization_article(
    organization_id: UUID,
    article_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uid = _current_user_id(credentials)
    try:
        row = _service.get_article(uid, str(organization_id), str(article_id))
        return OrganizationArticleResponse.model_validate(row)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "",
    response_model=OrganizationArticleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_organization_article(
    organization_id: UUID,
    body: OrganizationArticleCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Crée un article. Uploader d'abord les images dans le bucket `organization-articles`
    sous `{organization_id}/…` (JWT membre), puis renseigner les chemins.
    """
    uid = _current_user_id(credentials)
    try:
        row = _service.create_article(uid, str(organization_id), body)
        return OrganizationArticleResponse.model_validate(row)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.patch("/{article_id}", response_model=OrganizationArticleResponse)
def update_organization_article(
    organization_id: UUID,
    article_id: UUID,
    body: OrganizationArticleUpdate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uid = _current_user_id(credentials)
    try:
        row = _service.update_article(
            uid, str(organization_id), str(article_id), body
        )
        return OrganizationArticleResponse.model_validate(row)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization_article(
    organization_id: UUID,
    article_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uid = _current_user_id(credentials)
    try:
        _service.delete_article(uid, str(organization_id), str(article_id))
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
