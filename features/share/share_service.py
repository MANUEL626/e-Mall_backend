"""
Service public pour les pages de partage.

Ces lectures sont volontairement limitees aux articles actifs et aux medias publics.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from config.supabase_client import SUPABASE_URL
from features.customers.customer_catalog_service import CustomerCatalogService


class ShareService:
    ARTICLE_IMAGE_BUCKET = "organization-articles"
    POST_MEDIA_BUCKET = "organization-article-posts"

    def __init__(self) -> None:
        self._catalog = CustomerCatalogService()

    @staticmethod
    def _money_xof(value: Any) -> str:
        amount = Decimal(str(value))
        whole = int(amount)
        return f"{whole:,}".replace(",", " ") + " FCFA"

    @staticmethod
    def public_storage_url(bucket: str, path: Optional[str]) -> Optional[str]:
        if not path:
            return None
        clean = str(path).strip()
        if not clean:
            return None
        if clean.startswith(("http://", "https://")):
            return clean
        base = SUPABASE_URL.rstrip("/")
        encoded_path = quote(clean.lstrip("/"), safe="/")
        return f"{base}/storage/v1/object/public/{bucket}/{encoded_path}"

    def get_share_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        product = self._catalog.get_public_catalog_product(article_id)
        if product is None:
            return None

        posts: List[Dict[str, Any]] = self._catalog.list_public_article_posts(article_id)
        first_post = posts[0] if posts else None

        image_url = self.public_storage_url(
            self.ARTICLE_IMAGE_BUCKET,
            product.get("primary_image_storage_path"),
        )
        media_url = None
        if first_post:
            media_url = self.public_storage_url(
                self.POST_MEDIA_BUCKET,
                first_post.get("media_storage_path"),
            )

        return {
            **product,
            "formatted_price": self._money_xof(product.get("unit_sale_price", 0)),
            "image_url": image_url,
            "media_url": media_url,
            "first_post": first_post,
        }
