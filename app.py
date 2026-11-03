"""합성 개념과 문제로 학습·채점·복습을 보여 주는 로컬 데모 서버."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from scheduler import ReviewCard, ReviewPriority, sm2_update

# 예제는 공개 후보를 위해 새로 작성했으며 외부 교재에서 가져오지 않았다.
CONCEPTS = [
    {"id": "c1", "title": "함수의 입력과 출력", "note": "함수는 각 입력에 하나의 출력을 대응시킵니다. 예를 들어 f(x)=2x이면 입력 3의 출력은 6입니다.", "question": "f(x)=2x일 때 f(3)은?", "answer": "6", "explanation": "3을 대입하면 2 × 3 = 6입니다."},
    {"id": "c2", "title": "평균", "note": "산술평균은 값의 합을 값의 개수로 나눈 것입니다.", "question": "2와 4의 산술평균은?", "answer": "3", "explanation": "(2 + 4) ÷ 2 = 3입니다."},
]
ROOT = Path(__file__).resolve().parent

# 저장소 밖에도 명시적으로 지정할 수 있는 SQLite 연결을 만든다.
def connect(db_path):
    db = sqlite3.connect(db_path, timeout=5)
    db.row_factory = sqlite3.Row
    return db

# 예제 문제별 복습 상태를 저장할 테이블을 준비한다.
def initialize(db_path):
    with connect(db_path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS review (id TEXT PRIMARY KEY, passes INTEGER NOT NULL, interval INTEGER NOT NULL, ease REAL NOT NULL, priority TEXT NOT NULL, due TEXT)")

# 상태는 개인 학습 데이터가 아닌 사용자가 데모에서 만든 새 기록이다.
def get_state(db_path):
    with connect(db_path) as db:
        rows = {row['id']: dict(row) for row in db.execute('SELECT * FROM review')}
    return [{**{k: v for k, v in c.items() if k not in ('answer', 'explanation')}, 'review': rows.get(c['id'])} for c in CONCEPTS]

# 단답을 비교하고 원본 스케줄러를 이용해 해당 카드 상태를 갱신한다.
def answer(db_path, concept_id, value):
    concept = next((c for c in CONCEPTS if c['id'] == concept_id), None)
    if concept is None:
        raise ValueError('없는 개념입니다.')
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError('답은 200자 이하의 문자열이어야 합니다.')
    normalize = lambda s: ' '.join(s.strip().lower().split())
    passed = normalize(value) == normalize(concept['answer'])
    with connect(db_path) as db:
        # 동시에 온 제출도 카드 읽기부터 저장까지 직렬화한다.
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM review WHERE id=?', (concept_id,)).fetchone()
        card = ReviewCard(row['passes'], row['interval'], row['ease'], ReviewPriority(row['priority']), datetime.fromisoformat(row['due']) if row['due'] else None) if row else ReviewCard()
        # 예정일 전에 반복해서 맞혀도 복습 간격이 인위적으로 늘지 않는다.
        early = passed and row is not None and card.priority == ReviewPriority.scheduled and card.next_review_at > datetime.now(timezone.utc)
        if not early:
            sm2_update(card, passed)
        db.execute('INSERT OR REPLACE INTO review VALUES (?, ?, ?, ?, ?, ?)', (concept_id, card.consecutive_passes, card.interval, card.ease, card.priority.value, card.next_review_at.isoformat()))
    return {'passed': passed, 'answer': concept['answer'], 'explanation': concept['explanation'], 'interval': card.interval, 'priority': card.priority.value, 'due': card.next_review_at.isoformat(), 'schedule_changed': not early}

# 외부 모델 없이 준비된 예시 답만 반환한다.
def mock_tutor(concept_id):
    concept = next((c for c in CONCEPTS if c['id'] == concept_id), None)
    if concept is None:
        raise ValueError('없는 개념입니다.')
    return {'reply': '모의 튜터: ' + concept['note'] + ' 문제를 직접 푼 다음 답을 확인해 보세요.'}

# HTTP 경로를 화이트리스트로 제한해 임의 파일 제공을 막는다.
def make_handler(db_path):
    class Handler(BaseHTTPRequestHandler):
        # 브라우저의 DNS 재바인딩을 줄이기 위해 로컬 호스트만 허용한다.
        def local_host(self):
            port = self.server.server_port
            allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
            if port == 80:
                allowed.update({'127.0.0.1', 'localhost'})
            return self.headers.get('Host', '').lower() in allowed

        def respond(self, code, body, content_type='application/json; charset=utf-8'):
            raw = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, dict) else body
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if not self.local_host():
                return self.respond(403, {'error': '허용되지 않은 호스트입니다.'})
            path = urlparse(self.path).path
            if path == '/api/concepts':
                return self.respond(200, {'concepts': get_state(db_path)})
            if path == '/api/health':
                return self.respond(200, {'status': 'ok', 'mode': 'mock'})
            if path in ('/', '/index.html', '/app.js', '/style.css'):
                name = 'index.html' if path == '/' else path[1:]
                kind = {'index.html': 'text/html', 'app.js': 'text/javascript', 'style.css': 'text/css'}[name]
                return self.respond(200, (ROOT / name).read_bytes(), kind + '; charset=utf-8')
            return self.respond(404, {'error': '찾을 수 없습니다.'})

        def do_POST(self):
            if not self.local_host():
                return self.respond(403, {'error': '허용되지 않은 호스트입니다.'})
            origin = self.headers.get('Origin')
            if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
                return self.respond(403, {'error': '허용되지 않은 출처입니다.'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.respond(415, {'error': 'JSON이 필요합니다.'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if size < 1 or size > 4096:
                    raise ValueError('요청 크기가 올바르지 않습니다.')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('JSON 객체가 필요합니다.')
                if self.path == '/api/answer':
                    return self.respond(200, answer(db_path, data.get('id'), data.get('answer')))
                if self.path == '/api/tutor':
                    return self.respond(200, mock_tutor(data.get('id')))
                return self.respond(404, {'error': '찾을 수 없습니다.'})
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                return self.respond(400, {'error': str(exc)})
    return Handler

# 네트워크 공개가 아닌 자신의 컴퓨터에서만 접속하는 데모다.
def main():
    parser = argparse.ArgumentParser(description='로컬 합성 학습 데모')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--db', default='demo.sqlite3')
    args = parser.parse_args()
    initialize(args.db)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(args.db))
    print(f'http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
