# ============================================================
# Shopify OAuth 認証スクリプト
#
# 【役割】
#   Shopify Admin API のアクセストークンを OAuth フローで取得する
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python store/scripts/shopify_auth.py
#
# 【動作】
#   1. ローカルに HTTP サーバーを起動（port 8765）
#   2. ブラウザで Shopify 認証ページを開く
#   3. 原田がブラウザで承認する
#   4. コールバックで認証コードを受け取る
#   5. 認証コードをアクセストークンに交換する
#   6. トークンを .shopify_token.json に保存する
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

STORE = os.getenv("SHOPIFY_STORE", "")
CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "")
TOKEN_FILE = os.path.join(PROJECT_ROOT, ".shopify_token.json")

REDIRECT_URI = "http://localhost:8765/callback"
PORT = 8765

SCOPES = ",".join([
    "read_products", "write_products",
    "read_content", "write_content",
    "read_themes", "write_themes",
    "read_publications", "write_publications",
    "read_online_store_navigation", "write_online_store_navigation",
    "read_legal_policies", "write_legal_policies",
])

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
                b"<p>Shopify authorization successful. You can close this tab.</p>"
                b"</body></html>"
            )
            server_should_stop = True
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid request")

    def log_message(self, format, *args):
        pass  # ログを抑制


def exchange_code_for_token(code):
    """認証コードをアクセストークンに交換する"""
    url = f"https://{STORE}.myshopify.com/admin/oauth/access_token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
    }
    resp = requests.post(url, json=data)
    if resp.status_code == 200:
        return resp.json()
    else:
        print(f"[エラー] トークン交換に失敗: HTTP {resp.status_code}")
        print(f"  レスポンス: {resp.text}")
        return None


def save_token(token_data):
    """トークンをファイルに保存する"""
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2, ensure_ascii=False)
    print(f"[OK] トークン保存: {TOKEN_FILE}")


def load_token():
    """保存済みトークンを読み込む"""
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def test_token(access_token):
    """トークンが有効か確認する"""
    url = f"https://{STORE}.myshopify.com/admin/api/2026-04/shop.json"
    headers = {"X-Shopify-Access-Token": access_token}
    resp = requests.get(url, headers=headers)
    return resp.status_code == 200, resp


def main():
    global auth_code, server_should_stop

    print()
    print("=" * 60)
    print("  Shopify OAuth 認証")
    print("=" * 60)
    print()

    if not STORE or not CLIENT_ID or not CLIENT_SECRET:
        print("[エラー] .env に SHOPIFY_STORE / CLIENT_ID / CLIENT_SECRET を設定してください")
        sys.exit(1)

    # --- 既存トークンの確認 ---
    existing = load_token()
    if existing and "access_token" in existing:
        print("[INFO] 保存済みトークンが見つかりました。検証中...")
        # スコープが不足している場合は再認証
        saved_scope = existing.get("scope", "")
        required_scopes = set(SCOPES.split(","))
        current_scopes = set(saved_scope.split(",")) if saved_scope else set()
        missing = required_scopes - current_scopes
        if missing:
            print(f"[INFO] スコープ不足: {', '.join(missing)}")
            print("[INFO] 再認証を行います。")
        else:
            ok, resp = test_token(existing["access_token"])
            if ok:
                print("[OK] トークンは有効です。")
                shop = resp.json().get("shop", {})
                print(f"  ストア名: {shop.get('name', '?')}")
                print(f"  ドメイン: {shop.get('myshopify_domain', '?')}")
                return
            else:
                print("[INFO] トークンが無効です。再認証を行います。")

    # --- OAuth フロー ---
    print(f"[INFO] ローカルサーバーをポート {PORT} で起動します...")

    server = http.server.HTTPServer(("localhost", PORT), OAuthCallbackHandler)
    server_thread = threading.Thread(target=lambda: None)

    def serve_until_stop():
        while not server_should_stop:
            server.handle_request()

    server_thread = threading.Thread(target=serve_until_stop)
    server_thread.daemon = True
    server_thread.start()

    # 認証 URL を構築
    auth_url = (
        f"https://{STORE}.myshopify.com/admin/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&scope={SCOPES}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    )

    print()
    print("[INFO] ブラウザで Shopify 認証ページを開きます...")
    print(f"  URL: {auth_url[:80]}...")
    print()
    print("  ブラウザで「アプリをインストール」を承認してください。")
    print("  承認後、自動的にトークンを取得します。")
    print()

    webbrowser.open(auth_url)

    # コールバック待ち
    timeout = 120
    start = time.time()
    while auth_code is None and (time.time() - start) < timeout:
        time.sleep(0.5)

    server.server_close()

    if auth_code is None:
        print("[エラー] タイムアウトしました。もう一度実行してください。")
        sys.exit(1)

    print(f"[OK] 認証コードを受信しました")
    print()

    # --- トークン交換 ---
    print("[INFO] アクセストークンを取得しています...")
    token_data = exchange_code_for_token(auth_code)

    if not token_data or "access_token" not in token_data:
        print("[エラー] トークンの取得に失敗しました。")
        sys.exit(1)

    save_token(token_data)

    # --- 動作確認 ---
    access_token = token_data["access_token"]
    ok, resp = test_token(access_token)
    if ok:
        shop = resp.json().get("shop", {})
        print(f"[OK] 認証成功！")
        print(f"  ストア名: {shop.get('name', '?')}")
        print(f"  ドメイン: {shop.get('myshopify_domain', '?')}")
        print(f"  プラン: {shop.get('plan_display_name', '?')}")
    else:
        print(f"[警告] トークンは保存しましたが、API テストに失敗しました: HTTP {resp.status_code}")


if __name__ == "__main__":
    main()
