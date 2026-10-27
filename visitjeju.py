"""제주관광협회(visitjeju.or.kr) '행사안내' 게시판의 첨부 hwpx(월별 축제·행사 일정표)를 읽는다."""
import datetime as dt
import html
import io
import re
import zipfile

from common import http_get, http_get_bytes

SITE = "https://www.visitjeju.or.kr"
LIST = "/issue/data/event.htm"
DATE_RE = re.compile(r"(?:(20\d{2})\s*년\s*)?(\d{1,2})\s*[월.]\s*(\d{1,2})\s*일?")


def _download(url):
    return http_get_bytes(url, timeout=30)


def latest_posts():
    """최신 글 목록 → 월별로 가장 최근 글 하나씩 [{seq, title, year, month}]"""
    page = html.unescape(http_get(SITE + LIST))
    posts, months = [], set()
    for seq, title in re.findall(r'act=view&seq=(\d+)"[^>]*data-bs-title="([^"]+)"', page):
        m = re.search(r"(20\d{2})\D{1,4}(\d{1,2})\s*월", title)
        if not m:
            continue
        ym = (int(m.group(1)), int(m.group(2)))
        if ym in months:  # 같은 달의 예전 기준일 글은 건너뜀
            continue
        months.add(ym)
        posts.append({"seq": seq, "title": title, "year": ym[0], "month": ym[1]})
    return posts


def hwpx_rows(data):
    """hwpx(zip+XML) 안 표들의 행을 [[셀 텍스트, ...], ...]로 반환."""
    z = zipfile.ZipFile(io.BytesIO(data))
    rows = []
    for name in sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml", n)):
        x = z.read(name).decode("utf-8")
        for tr in re.findall(r"<hp:tr\b.*?</hp:tr>", x, re.S):
            cells = [html.unescape(re.sub(r"<[^>]+>|\s+", " ", " ".join(re.findall(r"<hp:t>(.*?)</hp:t>", tc, re.S)))).strip()
                     for tc in re.findall(r"<hp:tc\b.*?</hp:tc>", tr, re.S)]
            rows.append(cells)
    return rows


def parse_schedule(text, year, month):
    """'07월 04일 ~ 2027년 01월 03일' → (date, date). 연도 없는 날짜는 목록의 연·월로 추정."""
    ds = DATE_RE.findall(text)
    if not ds:
        return None
    (y1, m1, d1), (y2, m2, d2) = ds[0], (ds[1] if len(ds) > 1 else ds[0])
    m1, d1, m2, d2 = int(m1), int(d1), int(m2), int(d2)
    if y1:
        sy = int(y1)
    elif m1 < month - 6 and not (len(ds) > 1 and not y2 and m2 >= m1):
        sy = year + 1  # 12월 목록에 실린 '01월 05일' 같은 경우
    else:
        sy = year
    try:
        start = dt.date(sy, m1, d1)
        end = dt.date(int(y2) if y2 else sy, m2, d2)
    except ValueError:
        return None
    if end < start:
        end = end.replace(year=end.year + 1)
    return start, end


def collect_visitjeju(db, cfg, log=print):
    """월별 최신 일정표를 읽어 db['events']에 추가·갱신. 새 항목 목록 반환."""
    if not cfg.get("visitjeju", {}).get("enabled", True):
        return []
    seen = set(db["seen_posts"])
    by_id = {e["id"]: e for e in db["events"]}
    stale = dt.date.today() - dt.timedelta(days=30)
    new = []
    for post in latest_posts():
        key = f"visitjeju:{post['seq']}"
        if key in seen:
            continue
        view = html.unescape(http_get(f"{SITE}{LIST}?act=view&seq={post['seq']}"))
        files = re.findall(r'act=download&seq=\d+&no=(\d+)"[^>]*>\s*([^<]+?\.hwpx)\s*<', view)
        if not files:
            log(f"[비짓제주] {post['title']}: hwpx 첨부 없음, 건너뜀")
            continue
        url = f"{SITE}{LIST}?act=download&seq={post['seq']}&no={files[0][0]}"
        count = 0
        for cells in hwpx_rows(_download(url)):
            if len(cells) < 3 or "축제명" in cells or "행사명" in cells:
                continue
            name, sched, place = cells[-3:]
            kind = cells[0] if len(cells) >= 4 else ""
            found = parse_schedule(sched, post["year"], post["month"])
            if not name or not found or found[1] < stale:
                continue
            fields = {"title": name, "event_start": found[0].isoformat(), "event_end": found[1].isoformat()}
            info = " · ".join(x for x in (kind, place, sched) if x)
            eid = "vj-" + re.sub(r"\W", "", name)[:40] + "-" + fields["event_start"]
            ev = by_id.get(eid)
            if ev:  # 매주 갱신되는 일정표 — 직접 고친 날짜는 유지
                ev["info"] = info
                if not ev.get("edited"):
                    ev.update(fields)
                continue
            ev = {**fields, "apply_start": None, "apply_end": None, "id": eid,
                  "blog": "비짓제주 행사", "post_title": post["title"],
                  "url": f"{SITE}{LIST}?act=view&seq={post['seq']}",
                  "posted": dt.date.today().isoformat(), "info": info, "snippet": "",
                  "source": "visitjeju", "hidden": False, "memo": ""}
            db["events"].append(ev)
            by_id[eid] = ev
            new.append(ev)
            count += 1
        seen.add(key)
        db["seen_posts"] = sorted(seen)
        log(f"[비짓제주] {post['title']}: 새 행사 {count}건")
    return new
