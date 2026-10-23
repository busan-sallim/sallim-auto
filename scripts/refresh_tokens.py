"""토큰 자동 갱신 (60일짜리 토큰을 다시 60일로 늘리기)

일주일에 한 번 실행된다. 새 토큰은 화면에 찍지 않고 바로 깃허브 비밀 보관함에 덮어쓴다.
필요한 비밀 값: IG_TOKEN, THREADS_TOKEN, GH_PAT(비밀 보관함을 고칠 수 있는 깃허브 열쇠)
"""
import os
import subprocess
import sys

import requests

JOBS = [
    ("IG_TOKEN", "https://graph.instagram.com/refresh_access_token", "ig_refresh_token"),
    ("THREADS_TOKEN", "https://graph.threads.net/refresh_access_token", "th_refresh_token"),
]


def main():
    failed = False
    for name, url, grant in JOBS:
        old = os.environ.get(name)
        if not old:
            print(f"{name}: 비밀 값이 비어 있어요")
            failed = True
            continue
        r = requests.get(url, params={"grant_type": grant, "access_token": old}, timeout=60)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        new = data.get("access_token")
        if r.status_code != 200 or not new:
            print(f"{name}: 갱신 실패 ({r.status_code}) {data.get('error', {}).get('message', '')}")
            failed = True
            continue
        # gh 명령으로 비밀 값 덮어쓰기 (토큰은 표준입력으로만 전달 → 로그에 안 남음)
        subprocess.run(["gh", "secret", "set", name, "--repo", os.environ["GITHUB_REPOSITORY"]],
                       input=new, text=True, check=True,
                       env={**os.environ, "GH_TOKEN": os.environ["GH_PAT"]})
        days = int(data.get("expires_in", 0)) // 86400
        print(f"{name}: 갱신 완료 (앞으로 약 {days}일 사용 가능)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
