# ============================================================
# Facebook ページ自動投稿スクリプト
#
# 【役割】
#   Shopify の商品画像を使って Facebook ページに1日1投稿を自動実行
#   Instagram と同じ商品を同時投稿（クロスポスト）
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python store/scripts/facebook_auto_post.py
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
SHOPIFY_TOKEN_FILE = os.path.join(PROJECT_ROOT, ".shopify_token.json")
IG_TOKEN_FILE = os.path.join(PROJECT_ROOT, ".instagram_token.json")
POSTED_FILE = os.path.join(PROJECT_ROOT, "ops", "monitoring", "sns_posted.json")

SHOPIFY_URL = "https://%s.myshopify.com" % SHOPIFY_STORE

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)


def load_shopify_token():
    with open(SHOPIFY_TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("access_token", "")


def load_tokens():
    with open(IG_TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_posted():
    if not os.path.exists(POSTED_FILE):
        return {"posted": [], "history": []}
    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"posted": [], "history": []}


def save_posted(data):
    os.makedirs(os.path.dirname(POSTED_FILE), exist_ok=True)
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_todays_ig_post(posted_data):
    """今日の Instagram 投稿を取得（同じ商品を FB にも投稿するため）"""
    today_str = NOW.strftime("%Y-%m-%d")
    for h in posted_data.get("history", []):
        if h.get("date") == today_str and h.get("platform") == "instagram":
            return h
    return None


def post_to_facebook(page_token, page_id, message, image_url, link):
    """Facebook ページに画像付き投稿する"""

    # 画像付き投稿
    resp = requests.post(
        "https://graph.facebook.com/v25.0/%s/photos" % page_id,
        params={
            "access_token": page_token,
            "url": image_url,
            "message": message,
        },
        timeout=30,
    )

    if resp.status_code == 200:
        post_id = resp.json().get("id", "")
        print("[OK] Facebook post published! Post ID: %s" % post_id)
        return {"post_id": post_id}
    else:
        print("[ERROR] Facebook post failed: %s" % resp.text[:200])
        return None


def main():
    print("=" * 60)
    print("  Facebook Auto Post")
    print("  %s" % NOW.strftime("%Y-%m-%d %H:%M JST"))
    print("=" * 60)
    print()

    # トークン読み込み
    tokens = load_tokens()
    page_token = tokens.get("page_access_token", "")
    page_id = tokens.get("page_id", "")

    if not page_token or not page_id:
        print("[ERROR] Page token not found.")
        sys.exit(1)

    # 投稿済みリスト
    posted_data = load_posted()

    # 今日の FB 投稿済みチェック
    today_str = NOW.strftime("%Y-%m-%d")
    today_fb = [
        h for h in posted_data.get("history", [])
        if h.get("date") == today_str and h.get("platform") == "facebook"
    ]
    if today_fb:
        print("[SKIP] Already posted to Facebook today")
        return

    # 今日の IG 投稿を取得して同じ商品を FB にも投稿
    ig_post = get_todays_ig_post(posted_data)

    if ig_post:
        handle = ig_post.get("handle", "")
        title = ig_post.get("title", "")
        category = ig_post.get("category", "")
        print("[INFO] Cross-posting today's IG post to Facebook")
        print("  Product: %s" % title[:60])
    else:
        # IG 投稿がなければ Shopify から商品を選定
        print("[INFO] No IG post today. Selecting product from Shopify...")
        shopify_token = load_shopify_token()
        resp = requests.get(
            "%s/admin/api/2026-04/products.json?status=active&limit=50" % SHOPIFY_URL,
            headers={"X-Shopify-Access-Token": shopify_token},
            timeout=30,
        )
        products = resp.json().get("products", [])
        posted_handles = set(
            h.get("handle", "") for h in posted_data.get("history", [])
            if h.get("platform") == "facebook"
        )

        candidates = [
            p for p in products
            if p.get("handle", "") not in posted_handles and p.get("images")
        ]
        if not candidates:
            print("[SKIP] No unposted products")
            return

        product = candidates[0]
        handle = product["handle"]
        title = product["title"]
        category = product.get("product_type", "")

    # 商品画像を取得
    shopify_token = load_shopify_token()
    shopify_link = "%s/products/%s?utm_source=facebook&utm_medium=social&utm_campaign=daily-post&utm_content=%s" % (
        SHOPIFY_URL, handle, handle,
    )

    # Shopify から画像 URL を取得
    resp = requests.get(
        "%s/admin/api/2026-04/products.json?handle=%s&fields=images,title" % (SHOPIFY_URL, handle),
        headers={"X-Shopify-Access-Token": shopify_token},
        timeout=15,
    )
    products = resp.json().get("products", [])
    if not products or not products[0].get("images"):
        print("[ERROR] No images found for %s" % handle)
        return

    image_url = products[0]["images"][0]["src"]
    if not title:
        title = products[0]["title"]

    # FB 投稿メッセージ
    message = (
        "%s\n\n"
        "Pre-owned, inspected & shipped directly from Japan.\n\n"
        "Shop now: %s\n\n"
        "#japanesecollectibles #japantoys #shippedfromjapan #hdtoysjapan"
    ) % (title, shopify_link)

    print()
    print("[INFO] Posting to Facebook...")
    result = post_to_facebook(page_token, page_id, message, image_url, shopify_link)

    if result:
        posted_data.setdefault("history", []).append({
            "date": today_str,
            "handle": handle,
            "title": title[:80],
            "category": category,
            "post_id": result.get("post_id", ""),
            "platform": "facebook",
            "media_type": "image",
            "has_product_link": True,
            "product_url": shopify_link,
            "image_url": image_url,
            "posted_at": NOW.strftime("%Y-%m-%d %H:%M"),
            "engagement": {"impressions": 0, "clicks": 0, "likes": 0, "comments": 0, "shares": 0, "shopify_visits": 0},
        })
        save_posted(posted_data)
        print()
        print("[OK] Facebook post completed!")


if __name__ == "__main__":
    main()
