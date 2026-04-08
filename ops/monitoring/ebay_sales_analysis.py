# ============================================================
# eBay 売れ筋分析 → Shopify 展開候補モジュール
#
# 担当: catalog-migration-planner (主担当)
#       competitive-intelligence (補助)
#       price-auditor (価格分析)
#
# 機能:
# 1. eBay API から最近の売上データを取得
# 2. 売れ筋カテゴリ・商品を分析
# 3. Shopify 未展開の候補を特定
# 4. 類似商品・関連作品・周辺需要を推測
# 5. 提案結果を学習に反映
# ============================================================

import json
import os
import re
import base64
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

import requests

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

SALES_CACHE_FILE = os.path.join(SCRIPT_DIR, "ebay_sales_cache.json")

# カテゴリキーワードマッピング
CATEGORY_MAP = {
    "Figures": ["figure", "figuarts", "figma", "nendoroid", "statue", "banpresto", "ichiban kuji", "scale"],
    "Trading Cards": ["card", "tcg", "pokemon card", "promo", "holo", "yu-gi-oh"],
    "Video Games": ["game", "playstation", "nintendo", "console", "gameboy", "ps2", "ps3", "psp"],
    "Electronic Toys": ["tamagotchi", "digital pet", "digivice"],
    "Media & Books": ["manga", "book", "dvd", "blu-ray", "art book", "magazine", "comic"],
    "Plush": ["plush", "stuffed", "doll", "mascot", "cushion"],
    "Action Figures": ["sentai", "power rangers", "beyblade", "gundam", "transformers"],
    "K-Pop / Idol": ["bts", "nct", "seventeen", "stray kids", "twice", "idol", "k-pop"],
}

# 作品・キャラの関連性マッピング（学習で拡張）
FRANCHISE_RELATIONS = {
    "pokemon": ["pikachu", "charizard", "eevee", "mewtwo", "lugia", "gardevoir"],
    "one piece": ["luffy", "zoro", "nami", "shanks", "ace", "sabo"],
    "dragon ball": ["goku", "vegeta", "frieza", "gohan", "piccolo"],
    "naruto": ["naruto", "sasuke", "sakura", "kakashi", "itachi"],
    "attack on titan": ["eren", "levi", "mikasa", "armin"],
    "jojo": ["jotaro", "dio", "giorno", "jolyne", "josuke"],
    "ghibli": ["totoro", "chihiro", "howl", "kiki", "mononoke"],
    "digimon": ["agumon", "wargreymon", "gabumon", "patamon"],
    "power rangers": ["sentai", "megazord", "morpher", "ranger"],
}


def _get_ebay_user_token():
    """eBay ユーザートークンを取得（必要ならリフレッシュ）"""
    token_path = os.path.join(PROJECT_ROOT, ".ebay_token.json")
    if not os.path.exists(token_path):
        return None

    with open(token_path, "r") as f:
        token_data = json.load(f)

    token = token_data.get("access_token", "")

    # テストリクエスト
    test_resp = requests.get(
        "https://api.ebay.com/sell/fulfillment/v1/order?limit=1",
        headers={"Authorization": "Bearer %s" % token},
        timeout=10,
    )

    if test_resp.status_code == 401:
        # リフレッシュ
        from dotenv import dotenv_values
        env = dotenv_values(os.path.join(PROJECT_ROOT, ".env"))
        credentials = "%s:%s" % (env.get("EBAY_APP_ID", ""), env.get("EBAY_CERT_ID", ""))
        encoded = base64.b64encode(credentials.encode()).decode()

        refresh_resp = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": "Basic %s" % encoded},
            data={
                "grant_type": "refresh_token",
                "refresh_token": token_data.get("refresh_token", ""),
                "scope": "https://api.ebay.com/oauth/api_scope https://api.ebay.com/oauth/api_scope/sell.fulfillment",
            },
            timeout=15,
        )
        if refresh_resp.status_code == 200:
            new_data = refresh_resp.json()
            token_data["access_token"] = new_data["access_token"]
            with open(token_path, "w") as f:
                json.dump(token_data, f, indent=2)
            return new_data["access_token"]
        return None

    return token


def _categorize_title(title):
    """タイトルからカテゴリを推定"""
    title_lower = title.lower()
    for cat, keywords in CATEGORY_MAP.items():
        if any(kw in title_lower for kw in keywords):
            return cat
    return "Other"


def _detect_franchise(title):
    """タイトルから作品/フランチャイズを推定"""
    title_lower = title.lower()
    for franchise, chars in FRANCHISE_RELATIONS.items():
        if franchise in title_lower or any(c in title_lower for c in chars):
            return franchise
    return None


def _suggest_related(sold_item):
    """売れた商品から関連商品候補を推測"""
    suggestions = []
    title_lower = sold_item["title"].lower()
    franchise = _detect_franchise(sold_item["title"])

    if franchise and franchise in FRANCHISE_RELATIONS:
        chars = FRANCHISE_RELATIONS[franchise]
        # タイトルに含まれるキャラ以外の関連キャラを候補化
        title_chars = [c for c in chars if c in title_lower]
        related_chars = [c for c in chars if c not in title_lower]
        for char in related_chars[:3]:
            suggestions.append({
                "type": "related_character",
                "suggestion": "%s %s" % (franchise.title(), char.title()),
                "reason": "Same franchise as sold item (%s)" % ", ".join(title_chars) if title_chars else franchise,
                "confidence": "medium",
            })

    return suggestions


def fetch_recent_sales():
    """eBay API から最近の売上を取得"""
    token = _get_ebay_user_token()
    if not token:
        return []

    try:
        resp = requests.get(
            "https://api.ebay.com/sell/fulfillment/v1/order?limit=50",
            headers={"Authorization": "Bearer %s" % token},
            timeout=15,
        )
        if resp.status_code == 200:
            orders = resp.json().get("orders", [])
            sales = []
            for order in orders:
                date = order.get("creationDate", "")[:10]
                for item in order.get("lineItems", []):
                    sales.append({
                        "date": date,
                        "title": item.get("title", ""),
                        "price": float(item.get("lineItemCost", {}).get("value", "0")),
                        "sku": item.get("sku", ""),
                        "category": _categorize_title(item.get("title", "")),
                        "franchise": _detect_franchise(item.get("title", "")),
                    })
            return sales
    except Exception:
        pass
    return []


def analyze_sales_trends(sales, shopify_products):
    """売上傾向を分析して Shopify 展開候補を生成"""
    findings = []

    if not sales:
        findings.append({
            "type": "info", "agent": "catalog-migration-planner",
            "message": "eBay sales: No data available (token may need refresh)",
        })
        return findings

    # === 1. 売れ筋サマリ ===
    categories = Counter(s["category"] for s in sales)
    franchises = Counter(s["franchise"] for s in sales if s["franchise"])
    prices = [s["price"] for s in sales]
    avg_price = sum(prices) / len(prices) if prices else 0

    summary_details = [
        "Recent orders: %d items" % len(sales),
        "Avg price: $%.0f (range: $%.0f - $%.0f)" % (avg_price, min(prices), max(prices)),
        "Top categories: %s" % ", ".join("%s(%d)" % (k, v) for k, v in categories.most_common(5)),
    ]
    if franchises:
        summary_details.append("Top franchises: %s" % ", ".join("%s(%d)" % (k, v) for k, v in franchises.most_common(5)))

    findings.append({
        "type": "info", "agent": "catalog-migration-planner",
        "message": "eBay sales trends: %d items sold recently" % len(sales),
        "details": summary_details,
    })

    # === 2. Shopify 未展開候補（実績ベース） ===
    shopify_titles = set()
    shopify_cats = Counter()
    if shopify_products:
        for p in shopify_products:
            shopify_titles.add(p["title"].lower())
            shopify_cats[p.get("product_type", "")] += 1

    # 売れたがShopifyに類似品がないカテゴリ
    weak_cats = []
    for cat, sold_count in categories.most_common():
        shopify_count = shopify_cats.get(cat, 0)
        if sold_count >= 2 and shopify_count < 3:
            weak_cats.append({
                "category": cat,
                "ebay_sold": sold_count,
                "shopify_count": shopify_count,
            })

    if weak_cats:
        details = []
        for wc in weak_cats[:3]:
            details.append("[実績ベース] %s: eBay %d sold / Shopify %d products -> Strengthen" % (
                wc["category"], wc["ebay_sold"], wc["shopify_count"]
            ))
        findings.append({
            "type": "action", "agent": "catalog-migration-planner",
            "message": "Category gaps: %d categories selling on eBay but weak on Shopify" % len(weak_cats),
            "details": details,
        })

    # === 3. 売れ筋商品の代表例 ===
    top_sales = sorted(sales, key=lambda x: -x["price"])[:5]
    sale_details = []
    for s in top_sales:
        sale_details.append("[実績] $%.0f - %s (%s)" % (s["price"], s["title"][:45], s["category"]))

    findings.append({
        "type": "info", "agent": "catalog-migration-planner",
        "message": "Top selling items: %d items (by price)" % len(top_sales),
        "details": sale_details,
    })

    # === 4. 関連作品・キャラ推測候補 ===
    all_related = []
    for s in sales:
        related = _suggest_related(s)
        all_related.extend(related)

    # 重複除去
    seen = set()
    unique_related = []
    for r in all_related:
        if r["suggestion"] not in seen:
            seen.add(r["suggestion"])
            unique_related.append(r)

    if unique_related:
        details = []
        for r in unique_related[:5]:
            details.append("[%s][%s] %s (%s)" % (r["type"], r["confidence"], r["suggestion"], r["reason"][:40]))
        findings.append({
            "type": "action", "agent": "catalog-migration-planner",
            "message": "Related product candidates: %d items from franchise analysis" % len(unique_related),
            "details": details,
        })

    # === 5. キャッシュ保存 ===
    cache = {
        "last_updated": NOW.strftime("%Y-%m-%d %H:%M"),
        "sales_count": len(sales),
        "categories": dict(categories),
        "franchises": dict(franchises),
        "avg_price": avg_price,
        "top_items": [{"title": s["title"][:50], "price": s["price"], "category": s["category"]} for s in top_sales],
    }
    try:
        with open(SALES_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except IOError:
        pass

    return findings


# ============================================================
# メインエントリポイント
# ============================================================

def run_ebay_sales_analysis(shopify_products):
    """eBay 売れ筋分析を実行して findings を返す"""
    sales = fetch_recent_sales()
    return analyze_sales_trends(sales, shopify_products)
