# ============================================================
# Shopify 商品投入スクリプト（API 経由・draft 状態）
#
# 【役割】
#   shopify_ready_100.csv を読み込み、Shopify Admin API で
#   全商品を draft 状態で投入する
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python store/scripts/import_products.py
#
# 【注意】
#   - 全商品は draft 状態で投入（公開しない）
#   - eBay には一切変更を加えない
# ============================================================

import csv
import json
import os
import re
import sys
import time
import unicodedata

import requests
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

STORE = os.getenv("SHOPIFY_STORE", "")
TOKEN_FILE = os.path.join(PROJECT_ROOT, ".shopify_token.json")
DATA_DIR = os.path.join(PROJECT_ROOT, "product-migration", "data")
API_VERSION = "2026-04"

REQUEST_INTERVAL = 0.6  # レート制限対策


def load_token():
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("access_token", "")


def load_csv(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def api_url(endpoint):
    return f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/{endpoint}"


def headers(token):
    return {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }


def slugify(text):
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    return text[:255]


def create_product(token, row):
    """1商品を draft で作成する"""
    title = row.get("title", "")
    description = row.get("description_html", "")
    vendor = row.get("vendor", "")
    product_type = row.get("product_type", "")
    tags = row.get("tags", "")
    sku = row.get("sku", "")
    price = row.get("price", "0")
    compare_at = row.get("compare_at_price", "")
    weight = row.get("weight", "500")
    weight_unit = row.get("weight_unit", "g")

    # 画像 URL
    image_urls_raw = row.get("image_urls", "") or ""
    image_urls = [u.strip() for u in image_urls_raw.split("|") if u.strip()]

    images = []
    for i, url in enumerate(image_urls):
        img = {"src": url, "position": i + 1}
        if i == 0:
            img["alt"] = title[:255]
        images.append(img)

    # 重量を g に変換（Shopify は grams を使う）
    try:
        weight_grams = int(float(weight))
    except (ValueError, TypeError):
        weight_grams = 500

    product_data = {
        "product": {
            "title": title,
            "body_html": description,
            "vendor": vendor,
            "product_type": product_type,
            "tags": tags,
            "status": "draft",
            "variants": [
                {
                    "sku": sku,
                    "price": price,
                    "compare_at_price": compare_at if compare_at else None,
                    "grams": weight_grams,
                    "inventory_management": "shopify",
                    "inventory_quantity": 1,
                    "requires_shipping": True,
                    "taxable": False,
                }
            ],
            "images": images,
        }
    }

    resp = requests.post(
        api_url("products.json"),
        headers=headers(token),
        json=product_data,
    )
    return resp


def main():
    print()
    print("=" * 60)
    print("  Shopify 商品投入（draft 状態）")
    print("  ※ 商品は公開しません")
    print("  ※ eBay には一切変更を加えません")
    print("=" * 60)
    print()

    token = load_token()
    if not token:
        print("[エラー] トークンがありません")
        sys.exit(1)

    # 接続テスト
    resp = requests.get(api_url("shop.json"), headers=headers(token))
    if resp.status_code != 200:
        print(f"[エラー] API 接続失敗: HTTP {resp.status_code}")
        sys.exit(1)
    print(f"[OK] 接続確認: {resp.json()['shop']['name']}")

    # 既存商品数を確認
    resp = requests.get(api_url("products/count.json"), headers=headers(token))
    existing = resp.json().get("count", 0)
    if existing > 0:
        print(f"[INFO] 既存商品: {existing} 件")
        print(f"  既に商品が投入されています。重複投入を避けるため中断します。")
        print(f"  再投入する場合は、管理画面で既存商品を削除してから再実行してください。")
        sys.exit(0)

    # CSV 読み込み
    csv_path = os.path.join(DATA_DIR, "shopify_ready_100.csv")
    rows = load_csv(csv_path)
    print(f"[OK] {len(rows)} 商品を読み込みました")
    print()

    # 投入
    success = 0
    failed = 0
    errors = []

    for i, row in enumerate(rows, 1):
        title = (row.get("title", ""))[:50]
        print(f"  [{i:>3}/100] {title}... ", end="", flush=True)

        resp = create_product(token, row)

        if resp.status_code in (200, 201):
            product = resp.json().get("product", {})
            img_count = len(product.get("images", []))
            print(f"OK (画像 {img_count} 枚)")
            success += 1
        elif resp.status_code == 429:
            # レート制限 → 待って再試行
            print("レート制限 → 5秒待機...", end="", flush=True)
            time.sleep(5)
            resp = create_product(token, row)
            if resp.status_code in (200, 201):
                product = resp.json().get("product", {})
                img_count = len(product.get("images", []))
                print(f" OK (画像 {img_count} 枚)")
                success += 1
            else:
                print(f" 再試行も失敗: HTTP {resp.status_code}")
                failed += 1
                errors.append((row.get("item_id", ""), resp.text[:100]))
        else:
            print(f"エラー: HTTP {resp.status_code}")
            failed += 1
            errors.append((row.get("item_id", ""), resp.text[:200]))

        time.sleep(REQUEST_INTERVAL)

    print()

    # --- レポート ---
    print("=" * 60)
    print("  投入結果レポート")
    print("=" * 60)
    print()
    print(f"  成功: {success} 件")
    print(f"  失敗: {failed} 件")
    print()

    if errors:
        print("  --- エラー詳細 ---")
        for item_id, err in errors:
            print(f"  {item_id}: {err}")
        print()

    # 投入後の状態確認
    time.sleep(2)
    resp = requests.get(api_url("products/count.json?status=draft"), headers=headers(token))
    draft_count = resp.json().get("count", 0)
    resp = requests.get(api_url("products/count.json?status=active"), headers=headers(token))
    active_count = resp.json().get("count", 0)

    print(f"  --- 商品状態 ---")
    print(f"  Draft: {draft_count} 件")
    print(f"  Active: {active_count} 件")
    print()

    if active_count == 0:
        print("  ✓ 商品は公開されていません（全件 draft）")
    else:
        print("  ⚠ 公開済み商品があります！確認してください")

    # サンプル確認
    resp = requests.get(
        api_url("products.json?status=draft&limit=5"),
        headers=headers(token),
    )
    products = resp.json().get("products", [])
    if products:
        print()
        print("  --- サンプル5件 ---")
        for p in products:
            imgs = len(p.get("images", []))
            variant = p.get("variants", [{}])[0]
            price = variant.get("price", "?")
            compare = variant.get("compare_at_price", "")
            tags = p.get("tags", "")[:40]
            print(f"  ${price:>7} (was ${compare}) | img={imgs} | {p['title'][:55]}")
            print(f"    Tags: {tags}")


if __name__ == "__main__":
    main()
