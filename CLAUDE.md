# 작업 규칙 (유진·아름 사진 저장소)

- 응답은 한국어. 이 저장소는 앨범 **화면만** 담는다(index.html·manifest.webmanifest·sw.js·icons). 사진·암호는 절대 올리지 않는다.
- 서버(API `/api/album/*`)는 kwonyujin119/test 의 `server/sachil_server.py`에 있다. API를 바꾸면 그쪽 서버 버전도 올리고 zip을 다시 묶는다(그 저장소 CLAUDE.md 규칙).
- 서버 주소 기본값은 index.html의 `DEF_SRV`(https://app.sachil47.com). 서버의 `allowed_origins`에 https://kwonyujin119.github.io 가 있어야 한다.
- 배포: main에 머지하면 GitHub Pages(https://kwonyujin119.github.io/test3/)에 자동 반영. 화면을 바꾸면 index.html 안 `VER`을 올린다.
