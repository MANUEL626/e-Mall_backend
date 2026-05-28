"""
Routes : posts promotionnels par article (JWT membre).
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_service import AuthService
from features.organization_article_posts.organization_article_posts_models import (
    OrganizationArticlePostResponse,
    OrganizationArticlePostUpsert,
)
from features.organization_article_posts.organization_article_posts_service import (
    OrganizationArticlePostsService,
)

# Enfant de `organization_articles_route` : préfixe `/{article_id}/posts` (pas d’URL absolue ici).
router = APIRouter(tags=["Organization article posts"])

security = HTTPBearer()
_service = OrganizationArticlePostsService()
_auth = AuthService()


def _current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    try:
        return _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


@router.get("", response_model=List[OrganizationArticlePostResponse])
def list_article_posts(
    organization_id: UUID,
    article_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Liste les posts pour un article."""
    uid = _current_user_id(credentials)
    try:
        rows = _service.list_posts(uid, str(organization_id), str(article_id))
        return [OrganizationArticlePostResponse.model_validate(r) for r in rows]
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


@router.put(
    "/{slot}",
    response_model=OrganizationArticlePostResponse,
)
def upsert_article_post(
    organization_id: UUID,
    article_id: UUID,
    body: OrganizationArticlePostUpsert,
    background_tasks: BackgroundTasks,
    slot: int = Path(..., ge=1, description="Emplacement du post, entier >= 1"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Crée ou met à jour le post à l'emplacement `slot`.
    Uploader le média dans le bucket `organization-article-posts` sous `{organization_id}/…`.
    """
    uid = _current_user_id(credentials)
    try:
        row = _service.upsert_post(
            uid,
            str(organization_id),
            str(article_id),
            slot,
            body,
            background_tasks,
        )
        return OrganizationArticlePostResponse.model_validate(row)
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


@router.delete("/{slot}", status_code=status.HTTP_204_NO_CONTENT)
def delete_article_post(
    organization_id: UUID,
    article_id: UUID,
    slot: int = Path(..., ge=1),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uid = _current_user_id(credentials)
    try:
        _service.delete_post(uid, str(organization_id), str(article_id), slot)
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
