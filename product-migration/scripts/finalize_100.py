# ============================================================
# final_100.csv 生成スクリプト
#
# 【役割】
#   1. draft_100.csv から差し替え対象を除外
#   2. リザーブから差し替え候補を追加
#   3. Vendor フォールバック処理を適用
#   4. final_100.csv と final_100_summary.txt を出力
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/finalize_100.py
# ============================================================

import csv
import os
import sys
from collections import Counter
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "product-migration", "data")

SHOPIFY_RATE = 0.91

# --- 差し替え対象 ---

# 画像1枚で差し替え（W=80以下の3件）
REMOVE_LOW_IMAGE = {
    "125675764555",   # Sanrio マイメロディ W=80
    "125368588317",   # ベイブレード メテオLドラゴ W=59
    "125374190790",   # ベイブレード ソルブレイズ W=43
}

# たまごっち削減（14→8、6件削除）
REMOVE_TAMAGOTCHI = {
    "125829165327",   # iD L イエロー W=58
    "125612294521",   # iD イエロー W=54
    "126484737361",   # P's パープル W=54
    "125374196354",   # チビ版 ミニ W=46
    "127319151096",   # P's サンリオデコピアス W=44
    "125472436033",   # MIX メロディ ブルー W=43
}

REMOVE_IDS = REMOVE_LOW_IMAGE | REMOVE_TAMAGOTCHI

# --- Vendor 正規化テーブル（拡充版）---

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
    # オーナー承認で追加
    "Sony": ["sony"],
    "Epoch": ["epoch"],
    "Sanrio": ["sanrio"],
    "San-X": ["san-x"],
    "Microsoft": ["microsoft"],
}

# Brand が作品名・キャラ名の場合は Vendor に使わない
BRAND_BLOCKLIST = [
    "tamagotchi", "identityv", "identity v", "peanuts",
    "blythe", "pepsi", "parker",
    "takeshi obata",
    "samanthavega",
]


# ============================================================
# ユーティリティ
# ============================================================

def round_to_99(price):
    """価格を $X.99 に丸める"""
    return round(price) - 0.01


def shopify_price(ebay_price):
    """eBay 価格から Shopify 暫定価格を算出する"""
    return round_to_99(ebay_price * SHOPIFY_RATE)


def median(values):
    """中央値を計算する（偶数個の場合は中央2値の平均）"""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def normalize_vendor(brand, title):
    """Vendor を正規化する。3段階フォールバック"""
    # 1. VENDOR_NORMALIZE にマッチ
    for source in [brand, title]:
        sl = source.lower()
        for vendor, patterns in VENDOR_NORMALIZE.items():
            for p in patterns:
                if p in sl:
                    return vendor

    # 2. Brand が実在メーカー名ならそのまま使う
    brand_stripped = brand.strip()
    if brand_stripped:
        bl = brand_stripped.lower()
        blocked = any(block in bl for block in BRAND_BLOCKLIST)
        if not blocked and len(brand_stripped) >= 2:
            return brand_stripped

    # 3. Vendor 空欄
    return ""


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


# --- Product Type / Franchise / Condition 判定（サマリ用）---

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
    "gunpla": "Model Kits",
    "plush": "Plush & Soft Toys", "stuffed": "Plush & Soft Toys",
    "doll": "Plush & Soft Toys", "mascot": "Plush & Soft Toys",
    "vintage": "Vintage & Retro Toys", "retro": "Vintage & Retro Toys",
    "trading card": "Trading Cards", "pokemon card": "Trading Cards",
    "yugioh": "Trading Cards", "yu-gi-oh": "Trading Cards",
    "weiss schwarz": "Trading Cards", "tcg": "Trading Cards",
    "ccg": "Trading Cards", "holo": "Trading Cards",
    "blu-ray": "Media & Books", "dvd": "Media & Books",
    "manga": "Media & Books", "comics": "Media & Books",
    "comic": "Media & Books", "artbook": "Media & Books",
    "art book": "Media & Books", "book": "Media & Books",
    "novel": "Media & Books", "vinyl": "Media & Books",
    "game software": "Video Games", "famicom": "Video Games",
    "sega saturn": "Video Games", "dreamcast": "Video Games",
    "playstation": "Video Games", "neo geo": "Video Games",
    "pc engine": "Video Games", "game & watch": "Video Games",
    "amiibo": "Video Games",
    "acrylic stand": "Goods & Accessories", "keychain": "Goods & Accessories",
    "poster": "Goods & Accessories", "t-shirt": "Goods & Accessories",
    "n gauge": "Model Trains", "model train": "Model Trains",
    "tamagotchi": "Electronic Toys", "game watch": "Electronic Toys",
    "morpher": "Tokusatsu Toys", "henshin": "Tokusatsu Toys",
    "megazord": "Tokusatsu Toys", "memorial edition": "Tokusatsu Toys",
}


def detect_product_type(row):
    title = (row.get("title") or "").lower()
    category = (row.get("category_name") or "").lower()
    for kw, pt in PRODUCT_LINE_MAP.items():
        if kw in title:
            return pt
    if "action figure" in category:
        return "Action Figures"
    if "card game" in category or "ccg" in category:
        return "Trading Cards"
    if "video game" in category:
        return "Video Games"
    if "manga" in category or "comic" in category:
        return "Media & Books"
    if "tamagotchi" in category:
        return "Electronic Toys"
    if "plush" in category:
        return "Plush & Soft Toys"
    for kw, pt in TYPE_KEYWORDS.items():
        if kw in title:
            return pt
    return "(不明)"


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
    "Power Rangers": ["power rangers", "sentai", "gokaiger", "hurricaneger", "abaranger", "gaoranger"],
    "Godzilla": ["godzilla", "kaiju"],
    "Hatsune Miku": ["hatsune miku", "vocaloid", "miku"],
    "Resident Evil": ["resident evil", "biohazard"],
    "Star Wars": ["star wars"],
    "Disney": ["disney", "mickey"],
    "Marvel": ["marvel", "avengers"],
    "Mario": ["mario"],
    "Zelda": ["zelda"],
    "Monster Hunter": ["monster hunter"],
    "Fate": ["fate/", "fate stay", "fate grand"],
    "Beyblade": ["beyblade"],
    "Tamagotchi": ["tamagotchi"],
    "Yu-Gi-Oh": ["yu-gi-oh", "yugioh"],
    "LEGO": ["lego"],
    "Digimon": ["digimon"],
    "Bleach": ["bleach"],
}


def detect_franchise(row):
    ebay_f = (row.get("franchise") or "").strip()
    if ebay_f:
        return ebay_f
    title = (row.get("title") or "").lower()
    for fr, keywords in FRANCHISE_MAP.items():
        for kw in keywords:
            if kw in title:
                return fr
    return "(不明)"


CONDITION_MAP = {
    "new": "Mint", "brand new": "Mint",
    "new other": "Near Mint", "like new": "Near Mint",
    "very good": "Good", "good": "Good",
    "used": "Good", "pre-owned": "Good", "ungraded": "Good",
}


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


# ============================================================
# メイン
# ============================================================

def main():
    print()
    print("=" * 60)
    print("  final_100.csv 生成")
    print("=" * 60)
    print()

    # --- draft_100 を読み込む ---
    draft = load_csv(os.path.join(DATA_DIR, "draft_100.csv"))
    print(f"[OK] draft_100.csv 読み込み: {len(draft)} 件")

    # --- 差し替え対象を除外 ---
    removed = [r for r in draft if r["item_id"] in REMOVE_IDS]
    kept = [r for r in draft if r["item_id"] not in REMOVE_IDS]
    print(f"[OK] 差し替え除外: {len(removed)} 件")
    print(f"  画像1枚除外: {len([r for r in removed if r['item_id'] in REMOVE_LOW_IMAGE])} 件")
    print(f"  たまごっち削減: {len([r for r in removed if r['item_id'] in REMOVE_TAMAGOTCHI])} 件")
    print(f"  残り: {len(kept)} 件")
    print()

    # --- リザーブから補充 ---
    need = 100 - len(kept)

    auto = load_csv(os.path.join(DATA_DIR, "auto_convert.csv"))
    enriched = load_csv(os.path.join(DATA_DIR, "candidates_200_enriched.csv"))
    review = load_csv(os.path.join(DATA_DIR, "review_list.csv"))
    ok_ids = {r["item_id"] for r in review if (r.get("decision", "") or "").strip().lower() == "ok"}
    ok_enriched = [r for r in enriched if r["item_id"] in ok_ids]

    all_pool = auto + ok_enriched
    kept_ids = {r["item_id"] for r in kept}

    reserves = [r for r in all_pool
                if r["item_id"] not in kept_ids
                and r["item_id"] not in REMOVE_IDS]

    good_reserves = [r for r in reserves if int(r.get("image_count", "0") or "0") >= 3]
    good_reserves.sort(key=lambda r: get_watchers(r), reverse=True)

    added = good_reserves[:need]
    final = kept + added

    # shopify_price_draft を付与（全件に統一適用）
    for r in final:
        r["shopify_price_draft"] = f"{shopify_price(get_price(r)):.2f}"

    print(f"[OK] リザーブから補充: {len(added)} 件")
    for r in added:
        w = get_watchers(r)
        p = get_price(r)
        ic = r.get("image_count", "0")
        t = (r.get("title", ""))[:60]
        print(f"  W={w:>3} ${p:>7.0f} img={ic} | {t}")
    print()

    # --- Vendor フォールバック処理 ---
    vendor_from_normalize = 0
    vendor_from_brand = 0
    vendor_empty = 0

    for r in final:
        brand = (r.get("brand", "") or "").strip()
        title = r.get("title", "") or ""

        vendor = normalize_vendor(brand, title)
        r["vendor"] = vendor

        if not vendor:
            vendor_empty += 1
        else:
            matched_normalize = False
            for source in [brand, title]:
                sl = source.lower()
                for v, patterns in VENDOR_NORMALIZE.items():
                    for p in patterns:
                        if p in sl:
                            matched_normalize = True
                            break
                    if matched_normalize:
                        break
                if matched_normalize:
                    break
            if matched_normalize:
                vendor_from_normalize += 1
            else:
                vendor_from_brand += 1

    print(f"[OK] Vendor フォールバック処理完了")
    print(f"  VENDOR_NORMALIZE マッチ: {vendor_from_normalize} 件")
    print(f"  Brand そのまま採用    : {vendor_from_brand} 件")
    print(f"  Vendor 空欄          : {vendor_empty} 件")
    print()

    # --- watchers でソート ---
    final.sort(key=lambda r: get_watchers(r), reverse=True)

    # --- 保存 ---
    final_fields = [
        "item_id", "sku", "title", "category_id", "category_name",
        "price", "shopify_price_draft", "currency",
        "condition_id", "condition_name",
        "quantity_available", "brand", "vendor", "character", "franchise",
        "watchers", "image_count", "image_urls",
        "listing_start_date", "view_count",
    ]
    for r in final:
        for key in final_fields:
            if key not in r:
                r[key] = ""
        for k in list(r.keys()):
            if k not in final_fields:
                del r[k]

    final_path = os.path.join(DATA_DIR, "final_100.csv")
    save_csv(final, final_path, fieldnames=final_fields)
    print(f"[OK] final_100.csv 保存: {final_path} ({len(final)} 件)")
    print()

    # ============================================================
    # サマリレポート
    # ============================================================

    lines = []

    def w(text=""):
        lines.append(text)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    w("=" * 70)
    w(f"  final_100 サマリレポート（{timestamp}）")
    w("=" * 70)

    w()
    w("  --- 差し替え結果 ---")
    w(f"  draft_100 からの維持: {len(kept)} 件")
    w(f"  画像1枚による差し替え: {len(REMOVE_LOW_IMAGE)} 件除外")
    w(f"  たまごっち削減: {len(REMOVE_TAMAGOTCHI)} 件除外")
    w(f"  リザーブから補充: {len(added)} 件追加")
    w(f"  最終: {len(final)} 件")

    # 価格帯
    w()
    w("  --- 価格帯分布 ---")
    prices = [get_price(r) for r in final]
    sp = [get_price(r) * SHOPIFY_RATE for r in final]
    ranges = [(100, 200), (200, 300), (300, 500), (500, 1000)]
    for lo, hi in ranges:
        cnt = sum(1 for p in prices if lo <= p < hi)
        w(f"  ${lo:>3}-${hi:<4d}: {cnt:>3} 件")
    w()
    w(f"  eBay 平均: ${sum(prices)/len(prices):.0f}  中央値: ${median(prices):.0f}")
    w(f"  Shopify 平均: ${sum(sp)/len(sp):.0f}  中央値: ${median(sp):.0f}")

    # Product Type
    w()
    w("  --- Product Type ---")
    type_counts = Counter(detect_product_type(r) for r in final)
    for pt, cnt in type_counts.most_common():
        w(f"  {pt:25s}: {cnt:>3} 件")

    # Franchise
    w()
    w("  --- Franchise（上位15）---")
    fr_counts = Counter(detect_franchise(r) for r in final)
    for i, (fr, cnt) in enumerate(fr_counts.most_common(15)):
        w(f"  {fr:30s}: {cnt:>3} 件")
    rest = len(fr_counts) - 15
    if rest > 0:
        w(f"  ... 他 {rest} フランチャイズ")

    # Vendor
    w()
    w("  --- Vendor ---")
    vendor_counts = Counter(r.get("vendor", "") or "(空欄)" for r in final)
    for v, cnt in vendor_counts.most_common():
        w(f"  {v:25s}: {cnt:>3} 件")

    w()
    w(f"  Vendor 判明: {sum(1 for r in final if r.get('vendor',''))} 件")
    w(f"  Vendor 空欄: {sum(1 for r in final if not r.get('vendor',''))} 件")

    # Condition
    w()
    w("  --- Condition ---")
    cond_counts = Counter(map_condition(r) for r in final)
    for c, cnt in cond_counts.most_common():
        w(f"  {c:15s}: {cnt:>3} 件")

    # 画像
    w()
    w("  --- 画像 ---")
    img = [int(r.get("image_count", "0") or "0") for r in final]
    w(f"  平均: {sum(img)/len(img):.1f} 枚")
    w(f"  3枚未満: {sum(1 for c in img if c < 3)} 件")

    # たまごっち
    w()
    w("  --- たまごっち関連 ---")
    tama = sum(1 for r in final if "tamagotchi" in (r.get("title", "") or "").lower())
    w(f"  {tama} 件（削減前 14件 → 削減後 {tama} 件）")

    # Shopify 投入準備
    w()
    w("=" * 70)
    w("  Shopify 下書き投入に必要なデータ項目")
    w("=" * 70)
    w()
    w("  final_100.csv にあるデータ:")
    w("  ✓ Title（eBay タイトル → Shopify 用に調整が必要）")
    w("  ✓ Price（Shopify 暫定価格 × 0.91、$X.99 端数処理済み）")
    w("  ✓ eBay price（Compare at price に流用可能）")
    w("  ✓ Vendor（フォールバック済み）")
    w("  ✓ Images（eBay 画像 URL → ダウンロード＆再アップが必要）")
    w("  ✓ Condition（タグとして付与可能）")
    w()
    w("  追加で必要なデータ:")
    w("  □ Product Type（自動判定済みだが最終確認が必要）")
    w("  □ Collection（Product Type + Franchise でマッピング）")
    w("  □ Tags（Condition, Franchise, Brand 等）")
    w("  □ Description（eBay から取得 or 新規作成）")
    w("  □ Weight（配送料計算用。eBay に入っていれば流用）")
    w("  □ SKU（eBay SKU をそのまま使うか、Shopify 用に再設計するか）")
    w("  □ 画像ファイル（eBay CDN URL → ローカル DL → Shopify アップロード）")

    report = "\n".join(lines)
    report_path = os.path.join(DATA_DIR, "final_100_summary.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[OK] サマリ保存: {report_path}")
    print()
    print(report)


if __name__ == "__main__":
    main()
