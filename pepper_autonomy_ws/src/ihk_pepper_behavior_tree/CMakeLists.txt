cmake_minimum_required(VERSION 3.8)
project(ihk_pepper_behavior_tree)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(ament_index_cpp REQUIRED)
find_package(ihk_pepper_interfaces REQUIRED)
find_package(action_msgs REQUIRED)
find_package(std_msgs REQUIRED)
# NICHT installiert auf dem Entwicklungsrechner dieser Session -- siehe
# README.md/IMPLEMENTATION_REPORT.md. `sudo apt install
# ros-jazzy-behaviortree-cpp` noetig, bevor dieses Paket baut.
find_package(behaviortree_cpp REQUIRED)

add_library(ihk_pepper_bt_nodes SHARED
  src/bt_nodes.cpp
)
target_include_directories(ihk_pepper_bt_nodes PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
ament_target_dependencies(ihk_pepper_bt_nodes
  rclcpp rclcpp_action ihk_pepper_interfaces action_msgs std_msgs behaviortree_cpp
)

add_executable(bt_executor_node src/bt_executor_node.cpp)
target_link_libraries(bt_executor_node ihk_pepper_bt_nodes)
target_include_directories(bt_executor_node PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
ament_target_dependencies(bt_executor_node
  rclcpp rclcpp_action ament_index_cpp ihk_pepper_interfaces action_msgs
  std_msgs behaviortree_cpp
)

install(TARGETS ihk_pepper_bt_nodes
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION bin
)
install(TARGETS bt_executor_node
  DESTINATION lib/${PROJECT_NAME}
)
install(DIRECTORY include/
  DESTINATION include
)
install(DIRECTORY trees/
  DESTINATION share/${PROJECT_NAME}/trees
)
install(DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
