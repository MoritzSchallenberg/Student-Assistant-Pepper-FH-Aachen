from glob import glob
import os
from setuptools import find_packages, setup

package_name = "ihk_pepper_dialog"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        (os.path.join("share", package_name, "data"), glob("data/*.json")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="you",
    maintainer_email="you@example.com",
    description="Dialogmanager: FAQ-Cache, AnythingLLM, Sitzungsgedaechtnis, TTS-Aufbereitung.",
    license="BSD",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "dialog_manager_node = ihk_pepper_dialog.dialog_manager_node:main",
            "load_faq_seed = ihk_pepper_dialog.load_faq_seed:main",
        ],
    },
)
