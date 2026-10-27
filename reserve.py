"""제주교육청 통합예약시스템(org.jje.go.kr/reserve) 목록에서 운영기간·접수기간을 수집한다."""
import datetime as dt
import html
import re

from common import http_get

SITE = "https://org.jje.go.kr"
CATEGORIES = {
    "견학/체험": "/jjeExperience/list.jje?menuCd=DOM_000000501001000000",
    "교육/강좌": "/jjeEducation/list.jje?menuCd=DOM_000000502001000000",
    "공연/행사": "/jjeEvent/list.jje?menuCd=DOM_000000503001000000",
    "시설대관": "/jjeFacility/list.jje?menuCd=DOM_000000505001000000",
}
DEFAULT = {"categories": ["견학/체험", "교육/강좌", "공연/행사"], "max_pages": 20, "targets_any": []}

ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:\s+(\d{1,2}:\d{2}))?\s*~\s*(\d{4}-\d{2}-\d{2})(?:\s+(\d{1,2}:\d{2}))?")


def _text(cell):
    t = re.sub(r"<br\s*/?>", " ", cell)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", t))).strip()


def parse_list(page):
    """목록 페이지 → [{sid, url, org, title, event, apply, targets, status}]"""
    items = []
    for row in ROW_RE.findall(page):
        cells = CELL_RE.findall(row)
        if len(cells) < 7 or "href" not in cells[2]:
            continue
        href = html.unescape(re.search(r'href="([^"]+)"', cells[2]).group(1))
        sid = re.search(r"Sid=(\w+)|facltId=(\w+)", href)
        ev, ap = RANGE_RE.search(_text(cells[3])), RANGE_RE.search(_text(cells[4]))
        items.append({
            "sid": next(g for g in sid.groups() if g) if sid else href,
            "url": SITE + href,
            "org": _text(cells[1]),
            "title": _text(cells[2]),
            "event": ev.groups() if ev else None,
            "apply": ap.groups() if ap else None,
            "targets": _text(cells[5]),
            "status": _text(cells[6]),
        })
    return items


def collect_reserve(db, cfg, log=print):
    """db['events']에 새 항목은 추가하고 기존 항목은 날짜·상태를 갱신한다. 새 항목 목록 반환."""
    rcfg = {**DEFAULT, **cfg.get("reserve", {})}
    if not rcfg.get("enabled", True):
        return []
    by_id = {e["id"]: e for e in db["events"]}
    stale = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    want = rcfg["targets_any"]
    new = []
    for cat in rcfg["categories"]:
        path = CATEGORIES.get(cat)
        if not path:
            log(f"[예약] 알 수 없는 분류: {cat}")
            continue
        for page_no in range(1, rcfg["max_pages"] + 1):
            try:
                items = parse_list(http_get(f"{SITE}{path}&startPage={page_no}"))
            except Exception as e:
                log(f"[예약] {cat} {page_no}쪽 읽기 실패: {e}")
                break
            if not items:
                break
            for it in items:
                if want and not any(t in it["targets"] for t in want):
                    continue
                if it["event"] and it["event"][2] < stale:
                    continue  # 한 달 이상 지난 행사는 건너뜀
                fields = {
                    "title": it["title"],
                    "apply_start": it["apply"][0] if it["apply"] else None,
                    "apply_end": it["apply"][2] if it["apply"] else None,
                    "apply_end_time": it["apply"][3] if it["apply"] else None,
                    "event_start": it["event"][0] if it["event"] else None,
                    "event_end": it["event"][2] if it["event"] else None,
                }
                info = f"{it['org']} · 대상: {it['targets']} · {it['status']}"
                eid = f"jje-{it['sid']}"
                ev = by_id.get(eid)
                if ev:  # 기존 항목: 사용자가 직접 고친 날짜는 건드리지 않음
                    ev["info"] = info
                    if not ev.get("edited"):
                        ev.update(fields)
                    continue
                ev = {**fields, "id": eid, "blog": f"교육청 예약 · {cat}", "post_title": it["title"],
                      "url": it["url"], "posted": dt.date.today().isoformat(), "info": info,
                      "snippet": "", "source": "jje", "hidden": False, "memo": ""}
                db["events"].append(ev)
                by_id[eid] = ev
                new.append(ev)
            # 목록은 최신순 — 페이지 전체가 오래된 행사면 더 볼 필요 없음
            if all(i["event"] and i["event"][2] < stale for i in items):
                break
        log(f"[예약] {cat}: 새 항목 {sum(1 for e in new if e['blog'].endswith(cat))}건")
    return new
