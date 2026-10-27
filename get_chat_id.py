"""봇에게 아무 메시지나 보낸 뒤 실행하면 chat_id를 알려준다."""
import json
import urllib.request

from common import UA, load_config

token = load_config()["telegram_bot_token"]
req = urllib.request.Request(f"https://api.telegram.org/bot{token}/getUpdates", headers={"User-Agent": UA})
with urllib.request.urlopen(req, timeout=20) as r:
    res = json.loads(r.read())["result"]
chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name") or u["message"]["chat"].get("title")
         for u in res if "message" in u}
if not chats:
    print("메시지가 없습니다. 텔레그램에서 봇에게 아무 말이나 보낸 뒤 다시 실행하세요.")
for cid, name in chats.items():
    print(f"chat_id = {cid}  ({name})")
