cmake_minimum_required(VERSION 3.5)
project(pepper_meshes)

find_package(ament_cmake REQUIRED)

# HINWEIS: Das Original-Paket (ros-naoqi/pepper_meshes) laedt die Meshes
# beim Bauen per Installer aus dem Internet herunter (interaktiv, ohne
# I_AGREE_TO_PEPPER_MESHES_LICENSE=1 haengt der Build!). Fuer dieses
# portable Export-Paket liegen die Mesh-Dateien bereits real vor
# (meshes/), daher hier nur ein einfacher, offline-tauglicher Install-Schritt.

install(DIRECTORY meshes DESTINATION share/${PROJECT_NAME})

ament_package()
