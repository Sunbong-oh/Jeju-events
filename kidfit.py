"""행사가 어린 아이(기본 4~6살)와 함께 가기 좋은지 판정한다: good(추천) / maybe(가능) / no."""
import re

GOOD = re.compile(r"유아|영유아|어린이|아기|키즈|kids|가족|부모|엄마|아빠|그림책|동화|인형극|"
                  r"놀이|미취학|유치원|어린이집|육아|아이(?!디|스|템|콘|돌|폰|패드|러브|언)|자녀|꼬마|동물|토요가족|\(유\s*[,·)]", re.I)
NO = re.compile(r"교직원|교원|워크숍|강사|중학생|고등학생|중·고|중고생|청소년|대학생|성인|어르신|시니어|노인|"
                r"구직|취업|창업|채용|공무원|입찰|소상공인|기업|농가|어업인|초등\s*[3-6]|초등학생|초등(?!\s*[1-2])|"
                r"학부모\s*연수|사춘기|고등|중\s*[,·]\s*고|어린이집\s*대상|기관\s*대상|단체\s*대상|보호자\s*교육|자격|기관\(학교|중등|고교")
# 외국어·학습 과정: 아이 대상이라고 적혀 있지 않으면 제외
LANG = re.compile(r"외국어|영어|일본어|중국어|스페인어|프랑스어|독일어|베트남어|러시아어|회화|토익|토플|JLPT|HSK|"
                  r"온라인콘텐츠|자기주도학습|학습자|수강생|아카데미", re.I)
KID_WORD = re.compile(r"유아|어린이|키즈|kids|아기|영유아|가족|그림책|동화|놀이", re.I)
MAYBE = re.compile(r"축제|페스티벌|페스타|공연|음악회|콘서트|장터|마켓|야시장|체험|전시|문화제|버스킹|빛|불꽃|퍼레이드|투어")
AGE_RANGE = re.compile(r"(\d{1,2})\s*[~\-–]\s*(\d{1,2})\s*세")
AGE_MIN = re.compile(r"(\d{1,2})\s*세\s*이상")
AGE_MAX = re.compile(r"(\d{1,2})\s*세\s*(?:이하|미만)")
MONTHS = re.compile(r"(\d{2,3})\s*개월\s*(?:~\s*(\d{2,3})\s*개월)?")


def _age_ok(text, lo, hi):
    """본문에 나이 조건이 있으면 True/False, 없으면 None. lo~hi세와 겹치면 통과."""
    m = AGE_RANGE.search(text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return a <= hi and b >= lo
    m = MONTHS.search(text)
    if m:
        a = int(m.group(1)) / 12
        b = int(m.group(2)) / 12 if m.group(2) else 99
        return a <= hi and b >= lo
    m = AGE_MIN.search(text)
    if m:
        return int(m.group(1)) <= hi
    m = AGE_MAX.search(text)
    if m:
        return int(m.group(1)) >= lo
    return None


DEFAULT_LIKES = ["음악회", "콘서트", "공연", "버스킹", "뮤지컬", "오케스트라", "합창", "밴드", "가요제", "재즈", "국악", "음악"]


def _like_re(cfg):
    likes = cfg.get("child", {}).get("likes", DEFAULT_LIKES)
    return re.compile("|".join(map(re.escape, likes))) if likes else None


def _text(ev):
    return " ".join(str(ev.get(k) or "") for k in ("title", "info", "snippet", "post_title"))


def fit_cfg(ev, cfg):
    child = cfg.get("child", {})
    return fit(ev, child.get("age_min", 4), child.get("age_max", 6), _like_re(cfg))


def liked(ev, cfg):
    """좋아하는 종류(기본: 음악 공연)의 행사인지 — 🎵 표시용."""
    r = _like_re(cfg)
    return bool(r and r.search(_text(ev)))


def fit(ev, age_min=4, age_max=6, like_re=None):
    if ev.get("fit_override"):
        return ev["fit_override"]
    title = ev.get("title") or ev.get("post_title") or ""
    text = _text(ev)
    is_liked = bool(like_re and like_re.search(text))
    age_ok = _age_ok(text, age_min, age_max)
    if age_ok is not None:
        return "good" if age_ok else "no"
    # 제목에 적힌 대상이 가장 정확하므로 제목 판정을 먼저 한다 ('…(초등~성인)', '교원 워크숍')
    if NO.search(title):
        return "no"
    # 외국어·학습 과정은 유아·어린이 대상이라고 적힌 경우만 남긴다
    if LANG.search(title) and not KID_WORD.search(title):
        return "no"
    if GOOD.search(title):
        return "good"
    # 교육청 예약은 '대상: 유아 학생 …'이 정확하다 — 유아·가족·일반이 없으면 제외
    m = re.search(r"대상:\s*([^·]+)", ev.get("info") or "")
    if m:
        if re.search(r"유아|가족", m.group(1)):
            return "good"
        return ("good" if is_liked else "maybe") if "일반" in m.group(1) else "no"
    # 좋아하는 종류(음악 공연 등)는 아이와 함께 갈 수 있으면 추천으로 올린다
    if is_liked and not NO.search(text):
        return "good"
    if GOOD.search(text):
        return "good"
    if NO.search(text) or LANG.search(text):
        return "no"
    if MAYBE.search(text):
        return "maybe"
    return "no"
