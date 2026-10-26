"""발행 전 검수 (고정 규칙)

원고는 클로드가 4가지 기준으로 검수하고, 통과하면 원고 파일에 "review" 기록을 남긴다.
  ① 실제로 존재하는 방법인가   ② 법에 걸리지 않는가
  ③ 사람에게 해롭지 않은가      ④ 대중적으로 널리 쓰는 방법인가

이 파일은 그 위에 한 번 더 거는 '자동 안전망'이다. 아래 중 하나라도 걸리면 그 원고는 발행하지 않고 건너뛴다.
  - 검수 기록이 없거나, 4가지 중 하나라도 '통과'가 아님
  - 검수한 뒤에 원고 내용이 바뀜 (다시 검수 필요)
  - 신원이 드러날 수 있는 단어, 과장·의학 효능 표현
  - 섞으면 위험한 세제 조합이 경고 없이 함께 나옴

그리고 발행 전날 밤, 클로드가 실제 카드 이미지를 직접 열어 보고 '최종 확인 도장(final_check)'을 찍는다.
최종 확인 도장이 없으면 절대 발행하지 않는다 (고정 규칙).

막는 것(발행 안 함): 위 항목 + 최종 확인 없음 + 카드 글자 넘침 + 수수료 문구 규칙 위반
경고만(발행은 하고 메일): 주제 중복, 스팸성 해시태그, 쿠팡 링크 접속 안 됨

사용:
  python scripts/check.py                           발행 대기 원고 전체 점검
  python scripts/check.py --stamp 파일 "메모"        1차 검수 도장 (4가지 기준 확인 뒤)
  python scripts/check.py --final 파일 "메모"        최종 확인 도장 (카드 이미지를 직접 본 뒤)
"""
import datetime
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CRITERIA = {"real_method": "실제 방법", "legal": "법 위반 없음", "safe": "인체 무해", "common_practice": "대중적 방법"}

# 겸업 규정 때문에 신원이 드러나면 안 되는 단어 (브랜드명 '부산여자 살림코칭'은 예외)
IDENTITY_WORDS = ["간호사", "병원", "병동", "교직원"]
# 표시광고법·의료법에 걸릴 수 있는 과장·효능 표현
HYPE_WORDS = ["100%", "99%", "99.9", "완벽 제거", "무조건", "완치", "치료", "살균력", "멸균", "의사 추천", "식약처 인증"]
# 함께 쓰면 유독가스가 생기는 조합 (같은 장에 나오면 '섞지' 같은 경고가 있어야 함)
CHLORINE = ["락스", "염소"]
DANGER_PARTNERS = ["구연산", "식초", "산성", "암모니아", "알코올", "과탄산"]
WARN_WORDS = ["섞", "같이 쓰지", "함께 쓰지", "같은 날", "가스"]


STAMPS = ("review", "final_check", "photo", "photos")  # photo = 릴스 사진 검색어 (글 내용이 아니라서 도장과 무관)
BANNED_TAGS_FILE = ROOT / "banned_hashtags.txt"


def digest(post: dict) -> str:
    body = {k: v for k, v in post.items() if k not in STAMPS}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def overflow(post: dict) -> list[str]:
    """카드 글자가 아래 표시(넘겨보세요·쪽번호)와 겹치는지 미리 계산"""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import render as R
        from PIL import Image, ImageDraw
    except Exception:
        return []  # 그림 도구가 없는 곳에선 건너뜀 (깃허브에선 항상 있음)
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    out = []
    top = R.COVER_TITLE_Y_LINK if post.get("link") else R.COVER_TITLE_Y
    y = top + len(R.wrap(d, post["title"], R.font("Black", 108), R.W - 180)) * 130
    if post.get("subtitle"):
        y += 40 + len(R.wrap(d, post["subtitle"], R.font("Medium", 46), R.W - 180)) * 62
    if y > R.H - 210:
        out.append("표지 글자가 넘쳐요 (제목·부제를 줄여 주세요)")
    for i, sl in enumerate(post.get("slides", []), 1):
        y = 330 + len(R.wrap(d, sl["head"], R.font("Black", 72), R.W - 180)) * 90 + 90
        y += len(R.wrap(d, sl["body"], R.font("Medium", 46), R.W - 180)) * 72
        if y > R.H - 130:
            out.append(f"{i}번째 본문 카드 글자가 넘쳐요")
    return out


def problems(post: dict, need_final: bool = True) -> list[str]:
    out = []
    rv = post.get("review") or {}
    if not rv:
        out.append("검수 기록 없음")
    else:
        for key, name in CRITERIA.items():
            if rv.get(key) != "통과":
                out.append(f"검수 미통과: {name}")
        if rv.get("hash") != digest(post):
            out.append("검수 뒤에 내용이 바뀜 (다시 검수 필요)")
    if need_final:
        fc = post.get("final_check") or {}
        if not fc:
            out.append("클로드 최종 확인 없음 (발행 전날 밤 최종 확인 필요)")
        elif fc.get("hash") != digest(post):
            out.append("최종 확인 뒤에 내용이 바뀜 (다시 확인 필요)")

    texts = [post.get("title", ""), post.get("subtitle", ""), post.get("caption", "")]
    for sl in post.get("slides", []):
        texts += [sl.get("head", ""), sl.get("body", "")]
    whole = " ".join(texts).replace("부산여자 살림코칭", "")
    for w in IDENTITY_WORDS:
        if w in whole:
            out.append(f"신원 노출 위험 단어: {w}")
    for w in HYPE_WORDS:
        if w in whole:
            out.append(f"과장·효능 표현: {w}")
    # 문장마다 따로 본다: 한 문장에 락스와 산성 세제가 같이 나오면 그 문장 안에 경고가 있어야 함
    for t in texts:
        for sent in re.split(r"(?<=[.!?요])\s+|\n", t):
            if any(c in sent for c in CHLORINE) and any(d in sent for d in DANGER_PARTNERS):
                if not any(k in sent for k in WARN_WORDS):
                    out.append("위험한 세제 조합이 경고 없이 나옴: " + sent[:40])

    n = len(post.get("slides", []))
    if not 3 <= n <= 8:
        out.append(f"본문 장수 {n}장 (3~8장이어야 함)")
    tags = post.get("hashtags", [])
    if len(tags) > (4 if post.get("link") else 5):
        out.append("해시태그 초과 (쿠팡 링크 글은 #광고 포함 5개라 4개까지)")
    out += overflow(post)
    if post.get("link") and not re.match(r"^https://(link\.)?coupang\.com/", post["link"]):
        out.append("링크가 쿠팡 파트너스 주소가 아님")
    if post.get("link") and not post.get("product"):
        out.append("링크 글인데 제품 이름(product)이 없음")
    return out


def warnings(post: dict, stem: str, log: dict) -> list[str]:
    """발행은 막지 않지만 메일로 알려 줄 것"""
    out = []
    # 주제 중복: 최근 발행 30개와 제목이 많이 비슷한지
    recent = sorted(log, key=lambda k: log[k].get("date", ""))[-30:]
    for k in recent:
        f = ROOT / "content" / f"{k}.json"
        if k == stem or not f.exists():
            continue
        old = json.loads(f.read_text(encoding="utf-8"))
        if difflib.SequenceMatcher(None, old.get("title", ""), post.get("title", "")).ratio() > 0.6:
            out.append(f"주제 중복 의심: {k} 와 제목이 비슷해요")
    # 스팸성·금지 해시태그
    if BANNED_TAGS_FILE.exists():
        banned = {l.strip().lstrip("#") for l in BANNED_TAGS_FILE.read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.startswith("//")}
        for t in post.get("hashtags", []):
            if t.lstrip("#") in banned:
                out.append(f"쓰면 노출이 줄 수 있는 해시태그: #{t}")
    # 쿠팡 링크가 살아 있는지 (쿠팡이 로봇 접속을 막으면 확인 불가로 넘어감)
    if post.get("link"):
        try:
            import requests
            r = requests.get(post["link"], timeout=20, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code in (404, 410):
                out.append("쿠팡 링크가 없어졌어요 (상품 삭제·만료)")
        except Exception:
            pass
    return out


def main():
    log_path = ROOT / "published.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    bad = 0
    for p in sorted((ROOT / "content").glob("*.json")):
        rec = log.get(p.stem, {})
        if rec.get("instagram") and rec.get("threads"):
            continue
        probs = problems(json.loads(p.read_text(encoding="utf-8")))
        print(("❌ " if probs else "✅ ") + p.stem + ("" if not probs else " — " + " / ".join(probs)))
        bad += bool(probs)
    sys.exit(1 if bad else 0)


def stamp(path: str, note: str, final: bool = False):
    """--stamp: 4가지 기준 검수 뒤 / --final: 실제 카드 이미지를 직접 열어 본 뒤"""
    p = Path(path)
    post = json.loads(p.read_text(encoding="utf-8"))
    key = "final_check" if final else "review"
    if final and not post.get("review"):
        sys.exit("1차 검수 도장이 먼저 있어야 해요")
    if not final:
        post.pop("final_check", None)  # 내용을 다시 검수하면 최종 확인도 새로 받아야 함
    rec = {"date": datetime.date.today().isoformat(), "by": "claude"}
    if not final:
        rec.update({k: "통과" for k in CRITERIA})
    rec["note"] = note
    post[key] = rec
    rec["hash"] = digest(post)
    probs = problems(post, need_final=final)
    if probs:
        sys.exit(f"자동 안전망에 걸렸어요: {probs}")
    p.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(("최종 확인" if final else "검수") + " 도장 완료:", p.name)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] in ("--stamp", "--final"):
        stamp(sys.argv[2], " ".join(sys.argv[3:]) or "수정 없이 통과", final=sys.argv[1] == "--final")
    else:
        main()
