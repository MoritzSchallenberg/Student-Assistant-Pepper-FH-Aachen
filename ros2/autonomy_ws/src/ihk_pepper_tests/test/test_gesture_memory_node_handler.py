"""
Entwicklungsauftrag 04-B, AP5A: prueft, dass
gesture_memory_node.py::_handle_search_gestures() JEDES Feld von
GestureIndexEntry korrekt in die ROS2-Antwort (GestureCandidate.msg)
uebertraegt -- insbesondere affects_head (neu in diesem Auftrag, vorher
im Nachrichtentyp gar nicht vorhanden). Gleiches Duck-Typing-Muster wie
test_dialogue_thinking_loop.py -- die ECHTE, ungebundene Handler-Methode
laeuft gegen ein leichtgewichtiges Fake, kein rclpy.init() noetig.
"""
from ihk_pepper_gesture_memory.gesture_memory_node import GestureMemoryNode
from ihk_pepper_gesture_memory.gesture_search import GestureIndexEntry
from ihk_pepper_interfaces.msg import GestureCandidateArray
from ihk_pepper_interfaces.srv import SearchGestures


class _FakeParam:
    def __init__(self, value):
        self.value = value


class _FakeLogger:
    def info(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass


class _FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, msg):
        self.published.append(msg)


class _FakeClock:
    def now(self):
        class _T:
            def to_msg(self_inner):
                return None
        return _T()


class _FakeStore:
    def __init__(self, entries):
        self._entries = entries  # list[(GestureIndexEntry, score)]

    def search(self, request):
        return self._entries


class _FakeNode:
    _handle_search_gestures = GestureMemoryNode._handle_search_gestures

    def __init__(self, entries):
        self._params = {"production_mode": False}
        self.store = _FakeStore(entries)
        self.results_pub = _FakePublisher()

    def get_parameter(self, name):
        return _FakeParam(self._params[name])

    def get_logger(self):
        return _FakeLogger()

    def get_clock(self):
        return _FakeClock()


def _request(query="", top_k=5):
    req = SearchGestures.Request()
    req.query = query
    req.top_k = top_k
    req.exclude_recent = []
    return req


def test_affects_head_true_reaches_the_ros_response():
    entry = GestureIndexEntry(
        name="agree_nod", description="Zustimmendes Nicken", tested_status="draft",
        duration_s=1.6, allowed_interaction_states=["CONVERSATION_READY"],
        requires_stationary=True, affects_head=True, system_only=False, selectable_by_llm=True,
    )
    node = _FakeNode(entries=[(entry, 0.9)])
    response = node._handle_search_gestures(_request(), SearchGestures.Response())
    assert response.success is True
    assert len(response.candidates) == 1
    assert response.candidates[0].affects_head is True


def test_affects_head_false_reaches_the_ros_response():
    entry = GestureIndexEntry(
        name="wave_right", description="Winken", tested_status="dry_run_validated",
        duration_s=2.8, allowed_interaction_states=["CONVERSATION_READY"],
        requires_stationary=True, affects_head=False, system_only=False, selectable_by_llm=True,
    )
    node = _FakeNode(entries=[(entry, 0.5)])
    response = node._handle_search_gestures(_request(), SearchGestures.Response())
    assert response.candidates[0].affects_head is False


def test_search_failure_yields_empty_response_not_a_crash():
    class _FailingStore:
        def search(self, request):
            raise RuntimeError("DB-Fehler")

    node = _FakeNode(entries=[])
    node.store = _FailingStore()
    response = node._handle_search_gestures(_request(), SearchGestures.Response())
    assert response.success is False
    assert response.candidates == []


def test_published_topic_mirrors_the_response_candidates():
    entry = GestureIndexEntry(name="greet_open", affects_head=False)
    node = _FakeNode(entries=[(entry, 0.7)])
    node._handle_search_gestures(_request(), SearchGestures.Response())
    assert len(node.results_pub.published) == 1
    published: GestureCandidateArray = node.results_pub.published[0]
    assert published.candidates[0].name == "greet_open"
