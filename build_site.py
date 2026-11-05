"""GitHub Pages용 보기 전용 사이트(docs/)를 만든다: index.html + events.json(판정·지역 포함).
공개 페이지이므로 집에서의 거리(km)는 넣지 않는다."""
import json
import os
import re
import shutil

from common import BASE, is_past, load_config, load_db
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


# 블로그 글이 여러 개인 같은 행사를 한 카드로 묶는 이름 목록. 이름 + 같은 기간인 글만 묶는다.
ROUNDUP = re.compile(r"총정리|모음|정리|추천|BEST|TOP|목록|가볼|미리보기|축제 일정|행사 일정|첫째 주")
GROUP_NAMES = ["올레걷기축제", "제주감귤박람회", "칠십리축제", "정원문화박람회", "야페스타"]


def group_festivals(items):
    """GROUP_NAMES 중 하나가 제목에 있고 기간이 같은 글을 한 카드로 묶는다. 나머지는 related에 링크로 남긴다."""
    out = list(items)
    for name in GROUP_NAMES:
        key = _norm(name)
        members = [e for e in out if e.get("event_start") and key in _norm(e.get("title") or e.get("post_title"))]
        if len(members) < 2:
            continue
        # 가장 많이 나온 기간을 행사 기간으로 본다
        counts = {}
        for e in members:
            k = (e["event_start"], e.get("event_end"))
            counts[k] = counts.get(k, 0) + 1
        period = max(counts, key=counts.get)
        # 시작일이 행사 기간 안에 있는 글을 같은 행사로 본다 (하루짜리로 잘못 읽힌 글 포함)
        same = sorted([e for e in members if period[0] <= e["event_start"] <= (period[1] or period[0])],
                      key=lambda e: (PRIORITY.get(e.get("source"), 1), bool(ROUNDUP.search(e.get("title") or ""))))
        if len(same) < 2:
            continue
        main, rest = same[0], same[1:]
        main["related"] = [{"title": e.get("title") or e.get("post_title"), "url": e.get("url"), "blog": e.get("blog")}
                           for e in rest]
        ids = {id(e) for e in rest}
        out = [e for e in out if id(e) not in ids]
    return out


def build():
    cfg = load_config()
    out = []
    for e in load_db()["events"]:
        if e.get("hidden") or not is_jeju(e) or is_past(e):  # 제주 이외의 행사는 보여주지 않는다
            continue
        loc = where(e, None)
        out.append({**e, "fit": fit_cfg(e, cfg), "liked": liked(e, cfg), **loc,
                    "zone": zone(loc.get("area")), "big": is_big(e, cfg)})
    out = group_festivals(dedupe(out))
    os.makedirs(DOCS, exist_ok=True)
    shutil.copy(os.path.join(BASE, "index.html"), os.path.join(DOCS, "index.html"))
    with open(os.path.join(DOCS, "events.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    # GitHub Pages가 파일을 그대로 서빙하도록
    open(os.path.join(DOCS, ".nojekyll"), "w").close()
    return len(out)


if __name__ == "__main__":
    print(f"docs/ 생성: 행사 {build()}건")
