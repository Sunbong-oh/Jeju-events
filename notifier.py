"""오늘 날짜 기준으로 신청 시작·마감, 행사 당일(및 N일 전) 알림을 텔레그램으로 보낸다."""
import datetime as dt
import html

from common import load_config, load_db, save_db, send_telegram
from geo import where
from kidfit import fit_cfg, liked

# (날짜 필드, 라벨, 며칠 전 알림 여부)
TRIGGERS = [
    ("apply_start", "📝 신청 시작", False),
    ("apply_end", "⏰ 신청 마감", True),
    ("event_start", "🎉 행사 시작", True),
]


def _line(ev):
    def rng(a, b):
        if not a:
            return "-"
        return a if not b or a == b else f"{a} ~ {b}"
    t = html.escape(ev.get("title") or ev.get("post_title") or "")
    end_time = f" {ev['apply_end_time']}까지" if ev.get("apply_end_time") else ""
    info = f"{html.escape(ev['info'])}\n" if ev.get("info") else ""
    star = ("🎵 " if ev.get("_liked") else "") + ("⭐ " if ev.get("_fit") == "good" else "")
    loc = ev.get("_where") or {}
    km = f" · 집에서 약 {loc['km']}km" if "km" in loc else ""
    place = f"📍 {loc['area']}{km}\n" if loc else ""
    return (f"{star}<b>{t}</b> ({html.escape(ev.get('blog', ''))})\n{place}{info}"
            f"신청: {rng(ev.get('apply_start'), ev.get('apply_end'))}{end_time}\n"
            f"행사: {rng(ev.get('event_start'), ev.get('event_end'))}\n"
            f"<a href=\"{ev.get('url', '')}\">원문 보기</a>")


def due_today(db, today, remind_days):
    """[(key, 제목줄, 행사)] — 아직 안 보낸 오늘 알림 목록."""
    sent = set(db.get("sent", []))
    out = []
    for ev in db["events"]:
        if ev.get("hidden"):
            continue
        for field, label, remind in TRIGGERS:
            d = ev.get(field)
            if not d:
                continue
            d = dt.date.fromisoformat(d)
            if d == today:
                head = f"{label} (오늘)"
            elif remind and remind_days and d - today == dt.timedelta(days=remind_days):
                head = f"{label} D-{remind_days}"
            else:
                continue
            key = f"{ev['id']}|{field}|{head}|{d}"
            if key not in sent:
                out.append((key, head, ev))
    return out


def notify(new_events=(), today=None, log=print):
    cfg = load_config()
    if not cfg.get("telegram_bot_token") or not cfg.get("telegram_chat_id"):
        log("텔레그램 설정 없음 — 알림 건너뜀 (웹페이지만 사용)")
        return 0
    today = today or dt.date.today()
    db = load_db()
    child = cfg.get("child", {})
    max_km = cfg.get("notify_max_km")
    for e in list(db["events"]) + list(new_events):
        e["_fit"] = fit_cfg(e, cfg)
        e["_where"] = where(e, cfg["home"])
        e["_liked"] = liked(e, cfg)

    def wanted(e):
        if not child.get("notify_only_fit", True):
            return True
        if e["_fit"] == "no":
            return False
        # '가능' 등급은 너무 먼 곳이면 뺀다 (추천은 멀어도 알림)
        return e["_fit"] == "good" or not max_km or e["_where"].get("km", 0) <= max_km
    # 알림을 항목마다 따로 보내지 않고 하루치 묶음으로 보낸다
    blocks = []  # (key 목록, 텍스트)
    if cfg.get("notify_new_events") and new_events:
        upcoming = lambda e: max(e.get("apply_end") or "", e.get("event_end") or e.get("event_start") or "") >= today.isoformat()
        dated = [e for e in new_events if upcoming(e) and wanted(e)]
        dated.sort(key=lambda e: (not e["_liked"], e["_fit"] != "good"))  # 좋아하는 것·추천 먼저
        if dated:
            blocks.append(([], f"🆕 <b>새 행사 {len(dated)}건</b>"))
            blocks += [([], _line(e)) for e in dated[:15]]
            if len(dated) > 15:
                blocks.append(([], f"…외 {len(dated) - 15}건은 웹페이지에서 확인"))
    due = [d for d in due_today(db, today, cfg.get("remind_days_before", 1)) if wanted(d[2])]
    if due:
        blocks.append(([], f"📅 <b>{today:%m/%d} 오늘의 일정 {len(due)}건</b>"))
        blocks += [([key], f"{head}\n{_line(ev)}") for key, head, ev in due]

    # 텔레그램 한 메시지 4096자 제한에 맞춰 나눠 보냄
    msgs, keys, buf = [], [], ""
    for ks, text in blocks:
        if buf and len(buf) + len(text) > 3800:
            msgs.append((keys, buf))
            keys, buf = [], ""
        buf = f"{buf}\n\n{text}" if buf else text
        keys = keys + ks
    if buf:
        msgs.append((keys, buf))
    for e in db["events"]:
        e.pop("_fit", None)
        e.pop("_where", None)
        e.pop("_liked", None)  # 판정 결과는 저장하지 않음 (규칙이 바뀌면 다시 계산)
    for ks, text in msgs:
        send_telegram(text[:4000], cfg)
        db.setdefault("sent", []).extend(ks)  # 보낸 것만 기록 → 실패하면 다음 실행 때 다시 보냄
        save_db(db)
        log("전송: " + text.splitlines()[0])
    if not msgs:
        log("오늘 보낼 알림 없음")
    return len(msgs)


if __name__ == "__main__":
    print(f"알림 {notify()}건 전송")
