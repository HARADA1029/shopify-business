# ============================================================
# target.csv 母集団から50件サンプル再抽出 → GetItem 補完 → 再分析
#
# 【役割】
#   1. active_listings_target.csv から価格帯で層化した50件を抽出
#   2. GetItem API で詳細データを補完
#   3. sample_50_target_enriched.csv として保存
#   4. 前回結果との比較レポートを生成
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/enrich_target_sample.py
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

REQUEST_INTERVAL = 0.5

# target.csv の価格帯分布に合わせた層化抽出
# $0-30: 0件, $30-100: 441件(7%), $100-300: 2867件(47%), $300+: 2837件(46%)
STRATIFICATION = [
    (30.01, 100, 12),
    (100.01, 300, 22),
    (300.01, float("inf"), 16),
]

# ============================================================
# マッピング辞書（category-mapping.md に基づく ＋ 拡充）
# ============================================================

# 商品ライン → Product Type
PRODUCT_LINE_MAP = {
    # Action Figures
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
    "action figure": "Action Figures",
    # Scale Figures
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
    "freeing": "Scale Figures",
    "scale figure": "Scale Figures",
    "1/4 scale": "Scale Figures",
    "1/6 scale": "Scale Figures",
    "1/7 scale": "Scale Figures",
    "1/8 scale": "Scale Figures",
    "statue": "Scale Figures",
    "bust": "Scale Figures",
    "figure": "Scale Figures",
}

# タイトルキーワード → Product Type（補助判定）
TYPE_KEYWORDS = {
    "model kit": "Model Kits",
    "plastic model": "Model Kits",
    "plamo": "Model Kits",
    "gunpla": "Model Kits",
    "1/35": "Model Kits",
    "1/48": "Model Kits",
    "1/72": "Model Kits",
    "1/144": "Model Kits",
    "1/100": "Model Kits",
    "plush": "Plush & Soft Toys",
    "stuffed": "Plush & Soft Toys",
    "soft toy": "Plush & Soft Toys",
    "doll": "Plush & Soft Toys",
    "mascot": "Plush & Soft Toys",
    "vintage": "Vintage & Retro Toys",
    "retro": "Vintage & Retro Toys",
    # トレーディングカード
    "trading card": "Trading Cards",
    "pokemon card": "Trading Cards",
    "yugioh": "Trading Cards",
    "yu-gi-oh": "Trading Cards",
    "weiss schwarz": "Trading Cards",
    "union arena": "Trading Cards",
    "carddass": "Trading Cards",
    "tcg": "Trading Cards",
    "ccg": "Trading Cards",
    "holo": "Trading Cards",
    "foil card": "Trading Cards",
    # メディア（Blu-ray, DVD, CD, マンガ, 書籍）
    "blu-ray": "Media & Books",
    "bluray": "Media & Books",
    "dvd": "Media & Books",
    "manga": "Media & Books",
    "comics": "Media & Books",
    "comic": "Media & Books",
    "artbook": "Media & Books",
    "art book": "Media & Books",
    "art works": "Media & Books",
    "book": "Media & Books",
    "novel": "Media & Books",
    "soundtrack": "Media & Books",
    "ost": "Media & Books",
    "vinyl": "Media & Books",
    "cd ": "Media & Books",
    # ゲーム
    "game software": "Video Games",
    "game cartridge": "Video Games",
    "game boy": "Video Games",
    "gameboy": "Video Games",
    "famicom": "Video Games",
    "super famicom": "Video Games",
    "sega saturn": "Video Games",
    "dreamcast": "Video Games",
    "neo geo": "Video Games",
    "neogeo": "Video Games",
    "playstation": "Video Games",
    "ps1": "Video Games",
    "ps2": "Video Games",
    "ps3": "Video Games",
    "pc engine": "Video Games",
    "game & watch": "Video Games",
    "amiibo": "Video Games",
    # グッズ
    "acrylic stand": "Goods & Accessories",
    "acrylic keychain": "Goods & Accessories",
    "can badge": "Goods & Accessories",
    "pin badge": "Goods & Accessories",
    "rubber strap": "Goods & Accessories",
    "clear file": "Goods & Accessories",
    "tapestry": "Goods & Accessories",
    "poster": "Goods & Accessories",
    "shikishi": "Goods & Accessories",
    "keychain": "Goods & Accessories",
    "strap": "Goods & Accessories",
    "towel": "Goods & Accessories",
    "pen light": "Goods & Accessories",
    "light stick": "Goods & Accessories",
    # 鉄道模型
    "n gauge": "Model Trains",
    "model train": "Model Trains",
    "railway model": "Model Trains",
    "tomix": "Model Trains",
    "kato n": "Model Trains",
    # たまごっち等電子玩具
    "tamagotchi": "Electronic Toys",
    "game watch": "Electronic Toys",
}

BUILT_KEYWORDS = ["built", "assembled", "painted", "completed", "finished"]

# フランチャイズ辞書（拡充版）
FRANCHISE_MAP = {
    "Dragon Ball": ["dragon ball", "dragonball", "dbz", "db super", "dr. slump", "dr slump"],
    "One Piece": ["one piece", "onepiece"],
    "Naruto": ["naruto", "boruto", "shippuden"],
    "Gundam": ["gundam"],
    "Demon Slayer": ["demon slayer", "kimetsu"],
    "My Hero Academia": ["my hero academia", "boku no hero", "mha"],
    "Neon Genesis Evangelion": ["evangelion", "eva unit", "nerv"],
    "Sailor Moon": ["sailor moon"],
    "Pokemon": ["pokemon", "pikachu", "pokémon"],
    "Studio Ghibli": ["ghibli", "totoro", "spirited away", "kiki", "mononoke", "howl",
                       "nausicaa", "laputa", "ponyo", "joe hisaishi"],
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
    "Power Rangers": ["power rangers", "sentai", "megazord"],
    "Godzilla": ["godzilla", "kaiju"],
    "Hololive": ["hololive", "vtuber"],
    "Love Live": ["love live"],
    "Fate": ["fate/", "fate stay", "fate grand", "fate zero"],
    "Sword Art Online": ["sword art online", "sao "],
    "Re:Zero": ["re:zero", "re zero"],
    "Konosuba": ["konosuba"],
    "Touhou": ["touhou"],
    "Disney": ["disney", "mickey", "donald duck"],
    "Marvel": ["marvel", "avengers", "spider-man", "iron man"],
    "Star Wars": ["star wars"],
    "DC Comics": ["batman", "dc comics", "superman"],
    "Mario": ["mario", "super mario"],
    "Zelda": ["zelda", "hyrule"],
    "Kirby": ["kirby"],
    "Splatoon": ["splatoon"],
    "Monster Hunter": ["monster hunter"],
    "Persona": ["persona"],
    "NieR": ["nier automata", "nier replicant", "nier:"],
    "Haikyu!!": ["haikyu", "haikyuu"],
    "Doraemon": ["doraemon"],
    "Hello Kitty / Sanrio": ["hello kitty", "sanrio"],
    "Initial D": ["initial d"],
    "Cardcaptor Sakura": ["cardcaptor", "card captor sakura"],
    "Overlord": ["overlord"],
    "Violet Evergarden": ["violet evergarden"],
    "High School DxD": ["high school dxd"],
    "Ensemble Stars": ["ensemble stars"],
    "Project Sekai": ["project sekai"],
    "Obey Me": ["obey me"],
    "Pikmin": ["pikmin"],
    "Donkey Kong": ["donkey kong"],
    "King Kong": ["king kong"],
    "LEGO": ["lego"],
    "Digimon": ["digimon"],
    "Yu-Gi-Oh": ["yu-gi-oh", "yugioh"],
}

# Vendor 正規化テーブル（拡充版）
VENDOR_NORMALIZE = {
    "Bandai": ["bandai", "bandai namco", "bandai spirits"],
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
    "Hot Toys": ["hot toys"],
    "FREEing": ["freeing"],
    "FuRyu": ["furyu"],
    "SEGA": ["sega prize", "sega "],
    "Taito": ["taito prize", "taito "],
    "Aniplex": ["aniplex"],
    "Kyoto Animation": ["kyoto animation"],
    "Kodansha": ["kodansha"],
    "Shueisha": ["shueisha"],
    "Nintendo": ["nintendo"],
    "Konami": ["konami"],
    "Capcom": ["capcom"],
    "LEGO": ["lego"],
    "Tamiya": ["tamiya"],
    "Hasegawa": ["hasegawa"],
    "Aoshima": ["aoshima"],
    "NECA": ["neca"],
    "X-Plus": ["x-plus", "xplus"],
    "Art Storm": ["art storm"],
    "Prime 1 Studio": ["prime 1", "prime1"],
    "Ensky": ["ensky"],
    "Epoch": ["epoch"],
    "KATO": ["kato"],
    "TOMIX": ["tomix"],
    "Hori": ["hori"],
    "Pioneer": ["pioneer"],
    "Korg": ["korg"],
    "DMM": ["dmm"],
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
    # 追加: トレカ用
    "ungraded": "Good",
}


# ============================================================
# ユーティリティ
# ============================================================

def load_token():
    if not os.path.exists(TOKEN_FILE):
        print(f"[エラー] トークンファイルが見つかりません: {TOKEN_FILE}")
        sys.exit(1)
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    token = data.get("access_token", "")
    if not token:
        print("[エラー] access_token が空です。")
        sys.exit(1)
    return token


def load_csv(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_csv(rows, filepath, fieldnames=None):
    if not rows:
        return
    if not fieldnames:
        fieldnames = rows[0].keys()
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def extract_price(row):
    try:
        return float(row.get("price", "0") or "0")
    except ValueError:
        return 0.0


def get_text(element, path):
    el = element.find(path, NS)
    return el.text.strip() if el is not None and el.text else ""


def get_item_specific(item_el, name):
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
    sample = []
    for low, high, count in STRATIFICATION:
        stratum = [r for r in rows if low <= extract_price(r) <= high]
        actual = min(count, len(stratum))
        if len(stratum) <= count:
            sample.extend(stratum)
        else:
            sample.extend(random.sample(stratum, count))
        print(f"  ${low:>7.0f} 〜 ${high if high != float('inf') else '∞':>6}: {actual} 件抽出 (母集団 {len(stratum)} 件)")
    return sample


# ============================================================
# GetItem による詳細補完
# ============================================================

def fetch_item_details(access_token, item_id):
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
    return requests.post(TRADING_API_URL, headers=headers, data=xml_request)


def parse_item_details(response_text):
    root = ET.fromstring(response_text)
    ack = get_text(root, "e:Ack")
    if ack not in ("Success", "Warning"):
        errors = root.findall(".//e:Errors/e:ShortMessage", NS)
        return None, [e.text for e in errors if e.text]

    item = root.find(".//e:Item", NS)
    if item is None:
        return None, ["Item 要素が見つかりません"]

    pic_urls = item.findall(".//e:PictureDetails/e:PictureURL", NS)
    image_urls = [u.text for u in pic_urls if u.text]

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
    enriched = []
    total = len(sample)
    for i, row in enumerate(sample, 1):
        item_id = row.get("item_id", "")
        print(f"  [{i:>2}/{total}] GetItem: {item_id} ... ", end="", flush=True)

        try:
            response = fetch_item_details(access_token, item_id)
        except Exception as e:
            print(f"通信エラー: {e} → スキップ")
            enriched.append(row)
            time.sleep(REQUEST_INTERVAL)
            continue

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

        merged = dict(row)
        for key, value in details.items():
            if value:
                merged[key] = value
        enriched.append(merged)
        print("OK")
        time.sleep(REQUEST_INTERVAL)

    return enriched


# ============================================================
# マッピング判定
# ============================================================

def detect_product_type(row):
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
    if "card game" in category or "ccg" in category:
        return "Trading Cards"
    if "video game" in category:
        return "Video Games"
    if "manga" in category or "comic" in category:
        return "Media & Books"
    if "book" in category:
        return "Media & Books"
    if "dvd" in category or "blu-ray" in category:
        return "Media & Books"

    # 3. タイトルキーワードで判定
    for keyword, ptype in TYPE_KEYWORDS.items():
        if keyword in title:
            return ptype

    return ""


def detect_franchise(row):
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
# レポート生成
# ============================================================

# 前回の結果（比較用）
PREV_RESULTS = {
    "sample_size": 35,
    "source": "active_listings_usd.csv (6921件)",
    "product_type": 45.7,
    "franchise": 60.0,
    "vendor": 31.4,
    "condition": 80.0,
    "all_four": 25.7,
    "avg_images": 4.5,
}


def generate_report(sample, target_rows):
    lines = []

    def w(text=""):
        lines.append(text)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    w("=" * 70)
    w(f"  50件サンプル再分析レポート（{timestamp}）")
    w(f"  母集団: active_listings_target.csv {len(target_rows)} 件")
    w(f"  サンプル: {len(sample)} 件")
    w("=" * 70)

    # --- マッピング結果を計算 ---
    results = []
    for row in sample:
        results.append({
            "row": row,
            "product_type": detect_product_type(row),
            "franchise": detect_franchise(row),
            "vendor": normalize_vendor(row),
            "condition": map_condition(row),
        })

    # === サンプル価格帯内訳 ===
    w()
    w("=" * 70)
    w("  サンプルの価格帯内訳")
    w("=" * 70)
    w()
    ranges = [(30.01, 100), (100.01, 300), (300.01, float("inf"))]
    for low, high in ranges:
        count = sum(1 for r in results if low <= extract_price(r["row"]) <= high)
        high_label = f"${high:.0f}" if high != float("inf") else "$∞"
        w(f"  ${low:>7.0f} 〜 {high_label:>6s}: {count:>4} 件")

    # === 観点1: Product Type ===
    w()
    w("=" * 70)
    w("  観点1: Product Type の分布")
    w("=" * 70)
    w()

    type_counts = Counter(r["product_type"] or "(判定不能)" for r in results)
    for ptype, count in type_counts.most_common():
        w(f"  {ptype:25s}: {count} 件")
    w()
    type_resolved = sum(1 for r in results if r["product_type"])
    type_rate = type_resolved / len(sample) * 100
    w(f"  自動判定率: {type_resolved}/{len(sample)} ({type_rate:.1f}%)")
    w(f"  前回: {PREV_RESULTS['product_type']:.1f}% → 今回: {type_rate:.1f}% ({type_rate - PREV_RESULTS['product_type']:+.1f}pt)")

    # === 観点2: Franchise ===
    w()
    w("=" * 70)
    w("  観点2: Franchise の分布")
    w("=" * 70)
    w()

    franchise_counts = Counter(r["franchise"] or "(判定不能)" for r in results)
    for franchise, count in franchise_counts.most_common():
        w(f"  {franchise:30s}: {count} 件")
    w()
    franchise_resolved = sum(1 for r in results if r["franchise"])
    franchise_rate = franchise_resolved / len(sample) * 100
    w(f"  自動判定率: {franchise_resolved}/{len(sample)} ({franchise_rate:.1f}%)")
    w(f"  前回: {PREV_RESULTS['franchise']:.1f}% → 今回: {franchise_rate:.1f}% ({franchise_rate - PREV_RESULTS['franchise']:+.1f}pt)")

    # === 観点3: Vendor ===
    w()
    w("=" * 70)
    w("  観点3: Vendor の分布")
    w("=" * 70)
    w()

    brand_filled = sum(1 for r in results if (r["row"].get("brand") or "").strip())
    w(f"  GetItem Brand フィールド入力率: {brand_filled}/{len(sample)} ({brand_filled/len(sample)*100:.1f}%)")
    w()

    vendor_counts = Counter(r["vendor"] or "(判定不能)" for r in results)
    for vendor, count in vendor_counts.most_common():
        w(f"  {vendor:25s}: {count} 件")
    w()
    vendor_resolved = sum(1 for r in results if r["vendor"])
    vendor_rate = vendor_resolved / len(sample) * 100
    w(f"  自動判定率: {vendor_resolved}/{len(sample)} ({vendor_rate:.1f}%)")
    w(f"  前回: {PREV_RESULTS['vendor']:.1f}% → 今回: {vendor_rate:.1f}% ({vendor_rate - PREV_RESULTS['vendor']:+.1f}pt)")

    # === 観点4: Condition ===
    w()
    w("=" * 70)
    w("  観点4: Condition")
    w("=" * 70)
    w()

    w("  [eBay Condition 値]")
    raw_cond = Counter((r["row"].get("condition_name") or "(空欄)") for r in results)
    for cond, count in raw_cond.most_common():
        w(f"  {cond:30s}: {count} 件")
    w()

    w("  [Shopify マッピング結果]")
    cond_counts = Counter(r["condition"] or "(判定不能)" for r in results)
    for cond, count in cond_counts.most_common():
        w(f"  {cond:15s}: {count} 件")
    w()
    cond_resolved = sum(1 for r in results if r["condition"])
    cond_rate = cond_resolved / len(sample) * 100
    w(f"  自動判定率: {cond_resolved}/{len(sample)} ({cond_rate:.1f}%)")
    w(f"  前回: {PREV_RESULTS['condition']:.1f}% → 今回: {cond_rate:.1f}% ({cond_rate - PREV_RESULTS['condition']:+.1f}pt)")

    # === 観点5: 画像 ===
    w()
    w("=" * 70)
    w("  観点5: 画像の状況")
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
    w(f"  平均画像枚数: {avg:.1f} 枚 (前回: {PREV_RESULTS['avg_images']:.1f} 枚)")
    w(f"  画像3枚未満: {under_3}/{len(sample)} ({under_3/len(sample)*100:.1f}%)")

    # === マッピング自動判定率サマリー（前回比較付き）===
    w()
    w("=" * 70)
    w("  マッピング自動判定率サマリー（前回 vs 今回）")
    w("=" * 70)
    w()

    all_resolved = sum(1 for r in results
                       if r["product_type"] and r["franchise"]
                       and r["vendor"] and r["condition"])
    all_rate = all_resolved / len(sample) * 100

    w(f"  {'項目':20s} {'前回':>8s} {'今回':>8s} {'変化':>8s}")
    w(f"  {'-'*48}")
    w(f"  {'Product Type':20s} {PREV_RESULTS['product_type']:>7.1f}% {type_rate:>7.1f}% {type_rate - PREV_RESULTS['product_type']:>+7.1f}pt")
    w(f"  {'Franchise':20s} {PREV_RESULTS['franchise']:>7.1f}% {franchise_rate:>7.1f}% {franchise_rate - PREV_RESULTS['franchise']:>+7.1f}pt")
    w(f"  {'Vendor':20s} {PREV_RESULTS['vendor']:>7.1f}% {vendor_rate:>7.1f}% {vendor_rate - PREV_RESULTS['vendor']:>+7.1f}pt")
    w(f"  {'Condition':20s} {PREV_RESULTS['condition']:>7.1f}% {cond_rate:>7.1f}% {cond_rate - PREV_RESULTS['condition']:>+7.1f}pt")
    w(f"  {'-'*48}")
    w(f"  {'全4項目判定':20s} {PREV_RESULTS['all_four']:>7.1f}% {all_rate:>7.1f}% {all_rate - PREV_RESULTS['all_four']:>+7.1f}pt")
    w()

    target = 80
    if all_rate >= target:
        w(f"  → 目標 {target}% を達成!")
    else:
        w(f"  → 目標 {target}% 未達。さらなる辞書拡充が必要です。")

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
            w(f"    Brand    : {row.get('brand', '')}")
            w(f"    Condition: {row.get('condition_name', '')}")
            w(f"    判定結果 : Type={r['product_type'] or '?'} / Franchise={r['franchise'] or '?'} / Vendor={r['vendor'] or '?'} / Cond={r['condition'] or '?'}")
            w(f"    不足項目 : {', '.join(missing)}")
            w()

    if manual_count == 0:
        w("  なし（全件自動判定済み）")

    w()
    w(f"  手動確認が必要な商品: {manual_count}/{len(sample)} 件")

    return "\n".join(lines)


# ============================================================
# メイン処理
# ============================================================

def main():
    print()
    print("=" * 60)
    print("  target.csv 50件サンプル再抽出 → GetItem 補完 → 再分析")
    print("=" * 60)
    print()

    # --- target CSV を読み込む ---
    target_csv = os.path.join(DATA_DIR, "active_listings_target.csv")
    if not os.path.exists(target_csv):
        print(f"[エラー] {target_csv} が見つかりません。")
        print("  先に filter_target.py を実行してください。")
        sys.exit(1)

    target_rows = load_csv(target_csv)
    print(f"[OK] target.csv を読み込みました: {len(target_rows)} 件")
    print()

    # --- 50件サンプル抽出 ---
    random.seed(2026)  # 前回と異なるシードで新しいサンプルを取得
    print("[INFO] 価格帯で層化した50件を抽出...")
    sample = stratified_sample(target_rows)
    print(f"\n[OK] サンプル抽出: {len(sample)} 件")

    # sample_50_target.csv を保存
    sample_path = os.path.join(DATA_DIR, "sample_50_target.csv")
    save_csv(sample, sample_path)
    print(f"[OK] サンプル保存: {sample_path}")
    print()

    # --- GetItem で詳細補完 ---
    access_token = load_token()
    print("[INFO] GetItem で詳細データを補完します...")
    print()
    enriched = enrich_sample(access_token, sample)
    print()

    # --- 補完済みサンプルを保存 ---
    all_keys = [
        "item_id", "sku", "title", "category_id", "category_name",
        "price", "currency", "condition_id", "condition_name",
        "quantity_available", "brand", "character", "franchise",
        "watchers", "image_count", "image_urls",
        "listing_start_date", "view_count",
    ]
    for row in enriched:
        for key in all_keys:
            if key not in row:
                row[key] = ""
        # _filter_reason を除外
        row.pop("_filter_reason", None)

    enriched_path = os.path.join(DATA_DIR, "sample_50_target_enriched.csv")
    save_csv(enriched, enriched_path, fieldnames=all_keys)
    print(f"[OK] 補完済みサンプル保存: {enriched_path}")
    print()

    # --- 分析・レポート ---
    print("[INFO] 分析とマッピング試適用を実行しています...")
    report = generate_report(enriched, target_rows)

    report_path = os.path.join(DATA_DIR, "target_analysis_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[OK] レポート保存: {report_path}")
    print()
    print(report)


if __name__ == "__main__":
    main()
