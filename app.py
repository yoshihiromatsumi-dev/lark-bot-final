from flask import Flask, request, jsonify
import requests
import os
import sys
import json
import redis

app = Flask(__name__)

APP_ID = os.environ.get("LARK_APP_ID", "YOUR_APP_ID")
APP_SECRET = os.environ.get("LARK_APP_SECRET", "YOUR_APP_SECRET")

# Redis接続設定
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.Redis.from_url(REDIS_URL)

# デバッグ情報を出力
print(f"=== アプリ起動 ===", file=sys.stderr)
print(f"APP_ID: {APP_ID[:10]}..." if APP_ID != "YOUR_APP_ID" else "APP_ID: 未設定", file=sys.stderr)
print(f"APP_SECRET: {'設定済み' if APP_SECRET != 'YOUR_APP_SECRET' else '未設定'}", file=sys.stderr)
print(f"REDIS_URL: {REDIS_URL}", file=sys.stderr)
print(f"================", file=sys.stderr)

def get_tenant_access_token():
    """アクセストークン取得"""
    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    try:
        resp = requests.post(url, json={
            "app_id": APP_ID,
            "app_secret": APP_SECRET
        }, timeout=10)
        
        print(f"get_tenant_access_token: {resp.status_code} {resp.text}", file=sys.stderr)
        
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
    """ユーザー一覧取得（修正版）"""
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
            print(f"get_all_users: {resp.status_code} {resp.text}", file=sys.stderr)
            
            if resp.status_code != 200:
                print(f"ユーザー取得失敗: {resp.text}", file=sys.stderr)
                return None
                
            data = resp.json()
            if data.get("code") != 0:
                print(f"APIエラー: {data}", file=sys.stderr)
                return None
                
        except Exception as e:
            print(f"ユーザー取得例外: {e}", file=sys.stderr)
            return None
        
        # データ構造の確認（修正箇所）
        data_section = data.get("data", {})
        items = data_section.get("items", [])
        
        print(f"取得したアイテム数: {len(items)}", file=sys.stderr)
        users.extend(items)
        
        # ページネーション処理
        has_more = data_section.get("has_more", False)
        page_token = data_section.get("page_token", "")
        
        if not has_more or not page_token:
            break
    
    print(f"総ユーザー数: {len(users)}", file=sys.stderr)
    return users

def get_department_info(token, department_id):
    """部署情報取得"""
    url = f"https://open.larksuite.com/open-apis/contact/v3/departments/{department_id}"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        
        if resp.status_code != 200:
            return f"(部署名取得失敗: {department_id})"
        
        resp_json = resp.json()
        if resp_json.get("code") == 0 and "data" in resp_json:
            return resp_json["data"].get("name", f"(部署名不明: {department_id})")
        else:
            return f"(部署名取得失敗: {department_id})"
            
    except Exception as e:
        print(f"部署名取得例外: {e}", file=sys.stderr)
        return f"(部署名取得失敗: {department_id})"

def get_department_members(token, department_id):
    """部署メンバー取得"""
    url = "https://open.larksuite.com/open-apis/contact/v3/users"
    members = []
    page_token = ""
    
    headers = {"Authorization": f"Bearer {token}"}
    
    while True:
        params = {
            "department_id": department_id, 
            "page_size": 50,
            "user_id_type": "user_id",
            "department_id_type": "department_id"
        }
        if page_token:
            params["page_token"] = page_token
            
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=8)
            
            if resp.status_code != 200:
                return ["（部署メンバー取得に失敗しました）"]
                
            resp_json = resp.json()
            if resp_json.get("code") != 0:
                if resp_json.get("code") == 40004:
                    return ["（権限エラー: contact:department.member:readonly スコープが必要です）"]
                else:
                    return ["（部署メンバー取得に失敗しました）"]
                
        except Exception as e:
            print(f"部署メンバー取得例外: {e}", file=sys.stderr)
            return ["（部署メンバー取得に失敗しました）"]
        
        items = resp_json.get("data", {}).get("items", [])
        members.extend([u.get("name", "名前不明") for u in items])
        
        has_more = resp_json.get("data", {}).get("has_more", False)
        page_token = resp_json.get("data", {}).get("page_token", "")
        
        if not has_more or not page_token:
            break
    
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
        print(f"send_lark_reply: {resp.status_code} {resp.text}", file=sys.stderr)
        
        if resp.status_code != 200:
            print(f"返信送信失敗: {resp.text}", file=sys.stderr)
            return False
        else:
            resp_json = resp.json()
            if resp_json.get("code") != 0:
                print(f"返信送信APIエラー: {resp_json}", file=sys.stderr)
                return False
            return True
                
    except Exception as e:
        print(f"返信送信例外: {e}", file=sys.stderr)
        return False

@app.route('/', methods=['GET', 'POST'])
def lark_event():
    if request.method == 'GET':
        print("GET リクエスト受信", file=sys.stderr)
        return "Hello, Final Lark Bot! - Version 2.0"
        
    print("=== POST リクエスト受信 ===", file=sys.stderr)
    
    try:
        data = request.get_json()
        print(f"受信データ: {data}", file=sys.stderr)
    except Exception as e:
        print(f"JSONパース失敗: {e}", file=sys.stderr)
        return '', 400

    # Larkのチャレンジ応答
    if 'challenge' in data:
        print(f"チャレンジ応答: {data['challenge']}", file=sys.stderr)
        return jsonify({'challenge': data['challenge']})

    # イベント情報の抽出
    event = data.get("event", {})
    header = data.get("header", {})

    # ======== 重複排除ロジック追加 ========
    event_id = header.get("event_id")
    if event_id:
        redis_key = f"lark_event:{event_id}"
        if redis_client.get(redis_key):
            print(f"重複イベント検知: {event_id}", file=sys.stderr)
            return '', 200  # すでに処理済み
        else:
            redis_client.set(redis_key, 1, ex=300)  # 5分間だけ保存
    # ======== ここまで追加 ========

    print(f"event内容: {event}", file=sys.stderr)
    
    event_type = header.get("event_type") or event.get("event_type")
    print(f"event_type: {event_type}", file=sys.stderr)

    if event_type != "im.message.receive_v1":
        print(f"対象外のイベント: {event_type}", file=sys.stderr)
        return '', 200

    print("メッセージイベント検知", file=sys.stderr)

    # メッセージ情報の抽出
    message = event.get("message", {})
    chat_id = message.get("chat_id")
    content = message.get("content", "")
    
    print(f"ユーザー入力: {content}", file=sys.stderr)
    
    # メッセージ内容の抽出
    try:
        text = json.loads(content).get("text", "").strip()
    except Exception:
        text = content.strip()
    
    print(f"抽出されたテキスト: '{text}'", file=sys.stderr)

    if not text:
        print("空のメッセージ", file=sys.stderr)
        return '', 200

    # アクセストークン取得
    token = get_tenant_access_token()
    if not token:
        print("アクセストークン取得失敗", file=sys.stderr)
        send_lark_reply("dummy", chat_id, "認証エラー：管理者にご確認ください。")
        return '', 200

    # ユーザー一覧取得
    users = get_all_users(token)
    if users is None:
        print("ユーザー一覧取得失敗", file=sys.stderr)
        send_lark_reply(token, chat_id, "ユーザー一覧の取得に失敗しました。")
        return '', 200
    elif len(users) == 0:
        print("ユーザー数0", file=sys.stderr)
        send_lark_reply(token, chat_id, "ユーザーが見つかりませんでした。権限設定を確認してください。")
        return '', 200

    # ユーザー検索
    print(f"ユーザー検索開始: '{text}'", file=sys.stderr)
    matched_users = []
    for user in users:
        user_name = user.get("name", "")
        if text == user_name:
            matched_users.append(user)
    
    print(f"マッチしたユーザー数: {len(matched_users)}", file=sys.stderr)
    
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
        dept_name = get_department_info(token, dept_id)
        member_names = get_department_members(token, dept_id)
        
        if member_names and len(member_names) > 0 and not member_names[0].startswith("（"):
            members_str = "\n- " + "\n- ".join(member_names)
        else:
            members_str = " 取得不可"
            
        reply_lines.append(f"候補者: {user_name}\n所属部署: {dept_name}\n部署メンバー:{members_str}\n")
    
    reply_text = "\n".join(reply_lines)
    
    # 返信送信
    if send_lark_reply(token, chat_id, reply_text):
        print("返信送信成功", file=sys.stderr)
    else:
        print("返信送信失敗", file=sys.stderr)

    print("=== POST リクエスト処理完了 ===", file=sys.stderr)
    return '', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
