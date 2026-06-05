"""Service d'agent IA Performance avec fallback OpenRouter/OpenAI/Anthropic."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

from features.performance.performance_agent_models import (
    PerformanceAgentCapabilities,
    PerformanceAgentRequest,
    PerformanceAgentTask,
    PerformanceAgentTaskCapability,
)
from features.performance.performance_models import FinancialPeriod
from features.performance.performance_service import PerformanceService


@dataclass(frozen=True)
class _Candidate:
    provider: str
    model: str
    api_key: str
    key_index: Optional[int] = None


class PerformanceAgentService:
    DEFAULT_FREE_MODELS = [
        "openai/gpt-oss-120b:free",
        "openai/gpt-oss-20b:free",
        "deepseek/deepseek-r1:free",
        "qwen/qwen3-coder:free",
        "openrouter/free",
    ]
    TASKS = {
        PerformanceAgentTask.executive_summary: {
            "description": "Résumé court du dashboard pour dirigeant/vendeur.",
            "preferred_route": "openrouter_free",
            "fallback_route": "premium_then_openrouter_free",
            "system": "Tu es un analyste business e-commerce. Produis un résumé court, utile et vérifiable.",
            "complex": False,
        },
        PerformanceAgentTask.monthly_report: {
            "description": "Rapport mensuel narratif avec points forts, risques et actions.",
            "preferred_route": "premium",
            "fallback_route": "openrouter_free",
            "system": "Tu es un analyste senior. Rédige un rapport mensuel structuré, sans inventer de données.",
            "complex": True,
        },
        PerformanceAgentTask.financial_diagnosis: {
            "description": "Analyse revenus, coûts, marge estimée et limites de devise.",
            "preferred_route": "premium",
            "fallback_route": "openrouter_free",
            "system": "Tu es un contrôleur de gestion. Analyse les finances uniquement avec les chiffres fournis.",
            "complex": True,
        },
        PerformanceAgentTask.trend_analysis: {
            "description": "Analyse des produits tendance et signaux customer.",
            "preferred_route": "openrouter_free",
            "fallback_route": "premium_then_openrouter_free",
            "system": "Tu es un analyste produit. Explique les tendances client avec prudence.",
            "complex": False,
        },
        PerformanceAgentTask.stock_recommendations: {
            "description": "Actions stock: ruptures, stock faible, produits tendance à réassortir.",
            "preferred_route": "openrouter_free",
            "fallback_route": "premium_then_openrouter_free",
            "system": "Tu es un responsable stock. Donne des actions concrètes et courtes.",
            "complex": False,
        },
        PerformanceAgentTask.sales_actions: {
            "description": "Plan d'action commercial à partir des ventes, statuts et produits.",
            "preferred_route": "openrouter_free",
            "fallback_route": "premium_then_openrouter_free",
            "system": "Tu es un conseiller commercial e-commerce. Propose des actions simples et mesurables.",
            "complex": False,
        },
    }

    def __init__(self, performance: Optional[PerformanceService] = None) -> None:
        self.performance = performance or PerformanceService()
        self.timeout = float(os.getenv("AI_AGENT_TIMEOUT_SECONDS", "45"))
        self.openrouter_url = os.getenv(
            "OPENROUTER_BASE_URL",
            "https://openrouter.ai/api/v1/chat/completions",
        )
        self.openai_url = os.getenv(
            "OPENAI_BASE_URL",
            "https://api.openai.com/v1/chat/completions",
        )
        self.anthropic_url = os.getenv(
            "ANTHROPIC_BASE_URL",
            "https://api.anthropic.com/v1/messages",
        )

    def capabilities(self) -> PerformanceAgentCapabilities:
        premium = []
        if self._openai_key():
            premium.append("openai")
        if self._anthropic_key():
            premium.append("anthropic")
        return PerformanceAgentCapabilities(
            free_models=self._free_models(),
            openrouter_keys_configured=len(self._openrouter_keys()),
            premium_providers_configured=premium,
            tasks=[
                PerformanceAgentTaskCapability(
                    task=task,
                    description=str(cfg["description"]),
                    preferred_route=str(cfg["preferred_route"]),
                    fallback_route=str(cfg["fallback_route"]),
                )
                for task, cfg in self.TASKS.items()
            ],
        )

    def run(
        self,
        *,
        user_id: str,
        organization_id: str,
        body: PerformanceAgentRequest,
    ) -> Dict[str, Any]:
        context = self.performance.get_ai_context(
            user_id,
            organization_id,
            body.period,
        )
        candidates = self._candidates_for_task(body.task)
        if not candidates:
            raise RuntimeError(
                "Aucun provider IA configuré. Renseigner OPENROUTER_API_KEY_1 ou OPENAI_API_KEY/ANTHROPIC_API_KEY."
            )

        messages = self._messages(body, context)
        attempts: List[Dict[str, Any]] = []
        for index, candidate in enumerate(candidates):
            try:
                output = self._call_candidate(candidate, messages, body.max_tokens)
                attempts.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "key_index": candidate.key_index,
                        "status": "success",
                        "error": None,
                    }
                )
                return {
                    "generated_at": datetime.now(
                        ZoneInfo(self.performance.DEFAULT_TIMEZONE)
                    ).isoformat(),
                    "organization_id": organization_id,
                    "task": body.task.value,
                    "period_key": body.period.value,
                    "provider": candidate.provider,
                    "model": candidate.model,
                    "key_index": candidate.key_index,
                    "fallback_used": index > 0,
                    "attempts": attempts,
                    "output": output,
                    "context": {
                        "generated_at": context.get("generated_at"),
                        "anomalies": context.get("anomalies", []),
                        "data_keys": sorted((context.get("data") or {}).keys()),
                    },
                }
            except Exception as exc:
                attempts.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "key_index": candidate.key_index,
                        "status": "failed",
                        "error": str(exc)[:500],
                    }
                )

        raise RuntimeError(
            "Tous les modèles IA configurés ont échoué ou sont limités.",
            attempts,
        )

    def _messages(
        self,
        body: PerformanceAgentRequest,
        context: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        cfg = self.TASKS[body.task]
        instructions = "\n".join(str(x) for x in context.get("instructions", []))
        extra = body.extra_instructions.strip() if body.extra_instructions else ""
        user_content = {
            "task": body.task.value,
            "language": body.language,
            "required_output": [
                "Réponse en français sauf demande contraire.",
                "Structure courte avec: synthèse, constats, risques, actions recommandées.",
                "Ne jamais inventer de chiffres; citer les limites si les données manquent.",
            ],
            "backend_instructions": instructions,
            "extra_instructions": extra,
            "performance_context": context,
        }
        return [
            {"role": "system", "content": str(cfg["system"])},
            {
                "role": "user",
                "content": json.dumps(user_content, ensure_ascii=False, default=str),
            },
        ]

    def _candidates_for_task(self, task: PerformanceAgentTask) -> List[_Candidate]:
        cfg = self.TASKS[task]
        free = self._openrouter_candidates()
        premium = self._premium_candidates()
        if cfg.get("complex"):
            return premium + free
        return free + premium

    def _premium_candidates(self) -> List[_Candidate]:
        candidates: List[_Candidate] = []
        anthropic_key = self._anthropic_key()
        if anthropic_key:
            candidates.append(
                _Candidate(
                    provider="anthropic",
                    model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
                    api_key=anthropic_key,
                )
            )
        openai_key = self._openai_key()
        if openai_key:
            candidates.append(
                _Candidate(
                    provider="openai",
                    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    api_key=openai_key,
                )
            )
        return candidates

    def _openrouter_candidates(self) -> List[_Candidate]:
        keys = self._openrouter_keys()
        models = self._free_models()
        candidates = []
        for key_index, key in enumerate(keys, start=1):
            for model in models:
                candidates.append(
                    _Candidate(
                        provider="openrouter",
                        model=model,
                        api_key=key,
                        key_index=key_index,
                    )
                )
        return candidates

    def _call_candidate(
        self,
        candidate: _Candidate,
        messages: List[Dict[str, str]],
        max_tokens: int,
    ) -> str:
        if candidate.provider == "openrouter":
            return self._call_openai_compatible(
                url=self.openrouter_url,
                api_key=candidate.api_key,
                model=candidate.model,
                messages=messages,
                max_tokens=max_tokens,
                extra_headers={
                    "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", ""),
                    "X-Title": os.getenv("OPENROUTER_APP_NAME", "e-Mall Backend"),
                    "X-OpenRouter-Title": os.getenv(
                        "OPENROUTER_APP_NAME",
                        "e-Mall Backend",
                    ),
                },
            )
        if candidate.provider == "openai":
            return self._call_openai_compatible(
                url=self.openai_url,
                api_key=candidate.api_key,
                model=candidate.model,
                messages=messages,
                max_tokens=max_tokens,
            )
        if candidate.provider == "anthropic":
            return self._call_anthropic(candidate, messages, max_tokens)
        raise RuntimeError(f"Provider IA inconnu: {candidate.provider}")

    def _call_openai_compatible(
        self,
        *,
        url: str,
        api_key: str,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        for key, value in (extra_headers or {}).items():
            if value:
                headers[key] = value
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        self._raise_for_ai_error(response)
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Réponse IA sans choices")
        content = ((choices[0].get("message") or {}).get("content") or "").strip()
        if not content:
            raise RuntimeError("Réponse IA vide")
        return content

    def _call_anthropic(
        self,
        candidate: _Candidate,
        messages: List[Dict[str, str]],
        max_tokens: int,
    ) -> str:
        system = messages[0]["content"]
        user_messages = [m for m in messages if m["role"] != "system"]
        response = requests.post(
            self.anthropic_url,
            headers={
                "x-api-key": candidate.api_key,
                "anthropic-version": os.getenv(
                    "ANTHROPIC_VERSION",
                    "2023-06-01",
                ),
                "Content-Type": "application/json",
            },
            json={
                "model": candidate.model,
                "system": system,
                "messages": user_messages,
                "max_tokens": max_tokens,
                "temperature": 0.2,
            },
            timeout=self.timeout,
        )
        self._raise_for_ai_error(response)
        data = response.json()
        parts = data.get("content") or []
        text = "\n".join(
            str(part.get("text") or "")
            for part in parts
            if part.get("type") == "text"
        ).strip()
        if not text:
            raise RuntimeError("Réponse Anthropic vide")
        return text

    @staticmethod
    def _raise_for_ai_error(response: requests.Response) -> None:
        if response.status_code < 400:
            return
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        raise RuntimeError(f"HTTP {response.status_code}: {str(payload)[:400]}")

    @staticmethod
    def _split_csv(value: str) -> List[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def _free_models(self) -> List[str]:
        raw = os.getenv("OPENROUTER_FREE_MODELS", "").strip()
        return self._split_csv(raw) if raw else list(self.DEFAULT_FREE_MODELS)

    def _openrouter_keys(self) -> List[str]:
        keys = []
        for name in (
            "OPENROUTER_API_KEY_1",
            "OPENROUTER_API_KEY_2",
            "OPENROUTER_API_KEY_3",
        ):
            value = os.getenv(name, "").strip()
            if value:
                keys.append(value)
        legacy = os.getenv("OPENROUTER_API_KEY", "").strip()
        if legacy and legacy not in keys:
            keys.append(legacy)
        return keys

    @staticmethod
    def _openai_key() -> str:
        return os.getenv("OPENAI_API_KEY", "").strip()

    @staticmethod
    def _anthropic_key() -> str:
        return os.getenv("ANTHROPIC_API_KEY", "").strip()
