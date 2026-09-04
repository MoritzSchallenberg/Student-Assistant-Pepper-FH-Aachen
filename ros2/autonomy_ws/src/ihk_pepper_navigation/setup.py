from glob import glob
import os
from setuptools import find_packages, setup

package_name = "ihk_pepper_navigation"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
        (os.path.join("share", package_name, "keepout_zones"), glob("keepout_zones/*.yaml")),
        (os.path.join("share", package_name, "maps"), glob("maps/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="you",
    maintainer_email="you@example.com",
    description="Navigation/Mapping-Vorbereitung + Personen anfahren/begleiten/folgen.",
    license="BSD",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "laser_filter_node = ihk_pepper_navigation.laser_filter_node:main",
            "person_approach_node = ihk_pepper_navigation.person_approach_node:main",
            "camera_pose_gate_node = ihk_pepper_navigation.camera_pose_gate_node:main",
            "mock_nav2_server = ihk_pepper_navigation.mock_nav2_server:main",
        ],
    },
)
