"""분석 담당 — 인스타·스레드 통계 모으기

하는 일
  1) 권한 확인 (--check): 토큰에 '통계 보기' 권한이 있는지만 살펴본다. 아무것도 저장하지 않는다.
  2) 수집 (기본): 최근 30일 안에 올린 게시물의 반응과 팔로워 수를 모아 stats/ 폴더에 저장한다.
       stats/posts.json      게시물별 최신 숫자 (조회·도달·좋아요·댓글·저장·공유 등)
       stats/followers.csv   날마다 팔로워 수 한 줄씩
       stats/report.md       사람이 읽는 요약 (반응 좋은 글 순위, 주제별 평균, 쿠팡 링크 클릭)

필요한 권한
  인스타: instagram_business_basic + instagram_business_manage_insights
  스레드: threads_basic + threads_manage_insights
토큰은 깃허브 비밀 보관함(IG_TOKEN, THREADS_TOKEN)에서만 받는다. 화면·파일에 절대 찍지 않는다.
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "published.json"
STATS = ROOT / "stats"
IG_API = "https://graph.instagram.com/v23.0"
TH_API = "https://graph.threads.net/v1.0"
KST = dt.timezone(dt.timedelta(hours=9))

# 인스타 피드(캐러셀) 게시물에서 받을 수 있는 숫자 (impressions 는 2024년 이후 폐지 → views 사용)
IG_METRICS = ["views", "reach", "likes", "comments", "saved", "shares", "total_interactions", "follows"]
TH_METRICS = ["views", "likes", "replies", "reposts", "quotes", "shares"]
RECENT_DAYS = 30  # 이보다 오래된 글은 숫자가 거의 안 바뀌어서 다시 안 부른다


class NoPermission(Exception):
    pass


def get(url, **params):
    r = requests.get(url, params=params, timeout=60)
    try:
        data = r.json()
    except ValueError:
        data = {"error": {"message": r.text[:200]}}
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {})
        msg = str(err.get("message", ""))
        # 10·200번대 = 권한 문제, 190 = 토큰 만료/무효
        if err.get("code") in (10, 190, 200) or "permission" in msg.lower():
            raise NoPermission(f"{err.get('code')} {msg[:150]}")
        raise RuntimeError(f"{r.status_code} {err.get('code')} {msg[:150]}")
    return data


def values_of(data: dict) -> dict:
    """insights 응답에서 {이름: 숫자} 만 뽑기"""
    out = {}
    for item in data.get("data", []):
        if "total_value" in item:
            out[item["name"]] = item["total_value"].get("value", 0)
        elif item.get("values"):
            out[item["name"]] = item["values"][-1].get("value", 0)
    return out


def media_insights(api: str, media_id: str, metrics: list[str], tok: str) -> dict:
    """한 번에 다 부르고, 지원 안 하는 숫자가 섞여 실패하면 하나씩 다시 부른다"""
    try:
        return values_of(get(f"{api}/{media_id}/insights", metric=",".join(metrics), access_token=tok))
    except NoPermission:
        raise
    except RuntimeError:
        out = {}
        for m in metrics:
            try:
                out.update(values_of(get(f"{api}/{media_id}/insights", metric=m, access_token=tok)))
            except RuntimeError:
                pass
        return out


# ---------- 권한 확인 ----------
def check():
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else {}
    last = max(log.items(), key=lambda kv: kv[1].get("date", ""), default=(None, {}))[1]
    lines, ok_all = [], True

    ig, th = os.environ.get("IG_TOKEN"), os.environ.get("THREADS_TOKEN")
    # 인스타
    if not ig:
        lines.append("인스타: 비밀 값 IG_TOKEN 이 비어 있어요"); ok_all = False
    else:
        try:
            me = get(f"{IG_API}/me", fields="username,followers_count,media_count", access_token=ig)
            lines.append(f"인스타 기본 정보: 통과 (팔로워 {me.get('followers_count')}명, 게시물 {me.get('media_count')}개)")
        except Exception as e:
            lines.append(f"인스타 기본 정보: 실패 — {e}"); ok_all = False
        if last.get("instagram"):
            try:
                v = media_insights(IG_API, last["instagram"], IG_METRICS, ig)
                lines.append(f"인스타 통계 권한: 통과 (예: 도달 {v.get('reach')}, 저장 {v.get('saved')})")
            except NoPermission as e:
                lines.append(f"인스타 통계 권한: 없음 ❌ — {e}"); ok_all = False
    # 스레드
    if not th:
        lines.append("스레드: 비밀 값 THREADS_TOKEN 이 비어 있어요"); ok_all = False
    else:
        try:
            me = get(f"{TH_API}/me", fields="id,username", access_token=th)
            f = values_of(get(f"{TH_API}/{me['id']}/threads_insights", metric="followers_count", access_token=th))
            lines.append(f"스레드 통계 권한: 통과 (팔로워 {f.get('followers_count')}명)")
        except NoPermission as e:
            lines.append(f"스레드 통계 권한: 없음 ❌ — {e}"); ok_all = False
        except Exception as e:
            lines.append(f"스레드 통계: 실패 — {e}"); ok_all = False

    print("\n".join(lines))
    if not ok_all:
        print("::warning::통계 권한이 없는 곳이 있어요. 해당 토큰을 '통계(insights)' 권한을 켜고 다시 발급해야 해요.")
    return ok_all


# ---------- 수집 ----------
def collect():
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else {}
    STATS.mkdir(exist_ok=True)
    posts_file = STATS / "posts.json"
    posts = json.loads(posts_file.read_text(encoding="utf-8")) if posts_file.exists() else {}
    today = dt.datetime.now(KST).date()
    ig, th = os.environ.get("IG_TOKEN"), os.environ.get("THREADS_TOKEN")
    problems = []

    for stem, rec in log.items():
        date = dt.date.fromisoformat(rec.get("date", today.isoformat()))
        if (today - date).days > RECENT_DAYS and stem in posts:
            continue
        cfile = ROOT / "content" / f"{stem}.json"
        meta = json.loads(cfile.read_text(encoding="utf-8")) if cfile.exists() else {}
        row = posts.setdefault(stem, {})
        row.update({"date": rec.get("date"), "tag": meta.get("tag", ""), "title": meta.get("title", ""),
                    "has_link": bool(meta.get("link"))})
        for name, api, key, metrics, tok in (("instagram", IG_API, "instagram", IG_METRICS, ig),
                                             ("threads", TH_API, "threads", TH_METRICS, th)):
            if not (tok and rec.get(key)):
                continue
            try:
                row[name] = media_insights(api, rec[key], metrics, tok)
            except NoPermission as e:
                problems.append(f"{name} 통계 권한 없음: {e}")
                break
            except Exception as e:
                problems.append(f"{stem} {name}: {e}")
        row["updated"] = today.isoformat()

    # 팔로워 수 + 스레드 링크 클릭(최근 7일)
    ig_f = th_f = ""
    clicks = []
    if ig:
        try:
            ig_f = get(f"{IG_API}/me", fields="followers_count", access_token=ig).get("followers_count", "")
        except Exception as e:
            problems.append(f"인스타 팔로워: {e}")
    if th:
        try:
            uid = get(f"{TH_API}/me", fields="id", access_token=th)["id"]
            ins = get(f"{TH_API}/{uid}/threads_insights", metric="followers_count", access_token=th)
            th_f = values_of(ins).get("followers_count", "")
            since = int((dt.datetime.now(KST) - dt.timedelta(days=7)).timestamp())
            cl = get(f"{TH_API}/{uid}/threads_insights", metric="clicks", since=since, access_token=th)
            for item in cl.get("data", []):
                clicks += item.get("link_total_values", [])
        except Exception as e:
            problems.append(f"스레드 팔로워·클릭: {e}")

    posts_file.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    fcsv = STATS / "followers.csv"
    rows = list(csv.reader(fcsv.open(encoding="utf-8"))) if fcsv.exists() else [["date", "instagram", "threads"]]
    rows = [r for r in rows if r and r[0] != today.isoformat()] + [[today.isoformat(), str(ig_f), str(th_f)]]
    with fcsv.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)

    (STATS / "report.md").write_text(report(posts, rows, clicks, problems), encoding="utf-8")
    print((STATS / "report.md").read_text(encoding="utf-8"))
    if problems:
        print("::warning::" + " / ".join(problems[:5]))


def score(row: dict) -> float:
    """저장·공유가 팔로워를 모으는 핵심 → (저장+공유) ÷ 도달. 도달이 없으면 스레드 반응으로"""
    ig = row.get("instagram", {})
    reach = ig.get("reach") or 0
    if reach:
        return (ig.get("saved", 0) + ig.get("shares", 0)) / reach
    th = row.get("threads", {})
    v = th.get("views") or 0
    return (th.get("reposts", 0) + th.get("shares", 0) + th.get("likes", 0)) / v if v else 0.0


def report(posts: dict, followers: list, clicks: list, problems: list) -> str:
    out = [f"# 살림코칭 통계 ({dt.datetime.now(KST):%Y-%m-%d})", ""]
    data = [r for r in followers[1:] if r[1] or r[2]]
    if data:
        last = data[-1]
        week = data[-8] if len(data) >= 8 else data[0]
        def diff(i):
            try:
                return f"{int(last[i]) - int(week[i]):+d}"
            except ValueError:
                return "-"
        out += ["## 팔로워", f"- 인스타 {last[1]}명 (최근 7일 {diff(1)})", f"- 스레드 {last[2]}명 (최근 7일 {diff(2)})", ""]

    ranked = sorted(posts.items(), key=lambda kv: score(kv[1]), reverse=True)
    out += ["## 반응 좋은 글 (저장+공유 ÷ 도달)", "", "| 순위 | 원고 | 주제 | 인스타 도달 | 저장 | 공유 | 스레드 조회 | 점수 |",
            "|---|---|---|---|---|---|---|---|"]
    for i, (stem, r) in enumerate(ranked[:10], 1):
        ig, th = r.get("instagram", {}), r.get("threads", {})
        out.append(f"| {i} | {stem} | {r.get('tag','')} | {ig.get('reach','-')} | {ig.get('saved','-')} | "
                   f"{ig.get('shares','-')} | {th.get('views','-')} | {score(r):.1%} |")

    by_tag = {}
    for r in posts.values():
        by_tag.setdefault(r.get("tag") or "기타", []).append(score(r))
    out += ["", "## 주제별 평균 점수", ""]
    for tag, s in sorted(by_tag.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        out.append(f"- {tag}: {sum(s)/len(s):.1%} ({len(s)}개)")

    if clicks:
        out += ["", "## 스레드 링크 클릭 (최근 7일)", ""]
        for c in sorted(clicks, key=lambda c: -c.get("value", 0)):
            out.append(f"- {c.get('value', 0)}회 — {c.get('link_url', '')}")
    if problems:
        out += ["", "## 확인할 점", ""] + [f"- {p}" for p in problems]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="권한만 확인하고 저장은 안 함")
    a = ap.parse_args()
    if a.check:
        sys.exit(0 if check() else 1)
    collect()
