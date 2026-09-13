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
# Installation: sudo apt install ros-jazzy-behaviortree-cpp
# (bzw. per rosdep, siehe package.xml). Erfolgreich gegen 4.9.0 gebaut,
# siehe docs/DEVELOPMENT_ORDER_01_REPORT.md.
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
  # Entwicklungsauftrag 04-B, AP5B, Abschnitt 13: rein logischer Test der
  # begrenzten Cancel-Bestaetigung (waitForBoundedCancelConfirmation()),
  # ohne rclcpp_action/echten Action-Server -- siehe
  # test/test_bt_cancel_confirmation.cpp.
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_bt_cancel_confirmation test/test_bt_cancel_confirmation.cpp)
  target_include_directories(test_bt_cancel_confirmation PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  )
  ament_target_dependencies(test_bt_cancel_confirmation
    rclcpp rclcpp_action ihk_pepper_interfaces action_msgs std_msgs behaviortree_cpp
  )

  # Entwicklungsauftrag 04-B, AP8.8, Commit 13/14: funktionale Tests
  # gegen einen echten RunDialogueViaBT-Knoten + einen kontrollierten
  # Fake-ActionServer (echte rclcpp_action-Kommunikation ueber
  # Loopback-DDS, kein reiner Promise-/Future-Test) -- siehe
  # test/test_bt_dialogue_gesture_lifecycle.cpp.
  ament_add_gtest(
    test_bt_dialogue_gesture_lifecycle test/test_bt_dialogue_gesture_lifecycle.cpp)
  target_include_directories(test_bt_dialogue_gesture_lifecycle PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  )
  target_link_libraries(test_bt_dialogue_gesture_lifecycle ihk_pepper_bt_nodes)
  ament_target_dependencies(test_bt_dialogue_gesture_lifecycle
    rclcpp rclcpp_action ihk_pepper_interfaces action_msgs std_msgs behaviortree_cpp
  )

  # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 6/7: funktionaler Test
  # der Gruppenverlust-Praeemption -- ein echter ReactiveSequence-
  # Teilbaum aus MonitorParticipants + RunDialogueViaBT (dieselbe
  # Struktur wie GroupConversationLoop in pepper_main.xml), echte
  # /perception/conversation_groups-Publikation, echter
  # rclcpp_action-Fake-Server -- siehe test/test_bt_group_loss_preemption.cpp.
  ament_add_gtest(
    test_bt_group_loss_preemption test/test_bt_group_loss_preemption.cpp)
  target_include_directories(test_bt_group_loss_preemption PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  )
  target_link_libraries(test_bt_group_loss_preemption ihk_pepper_bt_nodes)
  ament_target_dependencies(test_bt_group_loss_preemption
    rclcpp rclcpp_action ihk_pepper_interfaces action_msgs std_msgs behaviortree_cpp
  )

  find_package(ament_lint_auto REQUIRED)
  # ament_copyright: Copyright-Kopfzeilen sind in diesem Projekt keine
  # Konvention (keine andere Datei im Repo traegt eine) -- eine erfundene
  # "Copyright <Jahr> <Besitzer>"-Zeile allein fuer dieses Paket waere
  # inkonsistent und ohne Auftrag, wessen Copyright das sein soll.
  #
  # cpplint: die eingebaute legal/copyright-Kategorie hat denselben
  # Grund; build/include_order erwartet als erstes einen zur .cpp
  # passenden Selbst-Header (X.h) -- bt_executor_node.cpp hat bewusst
  # keinen (nur main(), die eigentliche Logik liegt in bt_nodes.hpp/.cpp),
  # die Regel passt strukturell nicht auf dieses Paket. cpplint bietet
  # ueber ament_lint_auto keine Filter-Konfiguration pro Kategorie an,
  # deshalb bewusst ganz uebersprungen statt eine kollidierende zweite
  # Testregistrierung zu erzwingen. Echte cpplint-Funde (C-Style-Cast,
  # Kommentar-Abstaende) wurden gefunden und behoben, siehe
  # docs/DEVELOPMENT_ORDER_01_REPORT.md.
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
