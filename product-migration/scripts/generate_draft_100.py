# ============================================================
# ドラフト100件生成スクリプト
#
# 【役割】
#   1. review_list.csv の判断結果を反映
#   2. 分類 A（198件）から watchers 上位100件を選定
#   3. draft_100.csv と draft_100_summary.txt を出力
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/generate_draft_100.py
# ============================================================

import csv
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "product-migration", "data")

SHOPIFY_RATE = 0.91

# enrich_target_sample.py と同じマッピング辞書を使う
# ここでは必要な部分だけ再定義

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
    "model kit": "Model Kits", "plastic model": "Model Kits",
    "plamo": "Model Kits", "gunpla": "Model Kits",
    "1/35": "Model Kits", "1/48": "Model Kits", "1/72": "Model Kits",
    "1/144": "Model Kits", "1/100": "Model Kits",
    "plush": "Plush & Soft Toys", "stuffed": "Plush & Soft Toys",
    "soft toy": "Plush & Soft Toys", "doll": "Plush & Soft Toys",
    "mascot": "Plush & Soft Toys",
    "vintage": "Vintage & Retro Toys", "retro": "Vintage & Retro Toys",
    "trading card": "Trading Cards", "pokemon card": "Trading Cards",
    "yugioh": "Trading Cards", "yu-gi-oh": "Trading Cards",
    "weiss schwarz": "Trading Cards", "union arena": "Trading Cards",
    "tcg": "Trading Cards", "ccg": "Trading Cards",
    "holo": "Trading Cards", "foil card": "Trading Cards",
    "blu-ray": "Media & Books", "bluray": "Media & Books",
    "dvd": "Media & Books", "manga": "Media & Books",
    "comics": "Media & Books", "comic": "Media & Books",
    "artbook": "Media & Books", "art book": "Media & Books",
    "art works": "Media & Books", "book": "Media & Books",
    "novel": "Media & Books", "soundtrack": "Media & Books",
    "vinyl": "Media & Books", "cd ": "Media & Books",
    "game software": "Video Games", "game cartridge": "Video Games",
    "game boy": "Video Games", "gameboy": "Video Games",
    "famicom": "Video Games", "super famicom": "Video Games",
    "sega saturn": "Video Games", "dreamcast": "Video Games",
    "neo geo": "Video Games", "neogeo": "Video Games",
    "playstation": "Video Games", "ps1": "Video Games",
    "ps2": "Video Games", "ps3": "Video Games",
    "pc engine": "Video Games", "game & watch": "Video Games",
    "amiibo": "Video Games",
    "acrylic stand": "Goods & Accessories", "acrylic keychain": "Goods & Accessories",
    "can badge": "Goods & Accessories", "pin badge": "Goods & Accessories",
    "rubber strap": "Goods & Accessories", "clear file": "Goods & Accessories",
    "tapestry": "Goods & Accessories", "poster": "Goods & Accessories",
    "shikishi": "Goods & Accessories", "keychain": "Goods & Accessories",
    "towel": "Goods & Accessories", "pen light": "Goods & Accessories",
    "t-shirt": "Goods & Accessories", "tee": "Goods & Accessories",
    "n gauge": "Model Trains", "model train": "Model Trains",
    "tomix": "Model Trains", "kato n": "Model Trains",
    "tamagotchi": "Electronic Toys", "game watch": "Electronic Toys",
    "morpher": "Tokusatsu Toys", "henshin": "Tokusatsu Toys",
    "megazord": "Tokusatsu Toys", "memorial edition": "Tokusatsu Toys",
}

FRANCHISE_MAP = {
    "Dragon Ball": ["dragon ball", "dragonball", "dbz", "dr. slump", "dr slump"],
    "One Piece": ["one piece", "onepiece"],
    "Naruto": ["naruto", "boruto", "shippuden"],
    "Gundam": ["gundam"],
    "Demon Slayer": ["demon slayer", "kimetsu"],
    "My Hero Academia": ["my hero academia", "boku no hero"],
    "Evangelion": ["evangelion", "eva unit"],
    "Sailor Moon": ["sailor moon"],
    "Pokemon": ["pokemon", "pikachu"],
    "Studio Ghibli": ["ghibli", "totoro", "spirited away", "kiki", "mononoke",
                       "howl", "nausicaa", "laputa", "ponyo"],
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
    "Transformers": ["transformers"],
    "Power Rangers": ["power rangers", "sentai", "megazord", "gokaiger",
                       "hurricaneger", "abaranger", "gaoranger"],
    "Godzilla": ["godzilla", "kaiju"],
    "Hololive": ["hololive", "vtuber"],
    "Fate": ["fate/", "fate stay", "fate grand", "fate zero"],
    "Sword Art Online": ["sword art online"],
    "Disney": ["disney", "mickey"],
    "Marvel": ["marvel", "avengers", "spider-man", "iron man"],
    "Star Wars": ["star wars"],
    "Mario": ["mario", "super mario"],
    "Zelda": ["zelda", "hyrule"],
    "Kirby": ["kirby"],
    "Monster Hunter": ["monster hunter"],
    "Persona": ["persona"],
    "Hatsune Miku": ["hatsune miku", "vocaloid", "miku"],
    "Resident Evil": ["resident evil", "biohazard"],
    "Doraemon": ["doraemon"],
    "Digimon": ["digimon"],
    "LEGO": ["lego"],
    "Yu-Gi-Oh": ["yu-gi-oh", "yugioh"],
    "Beyblade": ["beyblade"],
    "Tamagotchi": ["tamagotchi"],
}

VENDOR_NORMALIZE = {
    "Bandai": ["bandai", "bandai namco", "bandai spirits"],
    "Banpresto": ["banpresto"],
    "Good Smile Company": ["good smile", "goodsmile"],
    "Kotobukiya": ["kotobukiya"],
    "MegaHouse": ["megahouse", "mega house"],
    "Tamashii Nations": ["tamashii nations", "tamashii"],
    "Kaiyodo": ["kaiyodo"],
    "Medicom Toy": ["medicom"],
    "Takara Tomy": ["takara tomy", "takara", "tomy"],
    "Max Factory": ["max factory"],
    "Square Enix": ["square enix", "play arts"],
    "Hasbro": ["hasbro"],
    "Nintendo": ["nintendo"],
    "Konami": ["konami"],
    "Capcom": ["capcom"],
    "LEGO": ["lego"],
    "Tamiya": ["tamiya"],
    "SEGA": ["sega"],
    "Taito": ["taito"],
    "FuRyu": ["furyu"],
    "Hot Toys": ["hot toys"],
    "FREEing": ["freeing"],
    "NECA": ["neca"],
    "X-Plus": ["x-plus"],
    "DAMTOYS": ["damtoys"],
    "KATO": ["kato"],
    "Hobby Max": ["hobby max"],
    "Union Creative": ["union creative"],
    "Aniplex": ["aniplex"],
    "Plex": ["plex"],
    "Ensky": ["ensky"],
}

CONDITION_MAP = {
    "new": "Mint", "brand new": "Mint",
    "new with tags": "Mint", "new with box": "Mint",
    "new other": "Near Mint", "new without tags": "Near Mint",
    "open box": "Near Mint", "like new": "Near Mint",
    "used - like new": "Near Mint",
    "very good": "Good", "used - very good": "Good",
    "good": "Good", "used - good": "Good",
    "used": "Good", "pre-owned": "Good",
    "acceptable": "Fair", "used - acceptable": "Fair",
    "ungraded": "Good",
}


def detect_product_type(row):
    title = (row.get("title") or "").lower()
    category = (row.get("category_name") or "").lower()
    for kw, pt in PRODUCT_LINE_MAP.items():
        if kw in title:
            return pt
    if "model" in category and "kit" in category:
        return "Model Kits"
    if "plush" in category or "stuffed" in category:
        return "Plush & Soft Toys"
    if "vintage" in category or "pre-1990" in category:
        return "Vintage & Retro Toys"
    if "action figure" in category:
        return "Action Figures"
    if "card game" in category or "ccg" in category:
        return "Trading Cards"
    if "video game" in category:
        return "Video Games"
    if "manga" in category or "comic" in category:
        return "Media & Books"
    if "book" in category:
        return "Media & Books"
    if "tamagotchi" in category:
        return "Electronic Toys"
    for kw, pt in TYPE_KEYWORDS.items():
        if kw in title:
            return pt
    return "(不明)"


def detect_franchise(row):
    ebay_f = (row.get("franchise") or "").strip()
    if ebay_f:
        return ebay_f
    title = (row.get("title") or "").lower()
    for franchise, keywords in FRANCHISE_MAP.items():
        for kw in keywords:
            if kw in title:
                return franchise
    return "(不明)"


def normalize_vendor(row):
    brand = (row.get("brand") or "").strip()
    sources = [brand, row.get("title") or ""]
    for source in sources:
        sl = source.lower()
        for vendor, patterns in VENDOR_NORMALIZE.items():
            for p in patterns:
                if p in sl:
                    return vendor
    return "(不明)"


def map_condition(row):
    cond = (row.get("condition_name") or "").strip().lower()
    if not cond:
        return "(不明)"
    if cond in CONDITION_MAP:
        return CONDITION_MAP[cond]
    for key, val in CONDITION_MAP.items():
        if key in cond:
            return val
    return "(不明)"


def load_csv(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_csv(rows, filepath, fieldnames):
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def get_price(row):
    try:
        return float(row.get("price", "0") or "0")
    except ValueError:
        return 0.0


def get_watchers(row):
    try:
        return int(row.get("watchers", "0") or "0")
    except ValueError:
        return 0


# ============================================================
# メイン
# ============================================================

def main():
    print()
    print("=" * 60)
    print("  ドラフト100件 生成")
    print("=" * 60)
    print()

    # --- 分類 A を読み込む ---
    auto_path = os.path.join(DATA_DIR, "auto_convert.csv")
    auto_rows = load_csv(auto_path)
    print(f"[OK] 分類 A 読み込み: {len(auto_rows)} 件")

    # --- review_list の ok を追加 ---
    review_path = os.path.join(DATA_DIR, "review_list.csv")
    review_rows = load_csv(review_path)

    ok_ids = set()
    exclude_ids = set()
    for r in review_rows:
        d = (r.get("decision") or "").strip().lower()
        if d == "ok":
            ok_ids.add(r["item_id"])
        elif d == "exclude":
            exclude_ids.add(r["item_id"])

    print(f"[OK] review_list: ok={len(ok_ids)}, exclude={len(exclude_ids)}")

    # ok の商品を enriched から取得して分類 A に追加
    enriched_path = os.path.join(DATA_DIR, "candidates_200_enriched.csv")
    enriched_rows = load_csv(enriched_path)
    enriched_map = {r["item_id"]: r for r in enriched_rows}

    added = 0
    for iid in ok_ids:
        if iid in enriched_map:
            r = enriched_map[iid]
            price = get_price(r)
            r["shopify_price_draft"] = f"{round(price * SHOPIFY_RATE) - 0.01:.2f}"
            r["_audit_class"] = "A"
            r["_audit_flags"] = "review_ok"
            auto_rows.append(r)
            added += 1

    print(f"[OK] review ok → 分類 A に {added} 件追加 → 合計 {len(auto_rows)} 件")
    print()

    # --- watchers 上位100件を選定 ---
    auto_rows.sort(key=lambda r: get_watchers(r), reverse=True)
    draft = auto_rows[:100]

    print(f"[OK] watchers 上位100件を選定")
    print(f"  Watchers 範囲: {get_watchers(draft[-1])} 〜 {get_watchers(draft[0])}")
    print()

    # --- draft_100.csv を保存 ---
    draft_fields = [
        "item_id", "sku", "title", "category_id", "category_name",
        "price", "shopify_price_draft", "currency",
        "condition_id", "condition_name",
        "quantity_available", "brand", "character", "franchise",
        "watchers", "image_count", "image_urls",
        "listing_start_date", "view_count",
    ]
    for r in draft:
        for key in draft_fields:
            if key not in r:
                r[key] = ""
        # 不要カラムを除去
        r.pop("_audit_class", None)
        r.pop("_audit_flags", None)
        r.pop("_filter_reason", None)

    draft_path = os.path.join(DATA_DIR, "draft_100.csv")
    save_csv(draft, draft_path, fieldnames=draft_fields)
    print(f"[OK] draft_100.csv 保存: {draft_path}")
    print()

    # --- サマリレポート ---
    lines = []

    def w(text=""):
        lines.append(text)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    w("=" * 70)
    w(f"  ドラフト100件 サマリレポート（{timestamp}）")
    w("=" * 70)

    # 基本情報
    w()
    w("  --- 基本情報 ---")
    w(f"  分類 A 合計     : {len(auto_rows)} 件")
    w(f"  うち review ok  : {added} 件")
    w(f"  ドラフト選定    : {len(draft)} 件（watchers 上位）")
    w(f"  Watchers 範囲   : {get_watchers(draft[-1])} 〜 {get_watchers(draft[0])}")
    w(f"  除外（関税上乗せ）: {len(exclude_ids)} 件")

    # 価格帯分布
    w()
    w("  --- 価格帯分布 ---")
    w()
    w(f"  {'価格帯':15s} {'eBay':>6s} {'Shopify(×0.91)':>15s} {'件数':>6s}")
    w(f"  {'-'*46}")
    ranges = [(100, 200), (200, 300), (300, 500), (500, 1000)]
    for lo, hi in ranges:
        cnt = sum(1 for r in draft if lo <= get_price(r) < hi)
        if cnt > 0:
            sp_lo = round(lo * SHOPIFY_RATE)
            sp_hi = round(hi * SHOPIFY_RATE)
            w(f"  ${lo:>3}-${hi:<4d}       ${sp_lo:>3}-${sp_hi:<4d}          {cnt:>4} 件")

    prices = [get_price(r) for r in draft]
    sp_prices = [get_price(r) * SHOPIFY_RATE for r in draft]
    w()
    w(f"  eBay 平均: ${sum(prices)/len(prices):.0f}  中央値: ${sorted(prices)[50]:.0f}")
    w(f"  Shopify 平均: ${sum(sp_prices)/len(sp_prices):.0f}  中央値: ${sorted(sp_prices)[50]:.0f}")

    # Product Type 分布
    w()
    w("  --- Product Type 分布 ---")
    w()
    type_counts = Counter(detect_product_type(r) for r in draft)
    for pt, cnt in type_counts.most_common():
        bar = "█" * cnt
        w(f"  {pt:25s}: {cnt:>3} 件  {bar}")

    # Franchise 分布
    w()
    w("  --- Franchise 分布（上位15 + 不明） ---")
    w()
    franchise_counts = Counter(detect_franchise(r) for r in draft)
    shown = 0
    for fr, cnt in franchise_counts.most_common():
        w(f"  {fr:30s}: {cnt:>3} 件")
        shown += 1
        if shown >= 16:
            remaining = len(franchise_counts) - 16
            if remaining > 0:
                w(f"  ... 他 {remaining} フランチャイズ")
            break

    # Vendor 分布
    w()
    w("  --- Vendor 分布 ---")
    w()
    vendor_counts = Counter(normalize_vendor(r) for r in draft)
    for v, cnt in vendor_counts.most_common():
        w(f"  {v:25s}: {cnt:>3} 件")

    # Condition 分布
    w()
    w("  --- Condition 分布 ---")
    w()
    cond_counts = Counter(map_condition(r) for r in draft)
    for c, cnt in cond_counts.most_common():
        w(f"  {c:15s}: {cnt:>3} 件")

    # 画像枚数
    w()
    w("  --- 画像枚数 ---")
    w()
    img_counts = []
    for r in draft:
        try:
            img_counts.append(int(r.get("image_count") or "0"))
        except ValueError:
            img_counts.append(0)
    avg_img = sum(img_counts) / len(img_counts)
    under3 = sum(1 for c in img_counts if c < 3)
    w(f"  平均: {avg_img:.1f} 枚")
    w(f"  3枚未満: {under3} 件 ({under3/len(draft)*100:.0f}%)")

    # --- バランス分析 ---
    w()
    w("=" * 70)
    w("  バランス分析")
    w("=" * 70)

    # Product Type の偏り
    w()
    w("  --- Product Type の偏り ---")
    top_type = type_counts.most_common(1)[0]
    if top_type[1] > 40:
        w(f"  ⚠ {top_type[0]} が {top_type[1]}% を占めており偏りがある")
    else:
        w(f"  ✓ 最多の {top_type[0]} が {top_type[1]}% で、極端な偏りなし")

    # 1件しかない Product Type
    single_types = [pt for pt, cnt in type_counts.items() if cnt == 1 and pt != "(不明)"]
    if single_types:
        w(f"  ⚠ 1件のみのタイプ: {', '.join(single_types)}")
        w(f"    → ストアのコレクションとして成立しにくい。増やすか初期から外すか検討")

    # Franchise の多様性
    w()
    w("  --- Franchise の多様性 ---")
    known_franchises = [fr for fr, cnt in franchise_counts.items() if fr != "(不明)"]
    unknown_cnt = franchise_counts.get("(不明)", 0)
    w(f"  判明: {len(known_franchises)} フランチャイズ / 不明: {unknown_cnt} 件")

    top_franchise = franchise_counts.most_common(1)[0]
    if top_franchise[0] != "(不明)" and top_franchise[1] > 15:
        w(f"  ⚠ {top_franchise[0]} が {top_franchise[1]} 件で多い。コレクション内で埋もれる可能性")

    # 価格帯の偏り
    w()
    w("  --- 価格帯の偏り ---")
    low_cnt = sum(1 for r in draft if get_price(r) < 200)
    mid_cnt = sum(1 for r in draft if 200 <= get_price(r) < 500)
    high_cnt = sum(1 for r in draft if get_price(r) >= 500)
    w(f"  $100-200: {low_cnt}件 / $200-500: {mid_cnt}件 / $500+: {high_cnt}件")
    if low_cnt < 15:
        w(f"  ⚠ $100-200 帯が {low_cnt} 件と少ない。エントリー価格帯の商品が不足")
    if high_cnt > 40:
        w(f"  ⚠ $500+ が {high_cnt} 件と多い。初回バイヤーにはハードルが高い可能性")

    # --- 最終レビュー確認ポイント ---
    w()
    w("=" * 70)
    w("  最終レビュー確認ポイント")
    w("=" * 70)

    w()
    w("  【そのままで良さそうな点】")
    checklist_ok = []
    if len(known_franchises) >= 15:
        checklist_ok.append("フランチャイズの多様性が十分（ストアの品揃え感）")
    if avg_img >= 4:
        checklist_ok.append(f"平均画像枚数 {avg_img:.1f} 枚（商品ページの説得力）")
    if under3 < 20:
        checklist_ok.append(f"画像3枚未満が {under3} 件のみ（大多数は十分な画像あり）")
    cond_unknown = cond_counts.get("(不明)", 0)
    if cond_unknown < 5:
        checklist_ok.append(f"Condition 不明が {cond_unknown} 件のみ（ほぼ全件判定済み）")

    for item in checklist_ok:
        w(f"  ✓ {item}")

    w()
    w("  【見直した方がよい点】")
    checklist_warn = []
    if low_cnt < 15:
        checklist_warn.append(f"$100-200 帯が {low_cnt} 件 → 手頃な価格の商品を追加検討")
    if unknown_cnt > 20:
        checklist_warn.append(f"Franchise 不明が {unknown_cnt} 件 → コレクション分類時に手動振り分けが必要")
    vendor_unknown = vendor_counts.get("(不明)", 0)
    if vendor_unknown > 30:
        checklist_warn.append(f"Vendor 不明が {vendor_unknown} 件 → Brand フィールドをそのまま Vendor に使う運用で対応可能")
    if single_types:
        checklist_warn.append(f"1件のみの Product Type あり → コレクション編成時に統合を検討")
    if under3 > 0:
        checklist_warn.append(f"画像3枚未満が {under3} 件 → 出品前に撮り直し or eBay 画像流用を確認")

    for item in checklist_warn:
        w(f"  ⚠ {item}")

    if not checklist_warn:
        w("  特になし")

    w()
    w("  【原田が目視確認すべきこと】")
    w("  1. 100件の顔ぶれを見て、Shopify に出したくない商品がないか")
    w("  2. Shopify 暫定価格（× 0.91）が利益率的に問題ないか")
    w("  3. 同じフランチャイズに偏りすぎていないか")
    w("  4. 商品画像のクオリティ（eBay のものをそのまま使えるか）")

    report = "\n".join(lines)

    # レポート保存
    report_path = os.path.join(DATA_DIR, "draft_100_summary.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[OK] サマリレポート保存: {report_path}")
    print()
    print(report)


if __name__ == "__main__":
    main()
