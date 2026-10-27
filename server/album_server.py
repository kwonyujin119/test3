# -*- coding: utf-8 -*-
r"""
유진·아름 사진 저장소 — 독립 서버 (다른 프로그램·도메인 불필요, 파이썬 표준 라이브러리만 사용)

  폴더 구성(이 파일이 있는 곳 기준)
    data\config.json   설정(포트·접속코드 해시·허용 주소·사진 폴더)
    data\album.db      사진 목록(SQLite)
    사진\               사진 원본(<id>) + 미리보기(<id>.t.jpg)  ← config.json의 photos_dir로 바꿀 수 있음

  실행: start.bat (자동 업데이트 포함)  /  접속코드 바꾸기: set-code.bat 또는 --set-code 새코드
  화면: 이 서버가 직접 보여 준다 — 같은 와이파이의 폰·PC에서 http://<이 PC 주소>:4848 을 연다(도메인 불필요)
        (화면 파일 index.html 등은 이 폴더의 상위 폴더 또는 web\ 폴더에서 찾는다)
  바깥(이동통신)에서도 쓰려면: 이 폴더에 cloudflared.exe 를 두면 켤 때마다 임시 공개 주소(trycloudflare.com)를 만들어 보여 준다(선택)
"""
import datetime, hashlib, json, os, re, secrets, shutil, sqlite3, sys, threading, time, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

VERSION = '1.1'
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


def code_hash(code):
    code = re.sub(r'[\s\-]', '', str(code or '')).lower()
    return hashlib.pbkdf2_hmac('sha256', code.encode('utf-8'), CODE_SALT, 200000).hex()


# ---------------------------------------------------------------- 설정
CONF_LOCK = threading.Lock()


def load_conf():
    defaults = {
        'port': 4848,
        'code_hash': CODE_HASH_DEFAULT,                 # 접속코드(해시로만 저장)
        'photos_dir': os.path.join(BASE, '사진'),       # 사진이 저장되는 폴더(다른 드라이브·폴더로 바꿀 수 있음)
        'max_store_mb': 20480,                          # 사진 총량(MB)
        'allowed_origins': ['https://kwonyujin119.github.io'],   # 화면(github.io)에서 오는 요청 허용
        'auto_update': True,                            # GitHub의 server/album_server.py가 새 버전이면 스스로 교체하고 다시 켬
        'update_url': 'https://raw.githubusercontent.com/kwonyujin119/test3/main/server/album_server.py',
        'update_check_min': 10,
        'tunnel': 'auto',                               # auto: 이 폴더(또는 상위)에 cloudflared.exe가 있으면 임시 공개 주소를 만든다 / off: 안 만든다
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
''')
DB.commit()


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
            'memo': r['memo'] or '', 'taken': r['taken'], 'ts': r['ts'], 'thumb': bool(r['thumb'])}


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
        return {'who': r['who'] or '', 'token': r['token']}

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
            if path == '/api/album/me':
                return self.send(200, dict(ok=True, who=u['who'], admin=True, has_code=bool(CONF.get('code_hash')), version=VERSION, **usage()))
            if path == '/api/album/photos':
                rows = q('SELECT * FROM photos ORDER BY taken DESC, ts DESC LIMIT 20000')
                return self.send(200, dict(ok=True, photos=[row_out(r) for r in rows], **usage()))
            m = re.fullmatch(r'/api/album/(file|thumb)/([a-f0-9]{24})', path)
            if m:
                r = q('SELECT * FROM photos WHERE id=?', (m.group(2),), one=True)
                if not r:
                    return self.err(404, '사진이 없습니다')
                fp = os.path.join(PHOTOS, r['id'])
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
            if path == '/api/album/logout':
                q('DELETE FROM sessions WHERE token=?', (u['token'],), commit=True)
                return self.send(200, {'ok': True})
            if path == '/api/album/upload':
                return self.upload(u, args)
            m = re.fullmatch(r'/api/album/thumb/([a-f0-9]{24})', path)
            if m:
                return self.thumb_put(m.group(1))
            m = re.fullmatch(r'/api/album/photos/([a-f0-9]{24})', path)
            if m:
                b = self.body_json()
                r = q('SELECT id FROM photos WHERE id=?', (m.group(1),), one=True)
                if not r:
                    return self.err(404, '사진이 없습니다')
                if 'memo' in b:
                    memo = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(b.get('memo') or '')).strip()[:300]
                    q('UPDATE photos SET memo=? WHERE id=?', (memo, r['id']), commit=True)
                if 'taken' in b:
                    tk = to_int(b.get('taken'), None, 0, 4102444800000)
                    if tk:
                        q('UPDATE photos SET taken=? WHERE id=?', (tk / 1000.0, r['id']), commit=True)
                return self.send(200, {'ok': True, 'photo': row_out(q('SELECT * FROM photos WHERE id=?', (r['id'],), one=True))})
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
            m = re.fullmatch(r'/api/album/photos/([a-f0-9]{24})', path)
            if not m:
                return self.err(404, '없는 주소입니다')
            r = q('SELECT * FROM photos WHERE id=?', (m.group(1),), one=True)
            if not r:
                return self.err(404, '사진이 없습니다')
            fp = os.path.join(PHOTOS, r['id'])
            for p in (fp, fp + '.t.jpg'):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError as e:
                    print('[앨범] 파일 삭제 실패:', p, e, flush=True)
            q('DELETE FROM photos WHERE id=?', (r['id'],), commit=True)
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
        return self.send(200, {'ok': True, 'token': token, 'who': who, 'admin': True, 'has_code': True})

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
        fid = secrets.token_hex(12)
        fp = os.path.join(PHOTOS, fid)
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
        q('INSERT INTO photos(id,who,name,mime,size,w,h,memo,taken,ts,thumb) VALUES(?,?,?,?,?,?,?,?,?,?,0)',
          (fid, u['who'], name or ('사진' + kind[1]), kind[0], n, w, h, memo, (taken / 1000.0) if taken else now, now), commit=True)
        print(f'[앨범] 올림: {name or fid} ({n // 1024}KB)', flush=True)
        return self.send(200, dict(ok=True, photo=row_out(q('SELECT * FROM photos WHERE id=?', (fid,), one=True)), **usage()))

    def thumb_put(self, fid):
        if not q('SELECT id FROM photos WHERE id=?', (fid,), one=True):
            return self.err(404, '사진이 없습니다')
        n = self.clen()
        if n <= 0 or n > THUMB_MAX:
            self.close_connection = True
            return self.err(413, '미리보기 그림이 너무 큽니다')
        data = self.rfile.read(n)
        self._body_read = True
        if len(data) != n or not data.startswith(b'\xff\xd8\xff'):
            return self.err(415, 'JPEG만 받습니다')
        with open(os.path.join(PHOTOS, fid + '.t.jpg'), 'wb') as f:
            f.write(data)
        q('UPDATE photos SET thumb=1 WHERE id=?', (fid,), commit=True)
        return self.send(200, {'ok': True})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass


# ---------------------------------------------------------------- 자동 업데이트(GitHub의 새 버전을 받아 스스로 교체하고 종료 코드 75로 끝냄 → start.bat이 다시 켬)
def ver_tuple(v):
    return tuple(int(x) for x in re.findall(r'\d+', str(v)))


def fetch_text(url, limit, timeout=30):
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'album-server'}), timeout=timeout) as r:
        return r.read(limit).decode('utf-8')


def upd_log(msg):
    try:
        with open(os.path.join(DATA, 'update.log'), 'a', encoding='utf-8') as f:
            f.write(datetime.datetime.now().isoformat(timespec='seconds') + ' ' + msg + '\n')
    except OSError:
        pass
    print('[업데이트]', msg, flush=True)


def auto_update_loop(srv):
    me = os.path.abspath(__file__)
    flag = os.path.join(DATA, 'update_verify.flag')
    if os.path.exists(flag):   # 업데이트 직후: 1분 버티면 성공
        time.sleep(60)
        try:
            os.remove(flag)
        except OSError:
            pass
        upd_log(f'서버 {VERSION}로 업데이트 완료')
    if os.environ.get('ALBUM_LOOP') != '1':
        return   # start.bat으로 켠 게 아니면 교체하지 않는다(꺼진 채로 남지 않게)
    while True:
        try:
            mins = max(5, float(CONF.get('update_check_min') or 10))
        except (TypeError, ValueError):
            mins = 10
        time.sleep(mins * 60)
        if not CONF.get('auto_update'):
            continue
        try:
            url = str(CONF.get('update_url') or '')
            if not url.startswith('https://'):
                continue
            src = fetch_text(url + '?t=' + str(int(time.time())), 2_000_000)
            m = re.search(r"^VERSION = '([0-9.]+)'", src, re.M)
            if not m or ver_tuple(m.group(1)) <= ver_tuple(VERSION):
                continue
            if 'def main()' not in src or 'ThreadingHTTPServer' not in src:
                raise ValueError('받은 파일이 서버 파일 같지 않음')
            compile(src, 'album_server.py', 'exec')
            shutil.copy2(me, me + '.bak')
            with open(me + '.new', 'w', encoding='utf-8', newline='') as f:
                f.write(src)
            os.replace(me + '.new', me)
            with open(flag, 'w', encoding='utf-8') as f:
                f.write(m.group(1))
            upd_log(f'새 버전 {m.group(1)} 받음 — 다시 켭니다')
            threading.Thread(target=srv.shutdown, daemon=True).start()
            time.sleep(3)
            os._exit(75)
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


def tunnel_loop(port):
    """선택 기능: cloudflared가 있으면 임시 공개 주소(https://…trycloudflare.com)를 만든다. 서버를 다시 켜면 주소가 바뀐다."""
    import subprocess
    exe = find_cloudflared()
    if not exe:
        return
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
            p.wait()
        except OSError as e:
            print('[터널] cloudflared를 실행할 수 없습니다:', e, flush=True)
            return
        TUNNEL_URL[0] = ''
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
    try:
        srv = Server(('0.0.0.0', port), H)
    except OSError as e:
        print('[오류] 서버를 시작하지 못했습니다:', e)
        print(f'  포트 {port}을(를) 다른 프로그램이 쓰고 있을 수 있습니다. data\\config.json의 port를 바꿔 보세요.')
        sys.exit(1)
    line = '=' * 70
    print(line)
    print(f'  유진·아름 사진 저장소 서버 {VERSION}   종료: 이 창에서 Ctrl+C')
    print(f'  이 PC에서:        http://localhost:{port}')
    print(f'  같은 와이파이 폰: http://{lan_ip()}:{port}   ← 폰 브라우저에 이 주소를 입력 (홈 화면에 추가해 두면 편함)')
    print(f'  사진 폴더:        {PHOTOS}' + ('' if web_dir() else '   [주의] 화면 파일(index.html)을 찾지 못함'))
    print(f'  접속코드:         설정됨 (바꾸기: set-code.bat)')
    print(f'  자동 업데이트:    {"켜짐(10분마다 확인)" if CONF.get("auto_update") else "꺼짐"}' + ('' if find_cloudflared() or str(CONF.get('tunnel')) == 'off' else '   · 바깥에서도 쓰려면 이 폴더에 cloudflared.exe 를 두세요(선택)'))
    print(line, flush=True)
    threading.Thread(target=auto_update_loop, args=(srv,), daemon=True).start()
    if str(CONF.get('tunnel') or 'auto') != 'off':
        threading.Thread(target=tunnel_loop, args=(port,), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n종료합니다.')


if __name__ == '__main__':
    main()
