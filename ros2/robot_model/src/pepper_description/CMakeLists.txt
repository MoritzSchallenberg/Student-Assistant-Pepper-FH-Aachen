cmake_minimum_required(VERSION 3.8)
project(pepper_description)

find_package(ament_cmake REQUIRED)

install(DIRECTORY urdf launch DESTINATION share/${PROJECT_NAME})
install(FILES pepper_offline.rviz DESTINATION share/${PROJECT_NAME})

ament_package()
