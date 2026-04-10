"""Plush & Soft Toys 記事作成スクリプト（1回実行用）"""
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
    "https://hd-toys-store-japan.myshopify.com/admin/api/2026-04/products.json?status=active&limit=50&fields=title,images,product_type",
    headers={"X-Shopify-Access-Token": st}, timeout=30,
)
plush_imgs = []
for p in r.json().get("products", []):
    if p.get("product_type") == "Plush & Soft Toys":
        for img in p.get("images", [])[:2]:
            plush_imgs.append(img["src"])
print("Plush images: %d" % len(plush_imgs))

prompt = (
    "IMPORTANT: Write in ENGLISH only. 1500+ words, 6+ H2, deep collector content.\n\n"
    "Title: Japanese Plush Toys Collector Guide: Pokemon, Rilakkuma, Sanrio & More\n\n"
    "<p>[Hook: Japanese plush toys are known worldwide for exceptional quality and adorable designs. "
    "From Pokemon Center exclusives to San-X Rilakkuma, Japanese plush represents the pinnacle of kawaii culture. 4-5 sentences.]</p>\n\n"
    "INSERT_IMAGE_1\n\n"
    "<h2>Why Japanese Plush Toys Are Special</h2>\n"
    "<p>[Quality: softer materials, better stitching, detailed embroidery. Japan-exclusive designs. 150+ words.]</p>\n\n"
    "<h3>Key Japanese Plush Brands</h3>\n"
    "<p>[Pokemon Center, San-X, Sanrio, Bandai, Takara Tomy. 100+ words.]</p>\n\n"
    "INSERT_IMAGE_2\n\n"
    "<h2>Most Collectible Japanese Plush Categories</h2>\n\n"
    "<h3>Pokemon Center Exclusives</h3>\n"
    "<p>[Life-size plush, seasonal editions, region-exclusive Pokemon. 120+ words.]</p>\n\n"
    "<h3>Rilakkuma and San-X Characters</h3>\n"
    "<p>[BIG cushion plush, collaboration editions. 100+ words.]</p>\n\n"
    "INSERT_IMAGE_3\n\n"
    "<h3>Sanrio Characters</h3>\n"
    "<p>[My Melody, Cinnamoroll, Kuromi limited editions. 100+ words.]</p>\n\n"
    "<h3>Sylvanian Families / Calico Critters</h3>\n"
    "<p>[Japan-exclusive sets, dollhouse bundles, parade series. 100+ words.]</p>\n\n"
    "INSERT_IMAGE_4\n\n"
    "<h2>Condition Guide for Pre-Owned Plush</h2>\n"
    "<ul>\n"
    "<li><strong>Fabric:</strong> Check for pilling, stains, fading</li>\n"
    "<li><strong>Stuffing:</strong> Evenly distributed, not lumpy</li>\n"
    "<li><strong>Tags:</strong> Original tags increase value significantly</li>\n"
    "<li><strong>Odor:</strong> Japanese sellers store in smoke-free environments</li>\n"
    "<li><strong>Embroidery:</strong> Check face details for loose threads</li>\n"
    "</ul>\n\n"
    "INSERT_IMAGE_5\n\n"
    "<h2>Price Guide and Value Trends</h2>\n"
    "<p>[Common $10-30, medium $30-80, rare $100-500+. Pokemon Center life-size appreciating. 120+ words.]</p>\n\n"
    "<h2>Why Buy from Japan</h2>\n"
    "<p>[Better condition, exclusive editions, careful packaging. 100+ words. Informative, not salesy.]</p>\n\n"
    "INSERT_IMAGE_6\n\n"
    "<h2>Conclusion</h2>\n"
    "<p>[Japanese plush is the finest collectible soft toys. 4 sentences.]</p>\n\n"
    "Rules: HTML tags only. NO h1. INSERT_IMAGE_1-6 placeholders. Not salesy."
)

url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=%s" % GEMINI_KEY
resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=180)
print("Gemini: %d" % resp.status_code)

if resp.status_code != 200:
    print("Error:", resp.text[:200])
    sys.exit(1)

html = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

for i in range(6):
    ph = "INSERT_IMAGE_%d" % (i + 1)
    if ph in html and i < len(plush_imgs):
        img = (
            '<figure style="margin:20px 0;text-align:center;">'
            '<img src="%s" alt="Japanese plush toy" style="max-width:100%%;height:auto;border-radius:6px;" />'
            '<figcaption style="font-size:12px;color:#888;margin-top:6px;">Source: HD Toys Store Japan</figcaption>'
            "</figure>" % plush_imgs[i]
        )
        html = html.replace(ph, img)
    elif ph in html:
        html = html.replace(ph, "")

html += (
    '<div style="margin:30px 0;padding:24px 20px;background:#f8f9fa;border:1px solid #e0e0e0;border-radius:10px;">'
    '<h3 style="font-size:17px;font-weight:bold;margin:0 0 12px 0;color:#333;">Where to Buy</h3>'
    '<div style="display:flex;gap:10px;flex-wrap:wrap;">'
    '<a href="https://hd-toys-store-japan.myshopify.com/collections/plush-soft-toys'
    '?utm_source=hd-bodyscience&utm_medium=article&utm_campaign=plush-guide" '
    'target="_blank" rel="noopener noreferrer" '
    'style="display:inline-block;padding:10px 22px;background:#4CAF50;color:#fff;'
    'text-decoration:none;border-radius:6px;font-weight:bold;font-size:14px;">'
    "View Plush Collection</a>"
    '<a href="https://www.ebay.com/str/hdtoysstore'
    '?utm_source=hd-bodyscience&utm_medium=article&utm_campaign=plush-guide" '
    'target="_blank" rel="noopener noreferrer" '
    'style="display:inline-block;padding:10px 22px;background:#0064D2;color:#fff;'
    'text-decoration:none;border-radius:6px;font-weight:bold;font-size:14px;">'
    "Browse on eBay</a></div>"
    '<p style="font-size:12px;color:#888;margin:10px 0 0 0;">All items shipped from Japan.</p></div>'
)

text = re.sub(r"<[^>]+>", "", html)
wc = len(text.split())
ic = len(re.findall(r"<img", html))
h2c = len(re.findall(r"<h2", html))
print("Quality: %dw, %dimg, %dH2" % (wc, ic, h2c))

if wc < 800 or h2c < 3:
    print("QUALITY FAILED")
    sys.exit(1)

# アイキャッチ
feat_id = None
if plush_imgs:
    try:
        img_data = requests.get(plush_imgs[0], timeout=30).content
        up = requests.post(
            "https://hd-bodyscience.com/wp-json/wp/v2/media",
            auth=(WP_USER, WP_PASS),
            headers={"Content-Disposition": "attachment; filename=plush-guide.jpg", "Content-Type": "image/jpeg"},
            data=img_data, timeout=30,
        )
        if up.status_code == 201:
            feat_id = up.json()["id"]
    except Exception:
        pass

# カテゴリ
cat_id = None
try:
    cr = requests.get("https://hd-bodyscience.com/wp-json/wp/v2/categories?search=Plush&_fields=id",
                       auth=(WP_USER, WP_PASS), timeout=10)
    if cr.status_code == 200 and cr.json():
        cat_id = cr.json()[0]["id"]
except Exception:
    pass
if not cat_id:
    try:
        cr2 = requests.post("https://hd-bodyscience.com/wp-json/wp/v2/categories",
                            auth=(WP_USER, WP_PASS), json={"name": "Plush & Soft Toys"}, timeout=10)
        if cr2.status_code == 201:
            cat_id = cr2.json()["id"]
    except Exception:
        pass

# タグ
tag_ids = []
for name in ["Plush", "Pokemon", "Rilakkuma", "Sanrio", "Sylvanian Families", "Japan Import", "Pre-owned"]:
    try:
        tr = requests.get("https://hd-bodyscience.com/wp-json/wp/v2/tags?search=%s&_fields=id" % name,
                          auth=(WP_USER, WP_PASS), timeout=10)
        if tr.status_code == 200 and tr.json():
            tag_ids.append(tr.json()[0]["id"])
            continue
        tr2 = requests.post("https://hd-bodyscience.com/wp-json/wp/v2/tags",
                            auth=(WP_USER, WP_PASS), json={"name": name}, timeout=10)
        if tr2.status_code == 201:
            tag_ids.append(tr2.json()["id"])
    except Exception:
        pass

payload = {
    "title": "Japanese Plush Toys Collector Guide: Pokemon, Rilakkuma, Sanrio & More",
    "content": html,
    "status": "publish",
}
if cat_id:
    payload["categories"] = [cat_id]
if tag_ids:
    payload["tags"] = tag_ids
if feat_id:
    payload["featured_media"] = feat_id

r = requests.post("https://hd-bodyscience.com/wp-json/wp/v2/posts",
                   auth=(WP_USER, WP_PASS), json=payload, timeout=30)
if r.status_code == 201:
    print("PUBLISHED: ID %d" % r.json()["id"])
    print("URL: %s" % r.json()["link"])
else:
    print("Failed: %d %s" % (r.status_code, r.text[:200]))
