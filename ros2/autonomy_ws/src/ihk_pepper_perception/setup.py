from glob import glob
import os
from setuptools import find_packages, setup

package_name = "ihk_pepper_perception"

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
    description="Multi-Personen-Tracking mit Interesse-Score.",
    license="BSD",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "perception_node = ihk_pepper_perception.perception_node:main",
        ],
    },
)
