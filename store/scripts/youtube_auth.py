# ============================================================
# YouTube OAuth 認証スクリプト
#
# 【役割】
#   YouTube Data API v3 のアクセストークンを OAuth フローで取得する
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python store/scripts/youtube_auth.py
# ============================================================

import http.server
import json
import os
import sys
import threading
import time
import urllib.parse
import webbrowser

import requests
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# GCP の OAuth クライアント ID を使う
# YouTube API は サービスアカウントでは動画アップロードできないため OAuth が必要
CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
TOKEN_FILE = os.path.join(PROJECT_ROOT, ".youtube_token.json")

REDIRECT_URI = "http://localhost:8765/callback"
PORT = 8765

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube"

auth_code = None
server_should_stop = False


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code, server_should_stop
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/callback" and "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>OK</h1><p>YouTube authorization successful. You can close this tab.</p></body></html>")
            server_should_stop = True
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def main():
    global auth_code, server_should_stop

    print()
    print("=" * 60)
    print("  YouTube OAuth 認証")
    print("=" * 60)
    print()

    if not CLIENT_ID or not CLIENT_SECRET:
        print("[INFO] YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET が未設定です")
        print()
        print("GCP コンソールで OAuth クライアント ID を作成してください:")
        print("  1. https://console.cloud.google.com/ -> hd-toys-analytics プロジェクト")
        print("  2. API とサービス -> 認証情報 -> + 認証情報を作成 -> OAuth クライアント ID")
        print("  3. アプリケーションの種類: デスクトップアプリ")
        print("  4. 名前: HD Toys YouTube")
        print("  5. 作成後、クライアント ID とクライアントシークレットを .env に追加:")
        print("     YOUTUBE_CLIENT_ID=xxxxx")
        print("     YOUTUBE_CLIENT_SECRET=xxxxx")
        print()
        print("  また、OAuth 同意画面の設定も必要です:")
        print("  1. API とサービス -> OAuth 同意画面")
        print("  2. User Type: 外部")
        print("  3. アプリ名: HD Toys Auto Post")
        print("  4. スコープ: youtube.upload を追加")
        print("  5. テストユーザー: 自分の Gmail アドレスを追加")
        sys.exit(1)

    # 既存トークンの確認
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            token_data = json.load(f)
        access_token = token_data.get("access_token", "")
        refresh_token = token_data.get("refresh_token", "")

        # トークンの有効性を確認
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet", "mine": "true", "access_token": access_token},
            timeout=15,
        )
        if resp.status_code == 200:
            channels = resp.json().get("items", [])
            if channels:
                print("[OK] トークンは有効です")
                print("  チャンネル: %s" % channels[0]["snippet"]["title"])
                return

        # リフレッシュトークンで更新を試みる
        if refresh_token:
            print("[INFO] トークンを更新しています...")
            refresh_resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=15,
            )
            if refresh_resp.status_code == 200:
                new_data = refresh_resp.json()
                token_data["access_token"] = new_data["access_token"]
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    json.dump(token_data, f, indent=2)
                print("[OK] トークンを更新しました")
                return

    # OAuth フロー
    print("[INFO] ブラウザで認証を行います...")

    server = http.server.HTTPServer(("localhost", PORT), OAuthCallbackHandler)

    def serve():
        while not server_should_stop:
            server.handle_request()

    thread = threading.Thread(target=serve)
    thread.daemon = True
    thread.start()

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        "?client_id=%s"
        "&redirect_uri=%s"
        "&response_type=code"
        "&scope=%s"
        "&access_type=offline"
        "&prompt=consent"
    ) % (CLIENT_ID, urllib.parse.quote(REDIRECT_URI), urllib.parse.quote(SCOPES))

    print("  ブラウザで承認してください...")
    webbrowser.open(auth_url)

    timeout = 120
    start = time.time()
    while auth_code is None and (time.time() - start) < timeout:
        time.sleep(0.5)

    server.server_close()

    if auth_code is None:
        print("[エラー] タイムアウトしました")
        sys.exit(1)

    print("[OK] 認証コード取得")

    # トークン交換
    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": auth_code,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )

    if token_resp.status_code != 200:
        print("[エラー] トークン取得失敗: %s" % token_resp.text[:200])
        sys.exit(1)

    token_data = token_resp.json()
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)

    print("[OK] YouTube トークン保存: %s" % TOKEN_FILE)

    # チャンネル確認
    ch_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet", "mine": "true", "access_token": token_data["access_token"]},
        timeout=15,
    )
    if ch_resp.status_code == 200:
        channels = ch_resp.json().get("items", [])
        if channels:
            print("  チャンネル: %s" % channels[0]["snippet"]["title"])


if __name__ == "__main__":
    main()
