"""
Entwicklungsauftrag 04-B, AP2: safety_topics.py existiert bewusst als
zwei eigenstaendige Kopien (ihk_pepper_bridge, ihk_pepper_interaction),
um keine neue Cross-Package-Abhaengigkeit fuer eine Handvoll String-
Konstanten einzufuehren. Dieser Test verhindert genau das
stillschweigende Auseinanderdriften, das der ganze Sinn dieser Datei
ist, zu vermeiden -- schlaegt fehl, sobald jemand nur EINE der beiden
Kopien aendert.
"""
import ihk_pepper_bridge.safety_topics as bridge_topics
import ihk_pepper_interaction.safety_topics as interaction_topics


def _public_names(module):
    return {n: getattr(module, n) for n in dir(module) if not n.startswith("_") and n.isupper()}


def test_safety_topics_constants_are_identical_across_packages():
    assert _public_names(bridge_topics) == _public_names(interaction_topics)


def test_freshbool_class_present_in_both_copies():
    assert hasattr(bridge_topics, "FreshBool")
    assert hasattr(interaction_topics, "FreshBool")


def test_gesture_in_progress_topic_matches_bridge_namespace():
    """Regressionstest fuer den in AP2 gefundenen Fehler: das absolute
    Thema muss tatsaechlich innerhalb des Bridge-Namespace liegen."""
    assert bridge_topics.GESTURE_IN_PROGRESS_TOPIC == "/pepper_bridge/gesture_in_progress"
    assert bridge_topics.GESTURE_IN_PROGRESS_TOPIC_RELATIVE == "gesture_in_progress"
