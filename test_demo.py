"""합성 예제와 격리 DB만 사용하는 로컬 데모 검증."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from scheduler import ReviewCard, ReviewPriority, sm2_update

# 복습 스케줄러의 실패 초기화와 연속 정답 간격을 검증한다.
class SchedulerTest(unittest.TestCase):
    def test_success_and_retry(self):
        card = ReviewCard()
        for expected in (1, 3, 7, 14, 30, 30):
            sm2_update(card, True)
            self.assertEqual(card.interval, expected)
            self.assertEqual(card.priority, ReviewPriority.scheduled)
        sm2_update(card, False)
        self.assertEqual((card.consecutive_passes, card.interval, card.priority), (0, 1, ReviewPriority.wrong_first))
        self.assertLessEqual(abs((datetime.now(timezone.utc) - card.next_review_at).total_seconds()), 3)
        sm2_update(card, True)
        self.assertEqual((card.consecutive_passes, card.interval, card.priority), (1, 1, ReviewPriority.scheduled))

# 실제 HTTP 서버를 띄우고 요청·저장·재시작을 확인한다.
class HttpFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / 'sample.sqlite3')
        self.start_server()

    def start_server(self):
        self.process = subprocess.Popen([sys.executable, '-u', 'app.py', '--port', '0', '--db', self.db], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.base = self.process.stdout.readline().strip()
        self.assertTrue(self.base.startswith('http://127.0.0.1:'))

    def stop_server(self):
        self.process.terminate()
        self.process.wait(timeout=5)
        self.process.stdout.close()

    def tearDown(self):
        self.stop_server()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        raw = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=raw, headers={'Content-Type':'application/json', **(headers or {})})
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.load(response)

    def test_learning_review_and_persistence(self):
        self.assertEqual(self.request('/api/health')[1]['mode'], 'mock')
        concepts = self.request('/api/concepts')[1]['concepts']
        self.assertEqual(len(concepts), 2)
        self.assertNotIn('answer', concepts[0])
        self.assertIn('모의 튜터', self.request('/api/tutor', {'id':'c1'})[1]['reply'])
        wrong = self.request('/api/answer', {'id':'c1', 'answer':'5'})[1]
        self.assertFalse(wrong['passed'])
        self.assertEqual((wrong['answer'], wrong['priority']), ('6', 'wrong_first'))
        right = self.request('/api/answer', {'id':'c1', 'answer':' 6 '})[1]
        self.assertTrue(right['passed'])
        self.assertEqual((right['priority'], right['interval']), ('scheduled', 1))
        early = self.request('/api/answer', {'id':'c1', 'answer':'6'})[1]
        self.assertFalse(early['schedule_changed'])
        self.assertEqual((early['interval'], early['due']), (1, right['due']))
        # 테스트 전용 DB에서 예정 시각을 과거로 바꿔 실제 복습을 재현한다.
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE review SET due='2000-01-01T00:00:00+00:00' WHERE id='c1'")
        due = self.request('/api/answer', {'id':'c1', 'answer':'6'})[1]
        self.assertTrue(due['schedule_changed'])
        self.assertEqual(due['interval'], 3)
        # 예정일 전 오답도 즉시 재복습으로 돌아간다.
        retry = self.request('/api/answer', {'id':'c1', 'answer':'5'})[1]
        self.assertEqual((retry['priority'], retry['interval']), ('wrong_first', 1))
        self.request('/api/answer', {'id':'c1', 'answer':'6'})
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request('/api/concepts')[1]['concepts'][0]['review']['passes'], 1)

    def test_rejects_invalid_or_cross_origin_request(self):
        for path, body, headers, status in [('/api/answer', {'id':'unknown', 'answer':'1'}, {}, 400), ('/api/answer', {'id':'c1', 'answer':'6'}, {'Origin':'https://example.invalid'}, 403), ('/api/answer', {'id':'c1', 'answer':'6'}, {'Host':'example.invalid'}, 403), ('/api/answer', {'id':'c1', 'answer':7}, {}, 400)]:
            with self.assertRaises(urllib.error.HTTPError) as err:
                self.request(path, body, headers)
            self.assertEqual(err.exception.code, status)
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(self.base + '/scheduler.py', timeout=5)
        self.assertEqual(err.exception.code, 404)
        for path in ('/../app.py', '/%2e%2e/app.py', '/.git/config', '/demo.sqlite3'):
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(self.base + path, timeout=5)
            self.assertEqual(err.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.request('/api/concepts', headers={'Host':'example.invalid'})
        self.assertEqual(err.exception.code, 403)

if __name__ == '__main__':
    unittest.main()
