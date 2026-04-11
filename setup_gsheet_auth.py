"""
首次執行此腳本以完成 Google OAuth 授權。
授權後 token 會儲存到 token.json，之後 API 會自動使用。

執行方式：
    uv run python setup_gsheet_auth.py
"""
import os
from google_auth_oauthlib.flow import InstalledAppFlow
import json

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRETS = os.path.join(BASE_DIR, "client_secrets.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.json")


def main():
    if not os.path.exists(CLIENT_SECRETS):
        print("❌ 找不到 client_secrets.json，請先下載並放到此目錄")
        return

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)

    print("\n========================================")
    print("  Google Sheets OAuth 授權流程")
    print("========================================")
    print("\n請用瀏覽器開啟以下網址並完成登入授權：\n")

    # 產生授權 URL（不啟動本地 server，改為手動貼上 code）
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    auth_url, _ = flow.authorization_url(prompt="consent")

    print(auth_url)
    print("\n授權完成後，將頁面顯示的授權碼貼到下方：")
    code = input("授權碼：").strip()

    flow.fetch_token(code=code)
    creds = flow.credentials

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }

    with open(TOKEN_PATH, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"\n✅ 授權成功！Token 已儲存到 {TOKEN_PATH}")
    print("現在可以使用 /api/export/gsheet API 了")


if __name__ == "__main__":
    main()
