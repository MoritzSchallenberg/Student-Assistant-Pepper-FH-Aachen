import numpy as np

from ihk_pepper_perception.deprojection import (
    CameraIntrinsics,
    deproject_pixel,
    estimate_patch_depth,
)


def _intrinsics():
    # fx=fy=500, Hauptpunkt in Bildmitte eines 640x480-Bildes.
    return CameraIntrinsics(fx=500.0, fy=500.0, cx=320.0, cy=240.0)


def test_deproject_known_pixel_at_principal_point():
    # Ein Pixel exakt am Hauptpunkt muss auf (0, 0, depth) abbilden.
    p = deproject_pixel(320.0, 240.0, depth_m=2.0, intrinsics=_intrinsics())
    assert p.x == 0.0
    assert p.y == 0.0
    assert p.z == 2.0


def test_deproject_known_offset_pixel():
    # 50px rechts vom Hauptpunkt bei fx=500, depth=2m -> x = 50*2/500 = 0.2m
    p = deproject_pixel(370.0, 240.0, depth_m=2.0, intrinsics=_intrinsics())
    assert abs(p.x - 0.2) < 1e-9
    assert p.z == 2.0


def test_patch_depth_valid_returns_median_and_confidence():
    depth = np.full((480, 640), 2.0, dtype=np.float32)
    est = estimate_patch_depth(depth, center_x_px=320, center_y_px=240, patch_radius_px=2)
    assert est is not None
    assert abs(est.depth_m - 2.0) < 1e-6
    assert est.confidence > 0.9  # homogener Patch -> hohe Konfidenz
    assert est.num_valid_samples == 25  # 5x5-Patch


def test_patch_depth_rejects_all_zero():
    depth = np.zeros((480, 640), dtype=np.float32)
    assert estimate_patch_depth(depth, 320, 240) is None


def test_patch_depth_rejects_nan_and_inf():
    depth = np.full((480, 640), np.nan, dtype=np.float32)
    depth[238:243, 318:323] = np.inf
    assert estimate_patch_depth(depth, 320, 240) is None


def test_patch_depth_rejects_too_close():
    depth = np.full((480, 640), 0.05, dtype=np.float32)  # 5cm -- unterhalb min_valid_depth_m
    assert estimate_patch_depth(depth, 320, 240, min_valid_depth_m=0.2) is None


def test_patch_depth_rejects_too_far():
    depth = np.full((480, 640), 20.0, dtype=np.float32)
    assert estimate_patch_depth(depth, 320, 240, max_valid_depth_m=8.0) is None


def test_patch_depth_out_of_image_bounds_returns_none():
    depth = np.full((480, 640), 2.0, dtype=np.float32)
    assert estimate_patch_depth(depth, -100, -100) is None


def test_patch_depth_uses_only_valid_pixels_within_mixed_patch():
    depth = np.full((480, 640), np.nan, dtype=np.float32)
    depth[238:243, 318:323] = 2.0  # 5x5-Patch mit gueltigen Werten inmitten von NaN
    est = estimate_patch_depth(depth, 320, 240, patch_radius_px=2)
    assert est is not None
    assert abs(est.depth_m - 2.0) < 1e-6
