from glob import glob
import os
from setuptools import find_packages, setup

package_name = "ihk_pepper_presentation"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
        (os.path.join("share", package_name, "content", "daily_topics"), glob("content/daily_topics/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="you",
    maintainer_email="you@example.com",
    description="Tagesthema-Datenmodell und Praesentationsbetrieb (Video/Quiz/Q&A) fuer Pepper.",
    license="BSD",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "presentation_manager_node = ihk_pepper_presentation.presentation_manager_node:main",
        ],
    },
)
