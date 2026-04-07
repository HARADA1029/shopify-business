# ============================================================
# Instagram 自動投稿スクリプト
#
# 【役割】
#   Shopify の商品画像を使って Instagram に1日1投稿を自動実行する
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python store/scripts/instagram_auto_post.py
#
# 【安全ルール】
#   - 1日1投稿のみ（Instagram API 制限: 25件/24h）
#   - 投稿済み商品は再投稿しない
#   - eBay には一切変更を加えない
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

# --- 設定 ---
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "")
SHOPIFY_TOKEN_FILE = os.path.join(PROJECT_ROOT, ".shopify_token.json")
IG_TOKEN_FILE = os.path.join(PROJECT_ROOT, ".instagram_token.json")
POSTED_FILE = os.path.join(PROJECT_ROOT, "ops", "monitoring", "sns_posted.json")

SHOPIFY_URL = "https://%s.myshopify.com" % SHOPIFY_STORE

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

# カテゴリ曜日ローテーション
CATEGORY_ROTATION = [
    "Action Figures",     # 月
    "Trading Cards",      # 火
    "Scale Figures",      # 水
    "Electronic Toys",    # 木
    "Video Games",        # 金
    "Media & Books",      # 土
    "Plush & Soft Toys",  # 日
]

# カテゴリ別ハッシュタグ
HASHTAGS = {
    "Action Figures": "#actionfigures #japanesetoys #shfiguarts #figma #bandai #japanesecollectibles #hdtoysjapan",
    "Scale Figures": "#animefigures #nendoroid #banpresto #japanfigures #scalefigure #japanesecollectibles #hdtoysjapan",
    "Trading Cards": "#pokemoncard #pokemontcg #tradingcards #japanesecard #rarecards #japanesecollectibles #hdtoysjapan",
    "Video Games": "#japanesegames #retrogaming #playstation #nintendo #japangames #japanesecollectibles #hdtoysjapan",
    "Electronic Toys": "#tamagotchi #digitalpet #japanesetoys #retrotoys #bandai #japanesecollectibles #hdtoysjapan",
    "Media & Books": "#manga #artbook #japanmanga #animeart #japanesemedia #japanesecollectibles #hdtoysjapan",
    "Plush & Soft Toys": "#plush #kawaii #japanplush #pokemonplush #sanrio #japanesecollectibles #hdtoysjapan",
    "Goods & Accessories": "#animegoods #cosplay #japangoods #animecollection #japanesecollectibles #hdtoysjapan",
}


def load_shopify_token():
    with open(SHOPIFY_TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("access_token", "")


def load_ig_token():
    with open(IG_TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_posted():
    """投稿済みリストを読み込む"""
    if not os.path.exists(POSTED_FILE):
        return {"posted": [], "history": []}
    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"posted": [], "history": []}


def save_posted(data):
    """投稿済みリストを保存する"""
    os.makedirs(os.path.dirname(POSTED_FILE), exist_ok=True)
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_shopify_products():
    """Shopify の Active 商品を取得"""
    token = load_shopify_token()
    url = "%s/admin/api/2026-04/products.json?status=active&limit=250" % SHOPIFY_URL
    headers = {"X-Shopify-Access-Token": token}
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code == 200:
        return resp.json().get("products", [])
    return []


def select_product(products, posted_handles):
    """今日のカテゴリから未投稿商品を1件選定"""
    day_of_week = NOW.weekday()
    today_category = CATEGORY_ROTATION[day_of_week % len(CATEGORY_ROTATION)]

    # 今日のカテゴリから未投稿を探す
    candidates = [
        p for p in products
        if p.get("product_type") == today_category
        and p.get("handle", "") not in posted_handles
        and p.get("images")
    ]

    # 候補がなければ他カテゴリから
    if not candidates:
        for cat in CATEGORY_ROTATION:
            if cat == today_category:
                continue
            candidates = [
                p for p in products
                if p.get("product_type") == cat
                and p.get("handle", "") not in posted_handles
                and p.get("images")
            ]
            if candidates:
                today_category = cat
                break

    if not candidates:
        return None, today_category

    return candidates[0], today_category


def generate_caption(product, category):
    """投稿キャプションを生成"""
    title = product["title"]
    handle = product["handle"]
    shopify_link = "%s/products/%s" % (SHOPIFY_URL, handle)

    tags = HASHTAGS.get(category, "#japanesecollectibles #hdtoysjapan")

    caption = (
        "%s\n"
        "\n"
        "Did you know? This item was originally released in Japan and is now a sought-after collectible worldwide.\n"
        "\n"
        "Pre-owned, carefully inspected & shipped from Japan\n"
        "\n"
        "More in bio\n"
        "\n"
        "%s\n"
        "#shippedfromjapan #japanimport #collector"
    ) % (title, tags)

    return caption


def post_to_instagram(ig_token_data, image_url, caption):
    """Instagram に投稿する"""
    access_token = ig_token_data["access_token"]
    ig_user_id = ig_token_data["ig_user_id"]

    # Step 1: コンテナ作成
    container_resp = requests.post(
        "https://graph.facebook.com/v25.0/%s/media" % ig_user_id,
        params={
            "image_url": image_url,
            "caption": caption,
            "access_token": access_token,
        },
        timeout=30,
    )

    if container_resp.status_code != 200:
        print("[ERROR] Container creation failed: %s" % container_resp.text[:200])
        return None

    container_id = container_resp.json().get("id")
    print("[OK] Container created: %s" % container_id)

    # Step 2: コンテナの状態を確認（処理完了を待つ）
    for i in range(10):
        time.sleep(3)
        status_resp = requests.get(
            "https://graph.facebook.com/v25.0/%s" % container_id,
            params={"fields": "status_code", "access_token": access_token},
            timeout=15,
        )
        if status_resp.status_code == 200:
            status = status_resp.json().get("status_code", "")
            if status == "FINISHED":
                break
            elif status == "ERROR":
                print("[ERROR] Container processing failed")
                return None

    # Step 3: 公開
    publish_resp = requests.post(
        "https://graph.facebook.com/v25.0/%s/media_publish" % ig_user_id,
        params={
            "creation_id": container_id,
            "access_token": access_token,
        },
        timeout=30,
    )

    if publish_resp.status_code == 200:
        media_id = publish_resp.json().get("id")
        print("[OK] Published! Media ID: %s" % media_id)

        # permalink を取得
        time.sleep(2)
        perm_resp = requests.get(
            "https://graph.facebook.com/v25.0/%s" % media_id,
            params={"fields": "permalink,timestamp", "access_token": access_token},
            timeout=15,
        )
        if perm_resp.status_code == 200:
            permalink = perm_resp.json().get("permalink", "")
            print("[OK] URL: %s" % permalink)
            return {"media_id": media_id, "permalink": permalink}

    else:
        print("[ERROR] Publish failed: %s" % publish_resp.text[:200])

    return None


def main():
    print("=" * 60)
    print("  Instagram Auto Post")
    print("  %s" % NOW.strftime("%Y-%m-%d %H:%M JST"))
    print("=" * 60)
    print()

    # トークン読み込み
    ig_token = load_ig_token()
    if not ig_token.get("access_token"):
        print("[ERROR] Instagram token not found. Run instagram_auth.py first.")
        sys.exit(1)

    # Shopify 商品取得
    print("[INFO] Fetching Shopify products...")
    products = get_shopify_products()
    print("  Active products: %d" % len(products))

    # 投稿済みリスト
    posted_data = load_posted()
    posted_handles = set(posted_data.get("posted", []))
    print("  Already posted: %d" % len(posted_handles))

    # 今日の投稿済みチェック
    today_str = NOW.strftime("%Y-%m-%d")
    today_posts = [
        h for h in posted_data.get("history", [])
        if h.get("date") == today_str
    ]
    if today_posts:
        print("[SKIP] Already posted today: %s" % today_posts[0].get("title", "?")[:40])
        return

    # 商品選定
    product, category = select_product(products, posted_handles)
    if not product:
        print("[SKIP] No unposted products available")
        return

    title = product["title"][:60]
    handle = product["handle"]
    image_url = product["images"][0]["src"]

    print()
    print("[INFO] Selected product:")
    print("  Title: %s" % title)
    print("  Category: %s" % category)
    print("  Handle: %s" % handle)
    print()

    # キャプション生成
    caption = generate_caption(product, category)

    # 投稿
    print("[INFO] Posting to Instagram...")
    result = post_to_instagram(ig_token, image_url, caption)

    if result:
        # 投稿済みリストに追加
        posted_data["posted"].append(handle)
        posted_data.setdefault("history", []).append({
            "date": today_str,
            "handle": handle,
            "title": product["title"][:80],
            "category": category,
            "media_id": result.get("media_id", ""),
            "permalink": result.get("permalink", ""),
            "platform": "instagram",
        })
        save_posted(posted_data)

        print()
        print("[OK] Post completed successfully!")
        print("  %s" % result.get("permalink", ""))
    else:
        print()
        print("[ERROR] Post failed")


if __name__ == "__main__":
    main()
