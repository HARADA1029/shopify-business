"""低品質記事を高品質で再生成するスクリプト（1回実行用）"""
import requests
import json
import re
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_APP_PASSWORD", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=%s" % GEMINI_KEY

# Shopify Electronic Toys 画像を取得
with open(os.path.join(PROJECT_ROOT, ".shopify_token.json"), "r") as f:
    shopify_token = json.load(f)["access_token"]

resp = requests.get(
    "https://hd-toys-store-japan.myshopify.com/admin/api/2026-04/products.json?status=active&limit=50&fields=id,title,handle,images,product_type",
    headers={"X-Shopify-Access-Token": shopify_token}, timeout=30,
)
products = resp.json().get("products", [])
et_products = [p for p in products if p.get("product_type") == "Electronic Toys" and p.get("images")]

all_images = []
for p in et_products:
    for img in p.get("images", [])[:2]:
        all_images.append(img["src"])

print("Available images: %d" % len(all_images))

CTA = (
    '<div style="margin:30px 0;padding:24px 20px;background:#f8f9fa;border:1px solid #e0e0e0;border-radius:10px;">'
    '<h3 style="font-size:17px;font-weight:bold;margin:0 0 12px 0;color:#333;">Where to Buy</h3>'
    '<div style="display:flex;gap:10px;flex-wrap:wrap;">'
    '<a href="https://hd-toys-store-japan.myshopify.com/collections/electronic-toys'
    '?utm_source=hd-bodyscience&utm_medium=article&utm_campaign=blog-regen" '
    'target="_blank" rel="noopener noreferrer" '
    'style="display:inline-block;padding:10px 22px;background:#4CAF50;color:#fff;'
    'text-decoration:none;border-radius:6px;font-weight:bold;font-size:14px;">'
    'View on HD Toys Store Japan</a>'
    '<a href="https://www.ebay.com/str/hdtoysstore'
    '?utm_source=hd-bodyscience&utm_medium=article&utm_campaign=blog-regen" '
    'target="_blank" rel="noopener noreferrer" '
    'style="display:inline-block;padding:10px 22px;background:#0064D2;color:#fff;'
    'text-decoration:none;border-radius:6px;font-weight:bold;font-size:14px;">'
    'Browse on eBay</a>'
    '</div>'
    '<p style="font-size:12px;color:#888;margin:10px 0 0 0;">'
    'All items shipped directly from Japan. Condition may vary.</p></div>'
)


def make_image_html(src, alt="Japanese collectible"):
    return (
        '<figure style="margin:20px 0;text-align:center;">'
        '<img src="%s" alt="%s" style="max-width:100%%;height:auto;border-radius:6px;" />'
        '<figcaption style="font-size:12px;color:#888;margin-top:6px;">'
        'Source: HD Toys Store Japan</figcaption></figure>' % (src, alt)
    )


def generate_and_update(post_id, prompt, images, category_ids, tag_names):
    """Geminiで生成→画像挿入→品質チェック→WordPress更新"""
    print("\n[INFO] Generating article for post %d..." % post_id)
    resp = requests.post(GEMINI_URL, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=180)

    if resp.status_code != 200:
        print("[ERROR] Gemini: %d" % resp.status_code)
        return False

    parts = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
    html = ""
    for part in parts:
        if "text" in part:
            html = part["text"]
            break

    if not html:
        print("[ERROR] No content generated")
        return False

    # 画像挿入
    for i in range(8):
        placeholder = "INSERT_IMAGE_%d" % (i + 1)
        if placeholder in html and i < len(images):
            html = html.replace(placeholder, make_image_html(images[i]))
        elif placeholder in html:
            html = html.replace(placeholder, "")

    # CTA追加
    html += CTA

    # 品質チェック
    text = re.sub(r"<[^>]+>", "", html)
    wc = len(text.split())
    ic = len(re.findall(r"<img", html))
    h2c = len(re.findall(r"<h2", html))
    print("[CHECK] Words:%d Images:%d H2:%d" % (wc, ic, h2c))

    if wc < 800:
        print("[REJECT] Too short (%d < 800)" % wc)
        return False
    if h2c < 3:
        print("[REJECT] Too few H2 (%d < 3)" % h2c)
        return False

    # タグ作成
    tag_ids = []
    for name in tag_names:
        try:
            tr = requests.get(
                "https://hd-bodyscience.com/wp-json/wp/v2/tags?search=%s&_fields=id" % requests.utils.quote(name),
                auth=(WP_USER, WP_PASS), timeout=10,
            )
            if tr.status_code == 200 and tr.json():
                tag_ids.append(tr.json()[0]["id"])
                continue
            tr2 = requests.post(
                "https://hd-bodyscience.com/wp-json/wp/v2/tags",
                auth=(WP_USER, WP_PASS), json={"name": name}, timeout=10,
            )
            if tr2.status_code == 201:
                tag_ids.append(tr2.json()["id"])
        except Exception:
            pass

    # アイキャッチ画像アップロード
    featured_id = None
    if images:
        try:
            img_data = requests.get(images[0], timeout=30).content
            upload = requests.post(
                "https://hd-bodyscience.com/wp-json/wp/v2/media",
                auth=(WP_USER, WP_PASS),
                headers={"Content-Disposition": "attachment; filename=article-%d.jpg" % post_id, "Content-Type": "image/jpeg"},
                data=img_data, timeout=30,
            )
            if upload.status_code == 201:
                featured_id = upload.json()["id"]
                print("[OK] Featured image uploaded: %d" % featured_id)
        except Exception:
            pass

    # WordPress 更新
    payload = {"content": html, "status": "publish"}
    if category_ids:
        payload["categories"] = category_ids
    if tag_ids:
        payload["tags"] = tag_ids
    if featured_id:
        payload["featured_media"] = featured_id

    update = requests.post(
        "https://hd-bodyscience.com/wp-json/wp/v2/posts/%d" % post_id,
        auth=(WP_USER, WP_PASS), json=payload, timeout=30,
    )

    if update.status_code == 200:
        print("[OK] Post %d updated and PUBLISHED (%dw, %dimg, %dH2)" % (post_id, wc, ic, h2c))
        return True
    else:
        print("[ERROR] Update failed: %d %s" % (update.status_code, update.text[:200]))
        return False


# ============================================================
# 記事 4861: Tamagotchi Collector Guide
# ============================================================
prompt1 = """IMPORTANT: Write this entire article in ENGLISH only.

Write a high-quality collector's guide about Tamagotchi for hd-bodyscience.com.
Match the quality of the best human-written articles on this site (1300+ words, 6+ H2, deep content).

Title: Tamagotchi Collector Guide: Top Models Worth Buying from Japan

Structure:

<p>[Hook: Evocative opening about Tamagotchi nostalgia from 1996. The tiny beeping device that became a worldwide phenomenon. Make the reader feel the nostalgia. 4-5 vivid sentences.]</p>

<p>[Bridge: Japan had exclusive Tamagotchi models never released elsewhere. Today these are highly collectible. 3-4 sentences.]</p>

INSERT_IMAGE_1

<h2>What Makes Japanese Tamagotchi Special</h2>
<p>[Japan-exclusive releases, collaborations, color variants not available internationally. Bandai released 100+ models in Japan vs ~30 internationally. 150+ words.]</p>

<h3>Tamagotchi Generations Explained</h3>
<p>[Original (1996-1998): the classic egg shape. Connection era (2004-2008): infrared communication. Color screen era (2008-2013): Tamagotchi iD, iD L, P's. Modern era (2017-present): Tamagotchi On/Pix/Uni. 150+ words with specific model names and years.]</p>

INSERT_IMAGE_2

<h2>Top 5 Tamagotchi Models Worth Collecting</h2>

<h3>1. Tamagotchi Chibi (Mini)</h3>
<p>[Compact version. Apple Tree Green rarity. Simple gameplay appeals to purists. Limited colorways. 100+ words.]</p>

<h3>2. Tamagotchi iD L</h3>
<p>[2011 release. Full color TFT screen. Downloadable characters via infrared. Pink and Yellow Japan-exclusive colors. One of the most advanced pre-modern models. 100+ words.]</p>

INSERT_IMAGE_3

<h3>3. Tamagotchi P's with Sanrio Characters Pierce</h3>
<p>[2013 release. Interchangeable Tama Deco Pierce system. Sanrio collaboration added Hello Kitty, My Melody characters. The Pierce accessories are now separately collectible. 100+ words.]</p>

<h3>4. Tamagotchi x Hatsune Miku (Mikutchi)</h3>
<p>[2021 Vocaloid collaboration. Raise Miku-themed characters. Turquoise design. Limited production run. Appeals to both Tamagotchi and Vocaloid collectors. 100+ words.]</p>

INSERT_IMAGE_4

<h3>5. Tamagotchi x L'Arc-en-Ciel (Larkutchi Z)</h3>
<p>[1998 collaboration with iconic Japanese rock band. Black heart-with-wings design. Three versions released: Larkutchi, Larkutchi Z, Larkutchi P!. Extremely rare, never reissued. 100+ words.]</p>

<h2>Condition Guide for Pre-Owned Tamagotchi</h2>
<p>[Introduction to why condition matters for electronic toys. Japanese collectors tend to preserve items carefully. 80+ words.]</p>

<h3>What to Inspect Before Buying</h3>
<ul>
<li><strong>Screen:</strong> Check for dead pixels, contrast fading, or screen burn. Color screen models are especially prone to this.</li>
<li><strong>Buttons:</strong> All three buttons should click cleanly and respond. Membrane buttons can wear out over time.</li>
<li><strong>Battery compartment:</strong> Open and check for corrosion. Japanese sellers typically remove batteries for storage.</li>
<li><strong>Sound:</strong> Speaker should produce clear tones without crackling or distortion.</li>
<li><strong>Chain/strap hole:</strong> The ball chain attachment should be intact. Missing chains reduce value slightly.</li>
<li><strong>Original packaging:</strong> Box, manual, and insert tray can double the value of common models.</li>
</ul>

INSERT_IMAGE_5

<h2>Price Ranges and Market Trends</h2>
<p>[General pricing: common models $15-40, mid-range collectibles $50-150, rare collaborations $200-500+. Market is appreciating as 90s nostalgia grows. Color screen era models are currently undervalued. 120+ words.]</p>

<h2>Why Buy Tamagotchi from Japan</h2>
<p>[Japanese collector culture values preservation. Items often stored in original packaging. Japan-exclusive editions only available through Japanese sellers. Buying from a specialist ensures authenticity verification. 100+ words. Informative tone, not promotional.]</p>

INSERT_IMAGE_6

<h2>Conclusion</h2>
<p>[Warm wrap-up from a collector's perspective. Tamagotchi represents a unique intersection of technology, culture, and nostalgia. The best time to start collecting is now while many models are still affordable. 4-5 sentences.]</p>

RULES:
- 1500+ words minimum
- HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>
- NO <h1> tags
- Write INSERT_IMAGE_1 through INSERT_IMAGE_6 exactly where specified
- Every section must have substantial, specific content
- Include years, manufacturer names, model numbers where relevant
- Tone: knowledgeable collector, warm, helpful
- NOT a sales pitch
"""

# カテゴリを検索/作成
try:
    cat_resp = requests.get(
        "https://hd-bodyscience.com/wp-json/wp/v2/categories?search=Electronic&_fields=id,name",
        auth=(WP_USER, WP_PASS), timeout=10,
    )
    et_cat_id = cat_resp.json()[0]["id"] if cat_resp.status_code == 200 and cat_resp.json() else None
except Exception:
    et_cat_id = None

if not et_cat_id:
    try:
        cr = requests.post(
            "https://hd-bodyscience.com/wp-json/wp/v2/categories",
            auth=(WP_USER, WP_PASS),
            json={"name": "Electronic Toys", "slug": "electronic-toys"},
            timeout=10,
        )
        if cr.status_code == 201:
            et_cat_id = cr.json()["id"]
    except Exception:
        pass

print("Electronic Toys category ID: %s" % et_cat_id)

result1 = generate_and_update(
    post_id=4861,
    prompt=prompt1,
    images=all_images[:6],
    category_ids=[et_cat_id] if et_cat_id else [],
    tag_names=["Tamagotchi", "Electronic Toys", "Japan Import", "Collectible", "Bandai", "Digital Pet", "Pre-owned"],
)

time.sleep(3)

# ============================================================
# 記事 4862: Electronic Toys Guide
# ============================================================
prompt2 = """IMPORTANT: Write this entire article in ENGLISH only.

Write a comprehensive guide about Japanese electronic toys for hd-bodyscience.com.
Match the quality of the best human-written articles on this site (1300+ words, 6+ H2, deep content).

Title: Electronic Toys from Japan: Tamagotchi, Digivice & Collector Essentials

Structure:

<p>[Hook: Japan has been at the forefront of electronic toy innovation since the 1980s. From digital pets to handheld gaming devices, Japanese electronic toys combine technology with creative design in ways no other country matches. 4-5 engaging sentences.]</p>

<p>[Bridge: For collectors, Japanese electronic toys represent a fascinating category: part technology, part pop culture artifact. Many items were Japan-exclusive and are now impossible to find outside specialist sellers. 3-4 sentences.]</p>

INSERT_IMAGE_1

<h2>The Golden Age of Japanese Electronic Toys</h2>
<p>[1990s-2000s overview. Tamagotchi (1996), Digimon/Digivice (1997), Pokemon Pikachu pedometer (1998), Mega Man Battle Chip Gate. How Japan's toy industry merged with anime/game franchises. 200+ words.]</p>

<h3>Why Japan's Electronic Toys Were Different</h3>
<p>[Japanese market got experimental designs, anime tie-ins, limited collaborations. Western markets got simplified versions. Cultural factors: Japanese willingness to adopt digital pets, compact design aesthetics. 150+ words.]</p>

INSERT_IMAGE_2

<h2>Key Categories of Japanese Electronic Toys</h2>

<h3>Digital Pets (Tamagotchi & Beyond)</h3>
<p>[Tamagotchi's impact and evolution. Other digital pets: Digimon, Pokemon Pikachu. Japan-exclusive variants. 150+ words.]</p>

INSERT_IMAGE_3

<h3>Digivice and Franchise Devices</h3>
<p>[Digimon virtual pet devices. Different generations. How they tied into the anime series. Collectibility factors. 120+ words.]</p>

<h3>Gaming Peripherals</h3>
<p>[Mega Man Battle Chip Gate, e-Reader, Barcode Battler. Devices that bridged physical and digital play. 120+ words.]</p>

INSERT_IMAGE_4

<h3>Music and Entertainment Devices</h3>
<p>[Drum Master mini, karaoke toys, Pripara/PriChan arcade card devices adapted for home. 100+ words.]</p>

<h2>Collector's Buying Guide: Pre-Owned Electronic Toys</h2>
<p>[Why buying pre-owned makes sense for this category. Many items discontinued, no longer manufactured. 80+ words.]</p>

<h3>Essential Condition Checks</h3>
<ul>
<li><strong>Battery compartment:</strong> The #1 issue with used electronic toys. Check for corrosion, leakage damage, spring contact quality.</li>
<li><strong>Screen condition:</strong> LCD screens can develop dead lines or faded segments over time. Test if possible.</li>
<li><strong>Button functionality:</strong> Rubber membrane buttons degrade. All inputs should register cleanly.</li>
<li><strong>Sound output:</strong> Speakers can blow or crackle. Essential for the full experience.</li>
<li><strong>Structural integrity:</strong> Check battery door clips, hinge mechanisms, and case screws.</li>
</ul>

INSERT_IMAGE_5

<h2>Value Trends in Japanese Electronic Toys</h2>
<p>[What's appreciating: limited collaborations, first-generation devices, complete-in-box items. What's stable: common models, damaged units. Market growing as 90s/00s nostalgia wave continues. 150+ words.]</p>

<h2>Why Source from Japan</h2>
<p>[Japanese collector culture of careful storage. Original packaging preservation. Authentication through specialist sellers. Japan-exclusive models only available from Japanese sellers. 120+ words. Informative, not pushy.]</p>

INSERT_IMAGE_6

<h2>Conclusion</h2>
<p>[Japanese electronic toys are a unique collecting niche that combines technology history with pop culture. 4-5 sentences, warm collector perspective.]</p>

RULES:
- 1500+ words minimum
- HTML tags: <h2>, <h3>, <p>, <ul>, <li>, <strong>
- NO <h1>
- INSERT_IMAGE_1 through INSERT_IMAGE_6 placeholders
- Deep, specific content in every section
- Tone: knowledgeable, collector-friendly, not salesy
"""

result2 = generate_and_update(
    post_id=4862,
    prompt=prompt2,
    images=all_images[:6],
    category_ids=[et_cat_id] if et_cat_id else [],
    tag_names=["Electronic Toys", "Tamagotchi", "Digivice", "Japan Import", "Collectible", "Bandai", "Pre-owned"],
)

print("\n=== Results ===")
print("Article 4861: %s" % ("PUBLISHED" if result1 else "FAILED"))
print("Article 4862: %s" % ("PUBLISHED" if result2 else "FAILED"))
