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


def _pixabay(query: str, n: int, key: str) -> list[str]:
    r = requests.get("https://pixabay.com/api/", headers=UA, timeout=30,
                     params={"key": key, "q": query, "image_type": "photo", "orientation": "vertical",
                             "safesearch": "true", "per_page": 40, "order": "popular"})
    r.raise_for_status()
    urls = []
    for p in r.json().get("hits", []):
        tags = " " + (p.get("tags") or "").lower() + " "
        if any(w.strip() in tags for w in PEOPLE):
            continue
        urls.append(p.get("largeImageURL") or p["webformatURL"])
        if len(urls) >= n:
            break
    return urls


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


def _search(query: str, n: int) -> list[str]:
    src = photo_source()
    if src == "Pixabay":
        return _pixabay(query, n, os.environ["PIXABAY_KEY"].strip())
    if src == "Pexels":
        return _pexels(query, n, os.environ["PEXELS_KEY"].strip())
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
        have = sorted(folder.glob("*.jpg"))
        if len(have) >= len(queries):
            return have[:len(queries)]
    if folder.exists():
        for f in folder.glob("*"):
            f.unlink()
    folder.mkdir(parents=True, exist_ok=True)
    used, out = set(), []
    for i, q in enumerate(queries[:n]):
        try:
            urls = [u for u in _search(q, 6) if u not in used]
        except Exception as e:  # 열쇠 값은 찍지 않음
            print(f"사진 검색 실패({q}): {type(e).__name__} {getattr(getattr(e, 'response', None), 'status_code', '')}")
            urls = []
        if not urls:
            print(f"'{q}' 사진을 못 찾아서 이 장은 사진 없이 만들어요")
            return []  # 한 장이라도 비면 글과 안 맞는 사진이 섞일 수 있어 전체를 사진 없이
        u = urls[0]
        used.add(u)
        b = requests.get(u, headers=UA, timeout=60)
        b.raise_for_status()
        f = folder / f"{i:02d}.jpg"
        f.write_bytes(b.content)
        out.append(f)
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
