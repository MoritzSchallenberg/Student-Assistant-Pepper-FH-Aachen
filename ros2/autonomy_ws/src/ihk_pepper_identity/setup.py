from glob import glob
import os
from setuptools import find_packages, setup

package_name = "ihk_pepper_identity"

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
    description=(
        "Consent-gated Gesichtserkennung -- fluechtige/persistente "
        "Erkennungspfade, getrennte biometrische Ablage."
    ),
    license="BSD",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "face_identity_node = ihk_pepper_identity.face_identity_node:main",
            "identityctl = ihk_pepper_identity.identityctl:main",
        ],
    },
)
