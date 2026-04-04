# ============================================================
# Shopify 投入用データ準備スクリプト
#
# 【役割】
#   final_100.csv を入力に、GetItem で Description / Weight を取得し、
#   Product Type / Collection / Tags / SKU を統合した
#   shopify_ready_100.csv を生成する
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/prepare_shopify_data.py
#
# 【参照】
#   docs/shopify-data-preparation.md
# ============================================================

import csv
import html
import json
import os
import re
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

REQUEST_INTERVAL = 0.5
SHOPIFY_RATE = 0.91


# ============================================================
# ユーティリティ
# ============================================================

def load_token():
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("access_token", "")


def load_csv(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_csv(rows, filepath, fieldnames):
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def round_to_99(price):
    """価格を $X.99 に丸める"""
    return round(price) - 0.01


def get_text(element, path):
    el = element.find(path, NS)
    return el.text.strip() if el is not None and el.text else ""


def median(values):
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


# ============================================================
# Description 整形
# ============================================================

def extract_description(raw_html):
    """eBay Description HTML から商品説明部分を抽出する"""
    if not raw_html:
        return ""

    # style タグと中身を除去
    text = re.sub(r"<style[^>]*>.*?</style>", "", raw_html, flags=re.DOTALL)

    # <br> を改行に
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # その他の HTML タグを除去
    text = re.sub(r"<[^>]+>", "", text)

    # HTML エンティティをデコード
    text = html.unescape(text)

    # 連続空白を正規化
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    # eBay 固有セクションを除去
    # "Shipping" 以降を切り取る
    for separator in ["Shipping", "International Buyers", "Import duties"]:
        idx = text.find(separator)
        if idx > 0:
            text = text[:idx].strip()

    # タイトルの重複除去（先頭に商品タイトルが2回入っていることが多い）
    # "Description" というラベルも除去
    text = re.sub(r"^.*?Description\s*", "", text, count=1, flags=re.DOTALL)
    text = text.strip()

    return text


def build_shopify_description(desc_text, product_type, condition, vendor, franchise):
    """Shopify 用の Description HTML を生成する"""
    # 商品説明部分
    if desc_text:
        # 改行を <br> に変換
        body = desc_text.replace("\n", "<br>\n")
        body_html = f"<p>{body}</p>"
    else:
        # フォールバック
        pt_label = product_type if product_type and product_type != "Other" else "collectible item"
        body_html = (
            f"<p>Authentic {pt_label} imported directly from Japan.</p>\n"
            f"<p>This item is pre-owned. Please refer to the photos for detailed condition.</p>"
        )

    # Details セクション
    details = []
    if condition:
        details.append(f"<li>Condition: {condition}</li>")
    if vendor:
        details.append(f"<li>Brand: {vendor}</li>")
    if franchise and franchise != "(不明)":
        details.append(f"<li>Franchise: {franchise}</li>")
    details.append("<li>Ships from Japan</li>")

    details_html = "\n".join(f"  {d}" for d in details)

    return f"{body_html}\n\n<h3>Details</h3>\n<ul>\n{details_html}\n</ul>"


# ============================================================
# Product Type / Collection / Tags / Weight
# ============================================================

PRODUCT_LINE_MAP = {
    "s.h.figuarts": "Action Figures", "shfiguarts": "Action Figures",
    "sh figuarts": "Action Figures", "figma": "Action Figures",
    "mafex": "Action Figures", "revoltech": "Action Figures",
    "robot spirits": "Action Figures", "robot damashii": "Action Figures",
    "d-arts": "Action Figures", "ultra-act": "Action Figures",
    "s.h.monsterarts": "Action Figures", "shmonsterarts": "Action Figures",
    "action figure": "Action Figures",
    "nendoroid": "Scale Figures", "banpresto": "Scale Figures",
    "prize figure": "Scale Figures", "ichiban kuji": "Scale Figures",
    "pop up parade": "Scale Figures", "q posket": "Scale Figures",
    "artfx": "Scale Figures", "p.o.p": "Scale Figures",
    "portrait of pirates": "Scale Figures", "g.e.m.": "Scale Figures",
    "alter": "Scale Figures", "freeing": "Scale Figures",
    "scale figure": "Scale Figures",
    "1/4 scale": "Scale Figures", "1/6 scale": "Scale Figures",
    "1/7 scale": "Scale Figures", "1/8 scale": "Scale Figures",
    "statue": "Scale Figures", "bust": "Scale Figures", "figure": "Scale Figures",
}

TYPE_KEYWORDS = {
    "model kit": "Model Kits", "plastic model": "Model Kits", "gunpla": "Model Kits",
    "plush": "Plush & Soft Toys", "stuffed": "Plush & Soft Toys",
    "doll": "Plush & Soft Toys", "mascot": "Plush & Soft Toys",
    "vintage": "Vintage & Retro Toys", "retro": "Vintage & Retro Toys",
    "trading card": "Trading Cards", "pokemon card": "Trading Cards",
    "yugioh": "Trading Cards", "yu-gi-oh": "Trading Cards",
    "weiss schwarz": "Trading Cards", "tcg": "Trading Cards",
    "ccg": "Trading Cards", "holo": "Trading Cards",
    "blu-ray": "Media & Books", "dvd": "Media & Books",
    "manga": "Media & Books", "comics": "Media & Books", "comic": "Media & Books",
    "artbook": "Media & Books", "art book": "Media & Books",
    "book": "Media & Books", "novel": "Media & Books", "vinyl": "Media & Books",
    "game software": "Video Games", "famicom": "Video Games",
    "sega saturn": "Video Games", "dreamcast": "Video Games",
    "playstation": "Video Games", "neo geo": "Video Games",
    "pc engine": "Video Games", "game & watch": "Video Games", "amiibo": "Video Games",
    "acrylic stand": "Goods & Accessories", "keychain": "Goods & Accessories",
    "poster": "Goods & Accessories", "t-shirt": "Goods & Accessories",
    "n gauge": "Model Trains", "model train": "Model Trains",
    "tamagotchi": "Electronic Toys", "game watch": "Electronic Toys",
    "morpher": "Tokusatsu Toys", "henshin": "Tokusatsu Toys",
    "megazord": "Tokusatsu Toys", "memorial edition": "Tokusatsu Toys",
}


def detect_product_type(title, category):
    tl = title.lower()
    cl = category.lower()
    for kw, pt in PRODUCT_LINE_MAP.items():
        if kw in tl:
            return pt
    if "action figure" in cl:
        return "Action Figures"
    if "card game" in cl or "ccg" in cl:
        return "Trading Cards"
    if "video game" in cl:
        return "Video Games"
    if "manga" in cl or "comic" in cl:
        return "Media & Books"
    if "tamagotchi" in cl:
        return "Electronic Toys"
    if "plush" in cl:
        return "Plush & Soft Toys"
    for kw, pt in TYPE_KEYWORDS.items():
        if kw in tl:
            return pt
    return "Other"


# 初期投入用メインコレクション（Product Type ベース）
COLLECTION_MAP = {
    "Action Figures": "Action Figures",
    "Scale Figures": "Figures & Statues",
    "Plush & Soft Toys": "Plush & Soft Toys",
    "Trading Cards": "Trading Cards",
    "Video Games": "Video Games",
    "Media & Books": "Media & Books",
    "Electronic Toys": "Electronic Toys",
    "Model Kits": "Model Kits",
    "Tokusatsu Toys": "Action Figures",
    "Goods & Accessories": "Other",
    "Model Trains": "Other",
    "Vintage & Retro Toys": "Other",
    "Other": "Other",
}

FRANCHISE_MAP = {
    "Dragon Ball": ["dragon ball", "dragonball", "dbz"],
    "One Piece": ["one piece", "onepiece"],
    "Naruto": ["naruto", "boruto"],
    "Gundam": ["gundam"],
    "Evangelion": ["evangelion"],
    "Sailor Moon": ["sailor moon"],
    "Pokemon": ["pokemon", "pikachu"],
    "Studio Ghibli": ["ghibli", "totoro", "spirited away", "howl", "nausicaa"],
    "Jujutsu Kaisen": ["jujutsu kaisen"],
    "Attack on Titan": ["attack on titan"],
    "Final Fantasy": ["final fantasy"],
    "Kamen Rider": ["kamen rider", "masked rider"],
    "Ultraman": ["ultraman"],
    "Transformers": ["transformers"],
    "Power Rangers": ["power rangers", "sentai", "gokaiger", "hurricaneger", "abaranger"],
    "Godzilla": ["godzilla", "kaiju"],
    "Hatsune Miku": ["hatsune miku", "vocaloid", "miku"],
    "Resident Evil": ["resident evil", "biohazard"],
    "Star Wars": ["star wars"],
    "Disney": ["disney", "mickey"],
    "Marvel": ["marvel", "avengers"],
    "Fate": ["fate/", "fate stay", "fate grand"],
    "Beyblade": ["beyblade"],
    "Tamagotchi": ["tamagotchi"],
    "Yu-Gi-Oh": ["yu-gi-oh", "yugioh"],
    "Bleach": ["bleach"],
}


def detect_franchise(title, ebay_franchise):
    if ebay_franchise:
        return ebay_franchise
    tl = title.lower()
    for fr, keywords in FRANCHISE_MAP.items():
        for kw in keywords:
            if kw in tl:
                return fr
    return ""


CONDITION_MAP = {
    "new": "Mint", "brand new": "Mint",
    "new other": "Near Mint", "like new": "Near Mint",
    "very good": "Good", "good": "Good",
    "used": "Good", "pre-owned": "Good", "ungraded": "Good",
}


def map_condition(condition_name):
    cl = condition_name.strip().lower()
    if not cl:
        return "Good"
    if cl in CONDITION_MAP:
        return CONDITION_MAP[cl]
    for key, val in CONDITION_MAP.items():
        if key in cl:
            return val
    return "Good"


# Product Type 別デフォルト重量（g）
DEFAULT_WEIGHT = {
    "Action Figures": 500,
    "Scale Figures": 800,
    "Plush & Soft Toys": 400,
    "Trading Cards": 100,
    "Video Games": 300,
    "Media & Books": 500,
    "Electronic Toys": 300,
    "Model Kits": 600,
    "Tokusatsu Toys": 500,
    "Goods & Accessories": 300,
    "Model Trains": 400,
    "Vintage & Retro Toys": 400,
    "Other": 500,
}


def build_tags(condition, franchise, product_type):
    """Shopify タグをカンマ区切りで生成する"""
    tags = []
    if condition:
        tags.append(condition)
    if franchise:
        tags.append(franchise)
    if product_type and product_type != "Other":
        tags.append(product_type)
    tags.append("Japan Import")
    return ", ".join(tags)


# ============================================================
# GetItem コール
# ============================================================

def fetch_description_and_weight(access_token, item_id):
    """GetItem で Description と Weight を取得する"""
    headers = {
        "X-EBAY-API-SITEID": "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "GetItem",
        "X-EBAY-API-IAF-TOKEN": access_token,
        "Content-Type": "text/xml",
    }
    xml_req = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
</GetItemRequest>"""

    resp = requests.post(TRADING_API_URL, headers=headers, data=xml_req)
    if resp.status_code != 200:
        return None, None, f"HTTP {resp.status_code}"

    root = ET.fromstring(resp.text)
    ack = get_text(root, "e:Ack")
    if ack not in ("Success", "Warning"):
        err = root.find(".//e:Errors/e:ShortMessage", NS)
        return None, None, err.text if err is not None else "Unknown error"

    item = root.find(".//e:Item", NS)
    if item is None:
        return None, None, "Item not found"

    # Description
    desc_el = item.find("e:Description", NS)
    raw_desc = desc_el.text if desc_el is not None and desc_el.text else ""

    # Weight (lbs/oz → g)
    wm = item.find(".//e:ShippingPackageDetails/e:WeightMajor", NS)
    wn = item.find(".//e:ShippingPackageDetails/e:WeightMinor", NS)
    weight_g = 0
    if wm is not None:
        try:
            lbs = float(wm.text or "0")
            oz = float(wn.text or "0") if wn is not None else 0
            weight_g = int(lbs * 453.592 + oz * 28.3495)
        except ValueError:
            pass

    return raw_desc, weight_g, None


# ============================================================
# メイン処理
# ============================================================

OUTPUT_FIELDS = [
    "item_id", "sku", "title", "description_html",
    "product_type", "collection", "vendor", "tags",
    "price", "compare_at_price", "condition",
    "weight", "weight_unit",
    "image_urls", "image_local_paths",
]


def main():
    print()
    print("=" * 60)
    print("  Shopify 投入用データ準備")
    print("=" * 60)
    print()

    # --- final_100 を読み込む ---
    final_path = os.path.join(DATA_DIR, "final_100.csv")
    rows = load_csv(final_path)
    print(f"[OK] final_100.csv 読み込み: {len(rows)} 件")

    # --- トークン ---
    access_token = load_token()
    if not access_token:
        print("[エラー] トークンがありません")
        sys.exit(1)

    # --- 各商品を処理 ---
    print()
    print("[INFO] GetItem で Description / Weight を取得...")
    print()

    results = []
    desc_ok = 0
    desc_fallback = 0
    weight_from_ebay = 0
    weight_default = 0
    errors = 0

    for i, row in enumerate(rows, 1):
        item_id = row.get("item_id", "")
        title = row.get("title", "")
        category = row.get("category_name", "")
        ebay_price = float(row.get("price", "0") or "0")
        condition_name = row.get("condition_name", "")
        vendor = row.get("vendor", "")
        ebay_franchise = row.get("franchise", "")
        image_urls = row.get("image_urls", "")

        print(f"  [{i:>3}/100] {item_id} ... ", end="", flush=True)

        # GetItem コール
        raw_desc, weight_g, err = fetch_description_and_weight(access_token, item_id)

        if err:
            print(f"エラー: {err}")
            errors += 1
            raw_desc = ""
            weight_g = 0

        else:
            print("OK")

        # --- Description 整形 ---
        desc_text = extract_description(raw_desc)
        product_type = detect_product_type(title, category)
        condition = map_condition(condition_name)
        franchise = detect_franchise(title, ebay_franchise)
        description_html = build_shopify_description(
            desc_text, product_type, condition, vendor, franchise
        )

        if desc_text:
            desc_ok += 1
        else:
            desc_fallback += 1

        # --- Weight ---
        if weight_g > 0:
            weight_from_ebay += 1
        else:
            weight_g = DEFAULT_WEIGHT.get(product_type, 500)
            weight_default += 1

        # --- Collection ---
        collection = COLLECTION_MAP.get(product_type, "Other")

        # --- Tags ---
        tags = build_tags(condition, franchise, product_type)

        # --- SKU ---
        sku = f"EB-{item_id}"

        # --- Shopify 価格 ---
        shopify_price = round_to_99(ebay_price * SHOPIFY_RATE)

        results.append({
            "item_id": item_id,
            "sku": sku,
            "title": title,
            "description_html": description_html,
            "product_type": product_type,
            "collection": collection,
            "vendor": vendor,
            "tags": tags,
            "price": f"{shopify_price:.2f}",
            "compare_at_price": f"{ebay_price:.2f}",
            "condition": condition,
            "weight": str(weight_g),
            "weight_unit": "g",
            "image_urls": image_urls,
            "image_local_paths": "",
        })

        time.sleep(REQUEST_INTERVAL)

    print()

    # --- 保存 ---
    output_path = os.path.join(DATA_DIR, "shopify_ready_100.csv")
    save_csv(results, output_path, fieldnames=OUTPUT_FIELDS)
    print(f"[OK] shopify_ready_100.csv 保存: {output_path}")
    print()

    # --- サマリ ---
    print("=" * 60)
    print("  データ準備サマリ")
    print("=" * 60)
    print()

    print(f"  --- Description ---")
    print(f"  eBay から抽出成功: {desc_ok} 件")
    print(f"  フォールバック使用: {desc_fallback} 件")
    if errors:
        print(f"  GetItem エラー: {errors} 件")
    print()

    print(f"  --- Weight ---")
    print(f"  eBay から取得: {weight_from_ebay} 件")
    print(f"  デフォルト値使用: {weight_default} 件")
    print()

    print(f"  --- Product Type ---")
    pt_counts = Counter(r["product_type"] for r in results)
    for pt, cnt in pt_counts.most_common():
        print(f"  {pt:25s}: {cnt:>3} 件")
    print()

    print(f"  --- Collection（初期投入用）---")
    col_counts = Counter(r["collection"] for r in results)
    for col, cnt in col_counts.most_common():
        print(f"  {col:25s}: {cnt:>3} 件")
    print()

    print(f"  --- Tags サンプル（先頭5件）---")
    for r in results[:5]:
        print(f"  {r['title'][:40]:40s} → {r['tags']}")
    print()

    print(f"  --- 価格 ---")
    prices = [float(r["price"]) for r in results]
    compare = [float(r["compare_at_price"]) for r in results]
    print(f"  Shopify 価格: 平均 ${sum(prices)/len(prices):.0f} / 中央値 ${median(prices):.0f}")
    print(f"  Compare at:   平均 ${sum(compare)/len(compare):.0f} / 中央値 ${median(compare):.0f}")
    print()

    print(f"  --- Vendor ---")
    filled = sum(1 for r in results if r["vendor"])
    print(f"  判明: {filled} 件 / 空欄: {len(results) - filled} 件")
    print()

    print("  --- 次のステップ ---")
    print("  1. shopify_ready_100.csv の Description を先頭10件ほど目視確認")
    print("  2. 問題なければ download_images.py に進む")


if __name__ == "__main__":
    main()
