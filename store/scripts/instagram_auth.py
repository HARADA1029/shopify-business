# ============================================================
# Instagram OAuth 認証スクリプト
#
# 【役割】
#   Instagram Graph API のアクセストークンを OAuth フローで取得する
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python store/scripts/instagram_auth.py
#
# 【動作】
#   1. ローカルに HTTP サーバーを起動（port 8765）
#   2. ブラウザで Instagram 認証ページを開く
#   3. 原田がブラウザで承認する
#   4. コールバックで認証コードを受け取る
#   5. 認証コードを短期トークンに交換する
#   6. 短期トークンを長期トークン（60日）に交換する
#   7. Instagram Business Account ID を取得する
#   8. トークンを .instagram_token.json に保存する
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

APP_ID = os.getenv("INSTAGRAM_APP_ID", "")
APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET", "")
TOKEN_FILE = os.path.join(PROJECT_ROOT, ".instagram_token.json")

REDIRECT_URI = "https://localhost:8765/callback"
PORT = 8765

# Instagram Business Content Publishing に必要なスコープ
SCOPES = ",".join([
    "instagram_business_basic",
    "instagram_business_content_publish",
    "instagram_business_manage_comments",
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
                b"<p>Instagram authorization successful. You can close this tab.</p>"
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
    """認証コードを短期トークンに交換する"""
    url = "https://api.instagram.com/oauth/access_token"
    data = {
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }
    resp = requests.post(url, data=data)
    if resp.status_code == 200:
        return resp.json()
    else:
        print(f"[エラー] 短期トークン取得失敗: HTTP {resp.status_code}")
        print(f"  レスポンス: {resp.text}")
        return None


def exchange_for_long_lived_token(short_token):
    """短期トークンを長期トークン（60日）に交換する"""
    url = "https://graph.instagram.com/access_token"
    params = {
        "grant_type": "ig_exchange_token",
        "client_secret": APP_SECRET,
        "access_token": short_token,
    }
    resp = requests.get(url, params=params)
    if resp.status_code == 200:
        return resp.json()
    else:
        print(f"[エラー] 長期トークン取得失敗: HTTP {resp.status_code}")
        print(f"  レスポンス: {resp.text}")
        return None


def get_instagram_business_account(access_token):
    """Instagram Business Account ID を取得する"""
    # まず Facebook Pages を取得
    url = "https://graph.facebook.com/v22.0/me/accounts"
    resp = requests.get(url, params={"access_token": access_token})
    if resp.status_code != 200:
        print(f"[エラー] Facebook Pages 取得失敗: {resp.text[:200]}")
        return None

    pages = resp.json().get("data", [])
    if not pages:
        print("[エラー] Facebook Pages が見つかりません")
        return None

    # 各ページの Instagram Business Account を確認
    for page in pages:
        page_id = page["id"]
        page_token = page["access_token"]
        ig_resp = requests.get(
            f"https://graph.facebook.com/v22.0/{page_id}",
            params={
                "fields": "instagram_business_account",
                "access_token": page_token,
            },
        )
        if ig_resp.status_code == 200:
            ig_data = ig_resp.json()
            ig_account = ig_data.get("instagram_business_account", {})
            if ig_account:
                return {
                    "ig_user_id": ig_account["id"],
                    "page_id": page_id,
                    "page_name": page.get("name", ""),
                    "page_access_token": page_token,
                }

    print("[エラー] Instagram Business Account が見つかりません")
    print("  Facebook ページと Instagram ビジネスアカウントが連携されているか確認してください")
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


def main():
    global auth_code, server_should_stop

    print()
    print("=" * 60)
    print("  Instagram OAuth 認証")
    print("=" * 60)
    print()

    if not APP_ID or not APP_SECRET:
        print("[エラー] .env に INSTAGRAM_APP_ID / INSTAGRAM_APP_SECRET を設定してください")
        sys.exit(1)

    # --- 既存トークンの確認 ---
    existing = load_token()
    if existing and "access_token" in existing:
        print("[INFO] 保存済みトークンが見つかりました。検証中...")
        resp = requests.get(
            "https://graph.instagram.com/v22.0/me",
            params={"fields": "id,username", "access_token": existing["access_token"]},
        )
        if resp.status_code == 200:
            user = resp.json()
            print(f"[OK] トークンは有効です。")
            print(f"  IG User ID: {user.get('id', '?')}")
            print(f"  Username: {user.get('username', '?')}")
            return
        else:
            print("[INFO] トークンが無効です。再認証を行います。")

    # --- OAuth フロー ---
    import ssl
    # HTTPS 用の自己署名証明書を生成（Instagram API は https redirect_uri が必須）
    print("[INFO] 認証用ローカルサーバーを起動しています...")
    print()

    # Instagram Graph API の認証 URL を構築
    auth_url = (
        f"https://www.instagram.com/oauth/authorize"
        f"?client_id={APP_ID}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope={SCOPES}"
    )

    print("[INFO] 以下の URL をブラウザで開いてください:")
    print()
    print(f"  {auth_url}")
    print()
    print("  ブラウザで承認後、リダイレクト先の URL をコピーして")
    print("  以下に貼り付けてください（https://localhost:8765/callback?code=XXXXX の形式）:")
    print()

    webbrowser.open(auth_url)

    redirect_url = input("  リダイレクト URL: ").strip()

    # URL からコードを抽出
    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)
    if "code" not in params:
        print("[エラー] 認証コードが URL に含まれていません")
        sys.exit(1)

    auth_code = params["code"][0]
    # Instagram のコードは末尾に #_ が付くことがある
    if auth_code.endswith("#_"):
        auth_code = auth_code[:-2]

    print(f"[OK] 認証コードを取得しました")
    print()

    # --- 短期トークン取得 ---
    print("[INFO] 短期アクセストークンを取得しています...")
    token_data = exchange_code_for_token(auth_code)

    if not token_data or "access_token" not in token_data:
        print("[エラー] トークンの取得に失敗しました。")
        sys.exit(1)

    short_token = token_data["access_token"]
    ig_user_id = token_data.get("user_id", "")
    print(f"[OK] 短期トークン取得成功 (user_id: {ig_user_id})")

    # --- 長期トークンに交換 ---
    print("[INFO] 長期トークンに交換しています...")
    long_token_data = exchange_for_long_lived_token(short_token)

    if long_token_data and "access_token" in long_token_data:
        access_token = long_token_data["access_token"]
        expires_in = long_token_data.get("expires_in", 0)
        print(f"[OK] 長期トークン取得成功 (有効期限: {expires_in // 86400}日)")
    else:
        access_token = short_token
        print("[警告] 長期トークン交換に失敗。短期トークンを使用します。")

    # --- Instagram ユーザー情報を取得 ---
    print("[INFO] Instagram アカウント情報を取得しています...")
    resp = requests.get(
        "https://graph.instagram.com/v22.0/me",
        params={"fields": "id,username,account_type,media_count", "access_token": access_token},
    )
    if resp.status_code == 200:
        user = resp.json()
        print(f"[OK] Instagram アカウント:")
        print(f"  ID: {user.get('id', '?')}")
        print(f"  Username: {user.get('username', '?')}")
        print(f"  Account Type: {user.get('account_type', '?')}")
        print(f"  Media Count: {user.get('media_count', '?')}")
    else:
        print(f"[警告] ユーザー情報取得失敗: {resp.text[:200]}")

    # --- 保存 ---
    save_data = {
        "access_token": access_token,
        "ig_user_id": ig_user_id,
        "token_type": "long_lived" if long_token_data else "short_lived",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_token(save_data)

    print()
    print("[OK] Instagram 認証完了！")


if __name__ == "__main__":
    main()
