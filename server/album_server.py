# -*- coding: utf-8 -*-
r"""
유진·아름 사진 저장소 — 독립 서버 (다른 프로그램·도메인 불필요, 파이썬 표준 라이브러리만 사용)

  폴더 구성(이 파일이 있는 곳 기준)
    data\config.json   설정(포트·접속코드 해시·허용 주소·사진 폴더)
    data\album.db      사진 목록(SQLite)
    사진\               사진 원본(<id>) + 미리보기(<id>.t.jpg)  ← config.json의 photos_dir로 바꿀 수 있음
    사진\<폴더이름>\      화면에서 만든 폴더(앨범)의 사진은 그 이름의 하위 폴더에 들어간다

  실행: start.bat (자동 업데이트 포함)  /  접속코드 바꾸기: set-code.bat 또는 --set-code 새코드
  화면: 이 서버가 직접 보여 준다 — 같은 와이파이의 폰·PC에서 http://<이 PC 주소>:4848 을 연다(도메인 불필요)
        (화면 파일 index.html 등은 이 폴더의 상위 폴더 또는 web\ 폴더에서 찾는다)
  바깥(이동통신)에서도 쓰려면: start.bat이 cloudflared.exe를 받아 켤 때마다 공개 주소(trycloudflare.com)를 만들고,
        GitHub 토큰(github-token-setup.bat)이 있으면 그 주소를 저장소의 server-url.json에 적어 둔다
        → 화면(https://kwonyujin119.github.io/test3/)이 그 파일을 읽어 어디서든 이 서버로 붙는다(도메인 불필요)
"""
import datetime, hashlib, json, os, re, secrets, shutil, sqlite3, sys, threading, time, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

VERSION = '1.9'
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
CONF_PATH = os.path.join(DATA, 'config.json')
os.makedirs(DATA, exist_ok=True)

WHO = ('유진', '아름')
PHOTO_MAX = 30 * 1024 * 1024          # 사진 1장 30MB
THUMB_MAX = 400 * 1024                # 미리보기 1장 400KB
SESSION_DAYS = 180                    # 로그인 유지(쓸 때마다 연장)
LOGIN_FAILS, LOGIN_WINDOW = 8, 600    # 10분에 8번 틀리면 잠금
CODE_SALT = b'yujin-areum-album'
# 기본 접속코드(사용자가 정한 값)의 해시만 둔다(코드 자체는 적지 않음) — 바꾸기: set-code.bat
CODE_HASH_DEFAULT = '911093919025a304c8438e4e5fcfb1fa49f803b17fe838f77a413ce8eeb7458f'
ADMIN_HASH_DEFAULT = 'cea62a928c673a3c54974f6274943efe1f52a642d8649789427063f72968d502'   # 1.9: 관리자 코드(사용자 지정)의 해시 — 관리자만 사진·폴더를 지울 수 있다. 바꾸기: --set-admin-code


def code_hash(code):
    code = re.sub(r'[\s\-]', '', str(code or '')).lower()
    return hashlib.pbkdf2_hmac('sha256', code.encode('utf-8'), CODE_SALT, 200000).hex()


# ---------------------------------------------------------------- 설정
CONF_LOCK = threading.Lock()


def load_conf():
    defaults = {
        'port': 4848,
        'code_hash': CODE_HASH_DEFAULT,                 # 접속코드(해시로만 저장)
        'admin_code_hash': ADMIN_HASH_DEFAULT,          # 1.9: 관리자 코드(해시로만 저장)
        'photos_dir': os.path.join(BASE, '사진'),       # 사진이 저장되는 폴더(다른 드라이브·폴더로 바꿀 수 있음)
        'max_store_mb': 20480,                          # 사진 총량(MB)
        'allowed_origins': ['https://kwonyujin119.github.io'],   # 화면(github.io)에서 오는 요청 허용
        'auto_update': True,                            # GitHub의 server/album_server.py가 새 버전이면 스스로 교체하고 다시 켬
        'update_url': 'https://raw.githubusercontent.com/kwonyujin119/test3/main/server/album_server.py',
        'update_check_min': 10,
        'tunnel': 'auto',                               # auto: 이 폴더(또는 상위)에 cloudflared.exe가 있으면 공개 주소를 만든다 / off: 안 만든다
        'github_token': '',                             # github-token-setup.bat으로 넣음. 공개 주소를 저장소의 server-url.json에 적는 데만 씀
        'github_repo': 'kwonyujin119/test3',            # 화면이 있는 저장소
    }
    conf = {}
    try:
        with open(CONF_PATH, encoding='utf-8') as f:
            conf = json.load(f)
        if not isinstance(conf, dict):
            conf = {}
    except (OSError, ValueError):
        conf = {}
    changed = False
    for k, v in defaults.items():
        if k not in conf:
            conf[k] = v
            changed = True
    if changed:
        write_conf(conf)
    return conf


def write_conf(conf):
    with CONF_LOCK:
        tmp = CONF_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(dict(conf), f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONF_PATH)


CONF = load_conf()
PHOTOS = str(CONF.get('photos_dir') or os.path.join(BASE, '사진'))
os.makedirs(PHOTOS, exist_ok=True)


def web_dir():
    """화면 파일(index.html 등)이 있는 폴더: web\\ → 상위 폴더(저장소 통째로 받았을 때) 순."""
    for d in (os.path.join(BASE, 'web'), os.path.dirname(BASE)):
        if os.path.exists(os.path.join(d, 'index.html')):
            return d
    return None


WEB_TYPES = {'.html': 'text/html; charset=utf-8', '.webmanifest': 'application/manifest+json', '.js': 'text/javascript; charset=utf-8',
             '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.ico': 'image/x-icon'}


def conf_disk(key):
    """서버가 켜진 채로 set-code.bat이 고친 값을 바로 쓰도록 config.json에서 그 항목만 다시 읽는다."""
    try:
        with open(CONF_PATH, encoding='utf-8') as f:
            d = json.load(f)
        if key in d:
            with CONF_LOCK:
                CONF[key] = d[key]
    except (OSError, ValueError):
        pass
    return CONF.get(key)


# ---------------------------------------------------------------- DB
DB_LOCK = threading.Lock()
DB = sqlite3.connect(os.path.join(DATA, 'album.db'), check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.executescript('''
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY, who TEXT, name TEXT, mime TEXT, size INTEGER, w INTEGER, h INTEGER, memo TEXT, taken REAL, ts REAL, thumb INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_photos_taken ON photos(taken);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, who TEXT, created REAL, seen REAL, ip TEXT);
CREATE TABLE IF NOT EXISTS folders(id TEXT PRIMARY KEY, name TEXT UNIQUE, ts REAL);
''')
try:   # 1.3: 사진이 속한 폴더(앨범). 빈 값이면 기본(폴더 없음)
    DB.execute('ALTER TABLE photos ADD COLUMN folder TEXT DEFAULT \'\'')
except sqlite3.OperationalError:
    pass
for _sql in ('ALTER TABLE sessions ADD COLUMN admin INTEGER DEFAULT 0',   # 1.9: 관리자 로그인 표시
             'ALTER TABLE folders ADD COLUMN cover TEXT DEFAULT \'\''):   # 1.9: 폴더 대표사진
    try:
        DB.execute(_sql)
    except sqlite3.OperationalError:
        pass
DB.commit()


def folder_name_ok(name):
    name = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', '', str(name or '')).strip().strip('.')
    name = re.sub(r'\s+', ' ', name)[:40]
    return name if name and name.lower() not in ('con', 'prn', 'aux', 'nul') else ''


def folder_row(r, counts):
    return {'id': r['id'], 'name': r['name'], 'ts': r['ts'], 'count': counts.get(r['id'], 0), 'cover': (r['cover'] if 'cover' in r.keys() else '') or ''}


def folders_out():
    counts = {x['folder']: x['n'] for x in q('SELECT folder, COUNT(*) n FROM photos GROUP BY folder')}
    return {'folders': [folder_row(r, counts) for r in q('SELECT * FROM folders ORDER BY name')], 'root_count': counts.get('', 0)}


def photo_dir(folder_id):
    """폴더(앨범)의 실제 디스크 폴더. 없으면 만든다."""
    if folder_id:
        f = q('SELECT name FROM folders WHERE id=?', (folder_id,), one=True)
        if f:
            d = os.path.join(PHOTOS, f['name'])
            os.makedirs(d, exist_ok=True)
            return d
    return PHOTOS


def photo_path(r):
    return os.path.join(photo_dir(r['folder'] if 'folder' in r.keys() else ''), r['id'])


def q(sql, args=(), one=False, commit=False):
    with DB_LOCK:
        cur = DB.execute(sql, args)
        if commit:
            DB.commit()
            return cur.lastrowid
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def th(token):
    return hashlib.sha256(token.encode()).hexdigest()


def to_int(s, default=None, lo=0, hi=2 ** 53):
    try:
        v = int(str(s).strip())
        return v if lo <= v <= hi else default
    except (TypeError, ValueError):
        return default


MAGIC = [(b'\xff\xd8\xff', 'image/jpeg', '.jpg'), (b'\x89PNG\r\n\x1a\n', 'image/png', '.png'), (b'GIF8', 'image/gif', '.gif')]


def sniff(head):
    for sig, mime, ext in MAGIC:
        if head.startswith(sig):
            return mime, ext
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp', '.webp'
    return None


FAILS, FAILS_LOCK = {}, threading.Lock()


def usage():
    r = q('SELECT COUNT(*) n, COALESCE(SUM(size),0) s FROM photos', one=True)
    return {'count': r['n'], 'bytes': r['s'], 'max_bytes': int(to_int(CONF.get('max_store_mb'), 20480, 1, 10 ** 7)) * 1024 * 1024}


def row_out(r):
    return {'id': r['id'], 'who': r['who'] or '', 'name': r['name'], 'mime': r['mime'], 'size': r['size'], 'w': r['w'], 'h': r['h'],
            'memo': r['memo'] or '', 'taken': r['taken'], 'ts': r['ts'], 'thumb': bool(r['thumb']), 'folder': r['folder'] or ''}


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = 'Album/' + VERSION
    sys_version = ''
    protocol_version = 'HTTP/1.1'
    timeout = 60

    def log_message(self, fmt, *args):
        pass

    def ip(self):
        peer = self.client_address[0]
        if peer in ('127.0.0.1', '::1'):
            return self.headers.get('CF-Connecting-IP') or self.headers.get('X-Forwarded-For', '').split(',')[0].strip() or peer
        return peer

    def clen(self):
        v = self.headers.get('Content-Length')
        if v is None or v == '':
            return 0
        n = to_int(v, -1)
        if n < 0:
            self.close_connection = True
        return n

    def drain(self):
        if getattr(self, '_body_read', False):
            return
        self._body_read = True
        n = self.clen()
        if n <= 0:
            return
        if n > 1024 * 1024:
            self.close_connection = True
            return
        try:
            self.rfile.read(n)
        except Exception:
            self.close_connection = True

    def cors_origin(self):
        o = (self.headers.get('Origin') or '').rstrip('/')
        allowed = [str(x).rstrip('/') for x in (CONF.get('allowed_origins') or [])]
        return o if o and o in allowed else None

    def end_headers(self):
        o = self.cors_origin()
        if o:
            self.send_header('Access-Control-Allow-Origin', o)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Expose-Headers', 'Content-Range, Accept-Ranges, Content-Length')
        super().end_headers()

    def send(self, status, body=b'', ctype='application/json; charset=utf-8', extra=None):
        self.drain()
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', (extra or {}).get('Cache-Control', 'no-store'))
        for k, v in (extra or {}).items():
            if k != 'Cache-Control':
                self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def err(self, status, msg):
        self.send(status, {'ok': False, 'error': msg})

    def body_json(self, limit=20000):
        n = self.clen()
        if n < 0 or n > limit:
            self.close_connection = True
            raise ValueError('요청이 너무 큽니다')
        raw = self.rfile.read(n) if n else b''
        self._body_read = True
        try:
            obj = json.loads(raw.decode('utf-8') or '{}')
        except Exception:
            raise ValueError('잘못된 요청입니다')
        return obj if isinstance(obj, dict) else {}

    def send_file(self, fp, mime, disposition, cache):
        try:
            size = os.path.getsize(fp)
        except OSError:
            return self.err(404, '파일이 없습니다')
        start, end, status = 0, size - 1, 200
        rng = self.headers.get('Range')
        if rng:
            m = re.fullmatch(r'bytes=(\d*)-(\d*)', rng.strip())
            if not m or (m.group(1) == '' and m.group(2) == ''):
                return self.send(416, b'', 'text/plain', {'Content-Range': f'bytes */{size}'})
            if m.group(1) == '':
                start = max(0, size - int(m.group(2)))
            else:
                start = int(m.group(1))
                if m.group(2):
                    end = min(size - 1, int(m.group(2)))
            if start > end or start >= size:
                return self.send(416, b'', 'text/plain', {'Content-Range': f'bytes */{size}'})
            status = 206
        self.drain()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Disposition', disposition)
        self.send_header('Cache-Control', cache)
        self.end_headers()
        if self.command == 'HEAD':
            return
        left = end - start + 1
        with open(fp, 'rb') as fh:
            fh.seek(start)
            while left > 0:
                chunk = fh.read(min(256 * 1024, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def web_get(self, rel):
        """앨범 화면(index.html·manifest·sw.js·icons·img)을 이 서버가 직접 내보낸다 — 같은 주소라 CORS·도메인이 필요 없다."""
        d = web_dir()
        if not d:
            return self.send(200, '유진·아름 사진 저장소 서버 ' + VERSION + ' — 화면 파일(index.html)이 없습니다. 저장소를 통째로 받아 server 폴더가 그 안에 있게 두거나, web 폴더에 화면 파일을 넣어 주세요.', 'text/plain; charset=utf-8')
        fp = os.path.realpath(os.path.join(d, rel))
        if not fp.startswith(os.path.realpath(d) + os.sep) or not os.path.isfile(fp):
            return self.err(404, '없는 주소입니다')
        ext = os.path.splitext(fp)[1].lower()
        return self.send_file(fp, WEB_TYPES.get(ext, 'application/octet-stream'), 'inline', 'no-cache' if ext in ('.html', '.webmanifest', '.js') else 'public, max-age=86400')

    # --- 인증
    def token(self):
        a = re.fullmatch(r'Bearer ([A-Za-z0-9_\-]{20,})', (self.headers.get('Authorization') or '').strip())
        if a:
            return a.group(1)
        t = urllib.parse.parse_qs(self.path.partition('?')[2]).get('t', [''])[0]
        return t if re.fullmatch(r'[A-Za-z0-9_\-]{20,}', t) else None

    def auth(self):
        tok = self.token()
        if not tok:
            return None
        r = q('SELECT * FROM sessions WHERE token=?', (th(tok),), one=True)
        if not r:
            return None
        now = time.time()
        if now - (r['seen'] or 0) > SESSION_DAYS * 86400:
            q('DELETE FROM sessions WHERE token=?', (r['token'],), commit=True)
            return None
        if now - (r['seen'] or 0) > 600:
            q('UPDATE sessions SET seen=? WHERE token=?', (now, r['token']), commit=True)
        return {'who': r['who'] or '', 'token': r['token'], 'admin': bool(r['admin'] if 'admin' in r.keys() else 0)}

    # --- 라우팅
    def do_OPTIONS(self):
        self._body_read = False
        if not self.cors_origin():
            return self.send(403, b'', 'text/plain')
        return self.send(204, b'', 'text/plain', {'Access-Control-Allow-Methods': 'GET, POST, DELETE, HEAD',
                                                  'Access-Control-Allow-Headers': 'X-ALBUM, Content-Type, Authorization, Range',
                                                  'Access-Control-Max-Age': '600'})

    def guard(self):
        return self.headers.get('X-ALBUM') == '1'

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._body_read = False
        path, _, qs = self.path.partition('?')
        args = urllib.parse.parse_qs(qs)
        try:
            if path == '/status':   # 1.6: 서버 상태(비밀값 없음) — 폰에서 열어 원인을 본다
                try:
                    with open(os.path.join(DATA, 'update.log'), encoding='utf-8', errors='replace') as f:
                        log = ''.join(f.readlines()[-12:])
                except OSError:
                    log = '(기록 없음)'
                wd = web_dir()
                ver = ''
                if wd:
                    try:
                        mm = re.search(r"const VER = '(v\d+)'", open(os.path.join(wd, 'index.html'), encoding='utf-8', errors='replace').read())
                        ver = mm.group(1) if mm else '?'
                    except OSError:
                        pass
                body = (f'사진 저장소 서버 {VERSION}\n\n화면 폴더: {wd or "(없음)"}  화면 버전: {ver}\n화면 갱신: {WEB_STATE["msg"]}\n'
                        f'공개 주소: {TUNNEL_URL[0] or "(없음) " + TUNNEL_STATE["msg"]}\n주소 등록(server-url.json): {PUBLISH_STATE["msg"] or "-"}\n'
                        f'GitHub 토큰: {"있음" if CONF.get("github_token") else "없음"}\n사진 폴더: {PHOTOS}\n\n최근 기록:\n{log}\n\n'
                        f'문제가 있으면 /update 를 여세요.')
                return self.send(200, body, 'text/plain; charset=utf-8')
            if path == '/update':   # 1.6: 업데이트 도우미(내장 화면) — web 폴더가 없어도 열린다
                return self.send(200, UPDATE_PAGE.replace('__VER__', VERSION), 'text/html; charset=utf-8')
            if path in ('/', '/index.html') or re.fullmatch(r'/(manifest\.webmanifest|sw\.js|icons/[A-Za-z0-9_\-]+\.png|img/[A-Za-z0-9_\-]+\.jpg)', path):
                return self.web_get('index.html' if path == '/' else path.lstrip('/'))
            if path == '/healthz':
                return self.send(200, {'ok': True})
            if path == '/api/me':   # 화면의 진단용
                return self.send(200, {'server': 'album', 'version': VERSION, 'album': True})
            if path == '/api/album/ping':
                return self.send(200, {'ok': True, 'server': 'album', 'version': VERSION, 'who': list(WHO), 'has_code': bool(conf_disk('code_hash'))})
            u = self.auth()
            if not u:
                return self.err(401, '앨범 로그인이 필요합니다')
            if path == '/api/album/github-token':   # 1.8: 로그인한 사람의 브라우저가 서버 대신 GitHub에 주소를 적을 때 쓴다
                return self.send(200, {'ok': True, 'token': str(CONF.get('github_token') or ''), 'repo': str(CONF.get('github_repo') or '')})
            if path == '/api/album/me':
                return self.send(200, dict(ok=True, who=u['who'], admin=u['admin'], has_code=bool(CONF.get('code_hash')), version=VERSION,
                                           public_url=TUNNEL_URL[0], has_token=bool(CONF.get('github_token')), published=PUBLISH_STATE['msg'], published_url=PUBLISH_STATE['url'],
                                           github_repo=str(CONF.get('github_repo') or ''),
                                           tunnel=('off' if str(CONF.get('tunnel')) == 'off' else 'on' if TUNNEL_URL[0] else TUNNEL_STATE['msg']), **usage()))
            if path == '/api/album/photos':
                rows = q('SELECT * FROM photos ORDER BY taken DESC, ts DESC LIMIT 20000')
                return self.send(200, dict(ok=True, photos=[row_out(r) for r in rows], **usage(), **folders_out()))
            if path == '/api/album/folders':
                return self.send(200, dict(ok=True, **folders_out()))
            m = re.fullmatch(r'/api/album/(file|thumb)/([a-f0-9]{24})', path)
            if m:
                r = q('SELECT * FROM photos WHERE id=?', (m.group(2),), one=True)
                if not r:
                    return self.err(404, '사진이 없습니다')
                fp = photo_path(r)
                if m.group(1) == 'thumb' and r['thumb'] and os.path.exists(fp + '.t.jpg'):
                    return self.send_file(fp + '.t.jpg', 'image/jpeg', 'inline', 'private, max-age=31536000, immutable')
                if not os.path.exists(fp):
                    return self.err(404, '사진 파일이 없습니다')
                disp = ('attachment' if args.get('dl') else 'inline') + "; filename*=UTF-8''" + urllib.parse.quote(r['name'] or 'photo')
                return self.send_file(fp, r['mime'], disp, 'private, max-age=31536000, immutable')
            return self.err(404, '없는 주소입니다')
        except (ConnectionError, TimeoutError, OSError):
            self.close_connection = True
        except Exception as e:
            print('[오류]', self.command, path, e, flush=True)
            try:
                self.err(500, '서버 오류')
            except Exception:
                pass

    def do_POST(self):
        self._body_read = False
        path, _, qs = self.path.partition('?')
        args = urllib.parse.parse_qs(qs)
        try:
            if not self.guard():
                return self.err(403, '허용되지 않은 요청입니다')
            if path == '/api/album/login':
                return self.login()
            u = self.auth()
            if not u:
                return self.err(401, '앨범 로그인이 필요합니다')
            if path == '/api/album/admin-login':   # 1.9: 관리자 코드로 이 로그인에 관리자 표시(삭제 권한)
                ip = self.ip()
                now = time.time()
                key = 'admin:' + ip
                with FAILS_LOCK:
                    lst = [t for t in FAILS.get(key, []) if now - t < LOGIN_WINDOW]
                    FAILS[key] = lst
                    if len(lst) >= LOGIN_FAILS:
                        return self.err(429, '여러 번 틀려 10분간 잠겼습니다')
                b = self.body_json()
                code = str(b.get('code') or '')
                h = str(conf_disk('admin_code_hash') or '')
                if not (h and re.sub(r'[\s\-]', '', code) and secrets.compare_digest(code_hash(code), h)):
                    with FAILS_LOCK:
                        FAILS.setdefault(key, []).append(now)
                    return self.send(403, {'ok': False, 'error': '관리자 코드가 맞지 않습니다'})
                q('UPDATE sessions SET admin=1 WHERE token=?', (u['token'],), commit=True)
                print(f'[앨범] 관리자 로그인 ({ip})', flush=True)
                return self.send(200, {'ok': True, 'admin': True})
            if path == '/api/album/admin-logout':
                q('UPDATE sessions SET admin=0 WHERE token=?', (u['token'],), commit=True)
                return self.send(200, {'ok': True, 'admin': False})
            if path == '/api/album/logout':
                q('DELETE FROM sessions WHERE token=?', (u['token'],), commit=True)
                return self.send(200, {'ok': True})
            if path == '/api/album/upload':
                return self.upload(u, args)
            m = re.fullmatch(r'/api/album/thumb/([a-f0-9]{24})', path)
            if m:
                return self.thumb_put(m.group(1))
            if path == '/api/album/folders':   # 1.3: 폴더(앨범) 만들기 — 디스크에도 같은 이름의 폴더
                b = self.body_json()
                name = folder_name_ok(b.get('name'))
                if not name:
                    return self.err(400, '폴더 이름을 적어 주세요(특수문자 \\ / : * ? " < > | 제외, 40자까지)')
                if q('SELECT id FROM folders WHERE name=?', (name,), one=True):
                    return self.err(409, '같은 이름의 폴더가 있어요')
                fid = secrets.token_hex(8)
                os.makedirs(os.path.join(PHOTOS, name), exist_ok=True)
                q('INSERT INTO folders(id,name,ts) VALUES(?,?,?)', (fid, name, time.time()), commit=True)
                print(f'[앨범] 폴더 만듦: {name}', flush=True)
                return self.send(200, dict(ok=True, folder={'id': fid, 'name': name, 'ts': time.time(), 'count': 0}, **folders_out()))
            m = re.fullmatch(r'/api/album/folders/([a-f0-9]{16})', path)
            if m:   # 폴더 이름 바꾸기(디스크 폴더도 함께)
                b = self.body_json()
                f = q('SELECT * FROM folders WHERE id=?', (m.group(1),), one=True)
                if not f:
                    return self.err(404, '폴더가 없어요')
                if 'cover' in b:   # 1.9: 대표사진 정하기(빈 값이면 자동: 최근 사진)
                    cov = str(b.get('cover') or '')
                    if cov and not q('SELECT id FROM photos WHERE id=?', (cov,), one=True):
                        return self.err(404, '사진이 없어요')
                    q('UPDATE folders SET cover=? WHERE id=?', (cov, f['id']), commit=True)
                    if 'name' not in b:
                        return self.send(200, dict(ok=True, **folders_out()))
                name = folder_name_ok(b.get('name'))
                if not name:
                    return self.err(400, '폴더 이름을 적어 주세요')
                if name != f['name']:
                    if q('SELECT id FROM folders WHERE name=?', (name,), one=True):
                        return self.err(409, '같은 이름의 폴더가 있어요')
                    old, new = os.path.join(PHOTOS, f['name']), os.path.join(PHOTOS, name)
                    if os.path.isdir(old):
                        os.replace(old, new)
                    else:
                        os.makedirs(new, exist_ok=True)
                    q('UPDATE folders SET name=? WHERE id=?', (name, f['id']), commit=True)
                return self.send(200, dict(ok=True, **folders_out()))
            m = re.fullmatch(r'/api/album/photos/([a-f0-9]{24})', path)
            if m:
                b = self.body_json()
                r = q('SELECT * FROM photos WHERE id=?', (m.group(1),), one=True)
                if not r:
                    return self.err(404, '사진이 없습니다')
                if 'folder' in b:   # 1.3: 다른 폴더로 옮기기(파일도 옮김)
                    dest = str(b.get('folder') or '')
                    if dest and not q('SELECT id FROM folders WHERE id=?', (dest,), one=True):
                        return self.err(404, '옮길 폴더가 없어요')
                    if dest != (r['folder'] or ''):
                        src, dst = photo_path(r), os.path.join(photo_dir(dest), r['id'])
                        for suf in ('', '.t.jpg'):
                            if os.path.exists(src + suf):
                                os.replace(src + suf, dst + suf)
                        q('UPDATE photos SET folder=? WHERE id=?', (dest, r['id']), commit=True)
                if 'memo' in b:
                    memo = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(b.get('memo') or '')).strip()[:300]
                    q('UPDATE photos SET memo=? WHERE id=?', (memo, r['id']), commit=True)
                if 'taken' in b:
                    tk = to_int(b.get('taken'), None, 0, 4102444800000)
                    if tk:
                        q('UPDATE photos SET taken=? WHERE id=?', (tk / 1000.0, r['id']), commit=True)
                return self.send(200, {'ok': True, 'photo': row_out(q('SELECT * FROM photos WHERE id=?', (r['id'],), one=True))})
            if path == '/api/album/update-now':   # 1.5: 폰에서 '지금 업데이트' — 새 버전이면 받아서 다시 켠다
                try:
                    msg = check_update()
                except Exception as e:
                    msg = '서버 확인 실패: ' + str(e)[:100]
                try:
                    web = update_web()
                except Exception as e:
                    web = '화면 갱신 실패: ' + str(e)[:80]
                return self.send(200, {'ok': True, 'result': f'{msg} · 화면: {web}', 'version': VERSION})
            if path == '/api/album/web-upload':   # 1.6: 폰 브라우저가 GitHub에서 받은 화면 파일(정해진 8개만)을 web 폴더에 넣는다 {files:{rel: base64}}
                import base64
                b = self.body_json(limit=6_000_000)
                files = b.get('files') if isinstance(b.get('files'), dict) else {}
                wd = os.path.join(BASE, 'web')
                saved = 0
                for rel, b64 in files.items():
                    if rel not in WEB_FILES:
                        continue
                    try:
                        data = base64.b64decode(str(b64))
                    except Exception:
                        continue
                    if rel == 'index.html' and (len(data) < 10_000 or b'</html>' not in data or b'const VER = ' not in data):
                        return self.err(400, 'index.html 모양이 아닙니다')
                    fp = os.path.join(wd, rel)
                    os.makedirs(os.path.dirname(fp), exist_ok=True)
                    with open(fp + '.new', 'wb') as f:
                        f.write(data)
                    os.replace(fp + '.new', fp)
                    saved += 1
                WEB_STATE['msg'] = f'브라우저로 {saved}개 받음'
                WEB_STATE['ts'] = time.time()
                print(f'[화면] 폰 브라우저가 받아 온 화면 파일 {saved}개 저장', flush=True)
                return self.send(200, {'ok': True, 'saved': saved})
            if path == '/api/album/published':   # 1.8: 브라우저가 대신 server-url.json을 적은 뒤 알려 준다
                b = self.body_json()
                u2 = str(b.get('url') or '')
                if b.get('ok') and u2:
                    PUBLISH_STATE['msg'] = '등록됨(브라우저)'
                    PUBLISH_STATE['url'] = u2
                    print('[주소] 브라우저가 server-url.json을 갱신했습니다:', u2, flush=True)
                else:
                    PUBLISH_STATE['msg'] = '브라우저 등록 실패: ' + str(b.get('msg') or '')[:80]
                return self.send(200, {'ok': True})
            if path == '/api/album/github-token':   # 1.4: 폰에서 GitHub 토큰 등록 → 공개 주소를 저장소에 바로 적는다
                b = self.body_json()
                m = re.search(r'(github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,})', str(b.get('token') or ''))
                if not m:
                    return self.err(400, 'github_pat_ 또는 ghp_ 로 시작하는 토큰을 붙여 넣어 주세요')
                CONF['github_token'] = m.group(1)
                write_conf(CONF)
                if TUNNEL_URL[0]:
                    publish_url(TUNNEL_URL[0])
                    return self.send(200, {'ok': True, 'published': PUBLISH_STATE['msg'], 'public_url': TUNNEL_URL[0]})
                return self.send(200, {'ok': True, 'published': '토큰 저장됨 — 공개 주소가 생기면 자동으로 적습니다', 'public_url': ''})
            if path == '/api/album/code':   # 접속코드 바꾸기(로그인한 사람 누구나 — 둘만 쓰는 서버). 빈 값은 받지 않음
                b = self.body_json()
                new = re.sub(r'[\s\-]', '', str(b.get('code') or ''))
                if len(new) < 4:
                    return self.err(400, '접속코드는 4자 이상으로 정하세요')
                CONF['code_hash'] = code_hash(new)
                write_conf(CONF)
                q('DELETE FROM sessions WHERE token<>?', (u['token'],), commit=True)   # 다른 폰은 새 코드로 다시 로그인
                print('[앨범] 접속코드 변경', flush=True)
                return self.send(200, {'ok': True, 'has_code': True})
            return self.err(404, '없는 주소입니다')
        except ValueError as e:
            return self.err(400, str(e))
        except (ConnectionError, TimeoutError, OSError):
            self.close_connection = True
        except Exception as e:
            print('[오류]', self.command, path, e, flush=True)
            try:
                self.err(500, '서버 오류')
            except Exception:
                pass

    def do_DELETE(self):
        self._body_read = False
        path = self.path.partition('?')[0]
        try:
            if not self.guard():
                return self.err(403, '허용되지 않은 요청입니다')
            u = self.auth()
            if not u:
                return self.err(401, '앨범 로그인이 필요합니다')
            if not u['admin']:   # 1.9: 지우기는 관리자만(⋯ 메뉴 → 관리자 로그인)
                return self.err(403, '지우기는 관리자만 할 수 있어요 (⋯ 메뉴 → 관리자 로그인)')
            mf = re.fullmatch(r'/api/album/folders/([a-f0-9]{16})', path)
            if mf:   # 1.3: 빈 폴더만 지울 수 있다(사진이 있으면 먼저 옮기거나 지우기)
                f = q('SELECT * FROM folders WHERE id=?', (mf.group(1),), one=True)
                if not f:
                    return self.err(404, '폴더가 없어요')
                n = q('SELECT COUNT(*) n FROM photos WHERE folder=?', (f['id'],), one=True)['n']
                if n:
                    return self.err(400, f'사진이 {n}장 들어 있어요. 먼저 옮기거나 지운 뒤 폴더를 지울 수 있어요')
                q('DELETE FROM folders WHERE id=?', (f['id'],), commit=True)
                d = os.path.join(PHOTOS, f['name'])
                try:
                    if os.path.isdir(d) and not os.listdir(d):
                        os.rmdir(d)
                except OSError:
                    pass
                return self.send(200, dict(ok=True, **folders_out()))
            m = re.fullmatch(r'/api/album/photos/([a-f0-9]{24})', path)
            if not m:
                return self.err(404, '없는 주소입니다')
            r = q('SELECT * FROM photos WHERE id=?', (m.group(1),), one=True)
            if not r:
                return self.err(404, '사진이 없습니다')
            fp = photo_path(r)
            for p in (fp, fp + '.t.jpg'):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError as e:
                    print('[앨범] 파일 삭제 실패:', p, e, flush=True)
            q('DELETE FROM photos WHERE id=?', (r['id'],), commit=True)
            q("UPDATE folders SET cover='' WHERE cover=?", (r['id'],), commit=True)
            print(f"[앨범] 삭제: {r['name']} ({(r['size'] or 0) // 1024}KB)", flush=True)
            return self.send(200, dict(ok=True, **usage()))
        except (ConnectionError, TimeoutError, OSError):
            self.close_connection = True
        except Exception as e:
            print('[오류]', self.command, path, e, flush=True)
            try:
                self.err(500, '서버 오류')
            except Exception:
                pass

    # --- 처리
    def login(self):
        ip = self.ip()
        now = time.time()
        with FAILS_LOCK:
            lst = [t for t in FAILS.get(ip, []) if now - t < LOGIN_WINDOW]
            FAILS[ip] = lst
            if len(lst) >= LOGIN_FAILS:
                return self.err(429, '여러 번 틀려 10분간 잠겼습니다. 잠시 후 다시 시도하세요')
        b = self.body_json()
        code = str(b.get('code') or '')
        who = str(b.get('who') or '').strip()
        if who not in WHO:
            who = ''
        h = str(conf_disk('code_hash') or '')
        if not (h and re.sub(r'[\s\-]', '', code) and secrets.compare_digest(code_hash(code), h)):
            with FAILS_LOCK:
                FAILS.setdefault(ip, []).append(now)
            print(f'[앨범] 접속코드 틀림 ({ip})', flush=True)
            return self.send(401, {'ok': False, 'error': '접속코드가 맞지 않습니다'})
        token = secrets.token_urlsafe(32)
        q('INSERT INTO sessions(token,who,created,seen,ip) VALUES(?,?,?,?,?)', (th(token), who, now, now, ip), commit=True)
        q('DELETE FROM sessions WHERE seen<?', (now - SESSION_DAYS * 86400,), commit=True)
        print(f'[앨범] 로그인 ({ip})', flush=True)
        return self.send(200, {'ok': True, 'token': token, 'who': who, 'admin': False, 'has_code': True})

    def upload(self, u, args):
        n = self.clen()
        if n <= 0:
            return self.err(400, '빈 파일입니다')
        if n > PHOTO_MAX:
            self.close_connection = True
            return self.err(413, '사진 1장은 30MB 이하만 올릴 수 있습니다')
        use = usage()
        if use['bytes'] + n > use['max_bytes']:
            self.close_connection = True
            return self.err(507, '앨범 저장 공간이 찼습니다(config.json의 max_store_mb를 늘리거나 사진을 지워 주세요)')
        name = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', '', (args.get('name') or [''])[0]).strip()[:120]
        memo = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', (args.get('memo') or [''])[0]).strip()[:300]
        taken = to_int((args.get('taken') or [''])[0], None, 0, 4102444800000)
        w = to_int((args.get('w') or [''])[0], 0, 0, 100000)
        h = to_int((args.get('h') or [''])[0], 0, 0, 100000)
        folder = (args.get('folder') or [''])[0]
        if folder and not q('SELECT id FROM folders WHERE id=?', (folder,), one=True):
            folder = ''
        fid = secrets.token_hex(12)
        fp = os.path.join(photo_dir(folder), fid)
        tmp = fp + '.up'
        head, left = b'', n
        try:
            with open(tmp, 'wb') as f:
                while left > 0:
                    b = self.rfile.read(min(262144, left))
                    if not b:
                        raise ConnectionError('업로드가 끊겼습니다')
                    if len(head) < 16:
                        head += b[:16]
                    f.write(b)
                    left -= len(b)
            self._body_read = True
            kind = sniff(head[:16])
            if not kind:
                return self.err(415, '사진(JPG·PNG·WEBP·GIF)만 올릴 수 있습니다')
            os.replace(tmp, fp)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        now = time.time()
        q('INSERT INTO photos(id,who,name,mime,size,w,h,memo,taken,ts,thumb,folder) VALUES(?,?,?,?,?,?,?,?,?,?,0,?)',
          (fid, u['who'], name or ('사진' + kind[1]), kind[0], n, w, h, memo, (taken / 1000.0) if taken else now, now, folder), commit=True)
        print(f'[앨범] 올림: {name or fid} ({n // 1024}KB)', flush=True)
        return self.send(200, dict(ok=True, photo=row_out(q('SELECT * FROM photos WHERE id=?', (fid,), one=True)), **usage()))

    def thumb_put(self, fid):
        r = q('SELECT * FROM photos WHERE id=?', (fid,), one=True)
        if not r:
            return self.err(404, '사진이 없습니다')
        n = self.clen()
        if n <= 0 or n > THUMB_MAX:
            self.close_connection = True
            return self.err(413, '미리보기 그림이 너무 큽니다')
        data = self.rfile.read(n)
        self._body_read = True
        if len(data) != n or not data.startswith(b'\xff\xd8\xff'):
            return self.err(415, 'JPEG만 받습니다')
        with open(photo_path(r) + '.t.jpg', 'wb') as f:
            f.write(data)
        q('UPDATE photos SET thumb=1 WHERE id=?', (fid,), commit=True)
        return self.send(200, {'ok': True})


UPDATE_PAGE = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>업데이트 도우미</title>
<style>body{font:15px/1.5 -apple-system,"Malgun Gothic",sans-serif;margin:0;padding:20px;background:#F3F4F6;color:#0B1B3F}h1{font-size:19px;margin:0 0 4px}p{color:#5F6672;margin:4px 0 14px;font-size:13px}
input{width:100%;box-sizing:border-box;padding:12px;border:2px solid #E2E5EA;border-radius:12px;font-size:17px;margin-bottom:10px}button{display:block;width:100%;padding:13px;border:0;border-radius:12px;background:#0B1B3F;color:#FDD000;font-weight:800;font-size:15px;margin-bottom:8px}
button.sub{background:#fff;color:#0B1B3F;border:2px solid #E2E5EA}pre{white-space:pre-wrap;word-break:break-all;background:#fff;border-radius:12px;padding:12px;font-size:12px;min-height:60px}a{color:#244EA2}</style></head><body>
<h1>사진 저장소 업데이트 도우미</h1><p>서버 __VER__ · 이 화면은 서버 안에 들어 있어 화면 파일이 없어도 열려요.</p>
<input id="code" type="password" inputmode="numeric" placeholder="접속코드">
<button id="b1">1. 서버가 GitHub에서 새 버전 받기 (서버·화면)</button>
<button id="b2" class="sub">2. 화면 파일만 이 폰 브라우저가 대신 받아 넣기</button>
<p>공개 주소가 "없음"이면: PC 브라우저로 <a href="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe">cloudflared 내려받기</a> → 파일 이름을 <b>cloudflared.exe</b>로 바꿔 <b>server</b> 폴더에 넣기 → 30초 안에 자동 시작</p>
<input id="tok" type="password" placeholder="GitHub 토큰 (github_pat_…) — 어디서든 접속용, 한 번만">
<button id="b4" class="sub">3. 토큰 등록 → kwonyujin119.github.io/test3 로 어디서든 접속</button>
<button id="b3" class="sub">서버 상태 보기</button>
<pre id="out">버튼을 누르면 결과가 여기에 나와요.</pre>
<p><a href="/">← 앨범으로</a></p>
<script>
const RAW='https://raw.githubusercontent.com/kwonyujin119/test3/main/';
const FILES=['index.html','manifest.webmanifest','sw.js','icons/icon-192.png','icons/icon-512.png','icons/icon-maskable-512.png','icons/apple-touch-icon.png','img/login.jpg'];
const out=m=>{document.getElementById('out').textContent=m;};
let TOKEN='';
async function login(){const code=document.getElementById('code').value.trim();if(!code){out('접속코드를 넣어 주세요');throw 0;}
 const r=await fetch('/api/album/login',{method:'POST',headers:{'X-ALBUM':'1','Content-Type':'application/json'},body:JSON.stringify({code})});const j=await r.json();if(!j.ok){out(j.error||'로그인 실패');throw 0;}TOKEN=j.token;}
const H=()=>({'X-ALBUM':'1','Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'});
document.getElementById('b1').onclick=async()=>{try{await login();out('서버가 GitHub에서 받는 중…');const r=await fetch('/api/album/update-now',{method:'POST',headers:H(),body:'{}'});const j=await r.json();out((j.result||JSON.stringify(j))+'\n\n새 버전을 받았다면 30초 뒤 이 페이지를 새로고침해 서버 번호를 확인하세요.');}catch(e){if(e)out('실패: '+e.message);}};
document.getElementById('b2').onclick=async()=>{try{await login();
 out('화면 파일 받는 중…');const files={};for(const f of FILES){const r=await fetch(RAW+f+'?t='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error(f+' 받기 실패 '+r.status);const buf=new Uint8Array(await r.arrayBuffer());let s='';for(let i=0;i<buf.length;i+=0x8000)s+=String.fromCharCode.apply(null,buf.subarray(i,i+0x8000));files[f]=btoa(s);}
 const r=await fetch('/api/album/web-upload',{method:'POST',headers:H(),body:JSON.stringify({files})});const j=await r.json();if(!j.ok)throw new Error(j.error);out('화면 파일 '+j.saved+'개 넣었어요. 앨범(/)을 다시 열면 새 화면이 나와요.');}catch(e){if(e)out('실패: '+(e.message||e));}};
async function publishViaBrowser(token,repo,url){const api='https://api.github.com/repos/'+repo+'/contents/server-url.json';const hd={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','Content-Type':'application/json'};let sha=null;try{const g=await fetch(api,{headers:hd,cache:'no-store'});if(g.ok){const cur=await g.json();sha=cur.sha;try{if(JSON.parse(atob(cur.content.replace(/\n/g,''))).url===url)return '이미 같은 주소가 등록돼 있어요';}catch(_){}}}catch(_){}
 const body={message:'서버 주소 갱신(브라우저)',content:btoa(unescape(encodeURIComponent(JSON.stringify({url,ts:Math.floor(Date.now()/1000)}))))};if(sha)body.sha=sha;const r=await fetch(api,{method:'PUT',headers:hd,body:JSON.stringify(body)});if(!r.ok)throw new Error('GitHub 응답 '+r.status+' — 토큰 권한(test3, Contents 읽기·쓰기)을 확인');return '등록됨';}
document.getElementById('b4').onclick=async()=>{try{await login();const token=document.getElementById('tok').value.trim();if(!token){out('토큰을 붙여 넣어 주세요');return;}out('등록하는 중…');const r=await fetch('/api/album/github-token',{method:'POST',headers:H(),body:JSON.stringify({token})});const j=await r.json();if(!j.ok)throw new Error(j.error);document.getElementById('tok').value='';
 let msg=j.published||'';if(j.public_url&&!/^등록됨/.test(msg)){out('서버가 직접 못 적어 이 브라우저가 대신 적는 중…');try{msg=await publishViaBrowser(token,'kwonyujin119/test3',j.public_url);await fetch('/api/album/published',{method:'POST',headers:H(),body:JSON.stringify({ok:true,url:j.public_url})});}catch(e){msg='브라우저 등록 실패: '+e.message;await fetch('/api/album/published',{method:'POST',headers:H(),body:JSON.stringify({ok:false,msg:e.message})});}}
 out(msg+(j.public_url?'\n공개 주소: '+j.public_url:'\n공개 주소가 아직 없어요(cloudflared). 위 안내대로 넣고 1분 뒤 다시 누르세요')+'\n\n"등록됨"이면 1~2분 뒤 https://kwonyujin119.github.io/test3/ 가 어디서든 열려요.');}catch(e){if(e)out('실패: '+(e.message||e));}};
document.getElementById('b3').onclick=async()=>{out(await (await fetch('/status',{cache:'no-store'})).text());};
</script></body></html>'''


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass


# ---------------------------------------------------------------- 자동 업데이트(GitHub의 새 버전을 받아 스스로 교체하고 종료 코드 75로 끝냄 → start.bat이 다시 켬)
def ver_tuple(v):
    return tuple(int(x) for x in re.findall(r'\d+', str(v)))


ALT_BASE = 'https://kwonyujin119.github.io/test3'   # 1.8: raw.githubusercontent.com이 막힌 망에서는 Pages에서 받는다(같은 파일)


def fetch_text(url, limit, timeout=30):
    import urllib.request
    last = None
    for u in (url, url.replace('https://raw.githubusercontent.com/kwonyujin119/test3/main', ALT_BASE)):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'album-server'}), timeout=timeout) as r:
                return r.read(limit).decode('utf-8')
        except Exception as e:
            last = e
            if u == url and ALT_BASE not in url:
                continue
            raise
    raise last


def upd_log(msg):
    try:
        with open(os.path.join(DATA, 'update.log'), 'a', encoding='utf-8') as f:
            f.write(datetime.datetime.now().isoformat(timespec='seconds') + ' ' + msg + '\n')
    except OSError:
        pass
    print('[업데이트]', msg, flush=True)


SRV_REF = [None]
UPDATE_LOCK = threading.Lock()


def check_update(apply=True):
    """GitHub의 서버 파일이 새 버전이면 받아서 교체하고 다시 켠다. 돌려주는 값: 사람이 읽을 결과 문구.
    start.bat으로 켰으면 종료 코드 75(bat이 다시 켬), 아니면 스스로 새 창을 띄우고 끝난다(1.5)."""
    me = os.path.abspath(__file__)
    flag = os.path.join(DATA, 'update_verify.flag')
    with UPDATE_LOCK:
        url = str(CONF.get('update_url') or '')
        if not url.startswith(('https://', 'http://127.0.0.1')):
            return '업데이트 주소가 없음'
        src = fetch_text(url + '?t=' + str(int(time.time())), 2_000_000)
        m = re.search(r"^VERSION = '([0-9.]+)'", src, re.M)
        if not m:
            raise ValueError('받은 파일에 VERSION이 없음')
        new = m.group(1)
        if ver_tuple(new) <= ver_tuple(VERSION):
            return f'지금이 최신({VERSION})'
        if 'def main()' not in src or 'ThreadingHTTPServer' not in src:
            raise ValueError('받은 파일이 서버 파일 같지 않음')
        compile(src, 'album_server.py', 'exec')
        if not apply:
            return f'새 버전 {new} 있음'
        shutil.copy2(me, me + '.bak')
        with open(me + '.new', 'w', encoding='utf-8', newline='') as f:
            f.write(src)
        os.replace(me + '.new', me)
        with open(flag, 'w', encoding='utf-8') as f:
            f.write(new)
        upd_log(f'새 버전 {new} 받음 — 다시 켭니다')
        threading.Thread(target=restart_self, daemon=True).start()
        return f'새 버전 {new} 받음 — 30초 뒤 새로고침하세요'


def restart_self():
    """답을 보낸 뒤 프로세스를 통째로 끝낸다(os._exit). srv.shutdown()을 먼저 부르면 주 스레드가 먼저 끝나 종료 코드가 0이 되는 문제(1.0~1.4)가 있었다."""
    time.sleep(2)
    if os.environ.get('ALBUM_LOOP') == '1':
        os._exit(75)   # start.bat이 바로 다시 켠다
    # start.bat 없이 켠 경우: 새 창에서 스스로 다시 켜고 이 창은 닫는다
    import subprocess
    me = os.path.abspath(__file__)
    try:
        if os.name == 'nt':
            subprocess.Popen([sys.executable, me], cwd=BASE, creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
        else:
            subprocess.Popen([sys.executable, me], cwd=BASE, start_new_session=True)
    except Exception as e:
        upd_log(f'다시 켜기 실패: {str(e)[:100]} — 수동으로 start.bat을 실행해 주세요')
        os._exit(1)
    os._exit(0)


def auto_update_loop(srv):
    SRV_REF[0] = srv
    flag = os.path.join(DATA, 'update_verify.flag')
    if os.path.exists(flag):   # 업데이트 직후: 1분 버티면 성공
        time.sleep(60)
        try:
            os.remove(flag)
        except OSError:
            pass
        upd_log(f'서버 {VERSION}로 업데이트 완료')
    while True:
        try:
            mins = max(5, float(CONF.get('update_check_min') or 10))
        except (TypeError, ValueError):
            mins = 10
        time.sleep(mins * 60)
        if not CONF.get('auto_update'):
            continue
        try:
            check_update()
        except Exception as e:
            upd_log(f'확인 실패(다음에 다시): {str(e)[:120]}')


TUNNEL_URL = ['']


def find_cloudflared():
    for d in (BASE, os.path.dirname(BASE)):
        for n in ('cloudflared.exe', 'cloudflared'):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return shutil.which('cloudflared')


PUBLISH_STATE = {'msg': '', 'url': ''}   # url: 저장소에 적힌 것으로 아는 주소
TUNNEL_STATE = {'msg': '준비 중'}


def publish_url(url):
    """공개 주소를 GitHub 저장소의 server-url.json에 적는다(화면이 읽어 서버를 찾음). 토큰이 없으면 건너뛴다."""
    import base64, urllib.request
    tok, repo = str(CONF.get('github_token') or ''), str(CONF.get('github_repo') or '')
    if not tok or not re.fullmatch(r'[A-Za-z0-9_\-]+/[A-Za-z0-9_.\-]+', repo):
        PUBLISH_STATE['msg'] = 'GitHub 토큰 없음'
        print('[주소] GitHub 토큰이 없어 server-url.json을 갱신하지 않습니다(화면 ⋯ 메뉴 → 어디서든 접속, 또는 github-token-setup.bat).', flush=True)
        return
    api = f'https://api.github.com/repos/{repo}/contents/server-url.json'
    hdr = {'Authorization': 'Bearer ' + tok, 'Accept': 'application/vnd.github+json', 'User-Agent': 'album-server', 'X-GitHub-Api-Version': '2022-11-28'}
    sha = None
    try:
        with urllib.request.urlopen(urllib.request.Request(api, headers=hdr), timeout=20) as r:
            cur = json.loads(r.read().decode('utf-8'))
            sha = cur.get('sha')
            try:
                old = json.loads(base64.b64decode(cur.get('content') or '').decode('utf-8'))
                if old.get('url') == url:
                    PUBLISH_STATE['msg'] = '등록됨'
                    PUBLISH_STATE['url'] = url
                    print('[주소] server-url.json이 이미 같은 주소입니다.', flush=True)
                    return
            except Exception:
                pass
    except Exception as e:
        if '404' not in str(e):
            print('[주소] server-url.json 확인 실패:', str(e)[:120], flush=True)
    body = {'message': '서버 주소 갱신 (' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M') + ')',
            'content': base64.b64encode(json.dumps({'url': url, 'ts': int(time.time())}).encode('utf-8')).decode('ascii')}
    if sha:
        body['sha'] = sha
    try:
        req = urllib.request.Request(api, data=json.dumps(body).encode('utf-8'), headers=dict(hdr, **{'Content-Type': 'application/json'}), method='PUT')
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        PUBLISH_STATE['msg'] = '등록됨'
        PUBLISH_STATE['url'] = url
        print('[주소] server-url.json 갱신 완료 — 1~2분 뒤 https://kwonyujin119.github.io/test3/ 가 이 서버로 붙습니다.', flush=True)
    except Exception as e:
        PUBLISH_STATE['msg'] = '서버가 직접 등록 실패(' + str(e)[:60] + ') — 앨범 화면을 열면 브라우저가 대신 등록'
        print('[주소] server-url.json 갱신 실패:', str(e)[:160], '— 앨범 화면(폰·PC)을 열면 브라우저가 대신 등록합니다', flush=True)


def ensure_cloudflared():
    """1.4: Windows에서 cloudflared.exe가 없으면 서버가 직접 내려받는다(PC를 만지지 않아도 공개 주소가 생기게)."""
    exe = find_cloudflared()
    if exe or os.name != 'nt':
        return exe
    import urllib.request
    url = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
    dst = os.path.join(BASE, 'cloudflared.exe')
    try:
        TUNNEL_STATE['msg'] = 'cloudflared 내려받는 중'
        print('[터널] cloudflared.exe를 내려받습니다(한 번만, 약 1분)…', flush=True)
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'album-server'}), timeout=120) as r, open(dst + '.part', 'wb') as f:
            shutil.copyfileobj(r, f)
        if os.path.getsize(dst + '.part') < 10_000_000:
            raise ValueError('받은 파일이 너무 작음')
        os.replace(dst + '.part', dst)
        print('[터널] cloudflared.exe 준비됨', flush=True)
        return dst
    except Exception as e:
        TUNNEL_STATE['msg'] = 'cloudflared 내려받기 실패: ' + str(e)[:60]
        print('[터널] cloudflared.exe 내려받기 실패:', str(e)[:120], flush=True)
        try:
            os.remove(dst + '.part')
        except OSError:
            pass
        return None


WEB_STATE = {'msg': '아직 안 받음', 'ts': 0}
WEB_FILES = ['index.html', 'manifest.webmanifest', 'sw.js', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/icon-maskable-512.png', 'icons/apple-touch-icon.png', 'img/login.jpg']


def update_web():
    """1.4: 화면 파일을 GitHub(main)에서 받아 web\\ 폴더에 둔다 — PC의 옛 화면 파일을 손대지 않아도 최신 화면이 나온다."""
    import urllib.request
    base = str(CONF.get('update_url') or '').rsplit('/server/', 1)[0]
    if not base.startswith(('https://', 'http://127.0.0.1')):
        return
    wd = os.path.join(BASE, 'web')
    changed = 0
    errors = []
    for rel in WEB_FILES:
        try:
            data = None
            for b2 in (base, ALT_BASE):
                try:
                    with urllib.request.urlopen(urllib.request.Request(f'{b2}/{rel}?t={int(time.time())}', headers={'User-Agent': 'album-server'}), timeout=30) as r:
                        data = r.read(20_000_000)
                    break
                except Exception as e2:
                    if b2 == ALT_BASE:
                        raise e2
            if rel == 'index.html' and (len(data) < 10_000 or b'</html>' not in data):
                raise ValueError('index.html 모양이 아님')
            fp = os.path.join(wd, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            if os.path.exists(fp) and open(fp, 'rb').read() == data:
                continue
            with open(fp + '.new', 'wb') as f:
                f.write(data)
            os.replace(fp + '.new', fp)
            changed += 1
        except Exception as e:
            errors.append(f'{rel}: {str(e)[:90]}')
            print('[화면]', rel, '받기 실패:', str(e)[:100], flush=True)
            if rel == 'index.html':
                WEB_STATE['msg'] = '받기 실패: ' + str(e)[:90]
                upd_log('화면 파일 받기 실패: ' + str(e)[:120])
                return WEB_STATE['msg']
    WEB_STATE['msg'] = (f'{changed}개 갱신' if changed else '이미 최신') + (f' (실패 {len(errors)})' if errors else '')
    WEB_STATE['ts'] = time.time()
    if changed:
        print(f'[화면] 화면 파일 {changed}개 갱신(web 폴더)', flush=True)
    return WEB_STATE['msg']


def web_update_loop():
    while True:
        ok = False
        try:
            ok = not str(update_web() or '').startswith('받기 실패')
        except Exception as e:
            WEB_STATE['msg'] = '갱신 실패: ' + str(e)[:90]
            print('[화면] 갱신 실패:', str(e)[:100], flush=True)
        time.sleep((max(5, float(CONF.get('update_check_min') or 10)) * 60) if ok else 60)


def tunnel_loop(port):
    """cloudflared로 공개 주소(https://…trycloudflare.com)를 만든다. 서버를 다시 켜면 주소가 바뀐다 → publish_url이 저장소에 적는다."""
    import subprocess
    exe = ensure_cloudflared()
    while not exe:   # 내려받기에 실패해도(인증서 문제 등) server 폴더에 cloudflared.exe를 넣어 주면 30초 안에 시작한다
        TUNNEL_STATE['msg'] = (TUNNEL_STATE['msg'] if 'cloudflared' in TUNNEL_STATE['msg'] else 'cloudflared 없음') + ' — server 폴더에 cloudflared.exe를 넣으면 바로 시작'
        time.sleep(30)
        exe = find_cloudflared()
    TUNNEL_STATE['msg'] = '공개 주소 만드는 중'
    while True:
        try:
            p = subprocess.Popen([exe, 'tunnel', '--no-autoupdate', '--url', f'http://127.0.0.1:{port}'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
            for line in p.stdout:
                m = re.search(r'https://(?!api\.)[a-z0-9\-]+\.trycloudflare\.com', line)
                if m and 'failed' not in line.lower() and not TUNNEL_URL[0]:
                    TUNNEL_URL[0] = m.group(0)
                    try:
                        with open(os.path.join(DATA, 'url.txt'), 'w', encoding='utf-8') as f:
                            f.write(TUNNEL_URL[0] + '\n')
                    except OSError:
                        pass
                    print('=' * 70 + f'\n  바깥(이동통신)에서 여는 주소: {TUNNEL_URL[0]}   (서버를 다시 켜면 바뀜 · data\\url.txt에도 저장)\n' + '=' * 70, flush=True)
                    threading.Thread(target=publish_url, args=(TUNNEL_URL[0],), daemon=True).start()
            p.wait()
        except OSError as e:
            TUNNEL_STATE['msg'] = 'cloudflared 실행 실패'
            print('[터널] cloudflared를 실행할 수 없습니다:', e, flush=True)
            return
        TUNNEL_URL[0] = ''
        TUNNEL_STATE['msg'] = '공개 주소 다시 만드는 중'
        time.sleep(15)


def lan_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return '127.0.0.1'


def main():
    if '--set-code' in sys.argv:
        new = re.sub(r'[\s\-]', '', ' '.join(sys.argv[sys.argv.index('--set-code') + 1:]))
        if len(new) < 4:
            print('접속코드는 4자 이상으로 정하세요.')
            sys.exit(1)
        CONF['code_hash'] = code_hash(new)
        write_conf(CONF)
        print('접속코드 저장 완료 (config.json에는 해시로만 저장). 이미 켜진 서버도 다음 로그인부터 새 코드를 씁니다.')
        return
    if '--set-admin-code' in sys.argv:
        new = re.sub(r'[\s\-]', '', ' '.join(sys.argv[sys.argv.index('--set-admin-code') + 1:]))
        if len(new) < 4:
            print('관리자 코드는 4자 이상으로 정하세요.')
            sys.exit(1)
        CONF['admin_code_hash'] = code_hash(new)
        write_conf(CONF)
        print('관리자 코드 저장 완료 (config.json에는 해시로만 저장).')
        return
    if '--set-github-token' in sys.argv:
        raw = ' '.join(sys.argv[sys.argv.index('--set-github-token') + 1:])
        m = re.search(r'(github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,})', raw)
        if not m:
            print('GitHub 토큰을 찾지 못했습니다. github_pat_ 또는 ghp_ 로 시작하는 토큰을 붙여 넣으세요.')
            sys.exit(1)
        CONF['github_token'] = m.group(1)
        write_conf(CONF)
        print('GitHub 토큰 저장 완료 (' + m.group(1)[:14] + '…). 서버를 켜면 공개 주소를 저장소에 자동으로 적습니다.')
        return
    if '--set-photos-dir' in sys.argv:
        d = ' '.join(sys.argv[sys.argv.index('--set-photos-dir') + 1:]).strip().strip('"')
        if not d:
            print('폴더 경로를 적어 주세요. 예: --set-photos-dir D:\\사진저장소')
            sys.exit(1)
        os.makedirs(d, exist_ok=True)
        CONF['photos_dir'] = d
        write_conf(CONF)
        print('사진 폴더 저장 완료:', d, '(서버를 다시 켜면 적용. 이미 올린 사진은 옛 폴더의 파일을 새 폴더로 옮겨 주세요)')
        return
    port = int(to_int(CONF.get('port'), 4848, 1, 65535))
    srv = None
    for attempt in range(15):   # 업데이트로 다시 켤 때 이전 프로세스가 포트를 놓을 때까지 잠깐 기다린다
        try:
            srv = Server(('0.0.0.0', port), H)
            break
        except OSError as e:
            if attempt == 14:
                print('[오류] 서버를 시작하지 못했습니다:', e)
                print(f'  포트 {port}을(를) 다른 프로그램이 쓰고 있을 수 있습니다. data\\config.json의 port를 바꿔 보세요.')
                sys.exit(1)
            time.sleep(1)
    line = '=' * 70
    print(line)
    print(f'  유진·아름 사진 저장소 서버 {VERSION}   종료: 이 창에서 Ctrl+C')
    print(f'  이 PC에서:        http://localhost:{port}')
    print(f'  같은 와이파이 폰: http://{lan_ip()}:{port}   ← 폰 브라우저에 이 주소를 입력 (홈 화면에 추가해 두면 편함)')
    print(f'  사진 폴더:        {PHOTOS}' + ('' if web_dir() else '   [주의] 화면 파일(index.html)을 찾지 못함'))
    print(f'  접속코드:         설정됨 (바꾸기: set-code.bat)')
    print(f'  자동 업데이트:    {"켜짐(10분마다 확인)" if CONF.get("auto_update") else "꺼짐"}')
    print(f'  바깥 접속:        ' + ('cloudflared 없음 — start.bat이 받지 못했으면 server 폴더에 cloudflared.exe를 넣어 주세요' if not find_cloudflared() else ('공개 주소 만드는 중… (아래에 뜸)' + ('' if CONF.get('github_token') else ' · GitHub 토큰 없음 → github-token-setup.bat 실행하면 화면이 주소를 자동으로 찾음'))))
    print(line, flush=True)
    threading.Thread(target=auto_update_loop, args=(srv,), daemon=True).start()
    if CONF.get('auto_update'):
        threading.Thread(target=web_update_loop, daemon=True).start()
    if str(CONF.get('tunnel') or 'auto') != 'off':
        threading.Thread(target=tunnel_loop, args=(port,), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n종료합니다.')


if __name__ == '__main__':
    main()
