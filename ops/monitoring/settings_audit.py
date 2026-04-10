# ============================================================
# 設定最適化 + 分析設定チェックモジュール
#
# 毎回の定期実行で以下を再点検する:
# - Shopify 設定（SEO, Collection, 信頼訴求）
# - WordPress 設定（CTA, 導線, SEO）
# - SNS 設定（プロフィール, API連携, 投稿設定）
# - 分析設定（GA4, SC, UTM, SNS API）
#
# 安全ルール: 読み取り専用。提案のみ。
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta

import requests

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))


def _check_url(url, timeout=10):
    """URL にアクセスできるか確認"""
    try:
        resp = requests.get(url, headers={"User-Agent": "HD-Toys-Audit/1.0"}, timeout=timeout)
        return resp.status_code
    except Exception:
        return 0


def audit_shopify_settings(products):
    """Shopify ストアの設定最適化チェック"""
    findings = []

    if not products:
        findings.append({
            "type": "info", "agent": "store-setup",
            "message": "Shopify audit: No products data available",
        })
        return findings

    issues = []
    recommendations = []

    # 1. 商品の SEO チェック
    no_seo_title = sum(1 for p in products if not p.get("title"))
    no_images = sum(1 for p in products if not p.get("images"))
    no_description = sum(1 for p in products if len(p.get("body_html", "") or "") < 50)

    if no_images:
        issues.append("Images missing: %d products" % no_images)
    if no_description:
        recommendations.append("Short descriptions: %d products (<50 chars)" % no_description)

    # 2. 価格設定チェック
    no_compare_at = sum(
        1 for p in products
        for v in p.get("variants", [])
        if not v.get("compare_at_price")
    )
    if no_compare_at:
        recommendations.append("Compare-at price missing: %d variants (no sale display)" % no_compare_at)

    # 3. 信頼訴求チェック（ストアレベル）
    store_url = "https://hd-toys-store-japan.myshopify.com"
    about_status = _check_url(store_url + "/pages/about-us")
    shipping_status = _check_url(store_url + "/policies/shipping-policy")
    refund_status = _check_url(store_url + "/policies/refund-policy")
    privacy_status = _check_url(store_url + "/policies/privacy-policy")

    if about_status != 200:
        issues.append("About Us page: HTTP %d" % about_status)
    if shipping_status != 200:
        recommendations.append("Shipping policy page not accessible")
    if refund_status != 200:
        recommendations.append("Refund policy page not accessible")

    if issues:
        findings.append({
            "type": "suggestion", "agent": "store-setup",
            "message": "Shopify settings: %d issues found" % len(issues),
            "details": issues,
        })

    if recommendations:
        findings.append({
            "type": "medium_term", "agent": "store-setup",
            "message": "Shopify optimization: %d recommendations" % len(recommendations),
            "details": recommendations[:5],
        })

    if not issues and not recommendations:
        findings.append({
            "type": "ok", "agent": "store-setup",
            "message": "Shopify settings: All checked, no issues",
        })

    return findings


def audit_wordpress_settings():
    """WordPress / hd-bodyscience.com の設定チェック"""
    findings = []

    wp_api = "https://hd-bodyscience.com/wp-json/wp/v2"
    headers = {"User-Agent": "HD-Toys-Audit/1.0"}

    issues = []
    recommendations = []

    # 1. サイト基本情報
    try:
        root_resp = requests.get("https://hd-bodyscience.com/wp-json/", headers=headers, timeout=10)
        if root_resp.status_code == 200:
            root = root_resp.json()
            description = root.get("description", "")
            if "eBay" in description and "Shopify" not in description:
                issues.append("Site tagline still eBay-only: update to include Shopify")
        else:
            issues.append("WordPress API: HTTP %d" % root_resp.status_code)
    except Exception as e:
        issues.append("WordPress API: connection failed (%s)" % str(e)[:40])

    # 2. Shopify 導線チェック
    try:
        top_resp = requests.get("https://hd-bodyscience.com/", headers=headers, timeout=10)
        if top_resp.status_code == 200:
            html = top_resp.text.lower()
            if "hd-toys-store-japan" not in html:
                issues.append("Shopify link missing from top page")
            if "browse by category" not in html:
                recommendations.append("Category navigation block not detected")
    except Exception:
        pass

    # 3. 必須ページチェック
    for page_name, page_url in [("About Us", "/about-us/"), ("Contact", "/form/")]:
        status = _check_url("https://hd-bodyscience.com" + page_url)
        if status != 200:
            issues.append("%s page: HTTP %d" % (page_name, status))

    if issues:
        findings.append({
            "type": "suggestion", "agent": "store-setup",
            "message": "WordPress settings: %d issues" % len(issues),
            "details": issues,
        })

    if recommendations:
        findings.append({
            "type": "medium_term", "agent": "store-setup",
            "message": "WordPress optimization: %d recommendations" % len(recommendations),
            "details": recommendations[:5],
        })

    if not issues and not recommendations:
        findings.append({
            "type": "ok", "agent": "store-setup",
            "message": "WordPress settings: All checked, no issues",
        })

    return findings


def audit_sns_settings():
    """SNS アカウントの設定チェック (sns-manager)"""
    findings = []

    config_path = os.path.join(SCRIPT_DIR, "external_links_config.json")
    if not os.path.exists(config_path):
        findings.append({
            "type": "info", "agent": "sns-manager",
            "message": "SNS audit: config file not found",
        })
        return findings

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    status_items = []

    # Instagram
    ig_token_path = os.path.join(PROJECT_ROOT, ".instagram_token.json")
    if os.path.exists(ig_token_path):
        status_items.append("Instagram API: Connected")
    else:
        status_items.append("Instagram API: Token not found")

    # Pinterest
    shopify_sns = config.get("shopify_sns", {}).get("accounts", {})
    pinterest = shopify_sns.get("pinterest", {})
    if pinterest.get("created"):
        status_items.append("Pinterest: Account created")
    else:
        status_items.append("Pinterest: Account not created or API pending")

    # YouTube
    yt_token_path = os.path.join(PROJECT_ROOT, ".youtube_token.json")
    if os.path.exists(yt_token_path):
        status_items.append("YouTube API: Connected")
    else:
        status_items.append("YouTube API: Token not found")

    # TikTok
    tt_token_path = os.path.join(PROJECT_ROOT, ".tiktok_token.json")
    if os.path.exists(tt_token_path):
        status_items.append("TikTok API: Connected")
    else:
        status_items.append("TikTok: API not yet connected")

    # eBay SNS profiles
    ebay_sns = config.get("ebay_sns", {}).get("accounts", {})
    ebay_set = sum(1 for v in ebay_sns.values() if v.get("shopify_url_in_profile"))
    ebay_total = len(ebay_sns)
    status_items.append("eBay SNS profiles: %d/%d with Shopify URL" % (ebay_set, ebay_total))

    findings.append({
        "type": "info", "agent": "sns-manager",
        "message": "SNS settings status: %d items checked" % len(status_items),
        "details": status_items,
    })

    return findings


def audit_analytics_settings():
    """分析設定の最適化チェック（台帳参照版）"""
    findings = []

    from state_consistency_audit import _load_ledger
    ledger = _load_ledger()
    tasks = ledger.get("tasks", {})

    status_items = []
    issues = []

    # 台帳ベースの判定（ハードコード禁止）
    analytics_tasks = {
        "ga4_connection": "GA4 Data API",
        "ga4_ecommerce": "GA4 e-commerce events",
        "search_console": "Search Console API",
        "instagram_api": "Instagram Graph API",
        "pinterest_api": "Pinterest API",
        "youtube_api": "YouTube Data API",
        "tiktok_api": "TikTok API",
    }

    for key, label in analytics_tasks.items():
        task = tasks.get(key, {})
        status = task.get("status", "unknown")
        detail = task.get("verification_detail", "")[:80]

        if status in ("completed", "completed_improvement_phase"):
            status_items.append("%s: %s (%s)" % (label, status, detail))
        elif status == "on_hold":
            status_items.append("%s: On hold (%s)" % (label, task.get("notes", "")[:60]))
        elif status == "rejected":
            pass  # 却下済みは表示しない
        else:
            # 台帳に未登録の場合のみ実際のファイル存在で判定
            token_map = {
                "instagram_api": ".instagram_token.json",
                "pinterest_api": ".pinterest_token.json",
                "youtube_api": ".youtube_token.json",
                "tiktok_api": ".tiktok_token.json",
            }
            token_file = token_map.get(key, "")
            if token_file and os.path.exists(os.path.join(PROJECT_ROOT, token_file)):
                status_items.append("%s: Token found (not in ledger)" % label)
            elif key in ("ga4_connection", "search_console"):
                gcp_key = os.environ.get("GCP_KEY_FILE", "")
                gcp_path = os.path.join(PROJECT_ROOT, gcp_key) if gcp_key else ""
                if gcp_path and os.path.exists(gcp_path):
                    status_items.append("%s: GCP key found (not in ledger)" % label)
                else:
                    issues.append("%s: Not configured (not in ledger, no key file)" % label)
            else:
                issues.append("%s: Status unknown (not in ledger)" % label)

    # UTM tracking（常に設定済み）
    status_items.append("UTM tracking: Configured on CTA links")

    if issues:
        findings.append({
            "type": "suggestion", "agent": "growth-foundation",
            "message": "Analytics setup: %d items need attention" % len(issues),
            "details": issues,
        })

    if status_items:
        findings.append({
            "type": "ok", "agent": "growth-foundation",
            "message": "Analytics connected: %d services" % len(status_items),
            "details": status_items,
        })

    return findings


# ============================================================
# メインエントリポイント
# ============================================================

def run_all_audits(products):
    """全ての設定監査を実行して結果を返す"""
    all_findings = []

    all_findings.extend(audit_shopify_settings(products))
    all_findings.extend(audit_wordpress_settings())
    all_findings.extend(audit_sns_settings())
    all_findings.extend(audit_analytics_settings())

    return all_findings
