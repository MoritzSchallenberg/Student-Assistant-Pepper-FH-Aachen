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
            # face_identity_node folgt in einem spaeteren Commit, sobald
            # die eigentliche Laufzeit-Verdrahtung (RealSense-Bilder,
            # Consent-Abfrage, PersonIdentityArray-Veroeffentlichung)
            # ansteht -- dieser Commit liefert nur die getestete
            # Backend-/Speicher-/Abgleichslogik.
        ],
    },
)
