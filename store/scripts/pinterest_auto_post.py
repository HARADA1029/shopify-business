# ============================================================
# Pinterest 自動投稿スクリプト
#
# 【役割】
#   Shopify の商品画像を使って Pinterest に1日1投稿を自動実行する
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python store/scripts/pinterest_auto_post.py
#
# 【安全ルール】
#   - 1日1投稿のみ
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
PINTEREST_TOKEN_FILE = os.path.join(PROJECT_ROOT, ".pinterest_token.json")
POSTED_FILE = os.path.join(PROJECT_ROOT, "ops", "monitoring", "sns_posted.json")

SHOPIFY_URL = "https://%s.myshopify.com" % SHOPIFY_STORE

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

# カテゴリ → Pinterest ボード ID マッピング
BOARD_MAP = {
    "Action Figures": "668995788338720708",
    "Trading Cards": "668995788338720709",
    "Scale Figures": "668995788338720710",
    "Video Games": "668995788338720711",
    "Electronic Toys": "668995788338720712",
    "Plush & Soft Toys": "668995788338720713",
    "Goods & Accessories": "668995788338720714",
    "Media & Books": "668995788338720714",
}
DEFAULT_BOARD = "668995788338720714"  # HD Toys Store Japan - All Items

# カテゴリ曜日ローテーション（Instagram と同じ）
CATEGORY_ROTATION = [
    "Action Figures",     # 月
    "Trading Cards",      # 火
    "Scale Figures",      # 水
    "Electronic Toys",    # 木
    "Video Games",        # 金
    "Media & Books",      # 土
    "Plush & Soft Toys",  # 日
]


def load_shopify_token():
    with open(SHOPIFY_TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("access_token", "")


def _request_with_retry(method, url, max_retries=3, **kwargs):
    """リトライ付きリクエスト"""
    kwargs.setdefault("timeout", 60)
    for attempt in range(max_retries):
        try:
            if method == "get":
                return requests.get(url, **kwargs)
            else:
                return requests.post(url, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retries - 1:
                print("[RETRY] %d/%d: %s" % (attempt + 1, max_retries, str(e)[:80]))
                time.sleep(5)
            else:
                raise


def load_pinterest_token():
    """Pinterest トークンを読み込み、必要ならリフレッシュする"""
    if not os.path.exists(PINTEREST_TOKEN_FILE):
        return None

    with open(PINTEREST_TOKEN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    token = data.get("access_token", "")

    # トークンの有効性確認
    resp = _request_with_retry(
        "get",
        "https://api.pinterest.com/v5/user_account",
        headers={"Authorization": "Bearer %s" % token},
    )

    if resp.status_code == 200:
        return token

    # リフレッシュ試行
    refresh_tok = data.get("refresh_token", "")
    if not refresh_tok:
        return None

    app_id = os.environ.get("PINTEREST_APP_ID", "")
    app_secret = os.environ.get("PINTEREST_APP_SECRET", "")

    refresh_resp = _request_with_retry(
        "post",
        "https://api.pinterest.com/v5/oauth/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=(app_id, app_secret),
        data={"grant_type": "refresh_token", "refresh_token": refresh_tok},
    )

    if refresh_resp.status_code == 200:
        new_data = refresh_resp.json()
        # リフレッシュトークンを保持
        if "refresh_token" not in new_data:
            new_data["refresh_token"] = refresh_tok
        with open(PINTEREST_TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=2)
        print("[OK] Pinterest トークンをリフレッシュしました")
        return new_data["access_token"]

    return None


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


def select_product(products, posted_pinterest_handles):
    """今日のカテゴリから未投稿商品を1件選定"""
    day_of_week = NOW.weekday()
    today_category = CATEGORY_ROTATION[day_of_week % len(CATEGORY_ROTATION)]

    # 今日のカテゴリから未投稿を探す
    candidates = [
        p for p in products
        if p.get("product_type") == today_category
        and p.get("handle", "") not in posted_pinterest_handles
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
                and p.get("handle", "") not in posted_pinterest_handles
                and p.get("images")
            ]
            if candidates:
                today_category = cat
                break

    if not candidates:
        return None, today_category

    return candidates[0], today_category


def create_pin(token, product, category):
    """Pinterest にピンを作成する"""
    handle = product["handle"]
    title = product["title"][:100]
    image_url = product["images"][0]["src"]
    product_url = "%s/products/%s?utm_source=pinterest&utm_medium=social&utm_campaign=daily-pin" % (SHOPIFY_URL, handle)

    # ボード選択
    board_id = BOARD_MAP.get(category, DEFAULT_BOARD)

    # 説明文生成
    price = ""
    if product.get("variants"):
        price = product["variants"][0].get("price", "")
    if price:
        price_text = "$%s" % price
    else:
        price_text = ""

    description = (
        "%s\n\n"
        "%s"
        "Pre-owned, carefully inspected & shipped from Japan.\n"
        "Visit HD Toys Store Japan for authentic Japanese collectibles.\n\n"
        "#japanesecollectibles #shippedfromjapan #hdtoysjapan #japanimport"
    ) % (title, ("%s | " % price_text) if price_text else "")

    # ピン作成
    resp = _request_with_retry(
        "post",
        "https://api.pinterest.com/v5/pins",
        headers={
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json",
        },
        json={
            "title": title,
            "description": description,
            "board_id": board_id,
            "media_source": {
                "source_type": "image_url",
                "url": image_url,
            },
            "link": product_url,
            "alt_text": title,
        },
    )

    return resp


def main():
    print("=" * 60)
    print("  Pinterest Auto Post")
    print("  %s" % NOW.strftime("%Y-%m-%d %H:%M JST"))
    print("=" * 60)
    print()

    # Pinterest トークン読み込み
    pinterest_token = load_pinterest_token()
    if not pinterest_token:
        print("[ERROR] Pinterest token not found or invalid. Run pinterest_auth.py first.")
        sys.exit(1)
    print("[OK] Pinterest token loaded")

    # Shopify 商品取得
    print("[INFO] Fetching Shopify products...")
    products = get_shopify_products()
    print("  Active products: %d" % len(products))

    if not products:
        print("[SKIP] No active products found")
        return

    # 投稿済みリスト（Pinterest 用）
    posted_data = load_posted()
    posted_pinterest = set(posted_data.get("posted_pinterest", []))
    print("  Already pinned: %d" % len(posted_pinterest))

    # 今日のPinterest投稿済みチェック
    today_str = NOW.strftime("%Y-%m-%d")
    today_pins = [
        h for h in posted_data.get("history", [])
        if h.get("date") == today_str and h.get("platform") == "pinterest"
    ]
    if today_pins:
        print("[SKIP] Already pinned today: %s" % today_pins[0].get("title", "?")[:40])
        return

    # 商品選定
    product, category = select_product(products, posted_pinterest)
    if not product:
        print("[SKIP] No unposted products available for Pinterest")
        return

    title = product["title"][:60]
    handle = product["handle"]
    image_url = product["images"][0]["src"]

    print()
    print("[INFO] Selected product:")
    print("  Title: %s" % title)
    print("  Category: %s" % category)
    print("  Board: %s" % BOARD_MAP.get(category, DEFAULT_BOARD))
    print("  Handle: %s" % handle)
    print()

    # ピン作成
    print("[INFO] Creating pin...")
    resp = create_pin(pinterest_token, product, category)

    if resp.status_code == 201:
        pin = resp.json()
        pin_id = pin.get("id", "")
        print("[OK] Pin created! ID: %s" % pin_id)

        # 投稿済みリストに追加
        posted_data.setdefault("posted_pinterest", []).append(handle)
        posted_data.setdefault("history", []).append({
            "date": today_str,
            "platform": "pinterest",
            "handle": handle,
            "title": title,
            "category": category,
            "pin_id": pin_id,
        })
        save_posted(posted_data)
        print("[OK] Posted list updated")

    else:
        print("[ERROR] Pin creation failed: HTTP %d" % resp.status_code)
        print("  Response: %s" % resp.text[:300])
        sys.exit(1)


if __name__ == "__main__":
    main()
