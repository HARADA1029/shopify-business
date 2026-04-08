# ============================================================
# TikTok OAuth 認証スクリプト
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

# Sandbox か Production かを引数で切り替え
USE_SANDBOX = "--sandbox" in sys.argv

if USE_SANDBOX:
    CLIENT_KEY = os.getenv("TIKTOK_SANDBOX_KEY", "")
    CLIENT_SECRET = os.getenv("TIKTOK_SANDBOX_SECRET", "")
    print("Mode: SANDBOX")
else:
    CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "")
    CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")
    print("Mode: PRODUCTION")

TOKEN_FILE = os.path.join(PROJECT_ROOT, ".tiktok_token.json")
REDIRECT_URI = "http://localhost:8765/callback"
PORT = 8765

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
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>OK</h1><p>TikTok authorization successful.</p></body></html>")
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
    print("  TikTok OAuth")
    print("=" * 60)
    print()

    if not CLIENT_KEY or not CLIENT_SECRET:
        print("[ERROR] TikTok credentials not set in .env")
        sys.exit(1)

    # PKCE S256 - TikTok独自仕様: hexエンコード（base64urlではない）
    import hashlib
    import string
    import random
    chars = string.ascii_letters + string.digits
    code_verifier = "".join(random.choices(chars, k=43))
    code_challenge = hashlib.sha256(code_verifier.encode("ascii")).hexdigest()

    # OAuth URL
    scopes = "user.info.basic,video.publish,video.upload"
    auth_url = (
        "https://www.tiktok.com/v2/auth/authorize/"
        "?client_key=%s"
        "&scope=%s"
        "&response_type=code"
        "&redirect_uri=%s"
        "&state=hdtoys"
        "&code_challenge=%s"
        "&code_challenge_method=S256"
    ) % (CLIENT_KEY, scopes, urllib.parse.quote(REDIRECT_URI), code_challenge)

    # ローカルサーバー起動
    server = http.server.HTTPServer(("localhost", PORT), OAuthCallbackHandler)

    def serve():
        while not server_should_stop:
            server.handle_request()

    thread = threading.Thread(target=serve)
    thread.daemon = True
    thread.start()

    print("[INFO] Opening browser for TikTok authorization...")
    print("  URL: %s" % auth_url[:80])
    webbrowser.open(auth_url)

    # コールバック待ち
    timeout = 120
    start = time.time()
    while auth_code is None and (time.time() - start) < timeout:
        time.sleep(0.5)

    server.server_close()

    if auth_code is None:
        print("[ERROR] Timeout")
        sys.exit(1)

    print("[OK] Auth code received")

    # トークン交換（PKCE: code_verifier を含める）
    token_resp = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": CLIENT_KEY,
            "client_secret": CLIENT_SECRET,
            "code": auth_code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        timeout=15,
    )

    print("Token status:", token_resp.status_code)
    if token_resp.status_code == 200:
        token_data = token_resp.json()
        if "access_token" in token_data:
            token_data["client_key"] = CLIENT_KEY
            token_data["client_secret"] = CLIENT_SECRET
            token_data["mode"] = "sandbox" if USE_SANDBOX else "production"

            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                json.dump(token_data, f, indent=2)
            print("[OK] Token saved: %s" % TOKEN_FILE)
            print("  Open ID: %s" % token_data.get("open_id", "?"))
        else:
            print("[ERROR] No access_token in response")
            print(json.dumps(token_data, indent=2)[:300])
    else:
        print("[ERROR]", token_resp.text[:300])


if __name__ == "__main__":
    main()
