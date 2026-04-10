# ============================================================
# YouTube Shorts 自動投稿スクリプト
#
# 【役割】
#   Veo 2.0 で生成した動画を YouTube Shorts としてアップロードする
#
# 【実行タイミング】
#   毎日 JST 08:00（画像投稿の12時間後、動画投稿の6時間後）
#
# 【安全ルール】
#   - 1日1本のみ
#   - 60秒以下の縦動画（9:16）= Shorts として認識
# ============================================================

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "")
SHOPIFY_URL = "https://%s.myshopify.com" % SHOPIFY_STORE
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")

SHOPIFY_TOKEN_FILE = os.path.join(PROJECT_ROOT, ".shopify_token.json")
YT_TOKEN_FILE = os.path.join(PROJECT_ROOT, ".youtube_token.json")
POSTED_FILE = os.path.join(PROJECT_ROOT, "ops", "monitoring", "sns_posted.json")

CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

VIDEO_PROMPTS = {
    "Action Figures": "Product showcase: A Japanese action figure toy rotating slowly on white background. Studio lighting. Camera orbits 180 degrees. No people. No text. 5 seconds.",
    "Scale Figures": "Product showcase: A beautiful Japanese anime scale figure rotating on white display stand. Warm studio lighting. Camera slowly orbits. No people. No text. 5 seconds.",
    "Trading Cards": "Product showcase: A rare Japanese trading card being tilted to show holographic shine. White background. Close-up cinematic shot. No people. No text. 5 seconds.",
    "Video Games": "Product showcase: A Japanese retro game console on white surface. Studio lighting. Camera moves left to right. No people. No text. 5 seconds.",
    "Electronic Toys": "Product showcase: A colorful Japanese electronic toy on white background. LED screen glowing. Camera zooms in and orbits. No people. No text. 5 seconds.",
    "Media & Books": "Product showcase: A Japanese art book pages turning slowly. White background. Studio lighting. No people. No text. 5 seconds.",
    "default": "Product showcase: A Japanese collectible item rotating on white pedestal. Studio lighting. Camera orbits. No people. No text. 5 seconds.",
}


def load_shopify_token():
    with open(SHOPIFY_TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("access_token", "")


def load_yt_token():
    if not os.path.exists(YT_TOKEN_FILE):
        return None
    with open(YT_TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_yt_token(data):
    with open(YT_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def refresh_yt_token(token_data):
    """YouTube トークンをリフレッシュする"""
    refresh_token = token_data.get("refresh_token", "")
    if not refresh_token or not CLIENT_ID or not CLIENT_SECRET:
        return None
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    if resp.status_code == 200:
        new_data = resp.json()
        token_data["access_token"] = new_data["access_token"]
        save_yt_token(token_data)
        return token_data
    return None


def load_posted():
    if not os.path.exists(POSTED_FILE):
        return {"posted": [], "history": []}
    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"posted": [], "history": []}


def save_posted(data):
    os.makedirs(os.path.dirname(POSTED_FILE), exist_ok=True)
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_video(prompt):
    """Veo 2.0 で動画生成"""
    model = "models/veo-2.0-generate-001"
    url = "https://generativelanguage.googleapis.com/v1beta/%s:predictLongRunning?key=%s" % (model, GEMINI_KEY)

    resp = requests.post(url, json={
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": "9:16", "durationSeconds": 5},
    }, timeout=30)

    if resp.status_code != 200:
        print("[ERROR] Veo API: %s" % resp.text[:200])
        return None

    op_name = resp.json().get("name", "")
    poll_url = "https://generativelanguage.googleapis.com/v1beta/%s?key=%s" % (op_name, GEMINI_KEY)

    for i in range(30):
        time.sleep(10)
        poll = requests.get(poll_url, timeout=15).json()
        if poll.get("done"):
            gen = poll.get("response", {}).get("generateVideoResponse", {})
            if gen.get("raiMediaFilteredCount", 0) > 0:
                print("[WARNING] Filtered: %s" % gen.get("raiMediaFilteredReasons", []))
                return None
            samples = gen.get("generatedSamples", [])
            if samples:
                uri = samples[0].get("video", {}).get("uri", "")
                if uri:
                    dl = requests.get(uri + ("&" if "?" in uri else "?") + "key=" + GEMINI_KEY, timeout=120)
                    if dl.status_code == 200:
                        return dl.content
            return None

    return None


def upload_to_youtube(access_token, video_bytes, title, description, tags):
    """YouTube に Shorts としてアップロード"""
    # Step 1: Resumable upload を開始
    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    init_resp = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": "Bearer %s" % access_token,
            "Content-Type": "application/json",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(len(video_bytes)),
        },
        json=metadata,
        timeout=30,
    )

    if init_resp.status_code != 200:
        print("[ERROR] Upload init: %d %s" % (init_resp.status_code, init_resp.text[:200]))
        return None

    upload_url = init_resp.headers.get("Location", "")
    if not upload_url:
        print("[ERROR] No upload URL")
        return None

    # Step 2: 動画をアップロード
    upload_resp = requests.put(
        upload_url,
        headers={"Content-Type": "video/mp4"},
        data=video_bytes,
        timeout=120,
    )

    if upload_resp.status_code == 200:
        video_id = upload_resp.json().get("id", "")
        print("[OK] YouTube Shorts uploaded! ID: %s" % video_id)
        print("  URL: https://youtube.com/shorts/%s" % video_id)
        return {"video_id": video_id, "url": "https://youtube.com/shorts/%s" % video_id}

    print("[ERROR] Upload: %d %s" % (upload_resp.status_code, upload_resp.text[:200]))
    return None


def main():
    print("=" * 60)
    print("  YouTube Shorts Auto Post")
    print("  %s" % NOW.strftime("%Y-%m-%d %H:%M JST"))
    print("=" * 60)
    print()

    if not GEMINI_KEY:
        print("[ERROR] GEMINI_API_KEY not set")
        sys.exit(1)

    # YouTube トークン
    yt_token = load_yt_token()
    if not yt_token:
        print("[ERROR] YouTube token not found. Run youtube_auth.py first.")
        sys.exit(1)

    access_token = yt_token.get("access_token", "")

    # トークンの有効性確認、必要ならリフレッシュ
    test_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet", "mine": "true", "access_token": access_token},
        timeout=15,
    )
    if test_resp.status_code == 401:
        print("[INFO] Token expired, refreshing...")
        yt_token = refresh_yt_token(yt_token)
        if not yt_token:
            print("[ERROR] Token refresh failed. Run youtube_auth.py again.")
            sys.exit(1)
        access_token = yt_token["access_token"]

    # 投稿済みチェック
    posted_data = load_posted()
    today_str = NOW.strftime("%Y-%m-%d")
    today_yt = [h for h in posted_data.get("history", []) if h.get("date") == today_str and h.get("platform") == "youtube_shorts"]
    if today_yt:
        print("[SKIP] Already posted YouTube Shorts today")
        return

    # Shopify から商品選定（YouTube 未投稿のもの）
    shopify_token = load_shopify_token()
    resp = requests.get(
        "%s/admin/api/2026-04/products.json?status=active&limit=50&fields=title,handle,product_type,images" % SHOPIFY_URL,
        headers={"X-Shopify-Access-Token": shopify_token},
        timeout=30,
    )
    products = resp.json().get("products", [])

    yt_posted = set(h.get("handle", "") for h in posted_data.get("history", []) if h.get("platform") == "youtube_shorts")
    candidates = [p for p in products if p.get("handle", "") not in yt_posted and p.get("images")]

    if not candidates:
        print("[SKIP] No unposted products for YouTube")
        return

    product = candidates[0]
    title = product["title"]
    handle = product["handle"]
    category = product.get("product_type", "")

    print("[INFO] Selected: %s (%s)" % (title[:50], category))
    print()

    # 動画生成
    prompt = VIDEO_PROMPTS.get(category, VIDEO_PROMPTS["default"])
    print("[INFO] Generating video...")
    video_bytes = generate_video(prompt)

    if not video_bytes:
        print("[ERROR] Video generation failed")
        return

    print("[OK] Video generated (%d KB)" % (len(video_bytes) // 1024))

    # YouTube にアップロード
    shopify_link = "%s/products/%s?utm_source=youtube&utm_medium=shorts&utm_campaign=daily-post&utm_content=%s" % (SHOPIFY_URL, handle, handle)

    yt_title = "%s | Japanese Collectibles #Shorts" % title[:70]
    yt_description = (
        "%s\n\n"
        "Pre-owned, inspected & shipped directly from Japan.\n\n"
        "Shop: %s\n\n"
        "#japanesecollectibles #japantoys #hdtoysjapan #shorts"
    ) % (title, shopify_link)
    yt_tags = ["japanese collectibles", "japan toys", "anime figures", category.lower(), "shorts", "hdtoysjapan"]

    print("[INFO] Uploading to YouTube Shorts...")
    result = upload_to_youtube(access_token, video_bytes, yt_title, yt_description, yt_tags)

    if result:
        posted_data.setdefault("history", []).append({
            "date": today_str,
            "handle": handle,
            "title": title[:80],
            "category": category,
            "platform": "youtube_shorts",
            "video_id": result.get("video_id", ""),
            "url": result.get("url", ""),
            "media_type": "video",
            "has_product_link": True,
            "product_url": shopify_link,
            "posted_at": NOW.strftime("%Y-%m-%d %H:%M"),
            "engagement": {"views": 0, "likes": 0, "comments": 0, "shares": 0, "shopify_visits": 0},
        })
        save_posted(posted_data)
        print()
        print("[OK] YouTube Shorts post completed!")


if __name__ == "__main__":
    main()
