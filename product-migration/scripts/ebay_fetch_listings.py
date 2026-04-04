# ============================================================
# eBay Active Listings 全件取得スクリプト
#
# 【役割】
#   Trading API の GetMyeBaySelling を使って Active Listings を全件取得し、
#   CSV ファイルに保存する。
#   ページネーションに対応し、200件ずつ取得して全件を網羅する。
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/ebay_fetch_listings.py
#
# 【前提】
#   ebay_auth.py でトークンを取得済みであること
# ============================================================

import csv
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests
from dotenv import load_dotenv

# --- 設定 ---

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

TOKEN_FILE = os.path.join(PROJECT_ROOT, ".ebay_token.json")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "product-migration", "data")

# 1ページあたりの取得件数（eBay の上限は200）
ENTRIES_PER_PAGE = 200

# API リクエスト間の待機時間（秒）。レート制限対策
REQUEST_INTERVAL = 1.0

# eBay Trading API エンドポイント
TRADING_API_URL = "https://api.ebay.com/ws/api.dll"

# eBay XML 名前空間
NS = {"e": "urn:ebay:apis:eBLBaseComponents"}

# --- CSV 出力カラム定義 ---
CSV_COLUMNS = [
    "item_id",
    "sku",
    "title",
    "category_id",
    "category_name",
    "price",
    "currency",
    "condition_id",
    "condition_name",
    "quantity_available",
    "brand",
    "character",
    "franchise",
    "watchers",
    "image_count",
    "image_urls",
    "listing_start_date",
    "view_count",
]


def load_token():
    """保存済みトークンを読み込む"""
    if not os.path.exists(TOKEN_FILE):
        print(f"[エラー] トークンファイルが見つかりません: {TOKEN_FILE}")
        print("  先に ebay_auth.py を実行してください。")
        sys.exit(1)

    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    access_token = data.get("access_token", "")
    if not access_token:
        print("[エラー] トークンファイルに access_token が含まれていません。")
        sys.exit(1)

    return access_token


def build_request_xml(page_number):
    """指定ページの GetMyeBaySelling XML リクエストを構築する"""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <ActiveList>
    <Sort>TimeLeft</Sort>
    <Pagination>
      <EntriesPerPage>{ENTRIES_PER_PAGE}</EntriesPerPage>
      <PageNumber>{page_number}</PageNumber>
    </Pagination>
  </ActiveList>
  <DetailLevel>ReturnAll</DetailLevel>
</GetMyeBaySellingRequest>"""


def fetch_page(access_token, page_number):
    """1ページ分の Active Listings を取得する"""
    headers = {
        "X-EBAY-API-SITEID": "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "GetMyeBaySelling",
        "X-EBAY-API-IAF-TOKEN": access_token,
        "Content-Type": "text/xml",
    }

    xml_request = build_request_xml(page_number)
    response = requests.post(TRADING_API_URL, headers=headers, data=xml_request)
    return response


def get_text(element, path, ns=NS):
    """XML 要素からテキストを安全に取得する"""
    el = element.find(path, ns)
    return el.text.strip() if el is not None and el.text else ""


def get_item_specific(item, name):
    """Item Specifics から指定した名前の値を取得する"""
    specifics = item.findall(".//e:ItemSpecifics/e:NameValueList", NS)
    for spec in specifics:
        spec_name = get_text(spec, "e:Name")
        if spec_name.lower() == name.lower():
            return get_text(spec, "e:Value")
    return ""


def parse_item(item):
    """1件の Item XML を辞書に変換する"""
    # 価格の取得（CurrentPrice → BuyItNowPrice の順で探す）
    price_el = item.find(".//e:CurrentPrice", NS)
    if price_el is None:
        price_el = item.find(".//e:BuyItNowPrice", NS)

    price = price_el.text if price_el is not None else ""
    currency = price_el.get("currencyID", "") if price_el is not None else ""

    # 画像 URL の取得
    pic_urls = item.findall(".//e:PictureDetails/e:PictureURL", NS)
    image_urls = [url.text for url in pic_urls if url.text]

    return {
        "item_id": get_text(item, "e:ItemID"),
        "sku": get_text(item, "e:SKU"),
        "title": get_text(item, "e:Title"),
        "category_id": get_text(item, ".//e:PrimaryCategory/e:CategoryID"),
        "category_name": get_text(item, ".//e:PrimaryCategory/e:CategoryName"),
        "price": price,
        "currency": currency,
        "condition_id": get_text(item, ".//e:ConditionID"),
        "condition_name": get_text(item, ".//e:ConditionDisplayName"),
        "quantity_available": get_text(item, "e:QuantityAvailable") or get_text(item, "e:Quantity"),
        "brand": get_item_specific(item, "Brand"),
        "character": get_item_specific(item, "Character") or get_item_specific(item, "Character Family"),
        "franchise": get_item_specific(item, "Franchise") or get_item_specific(item, "TV Show"),
        "watchers": get_text(item, "e:WatchCount") or "0",
        "image_count": str(len(image_urls)),
        "image_urls": " | ".join(image_urls),
        "listing_start_date": get_text(item, ".//e:ListingDetails/e:StartTime"),
        "view_count": get_text(item, "e:HitCount") or "0",
    }


def parse_page(response):
    """
    1ページ分のレスポンスをパースする。

    戻り値: (items_list, total_pages, total_entries, error_messages)
    """
    root = ET.fromstring(response.text)

    # エラーチェック
    ack = get_text(root, "e:Ack")
    if ack not in ("Success", "Warning"):
        errors = root.findall(".//e:Errors/e:ShortMessage", NS)
        error_msgs = [e.text for e in errors if e.text]
        return [], 0, 0, error_msgs

    # ページネーション情報
    total_pages_el = root.find(".//e:ActiveList/e:PaginationResult/e:TotalNumberOfPages", NS)
    total_entries_el = root.find(".//e:ActiveList/e:PaginationResult/e:TotalNumberOfEntries", NS)
    total_pages = int(total_pages_el.text) if total_pages_el is not None else 0
    total_entries = int(total_entries_el.text) if total_entries_el is not None else 0

    # 商品データ
    items = root.findall(".//e:ActiveList/e:ItemArray/e:Item", NS)
    listings = [parse_item(item) for item in items]

    return listings, total_pages, total_entries, None


def save_csv(all_listings, filepath):
    """全件を CSV に保存する"""
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_listings)


def main():
    """メイン処理: 全ページを順に取得して CSV に保存する"""
    print()
    print("=" * 60)
    print("  eBay Active Listings 全件取得")
    print("=" * 60)
    print()

    access_token = load_token()
    print("[OK] トークンを読み込みました")

    # --- 1ページ目を取得してページネーション情報を確認する ---
    print("[INFO] 1ページ目を取得しています...")
    response = fetch_page(access_token, 1)

    if response.status_code != 200:
        print(f"[エラー] HTTP {response.status_code}")
        if response.status_code == 401:
            print("  → トークンの有効期限切れです。ebay_auth.py を再実行してください。")
        sys.exit(1)

    listings, total_pages, total_entries, errors = parse_page(response)

    if errors:
        print(f"[エラー] eBay API エラー:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    if total_entries == 0:
        print("[INFO] Active Listings が0件です。")
        sys.exit(0)

    print(f"[INFO] Active Listings 総数: {total_entries} 件")
    print(f"[INFO] 総ページ数: {total_pages} ページ（{ENTRIES_PER_PAGE}件/ページ）")
    print()

    all_listings = list(listings)
    print(f"  ページ 1/{total_pages} ... {len(listings)} 件取得")

    # --- 2ページ目以降を取得する ---
    for page in range(2, total_pages + 1):
        # レート制限対策で待機する
        time.sleep(REQUEST_INTERVAL)

        response = fetch_page(access_token, page)

        if response.status_code != 200:
            print(f"  [警告] ページ {page} で HTTP {response.status_code}。スキップします。")
            continue

        listings, _, _, errors = parse_page(response)

        if errors:
            print(f"  [警告] ページ {page} でエラー: {errors[0]}。スキップします。")
            continue

        all_listings.extend(listings)
        print(f"  ページ {page}/{total_pages} ... {len(listings)} 件取得（累計 {len(all_listings)} 件）")

    # --- CSV 保存 ---
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"active_listings_{timestamp}.csv"
    filepath = os.path.join(OUTPUT_DIR, filename)

    save_csv(all_listings, filepath)

    print()
    print("=" * 60)
    print(f"  取得完了")
    print(f"  取得件数: {len(all_listings)} / {total_entries} 件")
    print(f"  保存先  : {filepath}")
    print("=" * 60)
    print()

    # --- 取得項目の充足率サマリー ---
    print("  --- 項目充足率 ---")
    for col in CSV_COLUMNS:
        if col == "image_urls":
            continue  # URL 一覧は充足率表示に不向き
        filled = sum(1 for item in all_listings if item.get(col) and item[col] != "0")
        rate = filled / len(all_listings) * 100 if all_listings else 0
        print(f"  {col:22s}: {filled:>6} / {len(all_listings):>6} ({rate:5.1f}%)")
    print()

    print("次のステップ:")
    print("  このCSVを使って50件サンプル分析とcategory-mapping試適用を行います。")


if __name__ == "__main__":
    main()
