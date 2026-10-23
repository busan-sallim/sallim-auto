"""발행 전 검수 (고정 규칙)

원고는 클로드가 4가지 기준으로 검수하고, 통과하면 원고 파일에 "review" 기록을 남긴다.
  ① 실제로 존재하는 방법인가   ② 법에 걸리지 않는가
  ③ 사람에게 해롭지 않은가      ④ 대중적으로 널리 쓰는 방법인가

이 파일은 그 위에 한 번 더 거는 '자동 안전망'이다. 아래 중 하나라도 걸리면 그 원고는 발행하지 않고 건너뛴다.
  - 검수 기록이 없거나, 4가지 중 하나라도 '통과'가 아님
  - 검수한 뒤에 원고 내용이 바뀜 (다시 검수 필요)
  - 신원이 드러날 수 있는 단어, 과장·의학 효능 표현
  - 섞으면 위험한 세제 조합이 경고 없이 함께 나옴

사용: python scripts/check.py            → 발행 대기 원고 전체 점검
"""
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


def digest(post: dict) -> str:
    body = {k: v for k, v in post.items() if k != "review"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def problems(post: dict) -> list[str]:
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
    if len(post.get("hashtags", [])) > 5:
        out.append("해시태그 5개 초과")
    if post.get("link") and not re.match(r"^https://(link\.)?coupang\.com/", post["link"]):
        out.append("링크가 쿠팡 파트너스 주소가 아님")
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


def stamp(path: str, note: str):
    """클로드가 4가지 기준으로 직접 검수한 뒤에만 쓰는 도장 찍기"""
    p = Path(path)
    post = json.loads(p.read_text(encoding="utf-8"))
    post.pop("review", None)
    post["review"] = {"date": __import__("datetime").date.today().isoformat(), "by": "claude",
                      **{k: "통과" for k in CRITERIA}, "note": note}
    post["review"]["hash"] = digest(post)
    probs = problems(post)
    if probs:
        sys.exit(f"자동 안전망에 걸렸어요: {probs}")
    p.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("검수 도장 완료:", p.name)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--stamp":
        stamp(sys.argv[2], " ".join(sys.argv[3:]) or "수정 없이 통과")
    else:
        main()
