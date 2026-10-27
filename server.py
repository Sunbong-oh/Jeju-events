"""행사 목록 웹페이지 (http://127.0.0.1:8765). 추가 설치 없이 파이썬 표준 라이브러리만 사용."""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from collector import collect
from common import BASE, load_config, load_db, save_db, send_telegram
from geo import where
from kidfit import fit_cfg, liked
from notifier import _line

EDITABLE = ("title", "apply_start", "apply_end", "event_start", "event_end", "memo", "hidden", "url", "fit_override")


def _decorate(ev, cfg):
    """화면용: 아이 적합도와 집에서의 거리를 붙인다 (저장하지 않음)."""
    return {**ev, "fit": fit_cfg(ev, cfg), "liked": liked(ev, cfg), **where(ev, cfg["home"])}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(BASE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if self.path == "/api/events":
            cfg = load_config()
            return self._send(200, [_decorate(e, cfg) for e in load_db()["events"]])
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            if self.path == "/api/events":
                ev = {k: None for k in EDITABLE}
                ev.update({k: v for k, v in self._body().items() if k in EDITABLE})
                ev.update(id=f"manual-{int(time.time() * 1000)}", source="manual", blog="직접입력",
                          post_title="", posted=time.strftime("%Y-%m-%d"), snippet="", hidden=False)
                db = load_db()
                db["events"].append(ev)
                save_db(db)
                return self._send(200, ev)
            if self.path == "/api/collect":
                logs = []
                new = collect(logs.append)
                return self._send(200, {"new": len(new), "log": logs})
            if self.path == "/api/test-telegram":
                send_telegram("✅ 제주 행사 알림 연결 테스트입니다.")
                return self._send(200, {"ok": True})
            if self.path.startswith("/api/send/"):
                ev = next(e for e in load_db()["events"] if e["id"] == self.path[10:])
                send_telegram("📌 " + _line(ev))
                return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def do_PUT(self):
        if not self.path.startswith("/api/events/"):
            return self._send(404, {"error": "not found"})
        eid = self.path[len("/api/events/"):]
        patch = {k: v for k, v in self._body().items() if k in EDITABLE}
        db = load_db()
        for ev in db["events"]:
            if ev["id"] == eid:
                ev.update(patch)
                if any(k.startswith(("apply_", "event_")) for k in patch):
                    ev["edited"] = True  # 자동 갱신이 직접 고친 날짜를 덮어쓰지 않게
                save_db(db)
                return self._send(200, _decorate(ev, load_config()))
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    port = load_config()["port"]
    print(f"http://127.0.0.1:{port} 에서 실행 중 (종료: Ctrl+C)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
