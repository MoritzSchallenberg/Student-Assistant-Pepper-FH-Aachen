from glob import glob
import os
from setuptools import find_packages, setup

package_name = "ihk_pepper_interaction"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="you",
    maintainer_email="you@example.com",
    description="Interaktions-Zustandsmaschine + Sicherheits-Supervisor.",
    license="BSD",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "supervisor_node = ihk_pepper_interaction.supervisor_node:main",
            "compute_health_mock_node = ihk_pepper_interaction.compute_health_mock_node:main",
            "motion_guard_node = ihk_pepper_interaction.motion_guard_node:main",
            "actuator_arbiter_node = ihk_pepper_interaction.actuator_arbiter_node:main",
            "orient_to_sound_node = ihk_pepper_interaction.orient_to_sound_node:main",
        ],
    },
)
