"""
Einheitliches Bewegungs-/Gesten-Katalogformat (Arbeitspaket 40).

Jede Geste ist eine YAML-Datei unter config/gestures/<name>.yaml:

    name: <eindeutiger Name, muss Dateiname ohne .yaml entsprechen>
    description: <fuer Menschen>
    metadata: {beliebige Zusatzinfos}
    disable_breathing: [Arms]        # optional, Liste von Body-Parts
    restore_after: true              # optional, Standard: true
    steps:
      - {joint: RShoulderPitch, angle: -1.0, duration: 1.0}
      - ...

Damit lassen sich bestehende Gesten (wave, t_pose, spaeter aufgezeichnete
Sequenzen aus ros2/robot_model/sim_qicli.py-Sessions) einheitlich ueber
PlayGesture.action per Name aufrufen -- Dialog/Praesentation muessen die
konkreten Gelenknamen/Winkel nicht kennen.

Bewusst NICHT Teil dieses Auftrags: automatisches Trainieren neuer
Bewegungen. Nur das Format + der Player werden hier bereitgestellt.
"""
import glob
import os
import yaml

from .joint_limits import validate_angle, JointLimitError


class GestureValidationError(ValueError):
    pass


class Gesture:
    def __init__(self, data: dict, source_path: str):
        self.name = data["name"]
        self.description = data.get("description", "")
        self.metadata = data.get("metadata", {})
        self.disable_breathing = data.get("disable_breathing", [])
        self.restore_after = data.get("restore_after", True)
        self.steps = data.get("steps", [])
        self.source_path = source_path
        self._validate()

    def _validate(self):
        if not self.steps:
            raise GestureValidationError(f"Geste '{self.name}': keine steps definiert")
        for i, step in enumerate(self.steps):
            for key in ("joint", "angle", "duration"):
                if key not in step:
                    raise GestureValidationError(
                        f"Geste '{self.name}', Schritt {i}: Feld '{key}' fehlt"
                    )
            if step["duration"] <= 0:
                raise GestureValidationError(
                    f"Geste '{self.name}', Schritt {i}: duration muss > 0 sein"
                )
            # Gelenkgrenzen pruefen (wirft JointLimitError bei Verletzung)
            try:
                validate_angle(step["joint"], step["angle"], strict=True)
            except JointLimitError as e:
                raise GestureValidationError(
                    f"Geste '{self.name}', Schritt {i}: {e}"
                ) from e

    def affected_joints(self):
        return sorted({s["joint"] for s in self.steps})


class GestureCatalog:
    def __init__(self, catalog_dir: str):
        self.catalog_dir = catalog_dir
        self._gestures: dict[str, Gesture] = {}
        self.reload()

    def reload(self):
        """Laedt/validiert alle *.yaml im Katalog-Ordner neu. Fehlerhafte
        Dateien werden uebersprungen (mit Fehlermeldung), nicht das ganze
        System blockieren."""
        self._gestures = {}
        errors = []
        for path in sorted(glob.glob(os.path.join(self.catalog_dir, "*.yaml"))):
            try:
                with open(path) as f:
                    data = yaml.safe_load(f)
                gesture = Gesture(data, path)
                if gesture.name != os.path.splitext(os.path.basename(path))[0]:
                    errors.append(
                        f"{path}: name '{gesture.name}' passt nicht zum Dateinamen"
                    )
                    continue
                self._gestures[gesture.name] = gesture
            except Exception as e:
                errors.append(f"{path}: {e}")
        return errors

    def names(self):
        return sorted(self._gestures.keys())

    def get(self, name: str) -> Gesture:
        if name not in self._gestures:
            raise KeyError(f"Unbekannte Geste: '{name}' (verfuegbar: {self.names()})")
        return self._gestures[name]

    def play(self, pepper_client, name: str, speed_scale: float = 1.0, feedback_cb=None):
        """Fuehrt eine Geste ueber den ThreadSafePepperClient aus.
        feedback_cb(status: str, progress: float) wird optional pro Schritt
        aufgerufen (fuer PlayGesture.action-Feedback)."""
        gesture = self.get(name)
        speed_scale = max(0.1, min(3.0, speed_scale))  # gegen Missbrauch/Divide-by-zero

        for part in gesture.disable_breathing:
            pepper_client.set_breathing(False, part)

        snapshot = None
        if gesture.restore_after:
            snapshot = pepper_client.snapshot_joints(gesture.affected_joints())

        try:
            total = len(gesture.steps)
            for i, step in enumerate(gesture.steps):
                duration = step["duration"] / speed_scale
                pepper_client.set_angle(step["joint"], step["angle"], duration)
                if feedback_cb:
                    feedback_cb(f"step_{i}", (i + 1) / total)
        finally:
            if snapshot is not None:
                pepper_client.restore_joints(snapshot)
            for part in gesture.disable_breathing:
                pepper_client.set_breathing(True, part)
