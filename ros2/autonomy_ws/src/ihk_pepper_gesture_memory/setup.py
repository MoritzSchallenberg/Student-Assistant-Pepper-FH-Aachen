from setuptools import find_packages, setup

package_name = "ihk_pepper_gesture_memory"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools", "PyYAML"],
    zip_safe=True,
    maintainer="you",
    maintainer_email="you@example.com",
    description=(
        "Gesten-Vektordatenbank: semantische Suche im YAML-Gestenkatalog, "
        "deterministischer Neuaufbau, harte Sicherheits-/Zustandsfilterung."
    ),
    license="BSD",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "gesture_memory_node = ihk_pepper_gesture_memory.gesture_memory_node:main",
        ],
    },
)
