"""제주관광협회(visitjeju.or.kr) '행사안내' 게시판의 첨부 hwpx(월별 축제·행사 일정표)를 읽는다."""
import datetime as dt
import html
import io
import re
import zipfile

from common import http_get, http_get_bytes
from hwp_table import hwp_rows

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
        files = re.findall(r'act=download&seq=\d+&no=(\d+)"[^>]*>\s*([^<]+?\.(?:hwpx|hwp))\s*<', view)
        if not files:
            log(f"[비짓제주] {post['title']}: 일정표(hwp·hwpx) 첨부 없음, 건너뜀")
            continue
        # 축제 일정표를 고른다 (주요행사 현황표는 열 구성이 달라서 건너뜀). 없으면 첫 첨부
        no, name = next((f for f in files if "축제" in f[1]), files[0])
        url = f"{SITE}{LIST}?act=download&seq={post['seq']}&no={no}"
        raw = _download(url)
        rows = hwp_rows(raw) if name.lower().endswith(".hwp") else hwpx_rows(raw)
        count = 0
        for cells in rows:
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


# ── 공지사항 게시판: 행사성 공지(예: 축제 개최 안내)의 본문에서 날짜를 읽는다 ──
NOTICE_LIST = "/comm/notice.htm"
NOTICE_EVENT_KW = re.compile(r"축제|페스티벌|행사|공연|콘서트|음악|뮤직|박람회|전시|개최")
NOTICE_SKIP_KW = re.compile(r"공고|모집|채용|지원|인사|표창|입찰|계약|설명회|사업자")
# '11. 7.( 토 )' 같은 날짜 (월 생략 가능: '8.( 일 )')
NOTICE_DATE = re.compile(r"(?:(\d{1,2})\s*\.\s*)?(\d{1,2})\s*\.\s*\(\s*[월화수목금토일]\s*\)")
NOTICE_CTX = re.compile(r"개최|열립|열리|진행|일시|기간|운영")


def notice_posts():
    """공지사항 첫 페이지 → [{seq, title, posted}]"""
    page = html.unescape(http_get(SITE + NOTICE_LIST))
    out = []
    for seq, title, ymd in re.findall(
            r'seq=(\d+)"[^>]*data-bs-title="([^"]+)".*?<td colspan="1">(\d{4}\.\d{2}\.\d{2})</td>', page, re.S):
        out.append({"seq": seq, "title": title, "posted": dt.datetime.strptime(ymd, "%Y.%m.%d").date()})
    return out


def notice_event(seq, title, posted):
    """공지 본문 → {event_start, event_end, body}. 행사 기간을 못 찾으면 None."""
    view = html.unescape(http_get(f"{SITE}{NOTICE_LIST}?act=view&seq={seq}"))
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", view, flags=re.S)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
    start = text.find("조회:")
    end = text.find("공유", start + 1) if start >= 0 else -1
    body = text[start + 5:end] if start >= 0 and end > start else text
    toks = [(m.start(), m.group(1), int(m.group(2))) for m in NOTICE_DATE.finditer(body)]
    if not toks:
        return None
    # 행사 기간을 말하는 첫 날짜(주변에 개최·일시·기간 등)에서 시작해, 바로 이어지는 '~ 8.( 일 )'까지 끝으로 본다
    k = next((i for i, (pos, _, _) in enumerate(toks)
              if NOTICE_CTX.search(body[max(0, pos - 40):pos + 40])), 0)
    _, mo, d = toks[k]
    sm, sd = int(mo) if mo else posted.month, d
    em, ed, last = sm, sd, toks[k][0]
    for pos, mo2, d2 in toks[k + 1:]:
        if pos - last > 25:
            break
        em, ed, last = (int(mo2) if mo2 else em), d2, pos
    try:
        y = posted.year + (1 if sm < posted.month - 6 else 0)
        start_d = dt.date(y, sm, sd)
        end_d = dt.date(y, em, ed)
    except ValueError:
        return None
    if end_d < start_d:
        end_d = start_d
    return {"event_start": start_d, "event_end": end_d, "body": body}


def collect_visitjeju_notices(db, cfg, log=print):
    """행사성 공지를 읽어 db['events']에 추가. 새 항목 목록 반환."""
    if not cfg.get("visitjeju", {}).get("enabled", True):
        return []
    seen = set(db["seen_posts"])
    by_id = {e["id"]: e for e in db["events"]}
    stale = dt.date.today() - dt.timedelta(days=30)
    new = []
    for post in notice_posts():
        if not NOTICE_EVENT_KW.search(post["title"]) or NOTICE_SKIP_KW.search(post["title"]):
            continue
        key = f"visitjeju-notice:{post['seq']}"
        if key in seen:
            continue
        seen.add(key)  # 날짜를 못 찾은 공지도 매일 다시 열지 않도록 표시
        found = notice_event(post["seq"], post["title"], post["posted"])
        if not found or found["event_end"] < stale:
            log(f"[비짓제주 공지] {post['title']}: 행사 날짜를 찾지 못함")
            continue
        s = found["event_start"].isoformat()
        eid = f"vjn-{post['seq']}-{s}"
        if eid in by_id:
            continue
        ev = {"title": post["title"][:80], "event_start": s, "event_end": found["event_end"].isoformat(),
              "apply_start": None, "apply_end": None, "id": eid, "blog": "비짓제주 공지",
              "post_title": post["title"], "url": f"{SITE}{NOTICE_LIST}?act=view&seq={post['seq']}",
              "posted": post["posted"].isoformat(), "info": "", "snippet": found["body"][:600],
              "source": "visitjeju", "hidden": False, "memo": ""}
        db["events"].append(ev)
        by_id[eid] = ev
        new.append(ev)
        log(f"[비짓제주 공지] 새 행사: {post['title']} ({s} ~ {ev['event_end']})")
    db["seen_posts"] = sorted(seen)
    return new
