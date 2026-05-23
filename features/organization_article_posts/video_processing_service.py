"""
Transcodage des videos de posts vers un format mobile-safe.

Le service est volontairement idempotent : relancer le traitement d'un post
reecrit les memes chemins Storage et met a jour la meme ligne.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from supabase import Client

from config.supabase_client import supabase_admin


class VideoProcessingService:
    BUCKET = "organization-article-posts"

    def __init__(self) -> None:
        self.db: Client = supabase_admin

    def process_post(self, post_id: str) -> None:
        post = self._get_post(post_id)
        if not post:
            return
        if post.get("media_kind") != "video":
            return

        original_path = (
            post.get("original_media_storage_path")
            or post.get("media_storage_path")
            or ""
        ).strip()
        if not original_path:
            self._mark_failed(post_id, "Chemin video original manquant")
            return

        ffmpeg = self._binary_path("FFMPEG_BINARY", "ffmpeg")
        ffprobe = self._binary_path("FFPROBE_BINARY", "ffprobe")
        if not ffmpeg or not ffprobe:
            self._mark_failed(post_id, "FFmpeg/ffprobe non installe sur le serveur")
            return

        organization_id = str(post.get("organization_id") or "")
        article_id = str(post.get("organization_article_id") or "")
        processed_path = f"{organization_id}/posts/{article_id}/{post_id}/processed/mobile-low.mp4"
        thumbnail_path = f"{organization_id}/posts/{article_id}/{post_id}/thumb.jpg"

        self._update_post(
            post_id,
            {
                "processing_status": "processing",
                "processing_error": None,
            },
        )

        try:
            with tempfile.TemporaryDirectory(prefix="emall-post-video-") as tmp:
                tmpdir = Path(tmp)
                input_file = tmpdir / "input"
                output_file = tmpdir / "feed.mp4"
                thumbnail_file = tmpdir / "thumb.jpg"

                input_file.write_bytes(self._download(original_path))
                self._run_ffmpeg(ffmpeg, input_file, output_file)
                self._run_thumbnail(ffmpeg, output_file, thumbnail_file)
                metadata = self._probe(ffprobe, output_file)

                self._upload(processed_path, output_file, "video/mp4")
                self._upload(thumbnail_path, thumbnail_file, "image/jpeg")

                self._update_post(
                    post_id,
                    {
                        "media_storage_path": processed_path,
                        "video_mobile_low_storage_path": processed_path,
                        "thumbnail_storage_path": thumbnail_path,
                        "processing_status": "ready",
                        "processing_error": None,
                        "media_width": metadata.get("width"),
                        "media_height": metadata.get("height"),
                        "media_duration_seconds": metadata.get("duration"),
                        "media_size_bytes": output_file.stat().st_size,
                    },
                )
        except Exception as exc:  # pragma: no cover - depend de FFmpeg/Storage
            self._mark_failed(post_id, str(exc)[:500])

    def _get_post(self, post_id: str) -> Optional[Dict[str, Any]]:
        res = (
            self.db.table("organization_article_posts")
            .select(
                "id, organization_article_id, media_kind, media_storage_path, "
                "original_media_storage_path"
            )
            .eq("id", post_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        row = rows[0]
        article = (
            self.db.table("organization_articles")
            .select("organization_id")
            .eq("id", row["organization_article_id"])
            .limit(1)
            .execute()
        )
        article_rows = article.data or []
        row["organization_id"] = article_rows[0].get("organization_id") if article_rows else None
        return row

    def _download(self, path: str) -> bytes:
        data = self.db.storage.from_(self.BUCKET).download(path)
        if isinstance(data, bytes):
            return data
        if hasattr(data, "content"):
            return data.content
        raise RuntimeError("Telechargement Storage impossible")

    @staticmethod
    def _binary_path(env_name: str, executable: str) -> Optional[str]:
        configured = os.getenv(env_name, "").strip()
        if configured:
            return configured if Path(configured).exists() else None
        return shutil.which(executable)

    def _upload(self, path: str, file_path: Path, content_type: str) -> None:
        data = file_path.read_bytes()
        bucket = self.db.storage.from_(self.BUCKET)
        try:
            bucket.upload(
                path,
                data,
                {
                    "content-type": content_type,
                    "x-upsert": "true",
                },
            )
        except Exception:
            bucket.update(
                path,
                data,
                {
                    "content-type": content_type,
                },
            )

    def _run_ffmpeg(self, ffmpeg: str, input_file: Path, output_file: Path) -> None:
        # Old Android hardware decoders are picky about H.264 frame dimensions.
        # Keep both axes multiples of 16 to avoid runtime buffer reconfiguration.
        scale = (
            "fps=24,"
            "scale=384:704:force_original_aspect_ratio=decrease:force_divisible_by=16,"
            "pad=384:704:(ow-iw)/2:(oh-ih)/2,"
            "format=yuv420p"
        )
        command = [
            ffmpeg,
            "-y",
            "-i",
            str(input_file),
            "-vf",
            scale,
            "-c:v",
            "libx264",
            "-profile:v",
            "baseline",
            "-level",
            "3.0",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "veryfast",
            "-crf",
            "27",
            "-maxrate",
            "600k",
            "-bufsize",
            "1200k",
            "-r",
            "24",
            "-bf",
            "0",
            "-refs",
            "1",
            "-g",
            "48",
            "-keyint_min",
            "48",
            "-sc_threshold",
            "0",
            "-x264-params",
            "keyint=48:min-keyint=48:scenecut=0:force-cfr=1:open-gop=0",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-b:a",
            "64k",
            "-movflags",
            "+faststart",
            str(output_file),
        ]
        self._run(command, "Transcodage video impossible")

    def _run_thumbnail(self, ffmpeg: str, input_file: Path, output_file: Path) -> None:
        command = [
            ffmpeg,
            "-y",
            "-ss",
            "00:00:01",
            "-i",
            str(input_file),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(output_file),
        ]
        self._run(command, "Generation miniature impossible")

    def _probe(self, ffprobe: str, file_path: Path) -> Dict[str, Any]:
        command = [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration",
            "-of",
            "json",
            str(file_path),
        ]
        result = self._run(command, "Lecture metadata video impossible")
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams") or []
        stream = streams[0] if streams else {}
        duration = stream.get("duration")
        return {
            "width": stream.get("width"),
            "height": stream.get("height"),
            "duration": float(duration) if duration is not None else None,
        }

    @staticmethod
    def _run(command: list[str], message: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"{message}: {detail[:500]}")
        return result

    def _mark_failed(self, post_id: str, error: str) -> None:
        self._update_post(
            post_id,
            {
                "processing_status": "failed",
                "processing_error": error,
                "active": False,
            },
        )

    def _update_post(self, post_id: str, values: Dict[str, Any]) -> None:
        self.db.table("organization_article_posts").update(values).eq("id", post_id).execute()
