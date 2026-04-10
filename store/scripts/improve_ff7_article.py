"""FF7 Potion 記事をguide型で再改善（1回実行用）"""
import requests, json, re, os, sys, time
sys.stdout.reconfigure(encoding="utf-8")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_APP_PASSWORD", "")

with open(os.path.join(PROJECT_ROOT, ".shopify_token.json"), "r") as f:
    st = json.load(f)["access_token"]

r = requests.get(
    "https://hd-toys-store-japan.myshopify.com/admin/api/2026-04/products.json?status=active&limit=250&fields=title,handle,images,product_type",
    headers={"X-Shopify-Access-Token": st}, timeout=30,
)
images = []
for p in r.json().get("products", []):
    if "final fantasy" in p.get("title", "").lower():
        for img in p.get("images", [])[:6]:
            images.append(img["src"])
        break
print("Images: %d" % len(images))

# guide型プロンプトで再生成
prompt = (
    "IMPORTANT: Write in ENGLISH only. 2000+ words. This is a COLLECTOR'S GUIDE, not just a product review.\n\n"
    "Title: Final Fantasy VII Potion Replica: Collector's Guide to the 10th Anniversary Limited Edition\n\n"
    "This article must be a comprehensive GUIDE for collectors, not just a product description.\n\n"

    "<p>[Hook: The 10th anniversary of FF7 was a cultural event. Square Enix released a real drinkable Potion "
    "in a replica bottle. What started as a novelty item is now a highly sought-after collector's piece. 4-5 vivid sentences.]</p>\n\n"
    "INSERT_IMAGE_1\n\n"

    "<h2>What Is the FF7 10th Anniversary Potion?</h2>\n"
    "<p>[Detailed: 100ml replica potion bottle released 2007. Sold at convenience stores in Japan. "
    "Two versions existed. Designed by Square Enix. Actual drinkable energy drink. 200+ words.]</p>\n\n"

    "<h3>Product Specifications</h3>\n"
    "<ul><li>Release: 2007</li><li>Manufacturer: Square Enix / Suntory</li>"
    "<li>Volume: 100ml</li><li>Contents: Energy drink (original) / empty (collectible)</li>"
    "<li>Packaging: Commemorative box with FF7 artwork</li></ul>\n\n"
    "INSERT_IMAGE_2\n\n"

    "<h2>Why Collectors Want This Item</h2>\n"
    "<p>[FF7 is the most influential JRPG ever. 10th anniversary items are increasingly rare. "
    "Unopened bottles command premium prices. Connection to FF7 nostalgia. 200+ words.]</p>\n\n"

    "<h3>Final Fantasy VII Cultural Impact</h3>\n"
    "<p>[FF7 changed gaming in 1997. Cloud, Sephiroth, Aerith became icons. "
    "The game sold 13 million copies. Remake revived interest in original merchandise. 150+ words.]</p>\n\n"
    "INSERT_IMAGE_3\n\n"

    "<h2>Collector's Buying Guide</h2>\n"
    "<p>[Practical guide: what to check when buying. 150+ words.]</p>\n\n"
    "<h3>Condition Checklist</h3>\n"
    "<ul><li>Bottle: Check for chips, cracks, label condition</li>"
    "<li>Cap: Original seal intact vs opened</li>"
    "<li>Box: Commemorative box significantly increases value</li>"
    "<li>Contents: Empty vs sealed (sealed = higher value but risk of leakage)</li>"
    "<li>Certificate: Some versions included authenticity cards</li></ul>\n\n"

    "<h3>Price Expectations</h3>\n"
    "<p>[Empty bottle: $30-80. With box: $80-200. Sealed: $200-500+. "
    "Complete set: $500+. Market trending up with FF7 Remake hype. 100+ words.]</p>\n\n"
    "INSERT_IMAGE_4\n\n"

    "<h2>Related FF7 Collectibles</h2>\n"
    "<p>[Other FF7 items: Advent Children figures, Play Arts Kai, music boxes, "
    "Crisis Core PSP, Dissidia limited consoles. Cross-collecting opportunities. 150+ words.]</p>\n\n"
    "INSERT_IMAGE_5\n\n"

    "<h2>Where to Find Authentic FF7 Collectibles</h2>\n"
    "<p>[Japan is the primary source. Japanese collectors preserve items carefully. "
    "Buying from specialist sellers ensures authenticity. HD Toys Store Japan inspects every item. "
    "100+ words. Informative, not salesy.]</p>\n\n"

    "<h2>Conclusion</h2>\n"
    "<p>[The FF7 Potion is more than a novelty. For collectors, it represents a piece of gaming history. "
    "With FF7 Remake keeping the franchise alive, original merchandise will only appreciate. 4-5 sentences.]</p>\n\n"
    "INSERT_IMAGE_6\n\n"

    "Rules: HTML only. NO h1. INSERT_IMAGE_1-6. 2000+ words. Every section substantial. Not salesy.\n"
    "MUST include: 'shipped from Japan', 'carefully inspected', 'pre-owned condition'."
)

url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=%s" % GEMINI_KEY
resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=180)
print("Gemini: %d" % resp.status_code)

if resp.status_code != 200:
    print("Error:", resp.text[:200])
    sys.exit(1)

html = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

# 画像挿入
for i in range(6):
    ph = "INSERT_IMAGE_%d" % (i + 1)
    if ph in html and i < len(images):
        img = (
            '<figure style="margin:20px 0;text-align:center;">'
            '<img src="%s" alt="Final Fantasy VII collectible" style="max-width:100%%;height:auto;border-radius:6px;" />'
            '<figcaption style="font-size:12px;color:#888;margin-top:6px;">Source: HD Toys Store Japan</figcaption>'
            "</figure>" % images[i]
        )
        html = html.replace(ph, img)
    elif ph in html:
        html = html.replace(ph, "")

# ミニCTA（中盤）
shopify_link = "https://hd-toys-store-japan.myshopify.com/products/final-fantasy-vii-10th-anniversary-limited-potion-replica-bottle100ml-collection?utm_source=hd-bodyscience&utm_medium=article&utm_campaign=ff7-guide"
mini_cta = (
    '<p style="margin:20px 0;padding:12px 16px;background:#f0f7f0;border-left:4px solid #4CAF50;border-radius:4px;font-size:14px;">'
    'Interested in this item? '
    '<a href="%s" target="_blank" rel="noopener noreferrer" style="color:#4CAF50;font-weight:bold;">'
    'View it on HD Toys Store Japan</a> — carefully inspected, shipped from Japan.</p>'
) % shopify_link

h2s = [m.start() for m in re.finditer(r"<h2", html)]
if len(h2s) >= 3:
    html = html[:h2s[2]] + mini_cta + html[h2s[2]:]

# メインCTA
html += (
    '<div style="margin:30px 0;padding:24px 20px;background:#f8f9fa;border:1px solid #e0e0e0;border-radius:10px;">'
    '<h3 style="font-size:17px;font-weight:bold;margin:0 0 12px 0;color:#333;">Where to Buy</h3>'
    '<p style="font-size:13px;color:#555;margin:0 0 12px 0;">Every item is carefully inspected and shipped directly from Japan. Pre-owned condition is documented with detailed photos.</p>'
    '<div style="display:flex;gap:10px;flex-wrap:wrap;">'
    '<a href="%s" target="_blank" rel="noopener noreferrer" '
    'style="display:inline-block;padding:10px 22px;background:#4CAF50;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold;font-size:14px;">'
    'View on HD Toys Store Japan</a>'
    '<a href="https://www.ebay.com/str/hdtoysstore?utm_source=hd-bodyscience&utm_medium=article&utm_campaign=ff7-guide" '
    'target="_blank" rel="noopener noreferrer" '
    'style="display:inline-block;padding:10px 22px;background:#0064D2;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold;font-size:14px;">'
    'Browse on eBay</a></div>'
    '<p style="font-size:12px;color:#888;margin:10px 0 0 0;">Shipped from Japan with tracking. Authentic items only.</p></div>'
) % shopify_link

# 内部リンク
if "hd-bodyscience.com" not in html.lower():
    html += '<p>Read more collector guides on <a href="https://hd-bodyscience.com/">our blog</a>.</p>'

# 品質チェック
text = re.sub(r"<[^>]+>", "", html)
wc = len(text.split())
ic = len(re.findall(r"<img", html))
h2c = len(re.findall(r"<h2", html))
print("Quality: %dw, %dimg, %dH2" % (wc, ic, h2c))

if wc < 800 or h2c < 3:
    print("QUALITY FAILED")
    sys.exit(1)

# WordPress 更新（既存記事4895を上書き）
r = requests.post(
    "https://hd-bodyscience.com/wp-json/wp/v2/posts/4895",
    auth=(WP_USER, WP_PASS),
    json={"content": html, "title": "Final Fantasy VII Potion Replica: Collector's Guide to the 10th Anniversary Limited Edition"},
    timeout=30,
)
if r.status_code == 200:
    print("UPDATED: ID 4895 (%dw, %dimg, %dH2)" % (wc, ic, h2c))
else:
    print("Failed: %d" % r.status_code)
