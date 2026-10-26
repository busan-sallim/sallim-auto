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


def photos(post: dict, stem: str, n: int) -> list[Path]:
    """n장의 사진 파일 경로 (못 구하면 빈 목록 → 사진 없는 디자인으로)"""
    query = post.get("photo")
    if not query:
        return []
    folder = ROOT / "out" / stem / "photos"
    have = sorted(folder.glob("*.jpg"))
    if len(have) >= n:
        return have[:n]
    folder.mkdir(parents=True, exist_ok=True)
    src = photo_source()
    try:
        if src == "Pixabay":
            urls = _pixabay(query, n, os.environ["PIXABAY_KEY"].strip())
        elif src == "Pexels":
            urls = _pexels(query, n, os.environ["PEXELS_KEY"].strip())
        else:
            print("사진 열쇠(PIXABAY_KEY)가 없어서 사진 없이 만들어요.")
            return []
    except Exception as e:  # 사진이 없어도 영상은 만든다 (열쇠 값은 찍지 않음)
        print(f"사진 검색 실패({src}): {type(e).__name__} {getattr(getattr(e, 'response', None), 'status_code', '')}")
        return []
    out = []
    for i, u in enumerate(urls):
        try:
            b = requests.get(u, headers=UA, timeout=60)
            b.raise_for_status()
            f = folder / f"{i:02d}.jpg"
            f.write_bytes(b.content)
            out.append(f)
        except Exception as e:
            print(f"사진 받기 실패: {e}")
    return out


def photo_source() -> str:
    if os.environ.get("PIXABAY_KEY", "").strip():
        return "Pixabay"
    if os.environ.get("PEXELS_KEY", "").strip():
        return "Pexels"
    return ""


def pick_track(used: dict) -> dict | None:
    """music/tracks.json 중 가장 오래전에 쓴(또는 안 쓴) 곡"""
    lst = ROOT / "music" / "tracks.json"
    if not lst.exists():
        return None
    tracks = [t for t in json.loads(lst.read_text(encoding="utf-8"))
              if t.get("use", True) and (ROOT / "music" / t["file"]).exists()]
    if not tracks:
        return None
    tracks.sort(key=lambda t: used.get(t["file"], ""))
    return tracks[0]
