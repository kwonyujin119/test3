# 유진·아름 사진 저장소 — 서버 (PC 한 대로 끝, 도메인 불필요)

다른 프로그램이나 도메인 없이 **이 폴더 하나**로 돕니다. 사진은 이 폴더 안 `사진\` 폴더에만 저장됩니다. GitHub에는 올라가지 않습니다.

## 1. 설치 (처음 한 번)

1. GitHub 저장소 첫 화면 → 초록 **Code** → **Download ZIP** → 압축 풀기
2. 압축을 푼 폴더(`test3-main`)를 통째로 D드라이브로 옮기고 이름을 바꿉니다. 예: `D:\사진저장소`
   - 그 안에 `index.html`(화면)과 `server` 폴더(서버)가 함께 있어야 합니다. `server` 폴더만 따로 떼어 두면 화면이 안 나옵니다.
3. `D:\사진저장소\server\start.bat` 더블클릭 → 검은 창에 "사진 저장소 서버"와 주소 두 줄이 뜨면 켜진 것입니다. (Python 3 필요: https://www.python.org/downloads/ 에서 설치할 때 "Add python.exe to PATH" 체크)

만들어지는 것: `server\data\config.json`(설정), `server\data\album.db`(목록), `server\사진\`(사진 원본·미리보기)

## 2. 쓰기

- **이 PC에서**: 검은 창의 `http://localhost:4848` 을 브라우저에 입력
- **같은 와이파이의 폰에서**: 검은 창의 `같은 와이파이 폰: http://192.168.x.x:4848` 주소를 폰 브라우저에 입력 → 접속코드 → 들어가기
  - 폰 브라우저 메뉴 → "홈 화면에 추가"를 해 두면 앱처럼 열립니다.
  - PC의 IP 주소가 바뀌면(공유기 재시작 등) 창에 뜨는 새 주소로 다시 엽니다. 공유기에서 PC IP를 고정해 두면 편합니다.
- 접속코드 바꾸기: 들어간 뒤 ⋯ 메뉴 → **접속코드 바꾸기**, 또는 PC에서 `set-code.bat`

## 3. 어디서든 kwonyujin119.github.io/test3 로 열리게 하기 (도메인 불필요)

`start.bat`이 `cloudflared.exe`를 한 번 내려받아, 켤 때마다 공개 주소(`https://….trycloudflare.com`)를 만듭니다. 이 주소는 켤 때마다 바뀌므로, 서버가 그 주소를 GitHub 저장소의 `server-url.json`에 스스로 적어 두고 화면(github.io/test3)이 그 파일을 읽어 서버를 찾습니다. 그러려면 GitHub 토큰이 한 번 필요합니다.

1. 브라우저에서 github.com 로그인 → 오른쪽 위 프로필 → **Settings** → 왼쪽 맨 아래 **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
2. Token name: `album` / Expiration: 원하는 기간(예: 1 year) / **Repository access: Only select repositories → test3**
3. **Permissions → Repository permissions → Contents → Read and write** → 맨 아래 **Generate token** → 토큰 복사(`github_pat_…`)
4. PC의 `server` 폴더에서 `github-token-setup.bat` 실행 → 토큰 붙여넣기 → Enter
5. `start.bat`으로 서버를 켜면 창에 공개 주소가 뜨고 "server-url.json 갱신 완료"가 나옵니다. 1~2분 뒤 폰에서 `https://kwonyujin119.github.io/test3/` 를 열면 접속됩니다(와이파이·이동통신 어디서든).

토큰 없이 쓰려면: 창에 뜬 `https://….trycloudflare.com` 주소를 폰에서 직접 열면 됩니다(서버를 다시 켤 때마다 주소가 바뀜).

## 3-1. 폴더(앨범)

접속한 사람 누구나 화면 위 칩 줄의 **+ 새 폴더**로 폴더를 만들 수 있습니다. 폴더를 고른 상태에서 올린 사진은 그 폴더에 들어가고, 크게 보기의 **폴더** 버튼으로 옮길 수 있습니다. PC의 `사진\` 안에도 같은 이름의 폴더가 생겨 파일이 그 안에 저장됩니다. 사진이 든 폴더는 지울 수 없습니다(먼저 옮기거나 지우기).

## 4. 집 밖(이동통신)에서도 보려면 — 참고

도메인 없이도 됩니다. https://github.com/cloudflare/cloudflared/releases 에서 `cloudflared-windows-amd64.exe`를 받아 이름을 `cloudflared.exe`로 바꿔 `server` 폴더에 넣고 `start.bat`을 다시 켜면, 검은 창에 `https://…trycloudflare.com` 주소가 뜹니다. 이 주소로 어디서든 열립니다. **서버를 다시 켤 때마다 주소가 바뀝니다**(`server\data\url.txt`에도 저장). 고정 주소가 필요하면 그때 도메인을 생각하면 됩니다.

## 5. 그 밖에

- 사진 폴더를 다른 곳(예: `E:\앨범사진`)으로 두려면 서버 창을 닫고 `server` 폴더에서 아래를 실행한 뒤 다시 켭니다.
  ```
  py album_server.py --set-photos-dir E:\앨범사진
  ```
- 자동 업데이트: 10분마다 GitHub의 `server/album_server.py`가 새 버전이면 스스로 교체하고 다시 켭니다(`start.bat`으로 켰을 때만).
- 용량: 사진 1장 30MB, 전체 20GB(`data\config.json`의 `max_store_mb`).
- 백업할 것: `server\사진\` 폴더와 `server\data\album.db`.
- 서버 창을 닫거나 PC가 꺼지면 폰에서 사진을 보지 못합니다.
