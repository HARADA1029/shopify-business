# ============================================================
# ブログ記事自動投稿スクリプト
#
# Shopify 商品データから hd-bodyscience.com に記事を自動生成する。
# 既存記事の文体・構成に沿いつつ、テスト要素も導入可能。
#
# 実行: python store/scripts/blog_auto_post.py
# ============================================================

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "")
SHOPIFY_URL = "https://%s.myshopify.com" % SHOPIFY_STORE
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_APP_PASSWORD", "")
WP_API = "https://hd-bodyscience.com/wp-json/wp/v2"

POSTED_FILE = os.path.join(PROJECT_ROOT, "ops", "monitoring", "blog_state.json")

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

# CTA テンプレート
CTA_TEMPLATE = '''
<div style="margin:30px 0;padding:24px 20px;background:#f8f9fa;border:1px solid #e0e0e0;border-radius:10px;">
<h3 style="font-size:17px;font-weight:bold;margin:0 0 12px 0;color:#333;">Where to Buy</h3>
<div style="display:flex;gap:10px;flex-wrap:wrap;">
<a href="{shopify_url}" target="_blank" rel="noopener noreferrer"
style="display:inline-block;padding:10px 22px;background:#4CAF50;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold;font-size:14px;">
{shopify_text}</a>
<a href="{ebay_url}" target="_blank" rel="noopener noreferrer"
style="display:inline-block;padding:10px 22px;background:#0064D2;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold;font-size:14px;">
Browse on eBay</a>
</div>
<p style="font-size:12px;color:#888;margin:10px 0 0 0;">All items shipped directly from Japan. Condition and availability may vary.</p>
</div>
'''


def load_shopify_token():
    with open(os.path.join(PROJECT_ROOT, ".shopify_token.json"), "r") as f:
        return json.load(f).get("access_token", "")


def load_blog_state():
    if not os.path.exists(POSTED_FILE):
        return {"articles_generated": [], "experiments": [], "template_scores": {}}
    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"articles_generated": [], "experiments": [], "template_scores": {}}


def save_blog_state(state):
    state["_last_updated"] = NOW.strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(POSTED_FILE), exist_ok=True)
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_shopify_products():
    token = load_shopify_token()
    resp = requests.get(
        "%s/admin/api/2026-04/products.json?status=active&limit=50" % SHOPIFY_URL,
        headers={"X-Shopify-Access-Token": token},
        timeout=30,
    )
    return resp.json().get("products", [])


def select_product_for_article(products, blog_state):
    """記事化すべき商品を選定する"""
    written_handles = set(a.get("handle", "") for a in blog_state.get("articles_generated", []))

    # WP 既存記事のタイトルキーワード
    try:
        resp = requests.get(
            WP_API + "/posts?per_page=50&_fields=title",
            headers={"User-Agent": "HD-Toys-Blog/1.0"}, timeout=15,
        )
        wp_titles = " ".join(
            p.get("title", {}).get("rendered", "").lower()
            for p in resp.json()
        )
    except Exception:
        wp_titles = ""

    candidates = []
    for p in products:
        handle = p.get("handle", "")
        if handle in written_handles:
            continue
        if not p.get("images"):
            continue

        title_lower = p["title"].lower()
        words = [w for w in title_lower.split() if len(w) > 4]
        coverage = sum(1 for w in words if w in wp_titles) / max(len(words), 1)

        if coverage < 0.4:
            candidates.append({
                "product": p,
                "coverage": coverage,
            })

    candidates.sort(key=lambda x: x["coverage"])
    return candidates[0]["product"] if candidates else None


def generate_article_with_gemini(product):
    """Gemini で記事本文を生成する"""
    title = product["title"]
    product_type = product.get("product_type", "Collectible")
    body_html = product.get("body_html", "")
    description = body_html[:500] if body_html else title
    handle = product["handle"]
    images = product.get("images", [])

    shopify_link = "%s/products/%s?utm_source=hd-bodyscience&utm_medium=article&utm_campaign=blog-auto&utm_content=%s" % (
        SHOPIFY_URL, handle, handle,
    )

    prompt = """IMPORTANT: Write this entire article in ENGLISH only. Do not use Japanese.

Write a blog article in English about this Japanese collectible product for an international audience of collectors.

Product: %s
Category: %s
Description: %s

Follow this structure exactly:

1. Introduction (2-3 paragraphs about why this item is special and appealing to collectors)

2. <h2>Product Details</h2>
   Include subsections with <h3> tags for:
   - Product Name
   - Category
   - Key Features
   - Rarity & Value

3. <h2>Background & Context</h2>
   Include subsections about the series/franchise and why this item is notable.

4. <h2>Related Items</h2>
   Mention similar products that collectors might also be interested in.

5. <h2>Summary</h2>
   A brief conclusion summarizing why this is worth collecting.

Important rules:
- Write in HTML format (use <h2>, <h3>, <p> tags)
- Tone: informative, collector-friendly, enthusiastic but not pushy
- Word count: 1200-1500 words
- Do NOT include any <h1> tags
- Do NOT include the product title as a heading (WordPress will add it)
- Include natural mentions of "shipped from Japan" and "pre-owned, inspected"
- Do NOT generate fake reviews or testimonials
""" % (title, product_type, description[:300])

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=%s" % GEMINI_KEY
    resp = requests.post(url, json={
        "contents": [{"parts": [{"text": prompt}]}],
    }, timeout=120)

    if resp.status_code == 200:
        data = resp.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        for part in parts:
            if "text" in part:
                return part["text"]
    return None


def add_cta_and_links(article_html, product):
    """CTA ブロックと内部リンクを追加する"""
    handle = product["handle"]
    product_type = product.get("product_type", "")
    title = product["title"]

    shopify_link = "%s/products/%s?utm_source=hd-bodyscience&utm_medium=article&utm_campaign=blog-auto&utm_content=%s" % (
        SHOPIFY_URL, handle, handle,
    )

    collection_map = {
        "Action Figures": "action-figures",
        "Scale Figures": "figures-statues",
        "Trading Cards": "trading-cards",
        "Video Games": "video-games",
        "Electronic Toys": "electronic-toys",
        "Media & Books": "media-books",
        "Plush & Soft Toys": "plush-soft-toys",
        "Goods & Accessories": "goods-accessories",
    }
    collection_handle = collection_map.get(product_type, "all")

    # Shopify CTA
    cta = CTA_TEMPLATE.format(
        shopify_url=shopify_link,
        shopify_text="Buy on Shopify",
        ebay_url="https://www.ebay.com/str/hdtoysstore",
    )

    # 記事末尾に CTA を追加
    article_html += cta

    return article_html


def post_to_wordpress(title, content, status="draft"):
    """WordPress に記事を投稿する"""
    if not WP_USER or not WP_PASS:
        print("[ERROR] WordPress credentials not set")
        return None

    resp = requests.post(
        WP_API + "/posts",
        auth=(WP_USER, WP_PASS),
        json={
            "title": title,
            "content": content,
            "status": status,
        },
        timeout=30,
    )

    if resp.status_code == 201:
        post = resp.json()
        return {
            "id": post["id"],
            "link": post["link"],
            "status": post["status"],
        }
    else:
        print("[ERROR] WordPress post failed: %s" % resp.text[:200])
        return None


def main():
    print("=" * 60)
    print("  Blog Auto Post")
    print("  %s" % NOW.strftime("%Y-%m-%d %H:%M JST"))
    print("=" * 60)
    print()

    if not GEMINI_KEY:
        print("[ERROR] GEMINI_API_KEY not set")
        sys.exit(1)

    blog_state = load_blog_state()

    # 今日の記事生成済みチェック
    today_str = NOW.strftime("%Y-%m-%d")
    today_articles = [
        a for a in blog_state.get("articles_generated", [])
        if a.get("date") == today_str
    ]
    if today_articles:
        print("[SKIP] Already generated article today: %s" % today_articles[0].get("title", "?")[:40])
        return

    # Shopify 商品取得
    print("[INFO] Fetching products...")
    products = get_shopify_products()
    print("  Products: %d" % len(products))

    # 商品選定
    product = select_product_for_article(products, blog_state)
    if not product:
        print("[SKIP] No products need articles")
        return

    title = product["title"]
    handle = product["handle"]
    print("[INFO] Selected: %s" % title[:60])
    print()

    # Gemini で記事生成
    print("[INFO] Generating article with Gemini...")
    article_html = generate_article_with_gemini(product)
    if not article_html:
        print("[ERROR] Article generation failed")
        return

    print("[OK] Article generated (%d chars)" % len(article_html))

    # CTA と内部リンクを追加
    article_html = add_cta_and_links(article_html, product)

    # WordPress に下書き投稿
    print("[INFO] Posting to WordPress (draft)...")
    result = post_to_wordpress(title, article_html, status="draft")

    if result:
        blog_state.setdefault("articles_generated", []).append({
            "date": today_str,
            "handle": handle,
            "title": title[:80],
            "category": product.get("product_type", ""),
            "wp_post_id": result["id"],
            "wp_link": result["link"],
            "template": "standard",
            "status": "draft",
        })
        save_blog_state(blog_state)

        print()
        print("[OK] Article created as draft!")
        print("  Title: %s" % title[:60])
        print("  WP Post ID: %d" % result["id"])
        print("  URL: %s" % result["link"])
        print("  Status: draft (review before publishing)")


if __name__ == "__main__":
    main()
