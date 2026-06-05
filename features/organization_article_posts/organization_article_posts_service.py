"""
CRUD posts promo par article (service role apres controle membre actif).
"""

from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks
from postgrest.exceptions import APIError
from supabase import Client

from config.supabase_client import supabase_admin
from features.organization_article_posts.organization_article_posts_models import (
    ArticlePostMediaKind,
    OrganizationArticlePostUpsert,
)
from features.organization_article_posts.video_processing_service import (
    VideoProcessingService,
)
from features.organization_articles.organization_articles_service import (
    OrganizationArticlesService,
)
from features.organization_subscriptions.organization_subscriptions_service import (
    OrganizationSubscriptionFeatureDenied,
    OrganizationSubscriptionService,
)


class OrganizationArticlePostsService:
    _BUCKET_PREFIX_RULE = (
        "Le media doit utiliser le prefixe {organization_id}/... "
        "dans le bucket organization-article-posts"
    )

    def __init__(self) -> None:
        self.db: Client = supabase_admin
        self._articles = OrganizationArticlesService()
        self.subscriptions = OrganizationSubscriptionService()
        self._video_processing = VideoProcessingService()

    @staticmethod
    def _org_path_prefix(organization_id: str) -> str:
        return f"{organization_id.strip()}/"

    def _assert_media_path_belongs_to_org(self, organization_id: str, path: str) -> None:
        prefix = self._org_path_prefix(organization_id)
        if not path.strip().startswith(prefix):
            raise ValueError(self._BUCKET_PREFIX_RULE.format(organization_id=organization_id))

    def _assert_article_posts_enabled(self, organization_id: str) -> None:
        try:
            self.subscriptions.assert_feature_enabled(organization_id, "article_posts")
        except OrganizationSubscriptionFeatureDenied as exc:
            raise PermissionError(str(exc)) from exc

    @staticmethod
    def _is_schema_cache_missing_column(exc: APIError) -> bool:
        return (
            getattr(exc, "code", None) == "PGRST204"
            and "video_mobile_low_storage_path" in str(exc)
        )

    def list_posts(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
    ) -> List[Dict[str, Any]]:
        self._articles.assert_org_member(user_id, organization_id)
        self._assert_article_posts_enabled(organization_id)
        self._articles.get_article(user_id, organization_id, article_id)
        res = (
            self.db.table("organization_article_posts")
            .select("*")
            .eq("organization_article_id", article_id)
            .order("slot")
            .execute()
        )
        return list(res.data or [])

    def list_posts_for_articles(
        self,
        user_id: str,
        organization_id: str,
        article_ids: List[str],
    ) -> List[Dict[str, Any]]:
        self._articles.assert_org_member(user_id, organization_id)
        self._assert_article_posts_enabled(organization_id)

        unique_article_ids = list(dict.fromkeys(str(article_id) for article_id in article_ids))
        if not unique_article_ids:
            return []

        articles_res = (
            self.db.table("organization_articles")
            .select("id")
            .eq("organization_id", organization_id)
            .in_("id", unique_article_ids)
            .execute()
        )
        found_ids = {str(row["id"]) for row in (articles_res.data or [])}
        missing_ids = set(unique_article_ids) - found_ids
        if missing_ids:
            raise LookupError("Un ou plusieurs articles sont introuvables dans cette organisation")

        res = (
            self.db.table("organization_article_posts")
            .select("*")
            .in_("organization_article_id", unique_article_ids)
            .order("organization_article_id")
            .order("slot")
            .execute()
        )
        return list(res.data or [])

    def upsert_post(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
        slot: int,
        body: OrganizationArticlePostUpsert,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> Dict[str, Any]:
        self._articles.assert_org_member(user_id, organization_id)
        self._assert_article_posts_enabled(organization_id)
        self._articles.get_article(user_id, organization_id, article_id)

        oid = str(organization_id)
        media_path = body.media_storage_path.strip()
        original_path = (
            body.original_media_storage_path.strip()
            if body.original_media_storage_path
            else media_path
        )
        self._assert_media_path_belongs_to_org(oid, media_path)
        self._assert_media_path_belongs_to_org(oid, original_path)

        is_video = body.media_kind == ArticlePostMediaKind.video
        payload: Dict[str, Any] = {
            "organization_article_id": str(article_id),
            "slot": slot,
            "media_kind": body.media_kind.value,
            "media_storage_path": media_path,
            "original_media_storage_path": original_path,
            "video_mobile_low_storage_path": None,
            "thumbnail_storage_path": None if is_video else media_path,
            "caption": body.caption,
            "active": body.active,
            "processing_status": "pending" if is_video else "ready",
            "processing_error": None,
            "media_width": None,
            "media_height": None,
            "media_duration_seconds": None,
            "media_size_bytes": None,
        }

        existing = (
            self.db.table("organization_article_posts")
            .select("id")
            .eq("organization_article_id", str(article_id))
            .eq("slot", slot)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        if rows:
            try:
                result = (
                    self.db.table("organization_article_posts")
                    .update(
                        {
                            "media_kind": payload["media_kind"],
                            "media_storage_path": payload["media_storage_path"],
                            "original_media_storage_path": payload["original_media_storage_path"],
                            "video_mobile_low_storage_path": payload["video_mobile_low_storage_path"],
                            "thumbnail_storage_path": payload["thumbnail_storage_path"],
                            "caption": payload["caption"],
                            "active": payload["active"],
                            "processing_status": payload["processing_status"],
                            "processing_error": payload["processing_error"],
                            "media_width": payload["media_width"],
                            "media_height": payload["media_height"],
                            "media_duration_seconds": payload["media_duration_seconds"],
                            "media_size_bytes": payload["media_size_bytes"],
                        }
                    )
                    .eq("id", rows[0]["id"])
                    .execute()
                )
            except APIError as exc:
                if self._is_schema_cache_missing_column(exc):
                    raise RuntimeError(
                        "Migration video mobile_low non appliquee ou cache schema Supabase non recharge. "
                        "Executer `supabase db push` puis relancer l'API. Si la migration est deja appliquee, "
                        "executer `NOTIFY pgrst, 'reload schema';` dans Supabase SQL Editor."
                    ) from exc
                raise
        else:
            try:
                result = self.db.table("organization_article_posts").insert(payload).execute()
            except APIError as exc:
                if self._is_schema_cache_missing_column(exc):
                    raise RuntimeError(
                        "Migration video mobile_low non appliquee ou cache schema Supabase non recharge. "
                        "Executer `supabase db push` puis relancer l'API. Si la migration est deja appliquee, "
                        "executer `NOTIFY pgrst, 'reload schema';` dans Supabase SQL Editor."
                    ) from exc
                raise

        out = result.data or []
        if not out:
            raise RuntimeError("Enregistrement du post refuse")

        row = out[0]
        self._enqueue_video_processing(row, background_tasks)
        return row

    def _enqueue_video_processing(
        self,
        row: Dict[str, Any],
        background_tasks: Optional[BackgroundTasks],
    ) -> None:
        if row.get("media_kind") != ArticlePostMediaKind.video.value:
            return
        post_id = str(row.get("id") or "")
        if not post_id:
            return
        if background_tasks is not None:
            background_tasks.add_task(self._video_processing.process_post, post_id)
        else:
            self._video_processing.process_post(post_id)

    def delete_post(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
        slot: int,
    ) -> None:
        self._articles.assert_org_member(user_id, organization_id)
        self._assert_article_posts_enabled(organization_id)
        self._articles.get_article(user_id, organization_id, article_id)
        self.db.table("organization_article_posts").delete().eq(
            "organization_article_id", str(article_id)
        ).eq("slot", slot).execute()
