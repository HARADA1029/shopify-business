# ============================================================
# Pinterest OAuth 認証スクリプト
#
# 【役割】
#   Pinterest API のアクセストークンを OAuth 2.0 フローで取得する
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python store/scripts/pinterest_auth.py
#
# 【動作】
#   1. ローカルに HTTP サーバーを起動（port 8766）
#   2. ブラウザで Pinterest 認証ページを開く
#   3. 原田がブラウザで承認する
#   4. コールバックで認証コードを受け取る
#   5. 認証コードをアクセストークンに交換する
#   6. トークンを .pinterest_token.json に保存する
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

APP_ID = os.getenv("PINTEREST_APP_ID", "")
APP_SECRET = os.getenv("PINTEREST_APP_SECRET", "")
TOKEN_FILE = os.path.join(PROJECT_ROOT, ".pinterest_token.json")

REDIRECT_URI = "http://localhost:8766/callback"
PORT = 8766

# Pinterest API v5 スコープ
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"

# 認証コードを受け取るためのグローバル変数
auth_code = None
server_should_stop = False


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """OAuth コールバックを受け取る HTTP ハンドラ"""

    def do_GET(self):
        global auth_code, server_should_stop

        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/callback" and "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>OK</h1>"
                b"<p>Pinterest authorization successful. You can close this tab.</p>"
                b"</body></html>"
            )
            server_should_stop = True
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid request")

    def log_message(self, format, *args):
        pass


def exchange_code_for_token(code):
    """認証コードをアクセストークンに交換する"""
    resp = requests.post(
        "https://api.pinterest.com/v5/oauth/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=(APP_ID, APP_SECRET),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json()
    else:
        print("[エラー] トークン交換に失敗: HTTP %d" % resp.status_code)
        print("  レスポンス: %s" % resp.text[:300])
        return None


def refresh_token(refresh_tok):
    """リフレッシュトークンでアクセストークンを更新する"""
    resp = requests.post(
        "https://api.pinterest.com/v5/oauth/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=(APP_ID, APP_SECRET),
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
        },
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json()
    else:
        print("[エラー] トークンリフレッシュに失敗: HTTP %d" % resp.status_code)
        print("  レスポンス: %s" % resp.text[:300])
        return None


def save_token(token_data):
    """トークンをファイルに保存する"""
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2, ensure_ascii=False)
    print("[OK] トークン保存: %s" % TOKEN_FILE)


def load_token():
    """保存済みトークンを読み込む"""
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def test_token(access_token):
    """トークンが有効か確認する"""
    resp = requests.get(
        "https://api.pinterest.com/v5/user_account",
        headers={"Authorization": "Bearer %s" % access_token},
        timeout=15,
    )
    return resp.status_code == 200, resp


def main():
    global auth_code, server_should_stop

    print()
    print("=" * 60)
    print("  Pinterest OAuth 認証")
    print("=" * 60)
    print()

    if not APP_ID or not APP_SECRET:
        print("[エラー] .env に PINTEREST_APP_ID / PINTEREST_APP_SECRET を設定してください")
        sys.exit(1)

    # --- 既存トークンの確認 ---
    existing = load_token()
    if existing and "access_token" in existing:
        print("[INFO] 保存済みトークンが見つかりました。検証中...")
        ok, resp = test_token(existing["access_token"])
        if ok:
            user = resp.json()
            print("[OK] トークンは有効です。")
            print("  ユーザー名: %s" % user.get("username", "?"))
            return
        else:
            # リフレッシュ試行
            if existing.get("refresh_token"):
                print("[INFO] トークン期限切れ。リフレッシュ中...")
                new_data = refresh_token(existing["refresh_token"])
                if new_data:
                    # リフレッシュトークンを保持
                    if "refresh_token" not in new_data and existing.get("refresh_token"):
                        new_data["refresh_token"] = existing["refresh_token"]
                    save_token(new_data)
                    print("[OK] トークンをリフレッシュしました。")
                    return
            print("[INFO] トークンが無効です。再認証を行います。")

    # --- OAuth フロー ---
    print("[INFO] ローカルサーバーをポート %d で起動します..." % PORT)

    server = http.server.HTTPServer(("localhost", PORT), OAuthCallbackHandler)

    def serve_until_stop():
        while not server_should_stop:
            server.handle_request()

    server_thread = threading.Thread(target=serve_until_stop)
    server_thread.daemon = True
    server_thread.start()

    # 認証URL生成
    auth_url = (
        "https://www.pinterest.com/oauth/?"
        "client_id=%s"
        "&redirect_uri=%s"
        "&response_type=code"
        "&scope=%s"
    ) % (APP_ID, urllib.parse.quote(REDIRECT_URI), urllib.parse.quote(SCOPES))

    print()
    print("[INFO] ブラウザで Pinterest 認証ページを開きます...")
    print("  URL: %s..." % auth_url[:80])
    webbrowser.open(auth_url)

    print()
    print("  ブラウザで「Allow」を押して承認してください。")
    print("  承認後、自動的にトークンを取得します。")
    print()

    # コールバック待ち（最大120秒）
    for _ in range(120):
        if auth_code:
            break
        time.sleep(1)

    server.shutdown()

    if not auth_code:
        print("[エラー] タイムアウト: 認証コードを受け取れませんでした")
        sys.exit(1)

    print("[OK] 認証コードを受信しました")
    print()

    # トークン交換
    print("[INFO] アクセストークンを取得しています...")
    token_data = exchange_code_for_token(auth_code)

    if not token_data or "access_token" not in token_data:
        print("[エラー] トークン取得に失敗しました")
        sys.exit(1)

    save_token(token_data)

    # 確認
    ok, resp = test_token(token_data["access_token"])
    if ok:
        user = resp.json()
        print("[OK] 認証成功！")
        print("  ユーザー名: %s" % user.get("username", "?"))
        print("  アカウント: %s" % user.get("account_type", "?"))
    else:
        print("[WARN] トークンは取得しましたが、APIテストに失敗しました")


if __name__ == "__main__":
    main()
