"""
Einfache dateibasierte Modus-Sperre (Entwicklungsauftrag 2, Abschnitt 8
"AP5 -- Mapping und Lokalisierung"): verhindert, dass Mapping- und
Lokalisierungsmodus gleichzeitig aktiv sind (beide steuern dieselbe
RTAB-Map-Datenbank/TF-Kette map->odom -- gleichzeitig aktiv wuerden sie
sich gegenseitig widersprechen). Kein ROS -- reine Dateilogik, von
realsense_mapping.launch.py/realsense_localization.launch.py ueber eine
OpaqueFunction aufgerufen.

Bekannte Grenze: eine Sperrdatei, die nach einem Absturz/Kill -9 nicht
regulaer entfernt wurde, muss manuell geloescht werden (Pfad wird in der
Fehlermeldung genannt). Kein verteiltes/prozessuebergreifendes Locking im
strengen Sinn -- fuer den Einzel-NUC-Entwicklungsfall dieses Auftrags
ausreichend.
"""
import os
import time


class ModeLockError(RuntimeError):
    pass


def acquire_mode_lock(lock_dir: str, mode_name: str, other_modes) -> str:
    """Prueft, ob eine der in `other_modes` genannten Sperrdateien bereits
    existiert -- wenn ja, wird ModeLockError ausgeloest (Launch soll dann
    abbrechen). Sonst wird die eigene Sperrdatei angelegt und ihr Pfad
    zurueckgegeben. Der Aufrufer ist dafuer verantwortlich, die Datei beim
    Beenden wieder zu entfernen (release_mode_lock)."""
    os.makedirs(lock_dir, exist_ok=True)
    for other in other_modes:
        other_path = os.path.join(lock_dir, f"{other}.lock")
        if os.path.exists(other_path):
            raise ModeLockError(
                f"Modus '{mode_name}' kann nicht gestartet werden -- "
                f"'{other}' ist bereits aktiv (Sperrdatei {other_path}). "
                f"Diesen Modus zuerst beenden (und die Sperrdatei manuell "
                f"loeschen, falls sie nach einem Absturz zurueckblieb), "
                f"bevor ein anderer RealSense-Navigationsmodus startet.")
    own_path = os.path.join(lock_dir, f"{mode_name}.lock")
    with open(own_path, "w") as f:
        f.write(str(time.time()))
    return own_path


def release_mode_lock(lock_path: str) -> None:
    if lock_path and os.path.exists(lock_path):
        os.remove(lock_path)
