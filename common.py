"""공통: 설정, 저장소, 텔레그램 전송."""
import json
import os
import sys
import threading
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
EVENTS_FILE = os.path.join(DATA_DIR, "events.json")
CONFIG_FILE = os.path.join(BASE, "config.json")
SETTINGS_FILE = os.path.join(BASE, "settings.json")
OVERRIDES_FILE = os.path.join(BASE, "overrides.json")
UA = "JejuEventCollector/1.0 (personal use)"

_lock = threading.Lock()

# 윈도우 콘솔(cp949)에서 이모지 출력 때문에 죽지 않도록
for _s in (sys.stdout, sys.stderr):
    if _s and hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_CONFIG = {
    # keywords: 글의 카테고리·제목에 하나라도 들어 있으면 수집 (빈 목록이면 전체 수집)
    "blogs": [
        {"blog_id": "wowjejusi", "name": "제주시", "keywords": ["오늘의 제주소식"]},
        {"blog_id": "seogwipo-si", "name": "서귀포시",
         "keywords": ["소식", "행사", "축제", "모집", "신청", "공연", "체험", "교육"]},
        {"blog_id": "jejudo_official", "name": "제주도",
         "keywords": ["소식", "행사", "축제", "모집", "신청", "공연", "체험", "교육", "가족", "어린이", "아이"]},
    ],
    # 아이 맞춤: age_min~age_max세와 겹치는 행사를 추천
    # notify_only_fit: 텔레그램 알림을 아이에게 맞는 행사(추천·가능)로만 제한
    # likes: 좋아하는 행사 종류 — 들어 있으면 추천(⭐)으로 올리고 🎵 표시
    "child": {"age_min": 4, "age_max": 6, "notify_only_fit": True,
              "likes": ["음악회", "콘서트", "공연", "버스킹", "뮤지컬", "오케스트라", "합창", "밴드", "가요제", "재즈", "국악", "음악"]},
    # 집 위치(거리 계산용)는 공개 저장소에 남기지 않도록 config.json 또는 환경변수 HOME_LAT/HOME_LNG로만 넣는다
    # notify_max_km: 이보다 먼 '가능' 행사는 알림 제외 (추천 행사는 거리와 상관없이 알림)
    "home": None,
    "notify_max_km": 25,
    # 제주교육청 통합예약시스템. categories: 견학/체험, 교육/강좌, 공연/행사, 시설대관
    # targets_any: 대상에 이 중 하나라도 있는 것만 (예: ["학부모", "가족", "일반"]), 빈 목록이면 전체
    "reserve": {"enabled": True, "categories": ["견학/체험", "교육/강좌", "공연/행사"],
                "max_pages": 3, "targets_any": []},
    # 제주관광협회 '행사안내' 월별 축제·행사 일정표(첨부 hwpx)
    "visitjeju": {"enabled": True},
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "remind_days_before": 1,
    "notify_new_events": True,
    "port": 8765,
}


def load_config():
    """기본값 ← settings.json(저장소에 올리는 일반 설정) ← config.json(이 PC 전용, 비밀값) ← 환경변수(GitHub Secrets)."""
    cfg = dict(DEFAULT_CONFIG)
    for path in (SETTINGS_FILE, CONFIG_FILE):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cfg.update(json.load(f))
    env = os.environ
    if env.get("TELEGRAM_BOT_TOKEN"):
        cfg["telegram_bot_token"] = env["TELEGRAM_BOT_TOKEN"]
    if env.get("TELEGRAM_CHAT_ID"):
        cfg["telegram_chat_id"] = env["TELEGRAM_CHAT_ID"]
    if env.get("HOME_LAT") and env.get("HOME_LNG"):
        cfg["home"] = {"lat": float(env["HOME_LAT"]), "lng": float(env["HOME_LNG"])}
    return cfg


def load_db():
    with _lock:
        if not os.path.exists(EVENTS_FILE):
            return {"events": [], "seen_posts": [], "sent": []}
        with open(EVENTS_FILE, encoding="utf-8") as f:
            return json.load(f)


def save_db(db):
    with _lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = EVENTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=1)
        os.replace(tmp, EVENTS_FILE)


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def send_telegram(text, cfg=None):
    cfg = cfg or load_config()
    token, chat = cfg.get("telegram_bot_token"), cfg.get("telegram_chat_id")
    if not token or not chat:
        raise RuntimeError("텔레그램 설정이 없습니다: config.json의 telegram_bot_token/telegram_chat_id "
                           "또는 GitHub Secrets의 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID를 넣어주세요.")
    body = urllib.parse.urlencode({
        "chat_id": chat, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=body,
        headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())
