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
# メインエントリポイント
# ============================================================

def run_competitive_analysis(products):
    """競合比較を実行して提案を返す"""
    competitor_data = fetch_competitor_data()
    findings = compare_with_self(competitor_data, products)
    return findings
