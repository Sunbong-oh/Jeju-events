"""HWP 5.x(구형 한글) 파일의 표를 [[셀 텍스트, ...], ...] 행 목록으로 읽는다. 외부 라이브러리 없이 olefile만 쓴다."""
import io
import struct
import zlib

TAG_PARA_TEXT = 67   # HWPTAG_BEGIN(16) + 51
TAG_LIST_HEADER = 72  # 표 셀(문단 목록) 시작


def _records(data):
    pos = 0
    while pos + 4 <= len(data):
        (hdr,) = struct.unpack_from("<I", data, pos)
        tag, level, size = hdr & 0x3FF, (hdr >> 10) & 0x3FF, (hdr >> 20) & 0xFFF
        pos += 4
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", data, pos)
            pos += 4
        yield tag, level, data[pos:pos + size]
        pos += size


def _text(payload):
    out, i = [], 0
    n = len(payload) // 2
    while i < n:
        code = struct.unpack_from("<H", payload, i * 2)[0]
        i += 1
        if code in (10, 13):          # 줄바꿈·문단 끝
            out.append(" ")
        elif code < 32:               # 인라인·확장 컨트롤: 뒤의 7글자는 값이므로 건너뛴다 (24~31은 한 글자)
            if code in (0,) or code >= 24:
                continue
            i += 7
        else:
            out.append(chr(code))
    return "".join(out)


def hwp_rows(data):
    """hwp 파일 바이트 → 표의 행 목록. 같은 행 주소의 셀끼리 묶고, 셀 안의 문단 글을 이어 붙인다."""
    import olefile  # 협회 hwp 일정표를 읽을 때만 필요하다 (없어도 다른 수집은 돌아간다)
    ole = olefile.OleFileIO(io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data)
    try:
        flags = struct.unpack_from("<I", ole.openstream("FileHeader").read(), 36)[0]
        compressed = bool(flags & 1)
        cells = []                    # (행 주소, 열 주소, 텍스트)
        cur = None                    # 지금 읽는 셀: [level, row, col, texts]
        sections = sorted(
            (s for s in ole.listdir() if s[0] == "BodyText" and s[1].startswith("Section")),
            key=lambda s: int(s[1][7:]))
        for s in sections:
            raw = ole.openstream(s).read()
            body = zlib.decompress(raw, -15) if compressed else raw
            for tag, level, payload in _records(body):
                if tag == TAG_LIST_HEADER:
                    if cur:
                        cells.append((cur[1], cur[2], "".join(cur[3]).strip()))
                    # 문단 수(4) 다음 속성(4) 뒤에 열 주소(2), 행 주소(2)
                    col, row = struct.unpack_from("<HH", payload, 8) if len(payload) >= 12 else (0, 0)
                    cur = [level, row, col, []]
                elif tag == TAG_PARA_TEXT and cur and level > cur[0]:
                    cur[3].append(_text(payload))
                elif cur and level < cur[0]:
                    cells.append((cur[1], cur[2], "".join(cur[3]).strip()))
                    cur = None
        if cur:
            cells.append((cur[1], cur[2], "".join(cur[3]).strip()))
    finally:
        ole.close()
    rows, last = [], None
    for row, col, text in cells:
        if not rows or row != last:
            rows.append([])
            last = row
        rows[-1].append(text)
    return rows
