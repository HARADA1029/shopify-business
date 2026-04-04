# ============================================================
# eBay API 接続テストスクリプト
#
# 【役割】
#   保存済みトークンを使って eBay API に接続し、
#   Active Listings を少数件取得して接続が正常か確認する。
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/ebay_test_connection.py
#
# 【前提】
#   ebay_auth.py でトークンを取得済みであること（.ebay_token.json が存在する）
# ============================================================

import json
import os
import sys

import requests
from dotenv import load_dotenv

# --- 設定 ---

# プロジェクトルート
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# トークンファイル
TOKEN_FILE = os.path.join(PROJECT_ROOT, ".ebay_token.json")

# テスト取得件数
TEST_LIMIT = 5

# eBay Sell Inventory API（出品データ取得）
# Trading API の GetMyeBaySelling を使う方が Active Listings の詳細を取りやすい
TRADING_API_URL = "https://api.ebay.com/ws/api.dll"


def load_token():
    """保存済みトークンを読み込む"""
    if not os.path.exists(TOKEN_FILE):
        print(f"[エラー] トークンファイルが見つかりません: {TOKEN_FILE}")
        print("  先に ebay_auth.py を実行してトークンを取得してください。")
        sys.exit(1)

    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    access_token = data.get("access_token", "")
    if not access_token:
        print("[エラー] トークンファイルに access_token が含まれていません。")
        print("  ebay_auth.py を再実行してください。")
        sys.exit(1)

    return access_token


def fetch_active_listings(access_token, limit=5):
    """
    Trading API の GetMyeBaySelling を使って Active Listings を取得する。

    Trading API は REST ではなく XML ベースだが、
    OAuth トークンで認証でき、出品の詳細情報を一括取得できる。
    """
    app_id = os.getenv("EBAY_APP_ID", "")
    dev_id = os.getenv("EBAY_DEV_ID", "")
    cert_id = os.getenv("EBAY_CERT_ID", "")

    headers = {
        "X-EBAY-API-SITEID": "0",  # US サイト（グローバル出品の場合）
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "GetMyeBaySelling",
        "X-EBAY-API-IAF-TOKEN": access_token,
        "Content-Type": "text/xml",
    }

    # XML リクエスト: ActiveList を少数件だけ取得する
    xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <ActiveList>
    <Sort>TimeLeft</Sort>
    <Pagination>
      <EntriesPerPage>{limit}</EntriesPerPage>
      <PageNumber>1</PageNumber>
    </Pagination>
  </ActiveList>
  <DetailLevel>ReturnAll</DetailLevel>
</GetMyeBaySellingRequest>"""

    response = requests.post(TRADING_API_URL, headers=headers, data=xml_request)
    return response


def parse_listings(response):
    """
    XML レスポンスから出品データを抽出する。
    軽量パースのため xml.etree.ElementTree を使う。
    """
    import xml.etree.ElementTree as ET

    root = ET.fromstring(response.text)
    # eBay の XML 名前空間
    ns = {"e": "urn:ebay:apis:eBLBaseComponents"}

    # エラーチェック
    ack = root.find("e:Ack", ns)
    if ack is not None and ack.text not in ("Success", "Warning"):
        errors = root.findall(".//e:Errors/e:ShortMessage", ns)
        error_msgs = [e.text for e in errors if e.text]
        return None, error_msgs

    # ActiveList 内の Item を抽出する
    items = root.findall(".//e:ActiveList/e:ItemArray/e:Item", ns)

    # 総出品数を取得する
    total_el = root.find(".//e:ActiveList/e:PaginationResult/e:TotalNumberOfEntries", ns)
    total_count = int(total_el.text) if total_el is not None else None

    listings = []
    for item in items:
        listing = {}

        # Item ID
        el = item.find("e:ItemID", ns)
        listing["item_id"] = el.text if el is not None else ""

        # Title
        el = item.find("e:Title", ns)
        listing["title"] = el.text if el is not None else ""

        # Price
        el = item.find(".//e:CurrentPrice", ns)
        if el is None:
            el = item.find(".//e:BuyItNowPrice", ns)
        if el is not None:
            listing["price"] = f"{el.text} {el.get('currencyID', '')}"
        else:
            listing["price"] = ""

        # Category
        el = item.find(".//e:PrimaryCategory/e:CategoryName", ns)
        listing["category"] = el.text if el is not None else ""

        el = item.find(".//e:PrimaryCategory/e:CategoryID", ns)
        listing["category_id"] = el.text if el is not None else ""

        # Condition
        el = item.find(".//e:ConditionDisplayName", ns)
        listing["condition"] = el.text if el is not None else ""

        # Quantity
        el = item.find("e:QuantityAvailable", ns)
        if el is None:
            el = item.find("e:Quantity", ns)
        listing["quantity"] = el.text if el is not None else ""

        # Watch Count
        el = item.find("e:WatchCount", ns)
        listing["watchers"] = el.text if el is not None else "0"

        # 画像URL（最初の1枚だけ取得）
        el = item.find(".//e:PictureDetails/e:PictureURL", ns)
        listing["image_url"] = el.text if el is not None else ""

        # 画像枚数
        pic_urls = item.findall(".//e:PictureDetails/e:PictureURL", ns)
        listing["image_count"] = len(pic_urls)

        listings.append(listing)

    return {"total_count": total_count, "listings": listings}, None


def display_results(data):
    """取得結果を見やすく表示する"""
    print()
    print("=" * 60)
    print("  eBay API 接続テスト結果")
    print("=" * 60)
    print()
    print(f"  接続状態: 成功")
    print(f"  Active Listings 総数: {data['total_count']} 件")
    print(f"  今回取得した件数: {len(data['listings'])} 件")
    print()

    for i, item in enumerate(data["listings"], 1):
        print(f"  --- 商品 {i} ---")
        print(f"  Item ID   : {item['item_id']}")
        print(f"  Title     : {item['title']}")
        print(f"  Price     : {item['price']}")
        print(f"  Category  : {item['category']} (ID: {item['category_id']})")
        print(f"  Condition : {item['condition']}")
        print(f"  Quantity  : {item['quantity']}")
        print(f"  Watchers  : {item['watchers']}")
        print(f"  Images    : {item['image_count']} 枚")
        print()

    # 取得できた項目のサマリー
    print("  --- 取得項目サマリー ---")
    fields = ["item_id", "title", "price", "category", "condition", "quantity", "watchers", "image_count"]
    for field in fields:
        filled = sum(1 for item in data["listings"] if item.get(field) and str(item[field]) != "0")
        total = len(data["listings"])
        status = "OK" if filled == total else f"{filled}/{total}"
        print(f"  {field:15s}: {status}")
    print()


def main():
    """メイン処理"""
    print()
    print("[INFO] eBay API 接続テストを開始します...")
    print()

    # トークン読み込み
    access_token = load_token()
    print("[OK] トークンを読み込みました")

    # Active Listings を取得
    print(f"[INFO] Active Listings を {TEST_LIMIT} 件取得しています...")
    response = fetch_active_listings(access_token, limit=TEST_LIMIT)

    # HTTP レベルのエラーチェック
    if response.status_code != 200:
        print(f"[エラー] HTTP {response.status_code}")
        print(f"  レスポンス: {response.text[:500]}")

        if response.status_code == 401:
            print()
            print("  → トークンの有効期限が切れている可能性があります。")
            print("    ebay_auth.py を再実行してトークンを更新してください。")
        sys.exit(1)

    # XML パース
    data, errors = parse_listings(response)

    if errors:
        print(f"[エラー] eBay API からエラーが返されました:")
        for err in errors:
            print(f"  - {err}")

        if any("token" in e.lower() or "auth" in e.lower() for e in errors):
            print()
            print("  → 認証エラーです。ebay_auth.py を再実行してください。")
        sys.exit(1)

    if not data or not data["listings"]:
        print("[警告] Active Listings が0件です。出品中の商品がないか確認してください。")
        sys.exit(0)

    # 結果表示
    display_results(data)

    print("[OK] 接続テスト完了。API からデータを正常に取得できました。")
    print()
    print("次のステップ:")
    print("  全件取得スクリプトで Active Listings を一括ダウンロードし、")
    print("  50件サンプル分析に進みます。")


if __name__ == "__main__":
    main()
