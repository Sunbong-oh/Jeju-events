"""매일 1회 실행: 새 글 수집 → 직접 고친 내용(overrides.json) 반영 → 텔레그램 알림 → 보기 전용 사이트 생성.
이 PC에서는 작업 스케줄러로, GitHub에서는 Actions(.github/workflows/daily.yml)로 실행한다."""
import datetime as dt
import json
import os
import traceback

from build_site import build
from collector import collect
from common import DATA_DIR, OVERRIDES_FILE, load_db, save_db
from notifier import notify

OVERRIDABLE = ("title", "apply_start", "apply_end", "event_start", "event_end", "hidden", "fit_override", "memo")


def apply_overrides(log):
    """overrides.json: {"행사 ID": {"hidden": true} 또는 {"fit_override": "good"/"no"} 또는 날짜 고치기}"""
    if not os.path.exists(OVERRIDES_FILE):
        return
    with open(OVERRIDES_FILE, encoding="utf-8") as f:
        overrides = json.load(f)
    db = load_db()
    by_id = {e["id"]: e for e in db["events"]}
    for eid, patch in overrides.items():
        ev = by_id.get(eid)
        if not ev or not isinstance(patch, dict):
            continue
        patch = {k: v for k, v in patch.items() if k in OVERRIDABLE}
        ev.update(patch)
        if any(k.startswith(("apply_", "event_")) for k in patch):
            ev["edited"] = True  # 자동 갱신이 덮어쓰지 않게
    save_db(db)
    log(f"직접 고친 항목 {len(overrides)}건 반영")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "run.log"), "a", encoding="utf-8") as f:
        def log(msg):
            line = f"{dt.datetime.now():%Y-%m-%d %H:%M} {msg}"
            print(line)
            f.write(line + "\n")
        new = []
        try:
            new = collect(log)
            log(f"새 행사 {len(new)}건")
        except Exception:
            log("수집 오류\n" + traceback.format_exc())
        try:
            apply_overrides(log)
        except Exception:
            log("overrides.json 오류\n" + traceback.format_exc())
        try:
            log(f"알림 {notify(new, log=log)}건 전송")
        except Exception:
            log("알림 오류\n" + traceback.format_exc())
        try:
            log(f"사이트 생성: 행사 {build()}건")
        except Exception:
            log("사이트 생성 오류\n" + traceback.format_exc())
    # 실행 기록은 GitHub에서도 볼 수 있게 저장소에 함께 저장 — 최근 500줄만 유지
    path = os.path.join(DATA_DIR, "run.log")
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()[-500:]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


if __name__ == "__main__":
    main()
