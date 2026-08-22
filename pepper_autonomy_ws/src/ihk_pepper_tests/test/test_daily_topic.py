from datetime import date

import pytest

from ihk_pepper_presentation.daily_topic import (
    load_topic, load_all_topics, select_active_topic, TopicValidationError,
)


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return str(p)


def test_load_minimal_valid_topic(tmp_path):
    path = _write(tmp_path, "t.yaml", """
id: t1
title: Test
intro_text: Hallo
short_description: Kurz
""")
    t = load_topic(path)
    assert t.id == "t1"
    assert t.has_video() is False  # kein video_path gesetzt
    assert t.summary_text == "Kurz"  # Default = short_description


def test_missing_required_field_raises(tmp_path):
    path = _write(tmp_path, "broken.yaml", "title: nur Titel\n")
    with pytest.raises(TopicValidationError):
        load_topic(path)


def test_load_all_topics_skips_broken(tmp_path):
    _write(tmp_path, "good.yaml", "id: g\ntitle: G\nintro_text: I\nshort_description: S\n")
    _write(tmp_path, "bad.yaml", "id: b\n")
    _write(tmp_path, "not_yaml.yaml", ": [ invalid {{\n")
    topics, errors = load_all_topics(str(tmp_path))
    assert list(topics.keys()) == ["g"]
    assert len(errors) == 2


def test_validity_window():
    from ihk_pepper_presentation.daily_topic import DailyTopic
    t = DailyTopic(id="x", title="X", intro_text="i", short_description="s",
                    valid_from="2020-01-01", valid_to="2020-12-31")
    assert t.is_valid_today(date(2020, 6, 1)) is True
    assert t.is_valid_today(date(2021, 1, 1)) is False


def test_select_active_topic_picks_highest_priority(tmp_path):
    _write(tmp_path, "low.yaml", "id: low\ntitle: L\nintro_text: i\nshort_description: s\npriority: 1\n")
    _write(tmp_path, "high.yaml", "id: high\ntitle: H\nintro_text: i\nshort_description: s\npriority: 10\n")
    topics, errors = load_all_topics(str(tmp_path))
    assert errors == []
    chosen = select_active_topic(topics)
    assert chosen.id == "high"


def test_select_active_topic_none_when_all_expired(tmp_path):
    _write(tmp_path, "expired.yaml",
           "id: e\ntitle: E\nintro_text: i\nshort_description: s\n"
           "valid_from: 2000-01-01\nvalid_to: 2000-12-31\n")
    topics, errors = load_all_topics(str(tmp_path))
    assert select_active_topic(topics) is None
