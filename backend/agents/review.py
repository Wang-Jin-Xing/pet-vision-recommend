"""人工审核的内存桥接存储。

SSE 是单向流：服务端发出 review_required 事件后无法在同一连接上接收
用户的确认/驳回，因此用 thread_id + threading.Event 在两条 HTTP 请求
之间同步：

- POST /api/chat/stream 的工作线程创建审核单并阻塞等待
- POST /api/review 在线程 B 中用 Command(resume=...) 恢复 LangGraph，
  得到最终回答后写入审核单并放行，SSE 线程再把回答增量推给前端

非流式 POST /api/chat 触发审核时没有 SSE 连接，无需创建审核单，
POST /api/review 直接恢复图并在自身响应里返回回答。

仅用于单机学习版；生产环境应替换为 Redis/数据库等持久化方案。
"""
import threading
import uuid
from typing import Optional

# 等待用户审核决定的最长秒数，超时自动按取消处理
REVIEW_TIMEOUT = 120


class _ReviewItem:
    __slots__ = (
        "review_id", "user_id", "question", "event",
        "claimed", "decision", "answer", "error",
    )

    def __init__(self, review_id: str, user_id: Optional[int], question: str):
        self.review_id = review_id
        self.user_id = user_id
        self.question = question
        self.event = threading.Event()
        # claimed：审核请求已被某一方（/api/review 或 SSE 超时处理）认领
        self.claimed = False
        self.decision: Optional[str] = None
        self.answer: Optional[str] = None
        self.error: Optional[str] = None


class ReviewStore:
    def __init__(self) -> None:
        self._items: dict[str, _ReviewItem] = {}
        self._lock = threading.Lock()

    def create(
        self,
        question: str,
        review_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> str:
        """创建一条待审核记录，返回 review_id（可显式指定为 thread_id）。"""
        review_id = review_id or uuid.uuid4().hex
        with self._lock:
            self._items[review_id] = _ReviewItem(review_id, user_id, question)
        return review_id

    def is_pending(self, review_id: str) -> bool:
        """该会话是否存在尚未完成的审核单（用于拒绝并发新消息）。"""
        with self._lock:
            item = self._items.get(review_id)
            return item is not None and not item.event.is_set()

    def claim(self, review_id: str, user_id: Optional[int] = None) -> bool:
        """原子认领一次审核恢复。

        记录不存在 / 已被认领 / 属于其他用户时返回 False，保证
        「用户点确认」与「SSE 超时自动驳回」不会同时恢复图。
        """
        with self._lock:
            item = self._items.get(review_id)
            if item is None or item.claimed or item.event.is_set():
                return False
            if item.user_id is not None and user_id != item.user_id:
                return False
            item.claimed = True
            return True

    def wait(self, review_id: str, timeout: int = REVIEW_TIMEOUT) -> Optional[_ReviewItem]:
        """阻塞等待审核恢复完成，超时或记录不存在返回 None。"""
        item = self._items.get(review_id)
        if item is None:
            return None
        item.event.wait(timeout=timeout)
        return item if item.event.is_set() else None

    def complete(
        self,
        review_id: str,
        decision: str,
        answer: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """写入恢复结果并唤醒等待中的 SSE 流，随后移除审核单。"""
        with self._lock:
            item = self._items.get(review_id)
            if item is None:
                return
            item.decision = decision
            item.answer = answer
            item.error = error
            item.event.set()
            self._items.pop(review_id, None)

    def discard(self, review_id: str) -> None:
        with self._lock:
            self._items.pop(review_id, None)


review_store = ReviewStore()
