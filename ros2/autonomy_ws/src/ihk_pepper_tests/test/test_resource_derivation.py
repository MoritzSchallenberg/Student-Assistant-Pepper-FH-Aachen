"""
Tests fuer die deterministische Gelenk->Ressource-Ableitung
(Entwicklungsauftrag 04-B, AP5B, Abschnitt 4).
"""
import pytest

from ihk_pepper_bridge.gesture_catalog import Gesture
from ihk_pepper_interaction.actuator_arbiter import BASE, HEAD, LEFT_ARM, RIGHT_ARM, SPEECH, TORSO
from ihk_pepper_interaction.resource_derivation import (
    resource_for_joint,
    resources_for_base,
    resources_for_gesture,
    resources_for_joint_names,
    resources_for_speech,
)


@pytest.mark.parametrize("joint,expected", [
    ("HeadYaw", HEAD), ("HeadPitch", HEAD),
    ("LShoulderPitch", LEFT_ARM), ("LElbowRoll", LEFT_ARM),
    ("LWristYaw", LEFT_ARM), ("LHand", LEFT_ARM),
    ("RShoulderPitch", RIGHT_ARM), ("RElbowRoll", RIGHT_ARM),
    ("RWristYaw", RIGHT_ARM), ("RHand", RIGHT_ARM),
    ("HipRoll", TORSO), ("HipPitch", TORSO), ("KneePitch", TORSO),
])
def test_resource_for_joint_matches_the_ordered_table(joint, expected):
    assert resource_for_joint(joint) == expected


def test_unknown_joint_returns_none():
    assert resource_for_joint("SomeFutureJoint") is None


def test_resources_for_joint_names_combines_multiple_resources():
    resources = resources_for_joint_names(["HeadYaw", "LShoulderPitch", "RElbowRoll"])
    assert resources == frozenset({HEAD, LEFT_ARM, RIGHT_ARM})


def test_resources_for_joint_names_raises_on_unknown_joint():
    with pytest.raises(ValueError):
        resources_for_joint_names(["HeadYaw", "TailFin"])


def test_resources_for_gesture_uses_the_real_affected_joints_method():
    gesture = Gesture(
        {
            "schema_version": 2, "name": "test_gesture",
            "keyframes": [{"time_from_start_s": 0.5, "joints": {"HeadYaw": 0.2, "LShoulderRoll": 0.5}}],
        },
        source_path="test",
    )
    assert resources_for_gesture(gesture) == frozenset({HEAD, LEFT_ARM})


def test_resources_for_speech_and_base_are_fixed_single_resources():
    assert resources_for_speech() == frozenset({SPEECH})
    assert resources_for_base() == frozenset({BASE})
