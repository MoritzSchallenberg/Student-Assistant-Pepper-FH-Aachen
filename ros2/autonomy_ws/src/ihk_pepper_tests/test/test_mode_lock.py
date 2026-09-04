import os

import pytest

from ihk_pepper_navigation.mode_lock import ModeLockError, acquire_mode_lock, release_mode_lock


def test_acquire_creates_lock_file(tmp_path):
    lock_path = acquire_mode_lock(str(tmp_path), "mapping", ["localization"])
    assert os.path.exists(lock_path)
    assert lock_path.endswith("mapping.lock")


def test_acquire_blocked_by_other_active_mode(tmp_path):
    acquire_mode_lock(str(tmp_path), "mapping", ["localization"])
    with pytest.raises(ModeLockError):
        acquire_mode_lock(str(tmp_path), "localization", ["mapping"])


def test_acquire_succeeds_when_no_other_mode_active(tmp_path):
    lock_path = acquire_mode_lock(str(tmp_path), "localization", ["mapping"])
    assert os.path.exists(lock_path)


def test_release_removes_lock_file(tmp_path):
    lock_path = acquire_mode_lock(str(tmp_path), "mapping", ["localization"])
    release_mode_lock(lock_path)
    assert not os.path.exists(lock_path)


def test_release_after_other_mode_freed_allows_new_acquire(tmp_path):
    lock_path = acquire_mode_lock(str(tmp_path), "mapping", ["localization"])
    release_mode_lock(lock_path)
    # Jetzt sollte localization moeglich sein.
    lock_path2 = acquire_mode_lock(str(tmp_path), "localization", ["mapping"])
    assert os.path.exists(lock_path2)


def test_release_nonexistent_path_is_noop(tmp_path):
    release_mode_lock(str(tmp_path / "does_not_exist.lock"))  # darf nicht werfen


def test_release_none_is_noop():
    release_mode_lock(None)  # darf nicht werfen


def test_same_mode_can_reacquire_its_own_lock(tmp_path):
    # mapping prueft nur gegen "localization" in other_modes, nicht gegen
    # sich selbst -- ein Neustart desselben Modus darf nicht blockieren.
    acquire_mode_lock(str(tmp_path), "mapping", ["localization"])
    lock_path = acquire_mode_lock(str(tmp_path), "mapping", ["localization"])
    assert os.path.exists(lock_path)
