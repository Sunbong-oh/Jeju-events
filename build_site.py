"""GitHub Pages용 보기 전용 사이트(docs/)를 만든다: index.html + events.json(판정·지역 포함).
공개 페이지이므로 집에서의 거리(km)는 넣지 않는다."""
import json
import os
import shutil

from common import BASE, load_config, load_db
from geo import where, zone
from kidfit import fit_cfg, is_big, liked

DOCS = os.path.join(BASE, "docs")


def build():
    cfg = load_config()
    out = []
    for e in load_db()["events"]:
        if e.get("hidden"):
            continue
        loc = where(e, None)
        out.append({**e, "fit": fit_cfg(e, cfg), "liked": liked(e, cfg), **loc,
                    "zone": zone(loc.get("area")), "big": is_big(e, cfg)})
    os.makedirs(DOCS, exist_ok=True)
    shutil.copy(os.path.join(BASE, "index.html"), os.path.join(DOCS, "index.html"))
    with open(os.path.join(DOCS, "events.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    # GitHub Pages가 파일을 그대로 서빙하도록
    open(os.path.join(DOCS, ".nojekyll"), "w").close()
    return len(out)


if __name__ == "__main__":
    print(f"docs/ 생성: 행사 {build()}건")
