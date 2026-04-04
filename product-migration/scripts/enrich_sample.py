# ============================================================
# Step 2: 50件サンプル抽出 → GetItem 詳細補完 → 分析・マッピング試適用
#
# 【役割】
#   1. active_listings_usd.csv から価格帯で層化した50件サンプルを抽出
#   2. GetItem API で各商品の詳細データ（Category, Condition, Brand,
#      Character, 画像枚数）を補完する
#   3. 補完済みサンプルを sample_50_enriched.csv として保存
#   4. ebay-data-analysis.md の6観点で分析
#   5. category-mapping.md のルールを試適用し自動判定率を計測
#   6. 手動確認リストとレポートを出力
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/enrich_sample.py
#
# 【前提】
#   - ebay_auth.py でトークン取得済み
#   - filter_us_listings.py で active_listings_usd.csv を作成済み
# ============================================================

import csv
import json
import os
import random
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime

import requests
from dotenv import load_dotenv

# --- 設定 ---

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

DATA_DIR = os.path.join(PROJECT_ROOT, "product-migration", "data")
TOKEN_FILE = os.path.join(PROJECT_ROOT, ".ebay_token.json")

TRADING_API_URL = "https://api.ebay.com/ws/api.dll"
NS = {"e": "urn:ebay:apis:eBLBaseComponents"}

# GetItem のリクエスト間隔（秒）
REQUEST_INTERVAL = 0.5

# 層化抽出の件数配分
STRATIFICATION = [
    (0, 30, 15),
    (30.01, 100, 20),
    (100.01, 300, 10),
    (300.01, float("inf"), 5),
]

# ============================================================
# マッピング辞書（category-mapping.md に基づく）
# ============================================================

# 商品ライン → Product Type
PRODUCT_LINE_MAP = {
    "s.h.figuarts": "Action Figures",
    "shfiguarts": "Action Figures",
    "sh figuarts": "Action Figures",
    "figma": "Action Figures",
    "mafex": "Action Figures",
    "revoltech": "Action Figures",
    "robot spirits": "Action Figures",
    "robot damashii": "Action Figures",
    "d-arts": "Action Figures",
    "ultra-act": "Action Figures",
    "s.h.monsterarts": "Action Figures",
    "shmonsterarts": "Action Figures",
    "nendoroid": "Scale Figures",
    "banpresto": "Scale Figures",
    "prize figure": "Scale Figures",
    "ichiban kuji": "Scale Figures",
    "pop up parade": "Scale Figures",
    "q posket": "Scale Figures",
    "artfx": "Scale Figures",
    "p.o.p": "Scale Figures",
    "portrait of pirates": "Scale Figures",
    "g.e.m.": "Scale Figures",
    "alter": "Scale Figures",
}

# タイトルキーワード → Product Type（補助判定）
TYPE_KEYWORDS = {
    "action figure": "Action Figures",
    "model kit": "Model Kits",
    "plastic model": "Model Kits",
    "plamo": "Model Kits",
    "gunpla": "Model Kits",
    "plush": "Plush & Soft Toys",
    "stuffed": "Plush & Soft Toys",
    "soft toy": "Plush & Soft Toys",
    "vintage": "Vintage & Retro Toys",
    "retro": "Vintage & Retro Toys",
    "statue": "Scale Figures",
}

BUILT_KEYWORDS = ["built", "assembled", "painted", "completed", "finished"]

# フランチャイズ辞書
FRANCHISE_MAP = {
    "Dragon Ball": ["dragon ball", "dragonball", "dbz", "db super"],
    "One Piece": ["one piece", "onepiece"],
    "Naruto": ["naruto", "boruto", "shippuden"],
    "Gundam": ["gundam"],
    "Demon Slayer": ["demon slayer", "kimetsu"],
    "My Hero Academia": ["my hero academia", "boku no hero", "mha"],
    "Neon Genesis Evangelion": ["evangelion", "eva unit", "nerv"],
    "Sailor Moon": ["sailor moon"],
    "Pokemon": ["pokemon", "pikachu", "pokémon"],
    "Studio Ghibli": ["ghibli", "totoro", "spirited away", "kiki", "mononoke", "howl"],
    "Jujutsu Kaisen": ["jujutsu kaisen", "jujutsu"],
    "Attack on Titan": ["attack on titan", "shingeki"],
    "Chainsaw Man": ["chainsaw man"],
    "Spy x Family": ["spy x family", "spy family"],
    "Bleach": ["bleach"],
    "Final Fantasy": ["final fantasy"],
    "Saint Seiya": ["saint seiya"],
    "Macross": ["macross", "robotech"],
    "Kamen Rider": ["kamen rider", "masked rider"],
    "Ultraman": ["ultraman"],
}

# Vendor 正規化テーブル
VENDOR_NORMALIZE = {
    "Bandai": ["bandai", "bandai namco"],
    "Banpresto": ["banpresto"],
    "Good Smile Company": ["good smile", "good smile company", "gsc", "goodsmile"],
    "Kotobukiya": ["kotobukiya", "koto"],
    "MegaHouse": ["megahouse", "mega house"],
    "Tamashii Nations": ["tamashii nations", "tamashii"],
    "Kaiyodo": ["kaiyodo"],
    "Medicom Toy": ["medicom", "medicom toy"],
    "Takara Tomy": ["takara tomy", "takara", "tomy"],
    "Funko": ["funko"],
    "Max Factory": ["max factory"],
    "Square Enix": ["square enix", "play arts"],
    "Plex": ["plex"],
    "Hasbro": ["hasbro"],
    "Mattel": ["mattel"],
}

# Condition マッピング
CONDITION_MAP = {
    "new": "Mint",
    "brand new": "Mint",
    "new with tags": "Mint",
    "new with box": "Mint",
    "new other": "Near Mint",
    "new without tags": "Near Mint",
    "open box": "Near Mint",
    "like new": "Near Mint",
    "used - like new": "Near Mint",
    "very good": "Good",
    "used - very good": "Good",
    "good": "Good",
    "used - good": "Good",
    "used": "Good",
    "pre-owned": "Good",
    "acceptable": "Fair",
    "used - acceptable": "Fair",
    "for parts or not working": "_EXCLUDE_",
    "for parts": "_EXCLUDE_",
}


# ============================================================
# ユーティリティ
# ============================================================

def load_token():
    """保存済みトークンを読み込む"""
    if not os.path.exists(TOKEN_FILE):
        print(f"[エラー] トークンファイルが見つかりません: {TOKEN_FILE}")
        print("  先に ebay_auth.py を実行してください。")
        sys.exit(1)
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    token = data.get("access_token", "")
    if not token:
        print("[エラー] access_token が空です。ebay_auth.py を再実行してください。")
        sys.exit(1)
    return token


def load_csv(filepath):
    """CSV を辞書リストとして読み込む"""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_csv(rows, filepath, fieldnames=None):
    """辞書リストを CSV に保存する"""
    if not rows:
        return
    if not fieldnames:
        fieldnames = rows[0].keys()
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def extract_price(row):
    """価格を float に変換する"""
    try:
        return float(row.get("price", "0") or "0")
    except ValueError:
        return 0.0


def get_text(element, path):
    """XML 要素からテキストを安全に取得する"""
    el = element.find(path, NS)
    return el.text.strip() if el is not None and el.text else ""


def get_item_specific(item_el, name):
    """ItemSpecifics から指定した名前の値を取得する"""
    specifics = item_el.findall(".//e:ItemSpecifics/e:NameValueList", NS)
    for spec in specifics:
        spec_name = get_text(spec, "e:Name")
        if spec_name.lower() == name.lower():
            return get_text(spec, "e:Value")
    return ""


# ============================================================
# サンプル抽出
# ============================================================

def stratified_sample(rows):
    """価格帯で層化したサンプルを抽出する"""
    sample = []
    for low, high, count in STRATIFICATION:
        stratum = [r for r in rows if low <= extract_price(r) <= high]
        if len(stratum) <= count:
            sample.extend(stratum)
        else:
            sample.extend(random.sample(stratum, count))
    return sample


# ============================================================
# GetItem による詳細補完
# ============================================================

def fetch_item_details(access_token, item_id):
    """GetItem API で1件の商品詳細を取得する"""
    headers = {
        "X-EBAY-API-SITEID": "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "GetItem",
        "X-EBAY-API-IAF-TOKEN": access_token,
        "Content-Type": "text/xml",
    }

    xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
  <IncludeItemSpecifics>true</IncludeItemSpecifics>
</GetItemRequest>"""

    response = requests.post(TRADING_API_URL, headers=headers, data=xml_request)
    return response


def parse_item_details(response_text):
    """GetItem のレスポンスから詳細データを抽出する"""
    root = ET.fromstring(response_text)

    ack = get_text(root, "e:Ack")
    if ack not in ("Success", "Warning"):
        errors = root.findall(".//e:Errors/e:ShortMessage", NS)
        return None, [e.text for e in errors if e.text]

    item = root.find(".//e:Item", NS)
    if item is None:
        return None, ["Item 要素が見つかりません"]

    # 画像 URL
    pic_urls = item.findall(".//e:PictureDetails/e:PictureURL", NS)
    image_urls = [u.text for u in pic_urls if u.text]

    # 価格
    price_el = item.find(".//e:SellingStatus/e:CurrentPrice", NS)
    if price_el is None:
        price_el = item.find(".//e:StartPrice", NS)

    details = {
        "category_id": get_text(item, ".//e:PrimaryCategory/e:CategoryID"),
        "category_name": get_text(item, ".//e:PrimaryCategory/e:CategoryName"),
        "condition_id": get_text(item, ".//e:ConditionID"),
        "condition_name": get_text(item, ".//e:ConditionDisplayName"),
        "brand": get_item_specific(item, "Brand"),
        "character": (get_item_specific(item, "Character")
                      or get_item_specific(item, "Character Family")),
        "franchise": (get_item_specific(item, "Franchise")
                      or get_item_specific(item, "TV Show")
                      or get_item_specific(item, "Theme")),
        "image_count": str(len(image_urls)),
        "image_urls": " | ".join(image_urls),
        "view_count": get_text(item, ".//e:HitCount") or "0",
    }
    return details, None


def enrich_sample(access_token, sample):
    """50件サンプルの各商品を GetItem で補完する"""
    enriched = []
    total = len(sample)

    for i, row in enumerate(sample, 1):
        item_id = row.get("item_id", "")
        print(f"  [{i:>2}/{total}] GetItem: {item_id} ... ", end="", flush=True)

        response = fetch_item_details(access_token, item_id)

        if response.status_code != 200:
            print(f"HTTP {response.status_code} → スキップ")
            enriched.append(row)
            time.sleep(REQUEST_INTERVAL)
            continue

        details, errors = parse_item_details(response.text)

        if errors:
            print(f"エラー: {errors[0]} → スキップ")
            enriched.append(row)
            time.sleep(REQUEST_INTERVAL)
            continue

        # 既存データに GetItem の結果をマージする
        merged = dict(row)
        for key, value in details.items():
            if value:  # 空でなければ上書き
                merged[key] = value
        enriched.append(merged)
        print("OK")

        time.sleep(REQUEST_INTERVAL)

    return enriched


# ============================================================
# マッピング判定
# ============================================================

def detect_product_type(row):
    """Product Type を自動判定する"""
    title = (row.get("title") or "").lower()
    category = (row.get("category_name") or "").lower()

    # 1. 商品ラインで判定
    for keyword, ptype in PRODUCT_LINE_MAP.items():
        if keyword in title:
            return ptype

    # 2. eBay カテゴリで判定
    if "model" in category and "kit" in category:
        if any(bw in title for bw in BUILT_KEYWORDS):
            return "Scale Figures"
        return "Model Kits"
    if "plush" in category or "stuffed" in category:
        return "Plush & Soft Toys"
    if "vintage" in category or "pre-1990" in category:
        return "Vintage & Retro Toys"
    if "action figure" in category:
        return "Action Figures"

    # 3. タイトルキーワードで判定（"figure" 以外）
    for keyword, ptype in TYPE_KEYWORDS.items():
        if keyword in title:
            return ptype

    # 4. 判定不能 → 手動確認リスト
    return ""


def detect_franchise(row):
    """Franchise を自動判定する"""
    # Item Specifics の franchise が取れていればそれを優先
    ebay_franchise = (row.get("franchise") or "").strip()
    if ebay_franchise:
        return ebay_franchise

    title = (row.get("title") or "").lower()
    for franchise, keywords in FRANCHISE_MAP.items():
        for kw in keywords:
            if kw in title:
                return franchise
    return ""


def normalize_vendor(row):
    """Vendor を正規化する"""
    # Item Specifics の brand を優先
    brand = (row.get("brand") or "").strip()
    sources = [brand, row.get("title") or ""]

    for source in sources:
        source_lower = source.lower()
        for vendor, patterns in VENDOR_NORMALIZE.items():
            for pattern in patterns:
                if pattern in source_lower:
                    return vendor
    return ""


def map_condition(row):
    """Condition を Shopify タグにマッピングする"""
    condition = (row.get("condition_name") or "").strip().lower()
    if not condition:
        return ""
    if condition in CONDITION_MAP:
        return CONDITION_MAP[condition]
    for key, value in CONDITION_MAP.items():
        if key in condition:
            return value
    return ""


# ============================================================
# 分析・レポート生成
# ============================================================

def generate_report(sample, usd_rows):
    """6観点分析 + マッピング試適用のレポートを生成する"""
    lines = []

    def w(text=""):
        lines.append(text)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    w("=" * 70)
    w(f"  50件サンプル分析レポート（{timestamp}）")
    w(f"  母集団: USD 出品 {len(usd_rows)} 件 / サンプル: {len(sample)} 件")
    w("=" * 70)

    # --- 各商品のマッピング結果を先に計算 ---
    results = []
    for row in sample:
        results.append({
            "row": row,
            "product_type": detect_product_type(row),
            "franchise": detect_franchise(row),
            "vendor": normalize_vendor(row),
            "condition": map_condition(row),
        })

    # === 観点1: 商品タイプ ===
    w()
    w("=" * 70)
    w("  観点1: 商品タイプの分布（Product Type）")
    w("=" * 70)
    w()

    type_counts = Counter(r["product_type"] or "(判定不能)" for r in results)
    for ptype, count in type_counts.most_common():
        w(f"  {ptype:25s}: {count} 件")
    w()
    type_resolved = sum(1 for r in results if r["product_type"])
    w(f"  自動判定率: {type_resolved}/{len(sample)} ({type_resolved/len(sample)*100:.1f}%)")

    # === 観点2: フランチャイズ ===
    w()
    w("=" * 70)
    w("  観点2: フランチャイズの分布")
    w("=" * 70)
    w()

    franchise_counts = Counter(r["franchise"] or "(判定不能)" for r in results)
    for franchise, count in franchise_counts.most_common():
        w(f"  {franchise:30s}: {count} 件")
    w()
    franchise_resolved = sum(1 for r in results if r["franchise"])
    w(f"  自動判定率: {franchise_resolved}/{len(sample)} ({franchise_resolved/len(sample)*100:.1f}%)")

    # === 観点3: メーカー ===
    w()
    w("=" * 70)
    w("  観点3: メーカー（Vendor）の分布")
    w("=" * 70)
    w()

    brand_filled = sum(1 for r in results if (r["row"].get("brand") or "").strip())
    w(f"  GetItem の Brand フィールド入力率: {brand_filled}/{len(sample)} ({brand_filled/len(sample)*100:.1f}%)")
    w()

    vendor_counts = Counter(r["vendor"] or "(判定不能)" for r in results)
    for vendor, count in vendor_counts.most_common():
        w(f"  {vendor:25s}: {count} 件")
    w()
    vendor_resolved = sum(1 for r in results if r["vendor"])
    w(f"  自動判定率: {vendor_resolved}/{len(sample)} ({vendor_resolved/len(sample)*100:.1f}%)")

    # === 観点4: 価格帯 ===
    w()
    w("=" * 70)
    w("  観点4: 価格帯の分布")
    w("=" * 70)
    w()

    w("  [母集団（USD全件）の価格帯分布]")
    ranges = [(0, 30), (30.01, 100), (100.01, 300), (300.01, float("inf"))]
    for low, high in ranges:
        count = sum(1 for r in usd_rows if low <= extract_price(r) <= high)
        high_label = f"${high:.0f}" if high != float("inf") else "$∞"
        rate = count / len(usd_rows) * 100 if usd_rows else 0
        w(f"  ${low:>7.0f} 〜 {high_label:>6s}: {count:>6} 件 ({rate:5.1f}%)")
    w()

    w("  [サンプルの価格帯分布]")
    for low, high in ranges:
        count = sum(1 for r in results if low <= extract_price(r["row"]) <= high)
        high_label = f"${high:.0f}" if high != float("inf") else "$∞"
        w(f"  ${low:>7.0f} 〜 {high_label:>6s}: {count:>4} 件")

    # === 観点5: Condition ===
    w()
    w("=" * 70)
    w("  観点5: Condition 表記の実態")
    w("=" * 70)
    w()

    w("  [サンプルの eBay Condition 値]")
    raw_cond = Counter((r["row"].get("condition_name") or "(空欄)") for r in results)
    for cond, count in raw_cond.most_common():
        w(f"  {cond:30s}: {count} 件")
    w()

    w("  [Shopify Condition タグへのマッピング結果]")
    cond_counts = Counter(r["condition"] or "(判定不能)" for r in results)
    for cond, count in cond_counts.most_common():
        w(f"  {cond:15s}: {count} 件")
    w()
    cond_resolved = sum(1 for r in results if r["condition"])
    w(f"  自動判定率: {cond_resolved}/{len(sample)} ({cond_resolved/len(sample)*100:.1f}%)")

    # === 観点6: 画像 ===
    w()
    w("=" * 70)
    w("  観点6: 画像の状況")
    w("=" * 70)
    w()

    img_counts = []
    for r in results:
        try:
            ic = int(r["row"].get("image_count") or "0")
        except ValueError:
            ic = 0
        img_counts.append(ic)

    avg = sum(img_counts) / len(img_counts) if img_counts else 0
    under_3 = sum(1 for c in img_counts if c < 3)
    w(f"  平均画像枚数: {avg:.1f} 枚")
    w(f"  画像3枚未満: {under_3}/{len(sample)} ({under_3/len(sample)*100:.1f}%)")
    w()

    img_dist = Counter(img_counts)
    w("  [画像枚数分布]")
    for count in sorted(img_dist.keys()):
        w(f"  {count:>2} 枚: {img_dist[count]} 件")

    # === マッピング自動判定率サマリー ===
    w()
    w("=" * 70)
    w("  マッピング自動判定率サマリー")
    w("=" * 70)
    w()

    all_resolved = sum(1 for r in results
                       if r["product_type"] and r["franchise"]
                       and r["vendor"] and r["condition"])

    w(f"  Product Type : {type_resolved/len(sample)*100:5.1f}%")
    w(f"  Franchise    : {franchise_resolved/len(sample)*100:5.1f}%")
    w(f"  Vendor       : {vendor_resolved/len(sample)*100:5.1f}%")
    w(f"  Condition    : {cond_resolved/len(sample)*100:5.1f}%")
    w(f"  ---")
    w(f"  全4項目判定  : {all_resolved/len(sample)*100:5.1f}% ({all_resolved}/{len(sample)})")
    w()
    target = 80
    if all_resolved / len(sample) * 100 >= target:
        w(f"  → 目標 {target}% を達成。")
    else:
        w(f"  → 目標 {target}% 未達。辞書・ルールの拡充が必要です。")

    # === 手動確認リスト ===
    w()
    w("=" * 70)
    w("  手動確認リスト（いずれかの項目が判定不能）")
    w("=" * 70)
    w()

    manual_count = 0
    for r in results:
        missing = []
        if not r["product_type"]:
            missing.append("ProductType")
        if not r["franchise"]:
            missing.append("Franchise")
        if not r["vendor"]:
            missing.append("Vendor")
        if not r["condition"]:
            missing.append("Condition")
        if missing:
            manual_count += 1
            row = r["row"]
            w(f"  [{row.get('item_id', '')}] ${row.get('price', '')}")
            w(f"    Title    : {(row.get('title') or '')[:80]}")
            w(f"    Category : {row.get('category_name', '')}")
            w(f"    Condition: {row.get('condition_name', '')}")
            w(f"    Brand    : {row.get('brand', '')}")
            w(f"    不足項目 : {', '.join(missing)}")
            w()

    if manual_count == 0:
        w("  なし（全件自動判定済み）")

    return "\n".join(lines)


# ============================================================
# メイン処理
# ============================================================

def main():
    print()
    print("=" * 60)
    print("  Step 2: サンプル抽出 → GetItem 補完 → 分析")
    print("=" * 60)
    print()

    # --- USD CSV を読み込む ---
    usd_csv = os.path.join(DATA_DIR, "active_listings_usd.csv")
    if not os.path.exists(usd_csv):
        print(f"[エラー] {usd_csv} が見つかりません。")
        print("  先に filter_us_listings.py を実行してください。")
        sys.exit(1)

    usd_rows = load_csv(usd_csv)
    print(f"[OK] USD 出品を読み込みました: {len(usd_rows)} 件")

    # --- 50件サンプル抽出 ---
    random.seed(42)
    sample = stratified_sample(usd_rows)
    print(f"[OK] サンプル抽出: {len(sample)} 件")
    print()

    # --- GetItem で詳細補完 ---
    access_token = load_token()
    print("[INFO] GetItem で詳細データを補完します...")
    print()
    enriched = enrich_sample(access_token, sample)
    print()

    # --- 補完済みサンプルを保存 ---
    # 全カラムを統一する
    all_keys = [
        "item_id", "sku", "title", "category_id", "category_name",
        "price", "currency", "condition_id", "condition_name",
        "quantity_available", "brand", "character", "franchise",
        "watchers", "image_count", "image_urls",
        "listing_start_date", "view_count",
    ]
    # 欠けているキーを空文字で補完
    for row in enriched:
        for key in all_keys:
            if key not in row:
                row[key] = ""

    sample_path = os.path.join(DATA_DIR, "sample_50_enriched.csv")
    save_csv(enriched, sample_path, fieldnames=all_keys)
    print(f"[OK] 補完済みサンプル保存: {sample_path}")

    # --- 分析・マッピング試適用 ---
    print("[INFO] 分析とマッピング試適用を実行しています...")
    report = generate_report(enriched, usd_rows)

    report_path = os.path.join(DATA_DIR, "analysis_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[OK] レポート保存: {report_path}")
    print()

    # コンソールにも表示
    print(report)


if __name__ == "__main__":
    main()
