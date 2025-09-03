from flask import Flask, request, jsonify
import requests
import os
import sys
import json
import time
import csv

app = Flask(__name__)

APP_ID = os.environ.get("LARK_APP_ID", "YOUR_APP_ID")
APP_SECRET = os.environ.get("LARK_APP_SECRET", "YOUR_APP_SECRET")

# メモリ上でevent_idを保持（event_id: 保存時刻）
event_id_cache = {}
EVENT_ID_CACHE_EXPIRE = 300  # 5分

# 部署マスタCSVを辞書化（pandasなし）
dept_id_to_name = {}
DEPT_CSV_PATH = "departments.csv"
try:
    with open(DEPT_CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dept_id = row["部署ID"].strip()
            dept_name = row["部署"].strip()
            dept_id_to_name[dept_id] = dept_name
    print(f"部署辞書ロード成功: {len(dept_id_to_name)}件", file=sys.stderr)
except Exception as e:
    print(f"部署辞書ロード失敗: {e}", file=sys.stderr)

def get_tenant_access_token():
    """アクセストークン取得"""
    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    try:
        resp = requests.post(url, json={
            "app_id": APP_ID,
            "app_secret": APP_SECRET
        }, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("code") != 0:
            return None
        return data.get("tenant_access_token")
    except Exception as e:
        print(f"get_tenant_access_token error: {e}", file=sys.stderr)
        return None

def get_all_users(token):
    """ユーザー一覧取得"""
    url = "https://open.larksuite.com/open-apis/contact/v3/users"
    users = []
    page_token = ""
    headers = {"Authorization": f"Bearer {token}"}
    while True:
        params = {
            "page_size": 50,
            "user_id_type": "user_id",
            "department_id_type": "department_id"
        }
        if page_token:
            params["page_token"] = page_token
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get("code") != 0:
                return None
        except Exception as e:
            print(f"ユーザー取得例外: {e}", file=sys.stderr)
            return None
        data_section = data.get("data", {})
        items = data_section.get("items", [])
        users.extend(items)
        has_more = data_section.get("has_more", False)
        page_token = data_section.get("page_token", "")
        if not has_more or not page_token:
            break
    return users

def get_department_info_from_csv(department_id):
    """CSV辞書から部署名取得"""
    dept_name = dept_id_to_name.get(str(department_id))
    if dept_name:
        return dept_name
    else:
        return f"(部署名取得失敗: {department_id})"

def get_department_members_from_users(users, department_id):
    """usersリストから部署ID一致のメンバー名リストを返す"""
    members = []
    for user in users:
        if department_id in user.get("department_ids", []):
            members.append(user.get("name", "名前不明"))
    return members

def send_lark_reply(token, chat_id, reply_text):
    """返信送信"""
    reply_url = "https://open.larksuite.com/open-apis/im/v1/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    body = {
        "receive_id": chat_id,
        "content": json.dumps({"text": reply_text}),
        "msg_type": "text"
    }
    params = {"receive_id_type": "chat_id"}
    try:
        resp = requests.post(reply_url, headers=headers, params=params, json=body, timeout=10)
        if resp.status_code != 200:
            return False
        else:
            resp_json = resp.json()
            if resp_json.get("code") != 0:
                return False
            return True
    except Exception as e:
        print(f"返信送信例外: {e}", file=sys.stderr)
        return False

@app.route('/', methods=['GET', 'POST'])
def lark_event():
    if request.method == 'GET':
        return "Hello, Final Lark Bot! - Version 2.0"
    try:
        data = request.get_json()
    except Exception as e:
        print(f"JSONパース失敗: {e}", file=sys.stderr)
        return '', 400

    # Larkのチャレンジ応答
    if 'challenge' in data:
        return jsonify({'challenge': data['challenge']})

    event = data.get("event", {})
    header = data.get("header", {})

    # ======== メモリによる重複排除ロジック ========
    event_id = header.get("event_id")
    now = time.time()
    expired_keys = [k for k, v in event_id_cache.items() if now - v > EVENT_ID_CACHE_EXPIRE]
    for k in expired_keys:
        del event_id_cache[k]
    if event_id:
        if event_id in event_id_cache:
            return '', 200  # すでに処理済み
        else:
            event_id_cache[event_id] = now
    # ======== ここまで ========

    event_type = header.get("event_type") or event.get("event_type")
    if event_type != "im.message.receive_v1":
        return '', 200

    message = event.get("message", {})
    chat_id = message.get("chat_id")
    content = message.get("content", "")
    try:
        text = json.loads(content).get("text", "").strip()
    except Exception:
        text = content.strip()
    if not text:
        return '', 200

    # アクセストークン取得
    token = get_tenant_access_token()
    if not token:
        send_lark_reply("dummy", chat_id, "認証エラー：管理者にご確認ください。")
        return '', 200

    # ユーザー一覧取得
    users = get_all_users(token)
    if users is None or len(users) == 0:
        send_lark_reply(token, chat_id, "ユーザー一覧の取得に失敗しました。")
        return '', 200

    # ユーザー検索
    matched_users = []
    for user in users:
        user_name = user.get("name", "")
        if text == user_name:
            matched_users.append(user)

    if not matched_users:
        send_lark_reply(token, chat_id, f"「{text}」に一致するユーザーが見つかりませんでした。")
        return '', 200

    # 結果構築
    reply_lines = []
    for user in matched_users:
        user_name = user.get("name", "名前不明")
        dept_ids = user.get("department_ids", [])
        if not dept_ids:
            reply_lines.append(f"候補者: {user_name}\n所属部署: なし\n部署メンバー: なし\n")
            continue
        dept_id = dept_ids[0]
        dept_name = get_department_info_from_csv(dept_id)
        member_names = get_department_members_from_users(users, dept_id)
        if member_names:
            members_str = "\n- " + "\n- ".join(member_names)
        else:
            members_str = " なし"
        reply_lines.append(f"候補者: {user_name}\n所属部署: {dept_name}\n部署メンバー:{members_str}\n")

    reply_text = "\n".join(reply_lines)
    send_lark_reply(token, chat_id, reply_text)
    return '', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
