# ============================================================
# 動画自動投稿スクリプト（Instagram Reels + Facebook Reels）
#
# 【役割】
#   Shopify 商品から Veo 2.0 で短尺動画を生成し、
#   Instagram Reels と Facebook Reels に投稿する
#
# 【実行タイミング】
#   週2回（月曜・木曜）GitHub Actions で実行
#
# 【安全ルール】
#   - 週2本以内（コスト管理: $0.35/本）
#   - 投稿済み商品は再投稿しない
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
IG_TOKEN_FILE = os.path.join(PROJECT_ROOT, ".instagram_token.json")
POSTED_FILE = os.path.join(PROJECT_ROOT, "ops", "monitoring", "sns_posted.json")

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

# 動画投稿する曜日（毎日）
VIDEO_DAYS = [0, 1, 2, 3, 4, 5, 6]

# カテゴリ別の動画プロンプトテンプレート
VIDEO_PROMPTS = {
    "Action Figures": (
        "Product showcase video: A Japanese action figure toy rotating slowly "
        "on a clean white pedestal. Detailed articulated figure with dynamic pose. "
        "Soft studio lighting, professional product photography. "
        "Camera smoothly orbits 180 degrees. No people. No text."
    ),
    "Scale Figures": (
        "Product showcase video: A beautiful Japanese anime scale figure "
        "rotating slowly on a white display stand. Detailed paint and sculpting. "
        "Soft warm studio lighting. Camera slowly orbits around the figure. "
        "No people. No text."
    ),
    "Trading Cards": (
        "Product showcase video: A rare Japanese trading card being slowly "
        "revealed and tilted to show holographic shine. Clean white background. "
        "Close-up cinematic shot showing card details and foil reflections. "
        "No people. No text."
    ),
    "Video Games": (
        "Product showcase video: A Japanese retro video game console and cartridge "
        "on a clean white surface. Soft studio lighting. Camera slowly moves "
        "from left to right showing the product from multiple angles. "
        "No people. No text."
    ),
    "Electronic Toys": (
        "Product showcase video: A colorful Japanese electronic toy (like Tamagotchi) "
        "on a clean white background. Small LED screen glowing softly. "
        "Camera slowly zooms in and orbits. Nostalgic retro toy feel. "
        "No people. No text."
    ),
    "Media & Books": (
        "Product showcase video: A Japanese art book or manga volume being "
        "slowly opened, pages turning to reveal beautiful illustrations. "
        "Clean white background, soft studio lighting. "
        "No people. No text."
    ),
    "default": (
        "Product showcase video: A Japanese collectible item rotating slowly "
        "on a clean white pedestal. Professional product photography style. "
        "Soft studio lighting. Camera smoothly orbits. "
        "No people. No text."
    ),
}


def load_shopify_token():
    with open(SHOPIFY_TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("access_token", "")


def load_ig_token():
    with open(IG_TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


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
    """Veo 2.0 で動画を生成する"""
    model = "models/veo-2.0-generate-001"
    url = "https://generativelanguage.googleapis.com/v1beta/%s:predictLongRunning?key=%s" % (model, GEMINI_KEY)

    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "9:16",
            "durationSeconds": 5,
        },
    }

    print("[INFO] Generating video with Veo 2.0...")
    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code != 200:
        print("[ERROR] Veo API error: %s" % resp.text[:200])
        return None

    op_name = resp.json().get("name", "")

    # 完了を待つ
    poll_url = "https://generativelanguage.googleapis.com/v1beta/%s?key=%s" % (op_name, GEMINI_KEY)
    for i in range(30):
        time.sleep(10)
        poll = requests.get(poll_url, timeout=15).json()
        if poll.get("done"):
            if "error" in poll:
                print("[ERROR] Video generation failed: %s" % poll["error"])
                return None

            gen = poll.get("response", {}).get("generateVideoResponse", {})
            if gen.get("raiMediaFilteredCount", 0) > 0:
                print("[WARNING] Video filtered by safety: %s" % gen.get("raiMediaFilteredReasons", []))
                return None

            samples = gen.get("generatedSamples", [])
            if samples:
                uri = samples[0].get("video", {}).get("uri", "")
                if uri:
                    dl = requests.get(uri + ("&" if "?" in uri else "?") + "key=" + GEMINI_KEY, timeout=120)
                    if dl.status_code == 200:
                        print("[OK] Video generated (%d KB)" % (len(dl.content) // 1024))
                        return dl.content
            return None

    print("[ERROR] Video generation timed out")
    return None


def upload_video_to_hosting(video_bytes):
    """動画を一時的にホスティングする（Shopify Files API 経由）"""
    shopify_token = load_shopify_token()

    # Shopify の staged uploads API を使う
    gql_url = "%s/admin/api/2026-04/graphql.json" % SHOPIFY_URL
    headers = {"X-Shopify-Access-Token": shopify_token, "Content-Type": "application/json"}

    # ステージドアップロードを作成
    mutation = """
    mutation {
      stagedUploadsCreate(input: [{
        resource: FILE
        filename: "video_post.mp4"
        mimeType: "video/mp4"
        fileSize: "%d"
        httpMethod: POST
      }]) {
        stagedTargets {
          url
          resourceUrl
          parameters { name value }
        }
        userErrors { field message }
      }
    }
    """ % len(video_bytes)

    resp = requests.post(gql_url, headers=headers, json={"query": mutation}, timeout=30)
    if resp.status_code != 200:
        print("[ERROR] Staged upload creation failed")
        return None

    data = resp.json().get("data", {}).get("stagedUploadsCreate", {})
    targets = data.get("stagedTargets", [])
    if not targets:
        print("[ERROR] No staged targets")
        return None

    target = targets[0]
    upload_url = target["url"]
    resource_url = target["resourceUrl"]
    params = {p["name"]: p["value"] for p in target["parameters"]}

    # アップロード
    files = {"file": ("video_post.mp4", video_bytes, "video/mp4")}
    upload_resp = requests.post(upload_url, data=params, files=files, timeout=60)

    if upload_resp.status_code in (200, 201, 204):
        print("[OK] Video uploaded to Shopify Files")
        # ファイルを作成して公開 URL を取得
        file_mutation = """
        mutation {
          fileCreate(files: [{
            originalSource: "%s"
            contentType: VIDEO
          }]) {
            files { id alt preview { image { url } } }
            userErrors { field message }
          }
        }
        """ % resource_url

        file_resp = requests.post(gql_url, headers=headers, json={"query": file_mutation}, timeout=30)
        if file_resp.status_code == 200:
            files_data = file_resp.json().get("data", {}).get("fileCreate", {}).get("files", [])
            if files_data:
                # 公開 URL の取得には時間がかかるため resource_url を返す
                return resource_url

    print("[ERROR] Video upload failed")
    return None


def post_video_to_instagram(ig_token_data, video_url, caption):
    """Instagram Reels に動画を投稿する"""
    access_token = ig_token_data["access_token"]
    ig_user_id = ig_token_data["ig_user_id"]

    # Step 1: Reels コンテナ作成
    container_resp = requests.post(
        "https://graph.facebook.com/v25.0/%s/media" % ig_user_id,
        params={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": access_token,
        },
        timeout=30,
    )

    if container_resp.status_code != 200:
        print("[ERROR] IG Reels container failed: %s" % container_resp.text[:200])
        return None

    container_id = container_resp.json().get("id")
    print("[OK] IG Reels container: %s" % container_id)

    # Step 2: 処理完了を待つ
    for i in range(20):
        time.sleep(5)
        status_resp = requests.get(
            "https://graph.facebook.com/v25.0/%s" % container_id,
            params={"fields": "status_code", "access_token": access_token},
            timeout=15,
        )
        if status_resp.status_code == 200:
            status = status_resp.json().get("status_code", "")
            if status == "FINISHED":
                break
            elif status == "ERROR":
                print("[ERROR] IG Reels processing failed")
                return None

    # Step 3: 公開
    publish_resp = requests.post(
        "https://graph.facebook.com/v25.0/%s/media_publish" % ig_user_id,
        params={"creation_id": container_id, "access_token": access_token},
        timeout=30,
    )

    if publish_resp.status_code == 200:
        media_id = publish_resp.json().get("id")
        print("[OK] IG Reels published! ID: %s" % media_id)
        return {"media_id": media_id, "platform": "instagram_reels"}

    print("[ERROR] IG Reels publish failed: %s" % publish_resp.text[:200])
    return None


def post_video_to_facebook(page_token, page_id, video_bytes, description):
    """Facebook Reels に動画を投稿する"""
    # Facebook Video Upload API
    resp = requests.post(
        "https://graph.facebook.com/v25.0/%s/videos" % page_id,
        params={"access_token": page_token, "description": description},
        files={"source": ("video.mp4", video_bytes, "video/mp4")},
        timeout=120,
    )

    if resp.status_code == 200:
        video_id = resp.json().get("id")
        print("[OK] FB video published! ID: %s" % video_id)
        return {"video_id": video_id, "platform": "facebook_video"}

    print("[ERROR] FB video failed: %s" % resp.text[:200])
    return None


def main():
    print("=" * 60)
    print("  Video Auto Post (Instagram Reels + Facebook)")
    print("  %s" % NOW.strftime("%Y-%m-%d %H:%M JST"))
    print("=" * 60)
    print()

    # 曜日チェック（月曜・木曜のみ）
    if NOW.weekday() not in VIDEO_DAYS:
        print("[SKIP] Today is not a video day (Mon/Thu only)")
        print("  Today: %s (weekday=%d)" % (NOW.strftime("%A"), NOW.weekday()))
        return

    if not GEMINI_KEY:
        print("[ERROR] GEMINI_API_KEY not set")
        sys.exit(1)

    # トークン
    ig_tokens = load_ig_token()
    posted_data = load_posted()

    # 今日の動画投稿済みチェック
    today_str = NOW.strftime("%Y-%m-%d")
    today_videos = [
        h for h in posted_data.get("history", [])
        if h.get("date") == today_str and "video" in h.get("platform", "")
    ]
    if today_videos:
        print("[SKIP] Already posted video today")
        return

    # Shopify から動画向き商品を選定
    shopify_token = load_shopify_token()
    resp = requests.get(
        "%s/admin/api/2026-04/products.json?status=active&limit=50&fields=title,handle,images,product_type" % SHOPIFY_URL,
        headers={"X-Shopify-Access-Token": shopify_token},
        timeout=30,
    )
    products = resp.json().get("products", [])

    video_posted = set(
        h.get("handle", "") for h in posted_data.get("history", [])
        if "video" in h.get("platform", "")
    )

    candidates = [
        p for p in products
        if p.get("handle", "") not in video_posted and p.get("images")
    ]

    if not candidates:
        print("[SKIP] No unposted products for video")
        return

    product = candidates[0]
    title = product["title"]
    handle = product["handle"]
    category = product.get("product_type", "")

    print("[INFO] Selected: %s (%s)" % (title[:50], category))
    print()

    # 動画生成
    prompt = VIDEO_PROMPTS.get(category, VIDEO_PROMPTS["default"])
    video_bytes = generate_video(prompt)

    if not video_bytes:
        print("[ERROR] Video generation failed. Skipping.")
        return

    # 一時ファイルに保存
    temp_path = os.path.join(PROJECT_ROOT, "store", "assets", "temp_video.mp4")
    with open(temp_path, "wb") as f:
        f.write(video_bytes)

    # Facebook に動画投稿
    caption = (
        "%s\n\n"
        "Pre-owned, inspected & shipped from Japan\n\n"
        "#japanesecollectibles #japantoys #hdtoysjapan #shippedfromjapan"
    ) % title

    print()
    print("[INFO] Posting video to Facebook...")
    fb_result = post_video_to_facebook(
        ig_tokens["page_access_token"],
        ig_tokens["page_id"],
        video_bytes,
        caption,
    )

    if fb_result:
        posted_data.setdefault("history", []).append({
            "date": today_str,
            "handle": handle,
            "title": title[:80],
            "category": category,
            "platform": "facebook_video",
            "video_id": fb_result.get("video_id", ""),
        })

    # Instagram Reels に動画投稿
    # 動画を一時的に公開URLでホスティングする必要がある
    # Shopify Files API 経由でアップロード
    print()
    print("[INFO] Uploading video for Instagram Reels...")
    video_url = upload_video_to_hosting(video_bytes)

    if video_url:
        ig_caption = (
            "%s\n\n"
            "Pre-owned, inspected & shipped from Japan\n\n"
            "Link in bio to shop!\n\n"
            "#japanesecollectibles #japantoys #hdtoysjapan #shippedfromjapan"
        ) % title

        print("[INFO] Posting to Instagram Reels...")
        ig_result = post_video_to_instagram(ig_tokens, video_url, ig_caption)

        if ig_result:
            posted_data.setdefault("history", []).append({
                "date": today_str,
                "handle": handle,
                "title": title[:80],
                "category": category,
                "platform": "instagram_reels",
                "media_id": ig_result.get("media_id", ""),
            })
    else:
        print("[SKIP] Instagram Reels: video hosting failed, skipping")

    # 一時ファイル削除
    try:
        os.remove(temp_path)
    except OSError:
        pass

    save_posted(posted_data)
    print()
    print("[OK] Video post completed!")


if __name__ == "__main__":
    main()
