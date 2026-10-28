"""네이버 블로그 검색 결과('10월 제주행사' 등)에서 블로그 글 목록을 모은다.
검색 결과 한 쪽은 10개이고, 같은 글이 여러 번 나오므로 블로그 ID·글 번호로 한 번만 센다."""
import datetime as dt
import html
import re
import urllib.parse

from common import http_get

DEFAULT = {"enabled": True, "queries": ["{m}월 제주행사"], "months_ahead": 1, "pages": 2}

# 검색 결과의 글 제목 링크: <a href="https://blog.naver.com/{blogId}/{logNo}" ...>제목</a>
POST_RE = re.compile(r'<a [^>]*href="https://blog\.naver\.com/([\w-]+)/(\d{9,})"[^>]*>(.*?)</a>', re.S)


def parse_results(body, today):
    """검색 결과 HTML → 글 목록. 같은 글은 처음 나온 제목 링크(글 제목)를 쓴다."""
    out = {}
    for m in POST_RE.finditer(body):
        bid, log_no = m.group(1), m.group(2)
        if (bid, log_no) in out:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        title = re.sub(r"\s*새 ?창 열림$", "", title)  # 링크 옆에 붙는 안내 문구
        if len(title) < 6:  # 아이콘·'더보기' 같은 빈 링크는 건너뜀
            continue
        out[(bid, log_no)] = {
            "blog_id": bid, "log_no": log_no, "title": title, "category": "", "desc": "",
            "link": f"https://blog.naver.com/{bid}/{log_no}", "pub_date": today,
        }
    return list(out.values())


def search_posts(cfg, log=print, today=None):
    """'이번 달'부터 months_ahead개월 뒤까지 검색어별로 pages쪽씩 읽는다."""
    today = today or dt.date.today()
    found = {}
    for i in range(cfg.get("months_ahead", 1) + 1):
        month = (today.month - 1 + i) % 12 + 1
        for tpl in cfg.get("queries", DEFAULT["queries"]):
            q = tpl.format(m=month)
            before = len(found)
            for page in range(cfg.get("pages", 2)):
                url = "https://search.naver.com/search.naver?" + urllib.parse.urlencode(
                    {"where": "blog", "query": q, "start": 1 + 10 * page})
                try:
                    posts = parse_results(http_get(url), today)
                except Exception as e:  # 검색이 실패해도 블로그 수집은 계속한다
                    log(f"[네이버 검색] '{q}' {page + 1}쪽 읽기 실패: {e}")
                    break
                if not posts:
                    break
                for p in posts:
                    found.setdefault((p["blog_id"], p["log_no"]), p)
            log(f"[네이버 검색] '{q}': 새 글 {len(found) - before}개")
    return list(found.values())
