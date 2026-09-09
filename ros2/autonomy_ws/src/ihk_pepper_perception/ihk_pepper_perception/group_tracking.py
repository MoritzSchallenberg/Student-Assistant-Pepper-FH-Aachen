"""
Gesprächsgruppen-Verfolgung (Entwicklungsauftrag 04-B, AP7, Abschnitt
14). Reine, ROS-freie Kernlogik -- group_tracking_node.py ist der
duenne ROS-Wrapper (baut TrackCandidate aus PersonTrackArray, bindet
GroupTracker an einen echten Timer/now_fn).

Verfolgt bewusst GENAU EINE aktuelle Gesprächsgruppe, gebunden an die
aktuelle Interaktion (anchor_track_id, Auftrag: "mindestens ein Bezug
zur aktuellen Interaktion besteht") -- KEIN allgemeines Mehrgruppen-
Tracking, Pepper führt ohnehin nur EIN Gespräch gleichzeitig (siehe
InteractionSession). Eine Gruppe entsteht NUR, wenn der Anker-Track
Mitglied eines ausreichend grossen, raeumlich zusammenstehenden
Clusters ist -- nicht jede zufaellig vorbeilaufende Person wird
automatisch Mitglied (Auftrag: "Nicht jede zufaellig vorbeilaufende
Person wird automatisch Gruppenmitglied").

group_id ist FLUECHTIG (neu bei jeder neu gebildeten Gruppe) -- KEINE
dauerhafte Identitaet, niemals als Schluessel in einer dauerhaften
Datenbank verwenden."""
from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple


@dataclass(frozen=True)
class GroupTrackingConfig:
    minimum_members: int = 2
    maximum_members: int = 6
    maximum_member_spacing_m: float = 1.8
    maximum_track_age_s: float = 0.5
    minimum_stable_duration_s: float = 1.0
    join_hysteresis_s: float = 1.0
    leave_hysteresis_s: float = 2.0


@dataclass(frozen=True)
class TrackCandidate:
    track_id: int
    x_m: float
    y_m: float
    stable: bool
    age_s: float
    has_3d_position: bool


@dataclass(frozen=True)
class GroupSnapshot:
    """formed=False bedeutet: aktuell KEINE Gruppe (weder neu gebildet
    noch fortbestehend) -- member_track_ids bleibt dann leer, group_id
    None. stable=False waehrend der ersten minimum_stable_duration_s
    einer neu gebildeten Gruppe (Auftrag: Gruppe muss "ueber mehrere
    Frames stabil" sein, bevor sie als verlaesslich gilt)."""

    group_id: Optional[str]
    member_track_ids: Tuple[int, ...]
    stable: bool
    formed: bool


def _pairwise_distance(a: TrackCandidate, b: TrackCandidate) -> float:
    return math.hypot(a.x_m - b.x_m, a.y_m - b.y_m)


def cluster_tracks(tracks: List[TrackCandidate], config: GroupTrackingConfig) -> List[List[int]]:
    """Reine Funktion: Single-Linkage-Clustering nach
    maximum_member_spacing_m -- zwei Tracks gehoeren zum selben Cluster,
    wenn es eine Kette paarweiser Abstaende <= maximum_member_spacing_m
    zwischen ihnen gibt. Verwirft VORHER jeden Track ohne gueltige
    3D-Position/Stabilitaet oder aelter als maximum_track_age_s. Ein
    Cluster mit weniger als minimum_members Mitgliedern wird NICHT
    zurueckgegeben (eine "Gruppe" von 1 ist keine Gruppe)."""
    valid = [t for t in tracks
             if t.has_3d_position and t.stable and t.age_s <= config.maximum_track_age_s]
    n = len(valid)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if _pairwise_distance(valid[i], valid[j]) <= config.maximum_member_spacing_m:
                union(i, j)

    clusters: Dict[int, List[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(valid[i].track_id)

    return [
        member_ids[:config.maximum_members]
        for member_ids in clusters.values()
        if len(member_ids) >= config.minimum_members
    ]


class GroupTracker:
    def __init__(
        self,
        config: GroupTrackingConfig = None,
        now_fn: Callable[[], float] = time.monotonic,
        id_fn: Callable[[], str] = None,
    ):
        self.config = config or GroupTrackingConfig()
        self._now_fn = now_fn
        self._id_fn = id_fn or (lambda: str(uuid.uuid4()))
        self._group_id: Optional[str] = None
        self._confirmed_members: Set[int] = set()
        self._candidate_since: Dict[int, float] = {}
        # Zeitpunkt, an dem ein Mitglied ZULETZT tatsaechlich im
        # Anker-Cluster gesehen wurde -- NICHT "seit wann abwesend"
        # (das wuerde bei unregelmaessigen update()-Aufrufen falsch
        # bleiben: ein einzelner, spaeter Aufruf nach einer langen Pause
        # wuerde die Verlassens-Hysterese sonst immer wieder bei Null
        # anfangen lassen, siehe test_group_dissolves_when_anchor_has_no_cluster).
        self._member_last_present: Dict[int, float] = {}
        self._group_formed_at: Optional[float] = None

    def _reset(self) -> None:
        self._group_id = None
        self._confirmed_members = set()
        self._candidate_since = {}
        self._member_last_present = {}
        self._group_formed_at = None

    def _snapshot(self, now: float) -> GroupSnapshot:
        if len(self._confirmed_members) < self.config.minimum_members:
            if self._group_id is not None:
                # Eine BESTEHENDE Gruppe ist unter die Mindestgroesse
                # gefallen -- endgueltig aufloesen. VOR dem ersten
                # tatsaechlichen Zustandekommen (group_id noch None)
                # NICHT zuruecksetzen, sonst wuerde jeder Aufruf die
                # gerade erst begonnene Beitritts-Hysterese wieder auf
                # Null setzen (siehe test_group_forms_after_join_hysteresis_elapses).
                self._reset()
            return GroupSnapshot(None, (), False, False)
        stable = (now - self._group_formed_at) >= self.config.minimum_stable_duration_s
        return GroupSnapshot(self._group_id, tuple(sorted(self._confirmed_members)), stable, True)

    def update(self, tracks: List[TrackCandidate], anchor_track_id: int) -> GroupSnapshot:
        """anchor_track_id: die aktuell interagierende Person (Auftrag:
        "mindestens ein Bezug zur aktuellen Interaktion") -- eine Gruppe
        wird NUR gebildet/fortgefuehrt, solange dieser Track (noch
        innerhalb der Verlassens-Hysterese) Mitglied eines Clusters ist."""
        now = self._now_fn()
        clusters = cluster_tracks(tracks, self.config)
        anchor_cluster_ids = next((set(c) for c in clusters if anchor_track_id in c), None)

        if anchor_cluster_ids is None:
            anchor_cluster_ids = set()

        # Kandidaten, die aktuell NICHT im Cluster sind, verlieren ihren
        # Kandidatenstatus sofort (keine unterbrochene Anwesenheit
        # anrechnen) -- betrifft auch den Fall "kein Cluster ueberhaupt".
        for member in list(self._candidate_since.keys()):
            if member not in anchor_cluster_ids:
                self._candidate_since.pop(member, None)

        # Anwesenheit aktualisieren + neue Kandidaten: Beitritts-Hysterese.
        for member in anchor_cluster_ids:
            self._member_last_present[member] = now
            if member in self._confirmed_members:
                continue
            self._candidate_since.setdefault(member, now)
            if now - self._candidate_since[member] >= self.config.join_hysteresis_s:
                self._confirmed_members.add(member)
                self._candidate_since.pop(member, None)
                if self._group_id is None:
                    self._group_id = self._id_fn()
                    self._group_formed_at = now

        # Bestehende Mitglieder: Verlassens-Hysterese anhand der ZULETZT
        # bekannten Anwesenheit (kurze Verdeckung toleriert, aber auch
        # bei seltenen update()-Aufrufen korrekt).
        for member in list(self._confirmed_members):
            last_present = self._member_last_present.get(member, now)
            if now - last_present > self.config.leave_hysteresis_s:
                self._confirmed_members.discard(member)
                self._member_last_present.pop(member, None)

        return self._snapshot(now)


@dataclass(frozen=True)
class GroupGeometry:
    center_x_m: float
    center_y_m: float
    angular_span_rad: float
    minimum_member_distance_m: float
    maximum_member_distance_m: float
    all_members_within_fov: bool


def _bearing_rad(x_m: float, y_m: float) -> float:
    return math.atan2(y_m, x_m)


def _minimum_enclosing_arc_rad(bearings_rad: List[float]) -> float:
    """Kleinste Winkelspanne (rad), die ALLE Peilungen umfasst -- robust
    gegen den +-pi-Uebergang (Standardverfahren: die Spanne ist 2*pi
    minus der groessten Luecke zwischen benachbarten, sortierten
    Peilungen)."""
    if not bearings_rad:
        return 0.0
    if len(bearings_rad) == 1:
        return 0.0
    sorted_b = sorted(bearings_rad)
    n = len(sorted_b)
    max_gap = 0.0
    for i in range(n):
        nxt = sorted_b[(i + 1) % n]
        cur = sorted_b[i]
        gap = (nxt - cur) % (2 * math.pi)
        max_gap = max(max_gap, gap)
    return 2 * math.pi - max_gap


def compute_group_geometry(
    members: List[TrackCandidate],
    observer_x_m: float = 0.0,
    observer_y_m: float = 0.0,
    camera_horizontal_fov_deg: float = 87.0,
) -> Optional[GroupGeometry]:
    """Reine Geometrie, aus Sicht von (observer_x_m, observer_y_m) --
    Standard (0,0) ist der aktuelle Roboterursprung (base_link). Gibt
    None zurueck, wenn members leer ist (keine erfundene Geometrie fuer
    eine nicht existierende Gruppe)."""
    if not members:
        return None
    center_x = sum(m.x_m for m in members) / len(members)
    center_y = sum(m.y_m for m in members) / len(members)

    bearings = [_bearing_rad(m.x_m - observer_x_m, m.y_m - observer_y_m) for m in members]
    span = _minimum_enclosing_arc_rad(bearings)

    distances = [math.hypot(m.x_m - observer_x_m, m.y_m - observer_y_m) for m in members]

    half_fov = math.radians(camera_horizontal_fov_deg) / 2.0
    within_fov = all(abs(_wrap_to_pi(b)) <= half_fov for b in bearings)

    return GroupGeometry(
        center_x_m=center_x, center_y_m=center_y, angular_span_rad=span,
        minimum_member_distance_m=min(distances), maximum_member_distance_m=max(distances),
        all_members_within_fov=within_fov,
    )


def _wrap_to_pi(angle_rad: float) -> float:
    return (angle_rad + math.pi) % (2 * math.pi) - math.pi
