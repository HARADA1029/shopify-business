# ============================================================
# Collection 説明文 + SEO + メニュー設定スクリプト
#
# 【役割】
#   1. 各 Collection に説明文・SEO title・meta description を設定
#   2. メインメニュー・フッターメニューを再構成
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python store/scripts/setup_collections_seo.py
# ============================================================

import json
import os
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
# Collection 説明文 + SEO データ
# ============================================================

COLLECTION_DATA = {
    "Action Figures": {
        "body_html": (
            "<p>Authentic Japanese action figures from top brands like Bandai, "
            "Tamashii Nations, and Kaiyodo. Featuring S.H.Figuarts, figma, MAFEX, "
            "and more — all shipped directly from Japan.</p>"
        ),
        "seo_title": "Japanese Action Figures | S.H.Figuarts, figma, MAFEX",
        "seo_description": (
            "Shop authentic Japanese action figures. S.H.Figuarts, figma, MAFEX, "
            "Revoltech and more from top Japanese brands. Pre-owned, inspected, "
            "and shipped directly from Japan."
        ),
    },
    "Figures & Statues": {
        "body_html": (
            "<p>Scale figures, statues, and prize figures from Japan's finest makers. "
            "Featuring Banpresto, Good Smile Company, Kotobukiya, and more. "
            "From Nendoroids to 1/7 scale beauties — every piece carefully inspected.</p>"
        ),
        "seo_title": "Japanese Scale Figures & Statues | Nendoroid, Banpresto, Prize Figures",
        "seo_description": (
            "Discover Japanese scale figures and statues. Nendoroids, Banpresto prize figures, "
            "Ichiban Kuji, Pop Up Parade and more. Pre-owned collectibles shipped from Japan."
        ),
    },
    "Plush & Soft Toys": {
        "body_html": (
            "<p>Adorable plush toys and soft collectibles from Japan. "
            "Featuring characters from Pokemon, Sanrio, Disney, and popular anime series. "
            "Many are Japan-exclusive releases you won't find elsewhere.</p>"
        ),
        "seo_title": "Japanese Plush Toys | Pokemon, Sanrio, Anime Plush from Japan",
        "seo_description": (
            "Cute and collectible Japanese plush toys. Pokemon, Sanrio, anime characters "
            "and Japan-exclusive releases. Pre-owned and shipped directly from Japan."
        ),
    },
    "Trading Cards": {
        "body_html": (
            "<p>Japanese trading cards including Pokemon, Yu-Gi-Oh!, Weiss Schwarz, "
            "and more. Featuring rare promos, holos, and signed cards — "
            "sourced directly from the Japanese market.</p>"
        ),
        "seo_title": "Japanese Trading Cards | Pokemon, Yu-Gi-Oh!, Weiss Schwarz",
        "seo_description": (
            "Rare Japanese trading cards. Pokemon, Yu-Gi-Oh!, Weiss Schwarz, Union Arena "
            "and more. Holo, promo, and signed cards shipped directly from Japan."
        ),
    },
    "Video Games": {
        "body_html": (
            "<p>Japanese video games, consoles, and limited editions. "
            "From retro classics like Super Famicom and Sega Saturn "
            "to modern PlayStation and Nintendo releases. "
            "Many are region-exclusive Japanese versions.</p>"
        ),
        "seo_title": "Japanese Video Games | Retro & Modern Games from Japan",
        "seo_description": (
            "Japanese video games and consoles. Retro games, limited editions, "
            "and Japan-exclusive titles. Super Famicom, Sega Saturn, PlayStation "
            "and more. Shipped from Japan."
        ),
    },
    "Media & Books": {
        "body_html": (
            "<p>Japanese manga, art books, Blu-ray, soundtracks, and collectible media. "
            "Complete manga sets, anime art books, and rare vinyl records — "
            "all original Japanese editions.</p>"
        ),
        "seo_title": "Japanese Manga, Art Books & Anime Media",
        "seo_description": (
            "Japanese manga sets, anime art books, Blu-ray, soundtracks and vinyl records. "
            "Original Japanese editions and rare collectible media. Shipped from Japan."
        ),
    },
    "Electronic Toys": {
        "body_html": (
            "<p>Japanese electronic toys and digital pets. "
            "Featuring Tamagotchi, Pocket Pikachu, and other beloved electronic collectibles. "
            "Many are rare limited editions no longer in production.</p>"
        ),
        "seo_title": "Tamagotchi & Japanese Electronic Toys | Rare Digital Pets",
        "seo_description": (
            "Rare Japanese electronic toys and digital pets. Tamagotchi, Pocket Pikachu "
            "and limited editions. Pre-owned collectibles shipped directly from Japan."
        ),
    },
}


def update_collections(token):
    """各 Collection に説明文と SEO を設定する"""
    print("=" * 60)
    print("  1. Collection 説明文 + SEO 設定")
    print("=" * 60)
    print()

    # 既存コレクションを取得
    resp = requests.get(api_url("smart_collections.json?limit=50"), headers=hdrs(token))
    collections = resp.json().get("smart_collections", [])

    updated = 0
    for col in collections:
        title = col["title"]
        col_id = col["id"]

        if title not in COLLECTION_DATA:
            print(f"  [スキップ] {title}（データなし）")
            continue

        data = COLLECTION_DATA[title]

        # REST API で更新
        update_payload = {
            "smart_collection": {
                "id": col_id,
                "body_html": data["body_html"],
            }
        }
        resp = requests.put(
            api_url(f"smart_collections/{col_id}.json"),
            headers=hdrs(token),
            json=update_payload,
        )
        time.sleep(REQUEST_INTERVAL)

        if resp.status_code == 200:
            print(f"  [OK] {title} — 説明文を設定")
        else:
            print(f"  [エラー] {title}: HTTP {resp.status_code} {resp.text[:100]}")
            continue

        # SEO は GraphQL の collectionUpdate で設定
        gql_mutation = """
        mutation collectionUpdate($input: CollectionInput!) {
          collectionUpdate(input: $input) {
            collection {
              id
              seo {
                title
                description
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        gql_variables = {
            "input": {
                "id": f"gid://shopify/Collection/{col_id}",
                "seo": {
                    "title": data["seo_title"],
                    "description": data["seo_description"],
                },
            }
        }
        resp = requests.post(
            graphql_url(),
            headers=hdrs(token),
            json={"query": gql_mutation, "variables": gql_variables},
        )
        time.sleep(REQUEST_INTERVAL)

        result = resp.json()
        errors = result.get("data", {}).get("collectionUpdate", {}).get("userErrors", [])
        if errors:
            print(f"  [警告] {title} SEO: {errors}")
        else:
            print(f"  [OK] {title} — SEO title + meta description を設定")

        updated += 1

    print()
    print(f"  更新: {updated} コレクション")
    return updated


# ============================================================
# メニュー再構成
# ============================================================

def update_menus(token):
    """メインメニューとフッターメニューを再構成する"""
    print()
    print("=" * 60)
    print("  2. メニュー再構成")
    print("=" * 60)
    print()

    # コレクションの handle を取得
    resp = requests.get(api_url("smart_collections.json?limit=50"), headers=hdrs(token))
    smart_cols = {c["title"]: c["handle"] for c in resp.json().get("smart_collections", [])}
    time.sleep(REQUEST_INTERVAL)

    # ページの handle を取得
    resp = requests.get(api_url("pages.json?limit=50"), headers=hdrs(token))
    pages = {p["title"]: p["handle"] for p in resp.json().get("pages", [])}
    time.sleep(REQUEST_INTERVAL)

    base = f"https://{STORE}.myshopify.com"

    # メニュー一覧を取得
    query = """
    {
      menus(first: 10) {
        edges {
          node {
            id
            title
            handle
          }
        }
      }
    }
    """
    resp = requests.post(graphql_url(), headers=hdrs(token), json={"query": query})
    menus = {
        edge["node"]["handle"]: edge["node"]
        for edge in resp.json().get("data", {}).get("menus", {}).get("edges", [])
    }
    time.sleep(REQUEST_INTERVAL)

    # --- メインメニュー ---
    main_menu = menus.get("main-menu")
    if main_menu:
        # Shop ドロップダウン（コレクション一覧）
        shop_items = []
        menu_order = [
            "Action Figures", "Figures & Statues", "Plush & Soft Toys",
            "Trading Cards", "Video Games", "Media & Books", "Electronic Toys",
        ]
        for col_name in menu_order:
            if col_name in smart_cols:
                shop_items.append({
                    "title": col_name,
                    "type": "HTTP",
                    "url": f"{base}/collections/{smart_cols[col_name]}",
                })

        # トップレベルメニュー項目
        items = [
            {
                "title": "Shop",
                "type": "HTTP",
                "url": f"{base}/collections/all",
                "items": shop_items,
            },
            {
                "title": "New Arrivals",
                "type": "HTTP",
                "url": f"{base}/collections/all?sort_by=created-descending",
            },
            {
                "title": "About Us",
                "type": "HTTP",
                "url": f"{base}/pages/{pages.get('About Us', 'about-us')}",
            },
            {
                "title": "Contact",
                "type": "HTTP",
                "url": f"{base}/pages/contact",
            },
        ]

        mutation = """
        mutation menuUpdate($id: ID!, $items: [MenuItemCreateInput!]!) {
          menuUpdate(id: $id, items: $items) {
            menu { id title }
            userErrors { field message }
          }
        }
        """
        resp = requests.post(
            graphql_url(),
            headers=hdrs(token),
            json={"query": mutation, "variables": {"id": main_menu["id"], "items": items}},
        )
        time.sleep(REQUEST_INTERVAL)

        errors = resp.json().get("data", {}).get("menuUpdate", {}).get("userErrors", [])
        if errors:
            print(f"  [警告] メインメニュー: {errors}")
        else:
            print(f"  [OK] メインメニュー更新")
            print(f"    Shop ▼ (7コレクション)")
            for col_name in menu_order:
                print(f"      └ {col_name}")
            print(f"    New Arrivals")
            print(f"    About Us")
            print(f"    Contact")
    else:
        print("  [スキップ] メインメニューが見つかりません")

    print()

    # --- フッターメニュー ---
    footer_menu = menus.get("footer")
    if footer_menu:
        items = []

        footer_links = [
            ("Shipping Policy", pages.get("Shipping Policy", "shipping-policy")),
            ("Return Policy", pages.get("Return Policy", "return-policy")),
            ("FAQ", pages.get("FAQ", "faq")),
            ("About Us", pages.get("About Us", "about-us")),
            ("Legal Notice", pages.get("Legal Notice (特定商取引法に基づく表記)", "legal-notice")),
            ("Contact", "contact"),
        ]

        for title, handle in footer_links:
            items.append({
                "title": title,
                "type": "HTTP",
                "url": f"{base}/pages/{handle}",
            })

        resp = requests.post(
            graphql_url(),
            headers=hdrs(token),
            json={"query": mutation, "variables": {"id": footer_menu["id"], "items": items}},
        )
        time.sleep(REQUEST_INTERVAL)

        errors = resp.json().get("data", {}).get("menuUpdate", {}).get("userErrors", [])
        if errors:
            print(f"  [警告] フッターメニュー: {errors}")
        else:
            print(f"  [OK] フッターメニュー更新")
            for title, _ in footer_links:
                print(f"    {title}")
    else:
        print("  [スキップ] フッターメニューが見つかりません")


# ============================================================
# 確認
# ============================================================

def verify(token):
    """設定結果を確認する"""
    print()
    print("=" * 60)
    print("  3. 設定結果の確認")
    print("=" * 60)
    print()

    resp = requests.get(api_url("smart_collections.json?limit=50"), headers=hdrs(token))
    collections = resp.json().get("smart_collections", [])

    for col in sorted(collections, key=lambda c: c["title"]):
        title = col["title"]
        body = (col.get("body_html") or "")
        has_body = "✓" if body else "✗"

        # SEO 情報は GraphQL で取得
        query = """
        query ($id: ID!) {
          collection(id: $id) {
            seo { title description }
          }
        }
        """
        resp = requests.post(
            graphql_url(),
            headers=hdrs(token),
            json={"query": query, "variables": {"id": f"gid://shopify/Collection/{col['id']}"}},
        )
        time.sleep(0.3)

        seo = resp.json().get("data", {}).get("collection", {}).get("seo", {})
        seo_title = seo.get("title") or "(なし)"
        seo_desc = seo.get("description") or "(なし)"
        has_seo = "✓" if seo.get("title") else "✗"

        print(f"  {title}")
        print(f"    説明文: {has_body} ({len(body)}文字)")
        print(f"    SEO:    {has_seo}")
        print(f"    SEO Title: {seo_title[:60]}")
        print(f"    Meta Desc: {seo_desc[:60]}...")
        print()


def main():
    print()
    print("=" * 60)
    print("  Collection SEO + メニュー設定")
    print("=" * 60)
    print()

    token = load_token()

    # 接続テスト
    resp = requests.get(api_url("shop.json"), headers=hdrs(token))
    if resp.status_code != 200:
        print(f"[エラー] API 接続失敗: HTTP {resp.status_code}")
        sys.exit(1)
    print(f"[OK] {resp.json()['shop']['name']}")
    print()

    update_collections(token)
    update_menus(token)
    verify(token)


if __name__ == "__main__":
    main()
