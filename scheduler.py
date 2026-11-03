"""원본 복습 스케줄러의 간격 갱신 부분을 독립 실행용으로 발췌했다."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

# 원본의 복습 우선순위를 단순한 문자열 열거형으로 제공한다.
class ReviewPriority(str, Enum):
    scheduled = "scheduled"
    wrong_first = "wrong_first"

# 원본 함수가 필요로 하는 카드 필드만 제공한다.
@dataclass
class ReviewCard:
    consecutive_passes: int = 0
    interval: int = 1
    ease: float = 2.3
    priority: ReviewPriority = ReviewPriority.scheduled
    next_review_at: datetime | None = None

# 원본의 간격표를 보존한다.
INTERVALS = [1, 3, 7, 14, 30]


def sm2_update(card: ReviewCard, passed: bool) -> None:
    """SM-2 간격 갱신 — 실패 시 리셋 + 즉시 재복습(오답 우선 큐 당일 노출).
    WHAT: consecutive_passes, interval, ease, priority, next_review_at 갱신.
    WHY: 통과 시 간격 확대; 실패 시 wrong_first·next_review_at=now.
    HOW: passed 분기; INTERVALS[idx]; ease ±0.1 cap 3.0.
    """
    now = datetime.now(timezone.utc)
    if passed:
        card.consecutive_passes += 1
        idx = min(card.consecutive_passes - 1, len(INTERVALS) - 1)
        card.interval = INTERVALS[idx]
        card.ease = min(card.ease + 0.1, 3.0)
        card.priority = ReviewPriority.scheduled
        card.next_review_at = now + timedelta(days=card.interval)
    else:
        card.consecutive_passes = 0
        card.interval = 1
        card.ease = 2.3
        card.priority = ReviewPriority.wrong_first
        card.next_review_at = now
