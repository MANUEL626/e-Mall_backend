"""Traduction des messages customer selon `customer_params.locale`."""

from typing import Dict, Optional

from config.supabase_client import supabase_admin

SUPPORTED_CUSTOMER_LOCALES = {"fr", "en", "de", "zh"}
DEFAULT_CUSTOMER_LOCALE = "fr"


MESSAGES: Dict[str, Dict[str, str]] = {
    "Compte customer créé, finalisez votre profil.": {
        "en": "Customer account created, complete your profile.",
        "de": "Customer-Konto erstellt, vervollständigen Sie Ihr Profil.",
        "zh": "客户账号已创建，请完善您的资料。",
    },
    "Connexion customer réussie.": {
        "en": "Customer login successful.",
        "de": "Customer-Anmeldung erfolgreich.",
        "zh": "客户登录成功。",
    },
    "Profil client introuvable": {
        "en": "Customer profile not found",
        "de": "Kundenprofil nicht gefunden",
        "zh": "未找到客户资料",
    },
    "Profil player introuvable": {
        "en": "Customer profile not found",
        "de": "Kundenprofil nicht gefunden",
        "zh": "未找到客户资料",
    },
    "Action non autorisée": {
        "en": "Action not allowed",
        "de": "Aktion nicht erlaubt",
        "zh": "操作未授权",
    },
    "Article introuvable ou inactif": {
        "en": "Article not found or inactive",
        "de": "Artikel nicht gefunden oder inaktiv",
        "zh": "商品不存在或未启用",
    },
    "Article introuvable ou indisponible": {
        "en": "Article not found or unavailable",
        "de": "Artikel nicht gefunden oder nicht verfügbar",
        "zh": "商品不存在或不可用",
    },
    "Fournir au moins un filtre : name, category, min_price ou max_price.": {
        "en": "Provide at least one filter: name, category, min_price or max_price.",
        "de": "Geben Sie mindestens einen Filter an: name, category, min_price oder max_price.",
        "zh": "请至少提供一个筛选条件：name、category、min_price 或 max_price。",
    },
    "min_price doit être inférieur ou égal à max_price.": {
        "en": "min_price must be less than or equal to max_price.",
        "de": "min_price muss kleiner oder gleich max_price sein.",
        "zh": "min_price 必须小于或等于 max_price。",
    },
    "Ligne introuvable": {
        "en": "Line not found",
        "de": "Position nicht gefunden",
        "zh": "未找到该条目",
    },
    "Panier introuvable": {
        "en": "Cart not found",
        "de": "Warenkorb nicht gefunden",
        "zh": "未找到购物车",
    },
    "Organisation introuvable": {
        "en": "Organization not found",
        "de": "Organisation nicht gefunden",
        "zh": "未找到组织",
    },
    "Abonnement actif introuvable": {
        "en": "Active subscription not found",
        "de": "Aktives Abonnement nicht gefunden",
        "zh": "未找到有效订阅",
    },
    "Token invalide ou expiré": {
        "en": "Invalid or expired token",
        "de": "Ungültiger oder abgelaufener Token",
        "zh": "令牌无效或已过期",
    },
    "Utilisateur introuvable dans le token": {
        "en": "User not found in token",
        "de": "Benutzer im Token nicht gefunden",
        "zh": "令牌中未找到用户",
    },
    "Token utilisateur manquant": {
        "en": "User token missing",
        "de": "Benutzer-Token fehlt",
        "zh": "缺少用户令牌",
    },
    "Le compte auth doit contenir un numéro de téléphone vérifié": {
        "en": "The auth account must contain a verified phone number",
        "de": "Das Auth-Konto muss eine verifizierte Telefonnummer enthalten",
        "zh": "认证账号必须包含已验证的手机号码",
    },
    "username ne peut pas être vide": {
        "en": "username cannot be empty",
        "de": "username darf nicht leer sein",
        "zh": "用户名不能为空",
    },
    "prenom ne peut pas être vide": {
        "en": "first name cannot be empty",
        "de": "Vorname darf nicht leer sein",
        "zh": "名字不能为空",
    },
    "nom ne peut pas être vide": {
        "en": "last name cannot be empty",
        "de": "Nachname darf nicht leer sein",
        "zh": "姓氏不能为空",
    },
    "Aucun champ à mettre à jour": {
        "en": "No field to update",
        "de": "Kein Feld zum Aktualisieren",
        "zh": "没有要更新的字段",
    },
    "Email ou nom d'utilisateur déjà utilisé par un autre compte": {
        "en": "Email or username already used by another account",
        "de": "E-Mail oder Benutzername wird bereits von einem anderen Konto verwendet",
        "zh": "邮箱或用户名已被其他账号使用",
    },
    "Mise à jour impossible (utilisateur introuvable)": {
        "en": "Update impossible: user not found",
        "de": "Aktualisierung nicht möglich: Benutzer nicht gefunden",
        "zh": "无法更新：未找到用户",
    },
    "Profil client introuvable après bootstrap": {
        "en": "Customer profile not found after bootstrap",
        "de": "Kundenprofil nach Bootstrap nicht gefunden",
        "zh": "初始化后未找到客户资料",
    },
    "Réponse invalide de bootstrap_customer_profile": {
        "en": "Invalid bootstrap_customer_profile response",
        "de": "Ungültige Antwort von bootstrap_customer_profile",
        "zh": "bootstrap_customer_profile 响应无效",
    },
    "Profil utilisateur introuvable après bootstrap": {
        "en": "User profile not found after bootstrap",
        "de": "Benutzerprofil nach Bootstrap nicht gefunden",
        "zh": "初始化后未找到用户资料",
    },
    "Mise à jour customer_params refusée": {
        "en": "Customer settings update refused",
        "de": "Aktualisierung der Kundeneinstellungen abgelehnt",
        "zh": "客户设置更新被拒绝",
    },
    "Articles introuvables pour cette organisation": {
        "en": "Articles not found for this organization",
        "de": "Artikel für diese Organisation nicht gefunden",
        "zh": "未找到该组织的商品",
    },
    "Profil client introuvable": {
        "en": "Customer profile not found",
        "de": "Kundenprofil nicht gefunden",
        "zh": "未找到客户资料",
    },
    "Utiliser l'endpoint marchand walk-in pour ce type": {
        "en": "Use the merchant walk-in endpoint for this type",
        "de": "Verwenden Sie für diesen Typ den Händler-Walk-in-Endpunkt",
        "zh": "此类型请使用商户线下销售接口",
    },
    "Création de commande refusée": {
        "en": "Order creation refused",
        "de": "Bestellerstellung abgelehnt",
        "zh": "订单创建被拒绝",
    },
    "Commande introuvable": {
        "en": "Order not found",
        "de": "Bestellung nicht gefunden",
        "zh": "未找到订单",
    },
    "Flux non applicable": {
        "en": "Flow not applicable",
        "de": "Ablauf nicht anwendbar",
        "zh": "流程不适用",
    },
    "Jeton de réception introuvable ; demander au marchand.": {
        "en": "Receipt token not found; ask the merchant.",
        "de": "Empfangstoken nicht gefunden; wenden Sie sich an den Händler.",
        "zh": "未找到收货令牌；请联系商户。",
    },
    "Code de réception invalide": {
        "en": "Invalid receipt code",
        "de": "Ungültiger Empfangscode",
        "zh": "收货码无效",
    },
    "Cette commande n'est pas une livraison": {
        "en": "This order is not a delivery",
        "de": "Diese Bestellung ist keine Lieferung",
        "zh": "此订单不是配送订单",
    },
    "Commande terminée : envoi de position impossible": {
        "en": "Order completed: sending location is impossible",
        "de": "Bestellung abgeschlossen: Standortübermittlung nicht möglich",
        "zh": "订单已完成：无法发送位置",
    },
}


def normalize_customer_locale(locale: Optional[str]) -> str:
    value = (locale or "").strip().lower()
    return value if value in SUPPORTED_CUSTOMER_LOCALES else DEFAULT_CUSTOMER_LOCALE


def translate_message(message: str, locale: Optional[str]) -> str:
    lang = normalize_customer_locale(locale)
    if lang == DEFAULT_CUSTOMER_LOCALE:
        return message
    translated = MESSAGES.get(message, {}).get(lang)
    return translated or message


class CustomerI18nService:
    def __init__(self) -> None:
        self.db = supabase_admin

    def locale_for_customer_id(self, customer_id: str) -> str:
        res = (
            self.db.table("customer_params")
            .select("locale")
            .eq("customer_id", customer_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return DEFAULT_CUSTOMER_LOCALE
        return normalize_customer_locale(rows[0].get("locale"))

    def locale_for_user_id(self, user_id: str) -> str:
        cres = (
            self.db.table("customers")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = cres.data or []
        if not rows:
            return DEFAULT_CUSTOMER_LOCALE
        return self.locale_for_customer_id(str(rows[0]["id"]))

    def translate_for_customer(self, customer_id: str, message: str) -> str:
        return translate_message(message, self.locale_for_customer_id(customer_id))

    def translate_for_user(self, user_id: str, message: str) -> str:
        return translate_message(message, self.locale_for_user_id(user_id))
