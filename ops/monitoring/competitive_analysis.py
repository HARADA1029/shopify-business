# ============================================================
# 競合比較モジュール（軽量版）
#
# 定期実行ごとに競合サイトのトップページを取得し、
# 前回との差分を検出して改善提案を生成する。
#
# 安全ルール: 読み取り専用。提案のみ。
# ============================================================

import json
import os
import re
import hashlib
from datetime import datetime, timezone, timedelta

import requests

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

COMPETITOR_CACHE = os.path.join(SCRIPT_DIR, "competitor_cache.json")

# 競合サイト一覧
COMPETITORS = {
    "solaris_japan": {
        "name": "Solaris Japan",
        "url": "https://solarisjapan.com/",
        "type": "shopify",
    },
    "japan_figure": {
        "name": "Japan Figure Store",
        "url": "https://japan-figure.com/",
        "type": "shopify",
    },
    "super_anime": {
        "name": "Super Anime Store",
        "url": "https://superanimestore.com/",
        "type": "shopify",
    },
}

HEADERS = {"User-Agent": "HD-Toys-CompetitiveAnalysis/1.0"}


def _load_cache():
    if not os.path.exists(COMPETITOR_CACHE):
        return {}
    try:
        with open(COMPETITOR_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_cache(cache):
    with open(COMPETITOR_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _extract_features(html):
    """HTML からサイトの特徴を抽出する"""
    features = {}
    html_lower = html.lower()

    # プロモーション・バナーテキスト
    promos = re.findall(r'(?:free shipping|sale|discount|% off|coupon|new arrival|limited)[^<]{0,50}', html_lower)
    features["promotions"] = list(set(p.strip()[:60] for p in promos[:5]))

    # レビュー関連
    features["has_reviews"] = any(kw in html_lower for kw in ["review", "trustpilot", "judge.me", "star-rating"])

    # 信頼訴求
    features["has_trust_badges"] = any(kw in html_lower for kw in ["shipped from japan", "authentic", "inspected", "verified"])

    # ニュースレター
    features["has_newsletter"] = any(kw in html_lower for kw in ["newsletter", "subscribe", "email signup", "join our"])

    # コレクション数（リンク数で推定）
    collection_links = re.findall(r'href="[^"]*collection[^"]*"', html_lower)
    features["collection_count"] = len(set(collection_links))

    # ソーシャルリンク
    social_platforms = ["instagram", "facebook", "twitter", "tiktok", "youtube", "pinterest"]
    features["social_links"] = [p for p in social_platforms if p in html_lower]

    # ページサイズ（コンテンツ量の指標）
    features["page_size_kb"] = len(html) // 1024

    # ハッシュ（変更検出用）
    features["content_hash"] = hashlib.md5(html.encode()[:5000]).hexdigest()

    return features


def fetch_competitor_data():
    """競合サイトの最新データを取得する"""
    cache = _load_cache()
    results = {}

    for key, comp in COMPETITORS.items():
        try:
            resp = requests.get(comp["url"], headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                features = _extract_features(resp.text)
                features["fetched_at"] = NOW.strftime("%Y-%m-%d %H:%M")
                features["status"] = "ok"

                # 前回との差分を検出
                prev = cache.get(key, {})
                if prev.get("content_hash") and prev["content_hash"] != features["content_hash"]:
                    features["changed_since_last"] = True
                else:
                    features["changed_since_last"] = False

                results[key] = features
            else:
                results[key] = {"status": "error", "http_code": resp.status_code}
        except Exception as e:
            results[key] = {"status": "error", "error": str(e)[:60]}

    # キャッシュを更新
    for key, data in results.items():
        if data.get("status") == "ok":
            cache[key] = data
    cache["_last_updated"] = NOW.strftime("%Y-%m-%d %H:%M")
    _save_cache(cache)

    return results


def compare_with_self(competitor_data, products):
    """競合データと自社を比較して改善提案を生成"""
    findings = []

    if not competitor_data:
        return findings

    # 自社の特徴
    self_features = {
        "has_reviews": False,  # レビュー機能なし
        "has_newsletter": False,  # ニュースレター登録なし
        "has_trust_badges": True,  # Shipped from Japan あり
        "collection_count": 8,
        "product_count": len(products) if products else 0,
    }

    suggestions = []
    changes = []

    for key, data in competitor_data.items():
        if data.get("status") != "ok":
            continue

        name = COMPETITORS[key]["name"]

        # レビュー機能
        if data.get("has_reviews") and not self_features["has_reviews"]:
            suggestions.append("[vs %s] Add product reviews (Judge.me or similar)" % name)

        # ニュースレター
        if data.get("has_newsletter") and not self_features["has_newsletter"]:
            suggestions.append("[vs %s] Add newsletter signup with first-order discount" % name)

        # プロモーション
        promos = data.get("promotions", [])
        if promos:
            for p in promos[:2]:
                suggestions.append("[vs %s] Promotion detected: \"%s\"" % (name, p[:50]))

        # ページ変更検出
        if data.get("changed_since_last"):
            changes.append("%s: site updated since last check" % name)

    # 重複を除去
    suggestions = list(dict.fromkeys(suggestions))

    if suggestions:
        findings.append({
            "type": "medium_term", "agent": "competitive-intelligence",
            "message": "Competitive insights: %d improvement ideas from %d competitors" % (len(suggestions), len(competitor_data)),
            "details": suggestions[:5],
        })

    if changes:
        findings.append({
            "type": "info", "agent": "competitive-intelligence",
            "message": "Competitor changes detected: %d sites updated" % len(changes),
            "details": changes,
        })

    return findings


# ============================================================
# UI/UX 継続改善ループ
# ============================================================

def analyze_uiux_gaps(competitor_data):
    """競合のUI/UX要素と自社を比較し、改善案を生成する"""
    findings = []

    if not competitor_data:
        return findings

    # 自社の現状（定期更新）
    self_uiux = {
        "hero_type": "product_photo",
        "color_scheme": "white_base_green_accent",
        "trust_badges": True,
        "reviews": False,
        "condition_labels": False,
        "newsletter_popup": False,
        "quick_view": False,
        "loyalty_program": False,
        "multi_language": False,
        "media_mentions": False,
    }

    gap_suggestions = []

    for key, data in competitor_data.items():
        if data.get("status") != "ok":
            continue

        name = COMPETITORS[key]["name"]

        # レビュー機能
        if data.get("has_reviews") and not self_uiux["reviews"]:
            gap_suggestions.append({
                "element": "Product reviews",
                "competitor": name,
                "self_status": "Not implemented",
                "action": "Add Judge.me or Shopify Product Reviews app",
                "priority": "high",
                "impact": "Trust + CVR improvement",
            })

        # ニュースレター
        if data.get("has_newsletter") and not self_uiux["newsletter_popup"]:
            gap_suggestions.append({
                "element": "Newsletter signup",
                "competitor": name,
                "self_status": "Not implemented",
                "action": "Add email capture with first-order incentive",
                "priority": "medium",
                "impact": "Customer retention + repeat visits",
            })

        # プロモーション表示
        promos = data.get("promotions", [])
        for p in promos[:1]:
            if "free shipping" in p.lower():
                gap_suggestions.append({
                    "element": "Free shipping promotion",
                    "competitor": name,
                    "self_status": "No shipping promotion displayed",
                    "action": "Add shipping threshold banner (e.g. Free shipping over $XX)",
                    "priority": "medium",
                    "impact": "AOV increase + conversion",
                })
                break

    # 重複除去（element ベース）
    seen = set()
    unique = []
    for s in gap_suggestions:
        if s["element"] not in seen:
            seen.add(s["element"])
            unique.append(s)

    if unique:
        details = []
        for s in unique[:3]:
            details.append(
                "[%s] %s: %s (ref: %s)" % (s["priority"], s["element"], s["action"][:50], s["competitor"])
            )

        findings.append({
            "type": "action", "agent": "competitive-intelligence",
            "message": "UI/UX improvement: %d gaps found vs competitors" % len(unique),
            "details": details,
        })

    return findings


def check_self_uiux():
    """自社サイトのUI/UX状態を確認する"""
    findings = []

    import requests as _req

    checks = []

    # Shopify トップページ確認
    try:
        resp = _req.get("https://hd-toys-store-japan.myshopify.com/", headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            html = resp.text.lower()

            if "trust-badge" not in html:
                checks.append("[Shopify] Trust badge bar not rendering")
            if "shipped from japan" not in html:
                checks.append("[Shopify] 'Shipped from Japan' not visible on top page")

            # CTA ボタンの視認性
            import re
            buttons = re.findall(r'class="[^"]*button[^"]*"', html)
            if len(buttons) < 2:
                checks.append("[Shopify] Few CTA buttons visible on top page")

    except Exception:
        checks.append("[Shopify] Top page check failed")

    # hd-bodyscience.com 確認
    try:
        resp = _req.get("https://hd-bodyscience.com/", headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            html = resp.text.lower()

            if "browse by category" not in html:
                checks.append("[Blog] Category navigation block missing")
            if "hd-toys-store-japan" not in html:
                checks.append("[Blog] Shopify link not on top page")

    except Exception:
        checks.append("[Blog] Top page check failed")

    if checks:
        findings.append({
            "type": "suggestion", "agent": "store-setup",
            "message": "Self UI/UX check: %d issues found" % len(checks),
            "details": checks[:5],
        })
    else:
        findings.append({
            "type": "ok", "agent": "store-setup",
            "message": "Self UI/UX check: All elements rendering correctly",
        })

    return findings


# ============================================================
# メインエントリポイント
# ============================================================

def run_competitive_analysis(products):
    """競合比較 + UI/UX改善ループを実行して提案を返す"""
    competitor_data = fetch_competitor_data()
    findings = compare_with_self(competitor_data, products)
    findings.extend(analyze_uiux_gaps(competitor_data))
    findings.extend(check_self_uiux())
    return findings
