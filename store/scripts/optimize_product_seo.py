# ============================================================
# 商品 SEO 最適化スクリプト
#
# 【役割】
#   全100商品に対して以下を設定:
#   1. SEO Title（検索結果に表示されるタイトル）
#   2. Meta Description（検索結果に表示される説明文）
#   3. 全画像の alt text（画像検索対策）
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python store/scripts/optimize_product_seo.py
# ============================================================

import json
import os
import re
import sys
import time

import requests
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

STORE = os.getenv("SHOPIFY_STORE", "")
TOKEN_FILE = os.path.join(PROJECT_ROOT, ".shopify_token.json")
API_VERSION = "2026-04"
REQUEST_INTERVAL = 0.5


def load_token():
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("access_token", "")


def api_url(endpoint):
    return f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/{endpoint}"


def graphql_url():
    return f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/graphql.json"


def hdrs(token):
    return {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}


# ============================================================
# SEO Title / Meta Description 生成ロジック
# ============================================================

def generate_seo_title(title, vendor, product_type):
    """
    SEO Title を生成する（最大70文字）
    フォーマット: {商品タイトル} | {ストア名}
    タイトルが長い場合は切り詰めてストア名を付ける
    """
    store_suffix = " | HD Toys Store Japan"
    max_title_len = 70 - len(store_suffix)

    # タイトルが長すぎる場合は切り詰め
    if len(title) > max_title_len:
        seo_title = title[:max_title_len - 3].rstrip() + "..." + store_suffix
    else:
        seo_title = title + store_suffix

    return seo_title[:70]


def generate_meta_description(title, vendor, product_type, condition, tags):
    """
    Meta Description を生成する（最大160文字）
    フォーマット: {商品概要}. {Condition}. {特徴}. Ships from Japan.
    """
    parts = []

    # 商品タイトルを短縮
    short_title = title[:80] if len(title) > 80 else title
    parts.append(short_title)

    # Condition
    if condition and condition not in ("(不明)", "Other"):
        parts.append(f"Condition: {condition}")

    # Vendor
    if vendor:
        parts.append(f"By {vendor}")

    parts.append("Authentic pre-owned. Ships from Japan.")

    desc = ". ".join(parts)
    return desc[:160]


def generate_image_alt(title, position, total_images):
    """
    画像の alt text を生成する
    1枚目: 商品タイトルそのまま
    2枚目以降: タイトル + 角度/詳細
    """
    if position == 1:
        return title[:255]

    suffixes = {
        2: "back view",
        3: "detail",
        4: "accessories",
        5: "box and packaging",
    }
    suffix = suffixes.get(position, f"image {position}")
    alt = f"{title[:230]} - {suffix}"
    return alt[:255]


# ============================================================
# メイン処理
# ============================================================

def main():
    print()
    print("=" * 60)
    print("  商品 SEO 最適化（100件一括）")
    print("=" * 60)
    print()

    token = load_token()

    # 接続テスト
    resp = requests.get(api_url("shop.json"), headers=hdrs(token))
    if resp.status_code != 200:
        print(f"[エラー] API 接続失敗")
        sys.exit(1)
    print(f"[OK] {resp.json()['shop']['name']}")
    print()

    # 全商品を取得（ページネーション）
    all_products = []
    url = api_url("products.json?status=draft&limit=50")
    while url:
        resp = requests.get(url, headers=hdrs(token))
        data = resp.json()
        all_products.extend(data.get("products", []))
        link = resp.headers.get("Link", "")
        if 'rel="next"' in link:
            match = re.search(r'<([^>]+)>; rel="next"', link)
            url = match.group(1) if match else None
        else:
            url = None
        time.sleep(REQUEST_INTERVAL)

    print(f"[OK] {len(all_products)} 商品を取得")
    print()

    # --- 各商品を最適化 ---
    seo_updated = 0
    alt_updated = 0
    errors = 0

    for i, product in enumerate(all_products, 1):
        pid = product["id"]
        title = product["title"]
        vendor = product.get("vendor", "")
        product_type = product.get("product_type", "")
        tags = product.get("tags", "")
        images = product.get("images", [])

        # Condition をタグから抽出
        condition = ""
        for tag in tags.split(","):
            tag = tag.strip()
            if tag in ("Mint", "Near Mint", "Good", "Fair"):
                condition = tag
                break

        print(f"  [{i:>3}/100] {title[:50]}...", end="", flush=True)

        # --- 1. SEO Title + Meta Description ---
        seo_title = generate_seo_title(title, vendor, product_type)
        meta_desc = generate_meta_description(title, vendor, product_type, condition, tags)

        mutation = """
        mutation productUpdate($input: ProductInput!) {
          productUpdate(input: $input) {
            product { id }
            userErrors { field message }
          }
        }
        """
        variables = {
            "input": {
                "id": f"gid://shopify/Product/{pid}",
                "seo": {
                    "title": seo_title,
                    "description": meta_desc,
                },
            }
        }
        resp = requests.post(graphql_url(), headers=hdrs(token), json={"query": mutation, "variables": variables})
        time.sleep(REQUEST_INTERVAL)

        result = resp.json()
        seo_errors = result.get("data", {}).get("productUpdate", {}).get("userErrors", [])
        if seo_errors:
            print(f" SEOエラー", end="")
            errors += 1
        else:
            seo_updated += 1

        # --- 2. 画像 alt text ---
        img_ok = 0
        for img in images:
            img_id = img["id"]
            position = img.get("position", 1)
            current_alt = img.get("alt") or ""

            alt_text = generate_image_alt(title, position, len(images))

            # alt text が既に設定されていて同じなら スキップ
            if current_alt == alt_text:
                img_ok += 1
                continue

            img_resp = requests.put(
                api_url(f"products/{pid}/images/{img_id}.json"),
                headers=hdrs(token),
                json={"image": {"id": img_id, "alt": alt_text}},
            )
            time.sleep(0.3)

            if img_resp.status_code == 200:
                img_ok += 1
            else:
                pass  # 画像エラーは致命的でない

        alt_updated += img_ok
        print(f" OK (SEO + alt×{img_ok})")

    print()

    # --- レポート ---
    total_images = sum(len(p.get("images", [])) for p in all_products)

    print("=" * 60)
    print("  SEO 最適化レポート")
    print("=" * 60)
    print()
    print(f"  SEO Title + Meta Desc 設定: {seo_updated}/100 商品")
    print(f"  画像 alt text 設定: {alt_updated}/{total_images} 枚")
    if errors:
        print(f"  エラー: {errors} 件")
    print()

    # サンプル表示
    print("  --- SEO サンプル（5件）---")
    for p in all_products[:5]:
        seo_title = generate_seo_title(p["title"], p.get("vendor", ""), p.get("product_type", ""))
        meta_desc = generate_meta_description(
            p["title"], p.get("vendor", ""), p.get("product_type", ""), "Good", p.get("tags", "")
        )
        print(f"  Title: {seo_title}")
        print(f"  Desc:  {meta_desc[:80]}...")
        print()


if __name__ == "__main__":
    main()
