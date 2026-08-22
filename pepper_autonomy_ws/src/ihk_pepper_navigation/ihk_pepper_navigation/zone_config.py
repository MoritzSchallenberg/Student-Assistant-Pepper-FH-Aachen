"""
Keepout-/Geschwindigkeits-Zonen (Arbeitspaket 6, Abschnitt "Karten und
Zonen"). Eigenes, einfaches YAML-Format -- unabhaengig von Nav2 selbst
installierbar/testbar (Nav2s Costmap-Filter-Format ist maechtiger, aber
setzt eine laufende Nav2-Instanz mit generierter Filter-Maske voraus, die
in dieser Session nicht verfuegbar ist, siehe IMPLEMENTATION_REPORT.md).
Dieses Format ist die Zwischenablage/Planungsgrundlage, aus der spaeter
(mit echtem Grundriss) eine Nav2-Costmap-Filter-Maske erzeugt werden kann.

Zonentypen:
    keepout      -- Bereich, den Pepper nie befahren darf (z.B. Treppe)
    slow         -- Bereich mit reduzierter max. Geschwindigkeit
    staff_only   -- nur mit spezieller Freigabe befahrbar (hier wie
                    keepout behandelt, bis eine Rollen-/Rechteverwaltung
                    existiert -- sicherer Default)
"""
import glob
import os
from dataclasses import dataclass, field

import yaml

VALID_ZONE_TYPES = ("keepout", "slow", "staff_only")
REQUIRED_FIELDS = ("id", "type", "polygon")


class ZoneValidationError(ValueError):
    pass


@dataclass
class Zone:
    id: str
    type: str
    polygon: list  # Liste von [x, y] Punkten (map-Frame, Meter)
    max_speed_mps: float = None  # nur fuer type == "slow"
    description: str = ""
    source_path: str = ""

    def contains_point(self, x: float, y: float) -> bool:
        """Einfacher Ray-Casting Point-in-Polygon-Test."""
        n = len(self.polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = self.polygon[i]
            xj, yj = self.polygon[j]
            if ((yi > y) != (yj > y)) and \
               (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
        return inside

    def is_hard_keepout(self) -> bool:
        return self.type in ("keepout", "staff_only")


def load_zone(path: str) -> Zone:
    with open(path) as f:
        data = yaml.safe_load(f)
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise ZoneValidationError(f"{path}: fehlende Pflichtfelder: {missing}")
    if data["type"] not in VALID_ZONE_TYPES:
        raise ZoneValidationError(f"{path}: ungueltiger type '{data['type']}', erlaubt: {VALID_ZONE_TYPES}")
    polygon = data["polygon"]
    if not isinstance(polygon, list) or len(polygon) < 3:
        raise ZoneValidationError(f"{path}: polygon braucht mindestens 3 Punkte")
    for p in polygon:
        if not (isinstance(p, list) and len(p) == 2):
            raise ZoneValidationError(f"{path}: jeder polygon-Punkt muss [x, y] sein, gefunden: {p}")
    if data["type"] == "slow" and "max_speed_mps" not in data:
        raise ZoneValidationError(f"{path}: type 'slow' braucht max_speed_mps")

    return Zone(
        id=data["id"], type=data["type"], polygon=[tuple(p) for p in polygon],
        max_speed_mps=data.get("max_speed_mps"), description=data.get("description", ""),
        source_path=path,
    )


def load_all_zones(directory: str):
    """Wie daily_topic.load_all_topics: laedt alles Ladbare, sammelt
    Fehler statt abzubrechen."""
    zones = {}
    errors = []
    for path in sorted(glob.glob(os.path.join(directory, "*.yaml"))):
        try:
            z = load_zone(path)
            zones[z.id] = z
        except Exception as e:
            errors.append(f"{path}: {e}")
    return zones, errors


def point_in_any_keepout(zones: dict, x: float, y: float) -> bool:
    return any(z.is_hard_keepout() and z.contains_point(x, y) for z in zones.values())


def speed_limit_at(zones: dict, x: float, y: float, default_mps: float) -> float:
    limits = [z.max_speed_mps for z in zones.values()
              if z.type == "slow" and z.contains_point(x, y) and z.max_speed_mps is not None]
    return min(limits + [default_mps])
