"""
Reine Entprojektions-/Tiefenschaetzungslogik (Entwicklungsauftrag 1,
Abschnitt 4). Kein ROS -- perception_node.py ruft diese Funktionen mit
bereits ausgepackten Rohdaten (Tiefenbild als numpy-Array, Intrinsics aus
CameraInfo.k) auf. Ersetzt die bisherige, immer has_3d_position=False
liefernde Platzhalterlogik.
"""
import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

# Uebliche Grenzen fuer eine RealSense D4xx im Innenraum-Einsatz --
# konfigurierbar (perception_node.py-Parameter), keine hartcodierten
# Physik-Grenzen.
DEFAULT_MIN_VALID_DEPTH_M = 0.2
DEFAULT_MAX_VALID_DEPTH_M = 8.0
DEFAULT_PATCH_RADIUS_PX = 3


@dataclass
class CameraIntrinsics:
    fx: float
    fy: float
    cx: float
    cy: float

    @classmethod
    def from_camera_info_k(cls, k: Sequence[float]) -> "CameraIntrinsics":
        """k = sensor_msgs/CameraInfo.k (row-major 3x3:
        [fx, 0, cx, 0, fy, cy, 0, 0, 1])."""
        return cls(fx=k[0], fy=k[4], cx=k[2], cy=k[5])


@dataclass
class Point3D:
    x: float
    y: float
    z: float


@dataclass
class DepthEstimate:
    depth_m: float
    confidence: float  # [0,1], siehe _confidence_from_spread()
    num_valid_samples: int


def estimate_patch_depth(
    depth_image: np.ndarray,
    center_x_px: float,
    center_y_px: float,
    depth_scale_to_m: float = 1.0,
    patch_radius_px: int = DEFAULT_PATCH_RADIUS_PX,
    min_valid_depth_m: float = DEFAULT_MIN_VALID_DEPTH_M,
    max_valid_depth_m: float = DEFAULT_MAX_VALID_DEPTH_M,
) -> Optional[DepthEstimate]:
    """Median aus einem quadratischen Pixelpatch um (center_x, center_y)
    -- robuster als ein einzelner, evtl. falscher Mittelpunktpixel (z.B.
    auf einer Kontur oder einem Loch im Tiefenbild). NaN/Inf/0/zu nah/zu
    fern werden verworfen. Gibt None zurueck, wenn kein gueltiger Wert im
    Patch liegt -- das MUSS zu has_3d_position=False fuehren, niemals zu
    einem geschaetzten Fantasiewert."""
    h, w = depth_image.shape[:2]
    cx, cy = int(round(center_x_px)), int(round(center_y_px))
    x0, x1 = max(0, cx - patch_radius_px), min(w, cx + patch_radius_px + 1)
    y0, y1 = max(0, cy - patch_radius_px), min(h, cy + patch_radius_px + 1)
    if x0 >= x1 or y0 >= y1:
        return None

    patch = depth_image[y0:y1, x0:x1].astype(np.float64) * depth_scale_to_m
    finite = patch[np.isfinite(patch)]
    valid = finite[(finite >= min_valid_depth_m) & (finite <= max_valid_depth_m)]
    if valid.size == 0:
        return None

    return DepthEstimate(
        depth_m=float(np.median(valid)),
        confidence=_confidence_from_spread(valid.tolist()),
        num_valid_samples=int(valid.size),
    )


def _confidence_from_spread(depth_values_m: Sequence[float]) -> float:
    """Grobe Konfidenz aus der relativen Streuung der gueltigen
    Tiefenwerte im Patch -- ein sehr uneinheitlicher Patch (z.B. am
    Personenrand, Ueberlappung mit Hintergrund) ist weniger
    vertrauenswuerdig als ein homogener. [0,1]."""
    if not depth_values_m:
        return 0.0
    if len(depth_values_m) == 1:
        return 0.5  # ein einzelner Wert: weder besonders vertrauenswuerdig noch verworfen
    mean = sum(depth_values_m) / len(depth_values_m)
    if mean <= 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in depth_values_m) / len(depth_values_m)
    rel_std = math.sqrt(variance) / mean
    # Heuristik: rel_std 0 -> Konfidenz 1.0, ab 0.3 relativer Streuung -> Konfidenz 0.0.
    return max(0.0, min(1.0, 1.0 - rel_std / 0.3))


def deproject_pixel(pixel_x: float, pixel_y: float, depth_m: float, intrinsics: CameraIntrinsics) -> Point3D:
    """Entprojiziert EINEN Pixel + Tiefe ins optische Kameraframe
    (x rechts, y unten, z vorwaerts -- Standard optical-frame-Konvention,
    passend zu z.B. realsense_color_optical_frame). Reine Geometrie,
    keine Validierung -- der Aufrufer muss depth_m bereits geprueft haben
    (siehe estimate_patch_depth)."""
    x = (pixel_x - intrinsics.cx) * depth_m / intrinsics.fx
    y = (pixel_y - intrinsics.cy) * depth_m / intrinsics.fy
    return Point3D(x=x, y=y, z=depth_m)
