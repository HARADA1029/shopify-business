# ============================================================
# eBay OAuth 認証スクリプト
#
# 【役割】
#   eBay API にアクセスするための User Token を取得・保存する。
#   初回は認証URLをブラウザで開き、eBay にログインして許可する。
#   取得したトークンはローカルファイルに保存し、以降のAPI呼び出しで使う。
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/ebay_auth.py
#
# 【前提】
#   .env ファイルに以下が設定されていること:
#     EBAY_APP_ID, EBAY_CERT_ID, EBAY_DEV_ID, EBAY_RUNAME
# ============================================================

import base64
import json
import os
import sys
from urllib.parse import quote, urlparse, parse_qs

import requests
from dotenv import load_dotenv

# --- .env の読み込み ---
# スクリプトの場所ではなく、プロジェクトルートの .env を読む
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# --- 認証情報の取得 ---
APP_ID = os.getenv("EBAY_APP_ID", "")
CERT_ID = os.getenv("EBAY_CERT_ID", "")
DEV_ID = os.getenv("EBAY_DEV_ID", "")
RUNAME = os.getenv("EBAY_RUNAME", "")

# --- 定数 ---
# トークン保存先（.gitignore 対象）
TOKEN_FILE = os.path.join(PROJECT_ROOT, ".ebay_token.json")

# eBay OAuth エンドポイント（Production）
AUTH_URL = "https://auth.ebay.com/oauth2/authorize"
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"

# API アクセスに必要なスコープ
SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly",
]


def check_credentials():
    """認証情報が .env に設定されているか確認する"""
    missing = []
    if not APP_ID:
        missing.append("EBAY_APP_ID")
    if not CERT_ID:
        missing.append("EBAY_CERT_ID")
    if not RUNAME:
        missing.append("EBAY_RUNAME")
    if missing:
        print(f"[エラー] .env に以下の値が設定されていません: {', '.join(missing)}")
        print(f"  .env の場所: {os.path.join(PROJECT_ROOT, '.env')}")
        sys.exit(1)


def generate_auth_url():
    """eBay の認証URL を生成する"""
    scope_str = quote(" ".join(SCOPES))
    url = (
        f"{AUTH_URL}"
        f"?client_id={APP_ID}"
        f"&response_type=code"
        f"&redirect_uri={RUNAME}"
        f"&scope={scope_str}"
    )
    return url


def extract_auth_code(user_input):
    """
    ユーザーの入力から認証コードを抽出する。
    完全なリダイレクト URL が貼られた場合は code パラメータを抽出する。
    コード単体が貼られた場合はそのまま返す。
    """
    user_input = user_input.strip()

    # URL が貼られた場合 → code パラメータを抽出する
    if user_input.startswith("http"):
        parsed = urlparse(user_input)
        params = parse_qs(parsed.query)
        if "code" in params:
            return params["code"][0]
        # フラグメントにある場合もチェック
        params = parse_qs(parsed.fragment)
        if "code" in params:
            return params["code"][0]
        print("[エラー] URL に code パラメータが見つかりませんでした。")
        return None

    # コード単体が貼られた場合
    return user_input


def exchange_code_for_token(auth_code):
    """認証コードをアクセストークンに交換する"""
    # Basic 認証ヘッダーを作成する（App ID:Cert ID を Base64 エンコード）
    credentials = base64.b64encode(f"{APP_ID}:{CERT_ID}".encode()).decode()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {credentials}",
    }

    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": RUNAME,
    }

    print("\n[INFO] トークンを取得しています...")
    response = requests.post(TOKEN_URL, headers=headers, data=data)

    if response.status_code != 200:
        print(f"[エラー] トークン取得に失敗しました（HTTP {response.status_code}）")
        print(f"  レスポンス: {response.text}")
        return None

    return response.json()


def refresh_access_token(refresh_token):
    """リフレッシュトークンを使ってアクセストークンを更新する"""
    credentials = base64.b64encode(f"{APP_ID}:{CERT_ID}".encode()).decode()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {credentials}",
    }

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": " ".join(SCOPES),
    }

    print("[INFO] アクセストークンを更新しています...")
    response = requests.post(TOKEN_URL, headers=headers, data=data)

    if response.status_code != 200:
        print(f"[エラー] トークン更新に失敗しました（HTTP {response.status_code}）")
        print(f"  レスポンス: {response.text}")
        return None

    return response.json()


def save_token(token_data):
    """トークンをファイルに保存する"""
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2, ensure_ascii=False)
    print(f"[OK] トークンを保存しました: {TOKEN_FILE}")


def load_token():
    """保存済みトークンを読み込む。なければ None を返す"""
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def test_token(access_token):
    """トークンが有効か確認するために、自分のアカウント情報を取得する"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # Sell Account API で自分のアカウント情報を取得する
    url = "https://api.ebay.com/sell/account/v1/privilege"
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return True
    return False


def main():
    """メイン処理"""
    check_credentials()

    print()
    print("=" * 60)
    print("  eBay OAuth 認証ツール")
    print("=" * 60)

    # --- 既存トークンの確認 ---
    existing = load_token()
    if existing and "refresh_token" in existing:
        print()
        print("[INFO] 保存済みトークンが見つかりました。更新を試みます...")
        result = refresh_access_token(existing["refresh_token"])
        if result and "access_token" in result:
            # リフレッシュトークンは前回のものを引き継ぐ
            result["refresh_token"] = existing["refresh_token"]
            save_token(result)

            if test_token(result["access_token"]):
                print("[OK] トークンは有効です。API にアクセスできます。")
            else:
                print("[警告] トークンの検証に失敗しました。再認証が必要かもしれません。")
            return
        else:
            print("[INFO] トークン更新に失敗しました。再認証を行います。")

    # --- 新規認証フロー ---
    auth_url = generate_auth_url()

    print()
    print("以下の手順で認証してください:")
    print()
    print("1. 下記の URL をブラウザで開いてください:")
    print()
    print(f"   {auth_url}")
    print()
    print("2. eBay にログインし、「I agree」で API アクセスを許可してください。")
    print()
    print("3. リダイレクトされたページの URL をコピーしてください。")
    print("   （ページが表示されなくても、ブラウザのアドレスバーの URL を")
    print("     そのままコピーすれば大丈夫です）")
    print()

    user_input = input("4. ここに URL またはコードを貼り付けてください: ")

    auth_code = extract_auth_code(user_input)
    if not auth_code:
        print("[エラー] 認証コードを取得できませんでした。")
        sys.exit(1)

    # --- トークン取得 ---
    token_data = exchange_code_for_token(auth_code)
    if not token_data or "access_token" not in token_data:
        print("[エラー] トークンの取得に失敗しました。")
        sys.exit(1)

    # --- 保存 ---
    save_token(token_data)

    # --- 動作確認 ---
    if test_token(token_data["access_token"]):
        print("[OK] 認証成功！eBay API にアクセスできます。")
    else:
        print("[警告] トークンは取得できましたが、API 接続テストに失敗しました。")
        print("  スコープ設定やアカウント権限を確認してください。")

    print()
    print("次のステップ:")
    print("  このトークンを使って、出品データの取得スクリプトを実行できます。")


if __name__ == "__main__":
    main()
