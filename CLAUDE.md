# 작업 규칙 (유진·아름 사진 저장소)

- 응답은 한국어. 이 저장소는 앨범 **화면**(index.html·manifest.webmanifest·sw.js·icons·img)과 **별도 서버**(`server/album_server.py`·start.bat·set-code.bat)를 담는다. 사진·접속코드 평문은 절대 올리지 않는다.
- 서버 API `/api/album/*`는 두 곳에 있다: 이 저장소 `server/album_server.py`(별도 서버, `VERSION`을 올리면 PC가 10분 안에 자동 업데이트)와 kwonyujin119/test 의 `server/sachil_server.py`(SACHIL 서버, 15.8+). API를 바꾸면 둘 다 맞추고, test 쪽은 그 저장소 규칙대로 버전·zip을 올린다.
- 화면은 `SRV_CANDIDATES` 순서(album.sachil47.com → app.sachil47.com)로 서버를 찾는다. 서버의 `allowed_origins`에 https://kwonyujin119.github.io 가 있어야 한다.
- 배포: main에 머지하면 GitHub Pages(https://kwonyujin119.github.io/test3/)에 자동 반영. 화면을 바꾸면 index.html 안 `VER`을 올린다.
