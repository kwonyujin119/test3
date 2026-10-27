# 작업 규칙 (유진·아름 사진 저장소)

- 응답은 한국어. 이 저장소는 **독립된** 사진 저장소다: 화면(index.html·manifest.webmanifest·sw.js·icons·img) + 서버(`server/album_server.py`·start.bat·set-code.bat). 다른 프로젝트·서버·도메인에 기대지 않는다. 사진·접속코드 평문은 절대 올리지 않는다.
- 서버가 화면을 직접 내보낸다(`web_dir()`: `server/web/` → 저장소 루트). 폰은 같은 와이파이에서 `http://<PC주소>:4848`로 연다. 바깥 접속은 선택(cloudflared.exe 임시 주소).
- 서버를 고치면 `VERSION`을 올린다(PC의 start.bat이 10분 안에 자동 업데이트). 화면을 고치면 index.html 안 `VER`을 올린다.
- 사진은 `server/사진/`(config `photos_dir`)에만, 목록은 `server/data/album.db`. 서버 API는 `/api/album/*`.
