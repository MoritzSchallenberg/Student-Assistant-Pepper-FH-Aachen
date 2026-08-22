import os
from glob import glob
from setuptools import find_packages, setup

package_name = "ihk_pepper_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        (os.path.join("share", package_name, "config", "gestures"), glob("config/gestures/*.yaml")),
    ],
    install_requires=["setuptools", "PyYAML"],
    zip_safe=True,
    maintainer="you",
    maintainer_email="you@example.com",
    description="Kapselt qicli/SSH-Zugriff auf Pepper als ROS2-Actions/Topics.",
    license="BSD",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "bridge_node = ihk_pepper_bridge.bridge_node:main",
        ],
    },
)
