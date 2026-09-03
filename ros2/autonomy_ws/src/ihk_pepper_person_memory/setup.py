from setuptools import find_packages, setup

package_name = "ihk_pepper_person_memory"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="you",
    maintainer_email="you@example.com",
    description=(
        "Versionierte Vertraege fuer ein spaeteres Personen-/"
        "Gespraechsgedaechtnis. Keine echte Gesichtsdatenbank."
    ),
    license="BSD",
    tests_require=["pytest"],
)
