"""
CRUD posts promo par article (service role après contrôle membre actif).
"""

from typing import Any, Dict, List

from supabase import Client

from config.supabase_client import supabase_admin
from features.organization_article_posts.organization_article_posts_models import (
    OrganizationArticlePostUpsert,
)
from features.organization_articles.organization_articles_service import (
    OrganizationArticlesService,
)


class OrganizationArticlePostsService:
    _BUCKET_PREFIX_RULE = (
        "Le média doit utiliser le préfixe {organization_id}/… "
        "dans le bucket organization-article-posts"
    )

    def __init__(self) -> None:
        self.db: Client = supabase_admin
        self._articles = OrganizationArticlesService()

    @staticmethod
    def _org_path_prefix(organization_id: str) -> str:
        return f"{organization_id.strip()}/"

    def _assert_media_path_belongs_to_org(self, organization_id: str, path: str) -> None:
        prefix = self._org_path_prefix(organization_id)
        if not path.strip().startswith(prefix):
            raise ValueError(self._BUCKET_PREFIX_RULE.format(organization_id=organization_id))

    def list_posts(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
    ) -> List[Dict[str, Any]]:
        self._articles.assert_org_member(user_id, organization_id)
        self._articles.get_article(user_id, organization_id, article_id)
        res = (
            self.db.table("organization_article_posts")
            .select("*")
            .eq("organization_article_id", article_id)
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
    ) -> Dict[str, Any]:
        self._articles.assert_org_member(user_id, organization_id)
        self._articles.get_article(user_id, organization_id, article_id)
        oid = str(organization_id)
        self._assert_media_path_belongs_to_org(oid, body.media_storage_path)

        payload: Dict[str, Any] = {
            "organization_article_id": str(article_id),
            "slot": slot,
            "media_kind": body.media_kind.value,
            "media_storage_path": body.media_storage_path.strip(),
            "caption": body.caption,
            "active": body.active,
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
            upd = (
                self.db.table("organization_article_posts")
                .update(
                    {
                        "media_kind": payload["media_kind"],
                        "media_storage_path": payload["media_storage_path"],
                        "caption": payload["caption"],
                        "active": payload["active"],
                    }
                )
                .eq("id", rows[0]["id"])
                .execute()
            )
            out = upd.data or []
            if out:
                return out[0]
        else:
            ins = self.db.table("organization_article_posts").insert(payload).execute()
            out = ins.data or []
            if out:
                return out[0]

        raise RuntimeError("Enregistrement du post refusé")

    def delete_post(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
        slot: int,
    ) -> None:
        self._articles.assert_org_member(user_id, organization_id)
        self._articles.get_article(user_id, organization_id, article_id)
        self.db.table("organization_article_posts").delete().eq(
            "organization_article_id", str(article_id)
        ).eq("slot", slot).execute()
