"""
Entwicklungsauftrag 04-B, AP2: safety_topics.py existiert bewusst als
mehrere eigenstaendige Kopien (ihk_pepper_bridge, ihk_pepper_interaction,
seit AP5A auch ihk_pepper_dialog), um keine neue Cross-Package-
Abhaengigkeit fuer eine Handvoll String-Konstanten einzufuehren. Dieser
Test verhindert genau das stillschweigende Auseinanderdriften, das der
ganze Sinn dieser Datei ist, zu vermeiden -- schlaegt fehl, sobald
jemand nur EINE der Kopien aendert.
"""
import ihk_pepper_bridge.safety_topics as bridge_topics
import ihk_pepper_dialog.safety_topics as dialog_topics
import ihk_pepper_interaction.safety_topics as interaction_topics

ALL_COPIES = {
    "ihk_pepper_bridge": bridge_topics,
    "ihk_pepper_interaction": interaction_topics,
    "ihk_pepper_dialog": dialog_topics,
}


def _public_names(module):
    return {n: getattr(module, n) for n in dir(module) if not n.startswith("_") and n.isupper()}


def test_safety_topics_constants_are_identical_across_all_packages():
    reference_name, reference_module = next(iter(ALL_COPIES.items()))
    reference = _public_names(reference_module)
    for name, module in ALL_COPIES.items():
        assert _public_names(module) == reference, (
            f"{name}.safety_topics ist von {reference_name}.safety_topics abgewichen"
        )


def test_freshbool_class_present_in_every_copy():
    for name, module in ALL_COPIES.items():
        assert hasattr(module, "FreshBool"), f"{name}.safety_topics hat kein FreshBool"


def test_gesture_in_progress_topic_matches_bridge_namespace():
    """Regressionstest fuer den in AP2 gefundenen Fehler: das absolute
    Thema muss tatsaechlich innerhalb des Bridge-Namespace liegen."""
    for name, module in ALL_COPIES.items():
        assert module.GESTURE_IN_PROGRESS_TOPIC == "/pepper_bridge/gesture_in_progress", name
        assert module.GESTURE_IN_PROGRESS_TOPIC_RELATIVE == "gesture_in_progress", name
