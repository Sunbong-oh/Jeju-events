"""네이버 블로그 RSS에서 '오늘의 제주소식' 글을 모아 행사별 신청일·행사일을 추출한다."""
import datetime as dt
import html
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from common import http_get, load_config, load_db, save_db
from reserve import collect_reserve
from visitjeju import collect_visitjeju
from kidfit import fit_cfg

APPLY_KW = ("신청", "접수", "모집", "응모", "예약", "등록")
EVENT_KW = ("일시", "기간", "행사", "축제", "개최", "일정", "운영", "공연", "교육", "날짜", "때")

# 항목 구분 기호: 디지스트형 글을 행사별로 쪼갤 때 사용
ITEM_START = re.compile(r"^\s*(?:[■□◆◇▶▷●○◎★☆♣♠✔✅📌📍🔹🔸•▪]|\d{1,2}\s*[.)]\s|[①-⑳]|[\[【<〈])")
# '▶ 신청기간 : ...' 같은 세부 항목 줄은 새 행사로 쪼개지 않는다
FIELD_LINE = re.compile(r"^\W*\s*[가-힣A-Za-z ]{1,10}[:：]")

D_FULL = r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*일?"
D_MD = r"(\d{1,2})\s*월\s*(\d{1,2})\s*일|(\d{1,2})\s*[./]\s*(\d{1,2})\s*\.?(?=\s*\(|\s*[~∼\-–]|\s*\.|\s|$)"
WEEKDAY = r"\s*(?:\([월화수목금토일]\)|[월화수목금토일]요일)?\.?"
DATE = rf"(?:{D_FULL}|{D_MD}){WEEKDAY}(?:\s*\d{{1,2}}\s*[:시]\s*\d{{0,2}}분?)?"
DATE_RE = re.compile(DATE)
RANGE_RE = re.compile(rf"(?P<a>{DATE})\s*[~∼\-–부터]+\s*(?:(?P<b>{DATE})|(?P<day>\d{{1,2}})\s*일)")


def _to_date(m, base):
    g = m.groups()
    try:
        if g[0]:
            return dt.date(int(g[0]), int(g[1]), int(g[2]))
        mo, d = (g[3], g[4]) if g[3] else (g[5], g[6])
        mo, d = int(mo), int(d)
        y = base.year
        # 연도 없는 날짜: 글 작성월보다 6개월 이상 앞서면 다음 해로 본다
        if mo < base.month - 6:
            y += 1
        elif mo > base.month + 6:
            y -= 1
        return dt.date(y, mo, d)
    except (ValueError, TypeError):
        return None


def parse_dates(line, base):
    """line에서 (시작, 끝) 날짜를 찾는다. 없으면 None."""
    r = RANGE_RE.search(line)
    if r:
        s = _to_date(DATE_RE.match(r.group("a")), base)
        if r.group("b"):
            e = _to_date(DATE_RE.match(r.group("b")), s or base)
        elif s and r.group("day"):
            try:
                e = s.replace(day=int(r.group("day")))
            except ValueError:
                e = None
        else:
            e = None
        if s:
            return s, (e if e and e >= s else s)
    m = DATE_RE.search(line)
    if m:
        d = _to_date(m, base)
        if d:
            return d, d
    return None


def extract_events(text, base, skip_kw="제주소식"):
    """글 본문을 항목별로 나눠 [{title, apply_start, apply_end, event_start, event_end, snippet}] 반환."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    chunks, cur = [], []
    for l in lines:
        if ITEM_START.match(l) and not FIELD_LINE.match(l) and cur:
            chunks.append(cur)
            cur = []
        cur.append(l)
    if cur:
        chunks.append(cur)

    out = []
    for ch in chunks:
        ev = {"apply_start": None, "apply_end": None, "event_start": None, "event_end": None}
        for l in ch:
            found = parse_dates(l, base)
            if not found:
                continue
            kind = "apply" if any(k in l for k in APPLY_KW) else "event"
            if ev[f"{kind}_start"] is None:
                ev[f"{kind}_start"], ev[f"{kind}_end"] = (d.isoformat() for d in found)
        if not (ev["apply_start"] or ev["event_start"]):
            continue
        if skip_kw and skip_kw in ch[0].replace(" ", "") and len(ch) == 1:
            continue  # '오늘의 제주소식 (10월 27일)' 같은 글 머리줄
        title = re.sub(r"^\s*(?:[■□◆◇▶▷●○◎★☆♣♠✔✅📌📍🔹🔸•▪]|\d{1,2}\s*[.)]|[①-⑳])\s*", "", ch[0])
        title = title.strip("[]【】<>〈〉 ")[:80]
        ev["title"] = title
        ev["snippet"] = "\n".join(ch)[:600]
        out.append(ev)
    return out


class _BodyText(HTMLParser):
    """스마트에디터 본문(se-main-container / postViewArea)의 텍스트만 뽑는다."""
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "span"}

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.depth:
            if tag == "div":
                self.depth += 1
            if tag in self.BLOCK and tag != "span":
                self.parts.append("\n")
        elif tag == "div" and ("se-main-container" in (a.get("class") or "")
                               or a.get("id") == "postViewArea"):
            self.depth = 1

    def handle_endtag(self, tag):
        if self.depth and tag == "div":
            self.depth -= 1
            self.parts.append("\n")
        elif self.depth and tag == "p":
            self.parts.append("\n")

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)

    def text(self):
        t = "".join(self.parts).replace("​", "")
        return re.sub(r"\n\s*\n+", "\n", t)


def fetch_post_text(blog_id, log_no):
    page = http_get(f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}")
    p = _BodyText()
    p.feed(page)
    return p.text()


def fetch_rss(blog_id):
    xml = http_get(f"https://rss.blog.naver.com/{blog_id}.xml")
    root = ET.fromstring(xml)
    items = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        m = re.search(r"/(\d{9,})", link)
        if not m:
            continue
        pub = it.findtext("pubDate") or ""
        try:
            pub_d = dt.datetime.strptime(pub[:25].strip(), "%a, %d %b %Y %H:%M:%S").date()
        except ValueError:
            pub_d = dt.date.today()
        items.append({
            "log_no": m.group(1),
            "title": html.unescape(it.findtext("title") or "").strip(),
            "category": (it.findtext("category") or "").strip(),
            "link": f"https://blog.naver.com/{blog_id}/{m.group(1)}",
            "pub_date": pub_d,
            "desc": html.unescape(re.sub(r"<[^>]+>", "\n", it.findtext("description") or "")),
        })
    return items


def _matches(post, keywords):
    hay = (post["category"] + post["title"]).replace(" ", "")
    return not keywords or any(k.replace(" ", "") in hay for k in keywords)


def collect(log=print):
    """설정된 모든 블로그에서 새 글을 수집해 DB에 추가하고, 새로 추가된 행사 목록을 반환."""
    cfg = load_config()
    db = load_db()
    seen = set(db["seen_posts"])
    new_events = []
    for blog in cfg["blogs"]:
        bid = blog["blog_id"]
        try:
            posts = fetch_rss(bid)
        except Exception as e:
            log(f"[{bid}] RSS 읽기 실패: {e}")
            continue
        for post in posts:
            key = f"{bid}:{post['log_no']}"
            if key in seen or not _matches(post, blog.get("keywords", [])):
                continue
            try:
                text = fetch_post_text(bid, post["log_no"]) or post["desc"]
            except Exception as e:  # 본문을 못 읽으면 RSS 요약으로 대체
                log(f"[{bid}] 본문 읽기 실패({post['log_no']}): {e}")
                text = post["desc"]
            found = extract_events(text, post["pub_date"])
            if not found:  # 날짜를 못 찾아도 아이에게 맞을 만한 글은 남겨서 웹에서 직접 입력할 수 있게 한다
                stub = {"title": post["title"], "snippet": text[:600], "apply_start": None,
                        "apply_end": None, "event_start": None, "event_end": None}
                found = [stub] if fit_cfg(stub, cfg) != "no" else []
            for i, ev in enumerate(found):
                ev.update({
                    "id": f"{bid}-{post['log_no']}-{i}",
                    "blog": blog.get("name", bid),
                    "post_title": post["title"],
                    "url": post["link"],
                    "posted": post["pub_date"].isoformat(),
                    "source": "auto",
                    "hidden": False,
                    "memo": "",
                })
                db["events"].append(ev)
                new_events.append(ev)
            seen.add(key)
            log(f"[{bid}] 수집: {post['title']} → {len(found)}건")
    db["seen_posts"] = sorted(seen)
    for extra in (collect_reserve, collect_visitjeju):
        try:
            new_events += extra(db, cfg, log)
        except Exception as e:  # 한 출처가 실패해도 나머지는 저장
            log(f"{extra.__name__} 실패: {e}")
    save_db(db)
    return new_events


if __name__ == "__main__":
    n = collect()
    print(f"새 행사 {len(n)}건")
