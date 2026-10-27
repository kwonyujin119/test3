# 유진·아름 사진 저장소 — 별도 서버

SACHIL:47 서버와 **완전히 별개**로 도는 작은 서버입니다. 사진은 이 서버 폴더의 `사진\` 폴더(또는 지정한 다른 폴더)에만 저장됩니다. GitHub에는 올라가지 않습니다.

## 1. PC에 설치 (처음 한 번)

1. 이 `server` 폴더의 파일 3개(`album_server.py`, `start.bat`, `set-code.bat`)를 PC의 새 폴더에 넣습니다. 예: `D:\사진저장소`
   - GitHub에서 받는 법: 저장소 첫 화면 → 초록 **Code** 버튼 → **Download ZIP** → 압축을 풀고 `server` 폴더 안의 파일을 복사
2. `start.bat`을 더블클릭합니다. 검은 창에 "사진 저장소 서버 1.0"과 사진 폴더 경로가 뜨면 켜진 것입니다. (Python 3가 PC에 있어야 합니다. SACHIL 서버가 도는 PC라면 이미 있습니다.)
3. 처음 켜면 `data\config.json`, `data\album.db`, `사진\` 폴더가 생깁니다.

사진 폴더를 다른 곳(예: `E:\앨범사진`)으로 두려면 서버 창을 닫고 같은 폴더에서 아래를 실행한 뒤 다시 켭니다.

```
py album_server.py --set-photos-dir E:\앨범사진
```

## 2. 바깥(폰)에서 접속되게 하기 — Cloudflare 터널에 주소 하나 추가

SACHIL 서버가 쓰는 Cloudflare 터널(`sachil`)에 주소를 하나 더 붙이면 됩니다. PC에서 따로 켤 프로그램은 없습니다.

1. Cloudflare 대시보드 → **Zero Trust** → **Networks** → **Tunnels** → `sachil` 클릭
2. **Public Hostname** 탭 → **Add a public hostname**
3. Subdomain: `album` / Domain: `sachil47.com` / Type: **HTTP** / URL: `localhost:4848` → Save

이제 `https://album.sachil47.com` 이 이 서버입니다. (포트를 바꿨다면 `data\config.json`의 `port`와 같은 번호로)

## 3. 폰에서 쓰기

1. `https://kwonyujin119.github.io/test3/` 열기 (화면은 `album.sachil47.com`을 먼저 찾고, 없으면 SACHIL 서버를 찾습니다)
2. 접속코드 입력 → 들어가기
3. 접속코드 바꾸기: 들어간 뒤 ⋯ 메뉴 → **접속코드 바꾸기**, 또는 PC에서 `set-code.bat`

## 4. 그 밖에

- 자동 업데이트: 10분마다 이 저장소의 `server/album_server.py`가 새 버전이면 스스로 교체하고 다시 켭니다(`start.bat`으로 켰을 때만).
- 용량: 사진 1장 30MB, 전체 20GB(`data\config.json`의 `max_store_mb`).
- 백업할 것: `사진\` 폴더와 `data\album.db`.
- 서버 창을 닫으면 폰에서 사진을 보지 못합니다. PC가 켜져 있고 이 창이 떠 있어야 합니다.
