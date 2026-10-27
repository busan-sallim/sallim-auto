"""릴스 재료 가져오기: 사진(펙셀스) · 음악(music/ 폴더)

사진
  - 원고의 "photo" (영어 검색어, 예: "knit sweater") 로 세로 사진을 찾는다.
  - PIXABAY_KEY(깃허브 비밀 보관함)가 있으면 픽사베이 — 무료, 상업적 사용 가능, 출처 표기 의무 없음
    (픽사베이 규칙: 사진은 내려받아 쓰기(링크로 직접 띄우기 금지), 결과는 24시간 저장, 대량 자동 다운로드 금지 → 하루 몇 장이라 괜찮음)
  - 없고 PEXELS_KEY 가 있으면 펙셀스 (2026-10 기준 펙셀스는 새 열쇠 발급 중단)
  - 둘 다 없으면 사진 없이 만든다.
  - 사람 얼굴이 크게 나온 사진은 설명(alt)으로 걸러 낸다.
음악
  - music/tracks.json 에 적힌 곡(사용자가 고른 무료 음원) 중 가장 오래 안 쓴 곡을 고른다.
  - 곡이 없으면 None → reel.py 가 직접 만든 배경음을 쓴다.
"""
import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "sallim-auto/1.0 (household tips reels)"}
PEOPLE = ("woman", "man ", "men ", "person", "people", "girl", "boy", "face", "portrait", "child", "kid", "lady", "guy")


def _pexels(query: str, n: int, key: str) -> list[str]:
    r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key, **UA}, timeout=30,
                     params={"query": query, "orientation": "portrait", "per_page": 40, "size": "large"})
    r.raise_for_status()
    urls = []
    for p in r.json().get("photos", []):
        alt = (p.get("alt") or "").lower() + " "
        if any(w in alt for w in PEOPLE):
            continue
        urls.append(p["src"]["large2x"])
        if len(urls) >= n:
            break
    return urls


STOP = {"a", "an", "the", "in", "on", "of", "with", "and", "for", "at", "to", "inside", "into"}


def _norm(w: str) -> str:
    """복수형을 단수로 (eggs→egg, bottles→bottle, berries→berry, boxes→box, tomatoes→tomato)"""
    w = w.strip().lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
        if w.endswith(("xe", "oe", "she", "che")):
            w = w[:-1]
    return w


def _pixabay(query: str, n: int, key: str, orientation: str = "vertical") -> list[str]:
    """태그가 검색어와 충분히 겹치는 사진만 (고정 규칙: 사진은 그 장의 글과 맞아야 함)
    검색어 낱말의 2/3 이상이 사진 태그에 있어야 통과, 많이 겹치는 순서로 고른다."""
    r = requests.get("https://pixabay.com/api/", headers=UA, timeout=30,
                     params={"key": key, "q": query, "image_type": "photo", "orientation": orientation,
                             "safesearch": "true", "per_page": 100, "order": "popular"})
    r.raise_for_status()
    words = [_norm(w) for w in query.replace(",", " ").split() if w.lower() not in STOP]
    need = max(1, -(-len(words) * 2 // 3))  # 올림(2/3)
    scored = []
    for i, h in enumerate(r.json().get("hits", [])):
        raw = (h.get("tags") or "").lower()
        tags = {_norm(t) for part in raw.split(",") for t in part.split()}
        if any(w.strip() in (" " + raw.replace(",", " ") + " ") for w in PEOPLE):
            continue
        hit = sum(1 for w in words if w in tags)
        if hit >= need:
            scored.append((-hit, i, (h.get("id"), h.get("largeImageURL") or h["webformatURL"])))
    scored.sort()
    return [u for _, _, u in scored[:n]]  # (사진 번호, 주소) — 픽사베이 주소는 요청마다 바뀌어서 번호로 겹침을 막는다


def pixabay_candidates(query: str, n: int = 8, hook: bool = False) -> list[dict]:
    """확인표용 후보: 태그가 검색어와 하나라도 겹치는 사진을 많이 겹치는 순서로 n장 (클로드가 눈으로 고른다)"""
    key = os.environ["PIXABAY_KEY"].strip()
    words = [_norm(w) for w in query.replace(",", " ").split() if w.lower() not in STOP]
    seen, out = set(), []
    for ori in (["vertical", "all"] if hook else ["horizontal", "all"]):
        r = requests.get("https://pixabay.com/api/", headers=UA, timeout=30,
                         params={"key": key, "q": query, "image_type": "photo", "orientation": ori,
                                 "safesearch": "true", "per_page": 100, "order": "popular"})
        r.raise_for_status()
        for i, h in enumerate(r.json().get("hits", [])):
            raw = (h.get("tags") or "").lower()
            if h["id"] in seen or any(w.strip() in (" " + raw.replace(",", " ") + " ") for w in PEOPLE):
                continue
            tags = {_norm(x) for part in raw.split(",") for x in part.split()}
            hit = sum(1 for w in words if w in tags)
            if hit:
                seen.add(h["id"])
                out.append({"score": hit, "order": i, "id": h["id"], "thumb": h.get("webformatURL"), "tags": raw})
        if len(out) >= n:
            break
    out.sort(key=lambda x: (-x["score"], x["order"]))
    return out[:n]


def pixabay_by_id(pid) -> str:
    """사진 번호로 큰 사진 주소 받기 (픽사베이 주소는 시간이 지나면 바뀌어서 번호로 다시 묻는다)"""
    r = requests.get("https://pixabay.com/api/", headers=UA, timeout=30,
                     params={"key": os.environ["PIXABAY_KEY"].strip(), "id": pid})
    r.raise_for_status()
    hits = r.json().get("hits", [])
    return (hits[0].get("largeImageURL") or hits[0]["webformatURL"]) if hits else ""


def photos_by_pick(stem: str, picks: list) -> list:
    """클로드가 확인표에서 고른 사진 번호대로 받기. None 인 장면은 사진 없이"""
    folder = ROOT / "out" / stem / "photos"
    if folder.exists():
        for f in folder.glob("*"):
            f.unlink()
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for i, pid in enumerate(picks):
        if not pid:
            out.append(None)
            continue
        u = pixabay_by_id(pid)
        if not u:
            print(f"[장면 {i}] 사진 {pid} 를 못 받아서 이 장면은 사진 없이")
            out.append(None)
            continue
        b = requests.get(u, headers=UA, timeout=60)
        b.raise_for_status()
        f = folder / f"{i:02d}.jpg"
        f.write_bytes(b.content)
        out.append(f)
    return out


def _openverse(query: str, n: int) -> list[str]:
    r = requests.get("https://api.openverse.org/v1/images/", headers=UA, timeout=30,
                     params={"q": query, "license": "cc0,pdm", "aspect_ratio": "tall", "page_size": 40,
                             "mature": "false"})
    r.raise_for_status()
    urls = []
    for p in r.json().get("results", []):
        title = (p.get("title") or "").lower() + " "
        if any(w in title for w in PEOPLE):
            continue
        urls.append(p["url"])
        if len(urls) >= n:
            break
    return urls


def _search(query: str, n: int, hook: bool = False) -> list[str]:
    """훅(전체 화면)은 세로 사진 먼저, 본문 장(가로 카드)은 가로·세로 모두에서 찾는다"""
    src = photo_source()
    if src == "Pixabay":
        key = os.environ["PIXABAY_KEY"].strip()
        if hook:
            return _pixabay(query, n, key, "vertical") or _pixabay(query, n, key, "all")
        return _pixabay(query, n, key, "horizontal") or _pixabay(query, n, key, "all")
    if src == "Pexels":
        return [(u, u) for u in _pexels(query, n, os.environ["PEXELS_KEY"].strip())]
    return []


def photos(post: dict, stem: str, n: int) -> list[Path]:
    """장면마다 1장 (첫 장 = 훅, 나머지 = 본문 장 순서).
    원고의 "photos" = 장면별 영어 검색어 목록 (고정 규칙: 사진은 그 장의 글 내용과 맞아야 한다).
    없으면 "photo" 하나로 여러 장을 찾는다. 못 구하면 빈 목록 → 사진 없는 디자인."""
    queries = post.get("photos") or ([post["photo"]] * n if post.get("photo") else [])
    if not queries or not photo_source():
        if queries:
            print("사진 열쇠(PIXABAY_KEY)가 없어서 사진 없이 만들어요.")
        return []
    folder = ROOT / "out" / stem / "photos"
    stamp = folder / "queries.json"
    if folder.exists() and stamp.exists() and json.loads(stamp.read_text(encoding="utf-8")) == queries:
        have = [folder / f"{i:02d}.jpg" for i in range(len(queries))]
        return [h if h.exists() else None for h in have]
    if folder.exists():
        for f in folder.glob("*"):
            f.unlink()
    folder.mkdir(parents=True, exist_ok=True)
    used, out = set(), []
    for i, q in enumerate(queries[:n]):
        if not q:  # 검색어를 비워 둔 장면 = 맞는 사진이 없어서 일부러 사진 없이
            out.append(None)
            continue
        try:
            urls = [x for x in _search(q, 10, hook=(i == 0)) if x[0] not in used]
        except Exception as e:  # 열쇠 값은 찍지 않음
            print(f"사진 검색 실패({q}): {type(e).__name__} {getattr(getattr(e, 'response', None), 'status_code', '')}")
            urls = []
        if not urls:
            print(f"[장면 {i}] '{q}' 와 맞는 사진이 없어 이 장면만 사진 없이 만들어요")
            out.append(None)
            continue
        pid, u = urls[0]
        used.add(pid)
        b = requests.get(u, headers=UA, timeout=60)
        b.raise_for_status()
        f = folder / f"{i:02d}.jpg"
        f.write_bytes(b.content)
        out.append(f)
        print(f"[장면 {i}] '{q}' 사진 찾음")
    stamp.write_text(json.dumps(queries, ensure_ascii=False), encoding="utf-8")
    return out


def photo_source() -> str:
    if os.environ.get("PIXABAY_KEY", "").strip():
        return "Pixabay"
    if os.environ.get("PEXELS_KEY", "").strip():
        return "Pexels"
    return ""


def pick_track(last_file: str | None) -> dict | None:
    """music/tracks.json 에서 use=true 인 곡 중 지난번과 다른 곡 (고정 규칙: 1번·2번 번갈아)"""
    lst = ROOT / "music" / "tracks.json"
    if not lst.exists():
        return None
    tracks = [t for t in json.loads(lst.read_text(encoding="utf-8"))
              if t.get("use", True) and (ROOT / "music" / t["file"]).exists()]
    if not tracks:
        return None
    tracks.sort(key=lambda t: t.get("no", 0))
    if last_file:
        nums = [t["file"] for t in tracks]
        if last_file in nums:
            return tracks[(nums.index(last_file) + 1) % len(tracks)]
    return tracks[0]
