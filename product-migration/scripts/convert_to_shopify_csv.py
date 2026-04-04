# ============================================================
# Shopify 商品CSV 変換スクリプト
#
# 【役割】
#   shopify_ready_100.csv を Shopify 商品インポート CSV 形式に変換する
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/convert_to_shopify_csv.py
#
# 【出力】
#   product-migration/data/shopify_import.csv
#
# 【参照】
#   docs/shopify-import-method.md
#   https://help.shopify.com/en/manual/products/import-export/using-csv
# ============================================================

import csv
import os
import re
import unicodedata
from collections import Counter
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "product-migration", "data")

# Shopify CSV のカラム定義（公式仕様に準拠）
SHOPIFY_COLUMNS = [
    "Handle",
    "Title",
    "Body (HTML)",
    "Vendor",
    "Product Category",
    "Type",
    "Tags",
    "Published",
    "Option1 Name",
    "Option1 Value",
    "Variant SKU",
    "Variant Grams",
    "Variant Inventory Tracker",
    "Variant Inventory Qty",
    "Variant Inventory Policy",
    "Variant Fulfillment Service",
    "Variant Price",
    "Variant Compare At Price",
    "Variant Requires Shipping",
    "Variant Taxable",
    "Image Src",
    "Image Position",
    "Image Alt Text",
    "SEO Title",
    "SEO Description",
    "Status",
]


def load_csv(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def slugify(text):
    """タイトルから Shopify Handle（URL スラッグ）を生成する"""
    # Unicode 正規化
    text = unicodedata.normalize("NFKD", text)
    # ASCII 以外を除去
    text = text.encode("ascii", "ignore").decode("ascii")
    # 小文字化
    text = text.lower()
    # 英数字とハイフン以外を除去
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    # スペースをハイフンに
    text = re.sub(r"[\s]+", "-", text.strip())
    # 連続ハイフンを1つに
    text = re.sub(r"-+", "-", text)
    # 先頭・末尾のハイフンを除去
    text = text.strip("-")
    # Shopify Handle は最大255文字
    return text[:255]


def make_unique_handles(handles):
    """Handle の重複を解消する（末尾に連番を付与）"""
    seen = Counter()
    result = []
    for h in handles:
        seen[h] += 1
        if seen[h] == 1:
            result.append(h)
        else:
            result.append(f"{h}-{seen[h]}")
    return result


def build_seo_description(title, condition, vendor):
    """SEO 用の meta description を生成する（160文字以内）"""
    parts = [title]
    if condition:
        parts.append(f"Condition: {condition}.")
    if vendor:
        parts.append(f"By {vendor}.")
    parts.append("Ships from Japan.")
    desc = " ".join(parts)
    return desc[:160]


def convert():
    print()
    print("=" * 60)
    print("  Shopify CSV 変換")
    print("=" * 60)
    print()

    # --- 入力 ---
    input_path = os.path.join(DATA_DIR, "shopify_ready_100.csv")
    rows = load_csv(input_path)
    print(f"[OK] 入力: {len(rows)} 商品")

    # --- Handle 生成 ---
    raw_handles = [slugify(r.get("title", "")) for r in rows]
    handles = make_unique_handles(raw_handles)

    # 重複チェック
    dup_count = sum(1 for i, h in enumerate(handles) if h != raw_handles[i])

    # --- 変換 ---
    output_rows = []
    warnings = []
    total_images = 0
    products_with_no_image = []

    for idx, (row, handle) in enumerate(zip(rows, handles)):
        title = row.get("title", "")
        body_html = row.get("description_html", "")
        vendor = row.get("vendor", "")
        product_type = row.get("product_type", "")
        tags = row.get("tags", "")
        sku = row.get("sku", "")
        weight_g = row.get("weight", "0")
        price = row.get("price", "0")
        compare_at = row.get("compare_at_price", "")
        condition = row.get("condition", "")

        # 画像 URL をリスト化
        image_urls_raw = row.get("image_urls", "") or ""
        image_urls = [u.strip() for u in image_urls_raw.split("|") if u.strip()]

        # バリデーション
        if not title:
            warnings.append(f"[{idx+1}] Title が空: item_id={row.get('item_id','')}")
        if not handle:
            warnings.append(f"[{idx+1}] Handle が生成できない: title={title[:30]}")
            handle = f"product-{idx+1}"

        # SEO
        seo_title = title[:70] if title else ""
        seo_desc = build_seo_description(title, condition, vendor)

        # --- 1行目（商品情報 + 1枚目の画像）---
        first_image = image_urls[0] if image_urls else ""
        if not image_urls:
            products_with_no_image.append(row.get("item_id", ""))

        first_row = {
            "Handle": handle,
            "Title": title,
            "Body (HTML)": body_html,
            "Vendor": vendor,
            "Product Category": "",
            "Type": product_type,
            "Tags": tags,
            "Published": "FALSE",
            "Option1 Name": "Title",
            "Option1 Value": "Default Title",
            "Variant SKU": sku,
            "Variant Grams": weight_g,
            "Variant Inventory Tracker": "shopify",
            "Variant Inventory Qty": "1",
            "Variant Inventory Policy": "deny",
            "Variant Fulfillment Service": "manual",
            "Variant Price": price,
            "Variant Compare At Price": compare_at,
            "Variant Requires Shipping": "TRUE",
            "Variant Taxable": "FALSE",
            "Image Src": first_image,
            "Image Position": "1" if first_image else "",
            "Image Alt Text": title[:255] if first_image else "",
            "SEO Title": seo_title,
            "SEO Description": seo_desc,
            "Status": "draft",
        }
        output_rows.append(first_row)
        if first_image:
            total_images += 1

        # --- 2行目以降（追加画像）---
        for img_idx, img_url in enumerate(image_urls[1:], 2):
            img_row = {col: "" for col in SHOPIFY_COLUMNS}
            img_row["Handle"] = handle
            img_row["Image Src"] = img_url
            img_row["Image Position"] = str(img_idx)
            img_row["Image Alt Text"] = f"{title[:240]} - Image {img_idx}"
            output_rows.append(img_row)
            total_images += 1

    # --- 出力 ---
    output_path = os.path.join(DATA_DIR, "shopify_import.csv")
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SHOPIFY_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"[OK] 出力: {output_path}")
    print()

    # --- レポート ---
    print("=" * 60)
    print("  変換レポート")
    print("=" * 60)
    print()
    print(f"  商品数       : {len(rows)}")
    print(f"  CSV 行数     : {len(output_rows)} 行（ヘッダー除く）")
    print(f"  画像数       : {total_images} 枚")
    print(f"  Handle 重複  : {dup_count} 件（連番で解消済み）")
    print()

    if products_with_no_image:
        print(f"  ⚠ 画像なし商品: {len(products_with_no_image)} 件")
        for iid in products_with_no_image:
            print(f"    {iid}")
        print()

    if warnings:
        print(f"  ⚠ 警告: {len(warnings)} 件")
        for w in warnings:
            print(f"    {w}")
        print()

    # Status / Published の確認
    print(f"  --- Shopify 設定値 ---")
    print(f"  Status       : draft（全件）")
    print(f"  Published    : FALSE（全件）")
    print(f"  Inventory Qty: 1（全件）")
    print(f"  Taxable      : FALSE（全件）")
    print(f"  Requires Ship: TRUE（全件）")
    print()

    # Collection の注意
    print(f"  --- Collection について ---")
    print(f"  Shopify CSV では Collection 列がないため、")
    print(f"  インポート後に Automated Collection（タグベース）で振り分ける。")
    print(f"  Tags に Product Type が含まれているため、")
    print(f"  「Tag = Scale Figures」→ Figures & Statues コレクション")
    print(f"  のような条件で自動振り分けが可能。")
    print()

    # Handle サンプル
    print(f"  --- Handle サンプル（先頭5件）---")
    for r in output_rows[:5]:
        if r["Title"]:
            print(f"  {r['Handle'][:60]}")
    print()

    # 最終確認ポイント
    print("=" * 60)
    print("  原田の最終確認ポイント")
    print("=" * 60)
    print()
    print("  1. shopify_import.csv をスプレッドシートで開き、")
    print("     Title / Variant Price / Body (HTML) を10件ほど確認")
    print()
    print("  2. Image Src の URL を5件ほどブラウザで開き、")
    print("     画像が表示されることを確認")
    print()
    print("  3. Tags が正しく入っているか確認")
    print("     （Good, Pokemon, Trading Cards, Japan Import 等）")
    print()
    print("  4. 問題なければ Shopify 管理画面から CSV インポート:")
    print("     Products > Import > shopify_import.csv を選択")
    print()


if __name__ == "__main__":
    convert()
