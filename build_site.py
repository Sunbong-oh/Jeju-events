"""GitHub Pages용 보기 전용 사이트(docs/)를 만든다: index.html + events.json(판정·지역 포함).
공개 페이지이므로 집에서의 거리(km)는 넣지 않는다."""
import json
import os
import re
import shutil

from common import BASE, load_config, load_db
from geo import is_jeju, where, zone
from kidfit import fit_cfg, is_big, liked

DOCS = os.path.join(BASE, "docs")
# 같은 행사가 여러 출처(협회·블로그)에 올라온 경우를 합친다. 교육청(jje)끼리는 회차·학년별 별도 프로그램이라 합치지 않는다.
PRIORITY = {"visitjeju": 0, "auto": 1, "jje": 2}


def _norm(t):
    t = re.sub(r"\[.*?\]|\(.*?\)|<.*?>|[「」『』《》]|\d+회차?|\d+회", " ", t or "")
    return re.sub(r"[^가-힣A-Za-z0-9]", "", t).lower()


def _grams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def same_event(a, b):
    if a.get("source") == "jje" and b.get("source") == "jje":
        return False
    if (a.get("event_start"), a.get("event_end")) != (b.get("event_start"), b.get("event_end")):
        return False
    ga, gb = _grams(_norm(a.get("title"))), _grams(_norm(b.get("title")))
    return len(ga & gb) / max(1, len(ga | gb)) >= 0.8


def dedupe(items):
    """같은 행사는 출처 우선순위가 높은 항목 하나만 남긴다 (데이터 파일은 그대로 둔다)."""
    items = sorted(items, key=lambda e: PRIORITY.get(e.get("source"), 1))
    kept = []
    for e in items:
        if not any(same_event(e, k) for k in kept):
            kept.append(e)
    return kept


def build():
    cfg = load_config()
    out = []
    for e in load_db()["events"]:
        if e.get("hidden") or not is_jeju(e):  # 제주 이외의 행사는 보여주지 않는다
            continue
        loc = where(e, None)
        out.append({**e, "fit": fit_cfg(e, cfg), "liked": liked(e, cfg), **loc,
                    "zone": zone(loc.get("area")), "big": is_big(e, cfg)})
    out = dedupe(out)
    os.makedirs(DOCS, exist_ok=True)
    shutil.copy(os.path.join(BASE, "index.html"), os.path.join(DOCS, "index.html"))
    with open(os.path.join(DOCS, "events.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    # GitHub Pages가 파일을 그대로 서빙하도록
    open(os.path.join(DOCS, ".nojekyll"), "w").close()
    return len(out)


if __name__ == "__main__":
    print(f"docs/ 생성: 행사 {build()}건")
