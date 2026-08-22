// ihk_pepper_behavior_tree: laedt trees/pepper_main.xml, registriert die
// Custom-Knoten aus bt_nodes.hpp/.cpp und tickt den Baum in einer
// Schleife. Verbindet einen Groot2Publisher fuer Live-Monitoring/-Steuerung
// in Groot2 (Verbinden ueber "localhost:1667", siehe README.md).
//
// NICHT KOMPILIERT/GETESTET in dieser Session, siehe bt_nodes.hpp und
// README.md fuer den Grund (behaviortree_cpp nicht installiert).
#include <chrono>
#include <memory>

#include <behaviortree_cpp/bt_factory.h>
#include <behaviortree_cpp/loggers/groot2_publisher.h>
#include <rclcpp/rclcpp.hpp>
#include <ament_index_cpp/get_package_share_directory.hpp>

#include "ihk_pepper_behavior_tree/bt_nodes.hpp"

using namespace std::chrono_literals;

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>("bt_executor");

  node->declare_parameter<std::string>("tree_file", "");
  node->declare_parameter<double>("tick_rate_hz", 10.0);
  node->declare_parameter<int>("groot2_port", 1667);

  std::string tree_file = node->get_parameter("tree_file").as_string();
  if (tree_file.empty()) {
    tree_file = ament_index_cpp::get_package_share_directory("ihk_pepper_behavior_tree")
      + "/trees/pepper_main.xml";
  }
  RCLCPP_INFO(node->get_logger(), "Lade Baum: %s", tree_file.c_str());

  BT::BehaviorTreeFactory factory;

  // Bedingungen/Aktionen, die einen gemeinsamen rclcpp::Node brauchen,
  // werden ueber registerBuilder mit einer Lambda-Fabrik registriert
  // (Standard-Pattern fuer BT.CPP + ROS2, da der Default-Konstruktor von
  // BT::TreeNode keinen Platz fuer zusaetzliche Argumente hat).
  factory.registerBuilder<ihk_pepper_bt::IsSafetyTriggered>(
    "IsSafetyTriggered",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::IsSafetyTriggered>(name, config, node);
    });
  factory.registerBuilder<ihk_pepper_bt::IsBatteryLow>(
    "IsBatteryLow",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::IsBatteryLow>(name, config, node);
    });
  factory.registerBuilder<ihk_pepper_bt::InteractionStateCondition>(
    "IsPersonEngaged",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::InteractionStateCondition>(
        name, config, node, ihk_pepper_bt::INTERACTION_STATE_ENGAGED);
    });
  factory.registerBuilder<ihk_pepper_bt::InteractionStateCondition>(
    "ShouldShowPresentation",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::InteractionStateCondition>(
        name, config, node, ihk_pepper_bt::INTERACTION_STATE_IDLE);
    });
  factory.registerBuilder<ihk_pepper_bt::InteractionStateCondition>(
    "IsPersonAttracted",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::InteractionStateCondition>(
        name, config, node, ihk_pepper_bt::INTERACTION_STATE_ATTRACT);
    });
  factory.registerBuilder<ihk_pepper_bt::InteractionStateCondition>(
    "IsNavigationTaskActive",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::InteractionStateCondition>(
        name, config, node, ihk_pepper_bt::INTERACTION_STATE_NAVIGATING);
    });

  factory.registerBuilder<ihk_pepper_bt::SpeakText>(
    "SpeakText",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::SpeakText>(name, config, node);
    });
  factory.registerBuilder<ihk_pepper_bt::WaveGesture>(
    "WaveGesture",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::WaveGesture>(name, config, node);
    });
  factory.registerBuilder<ihk_pepper_bt::PlayDailyPresentation>(
    "PlayDailyPresentation",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::PlayDailyPresentation>(name, config, node);
    });
  factory.registerBuilder<ihk_pepper_bt::ApproachTargetPerson>(
    "ApproachTargetPerson",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::ApproachTargetPerson>(name, config, node);
    });
  factory.registerBuilder<ihk_pepper_bt::SafeStopAll>(
    "SafeStopAll",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::SafeStopAll>(name, config, node);
    });

  // Braucht keinen ROS-Node -> normale registerNodeType reicht.
  factory.registerNodeType<ihk_pepper_bt::AlwaysSuccessIdle>("AlwaysSuccessIdle");

  BT::Tree tree = factory.createTreeFromFile(tree_file);

  // Groot2 (Desktop-App, siehe README.md) verbindet sich live auf
  // "localhost:<groot2_port>" (Standard 1667) und zeigt/kann steuern,
  // welcher Knoten gerade laeuft -- das ist der eigentliche "Baum
  // oeffnen und live sehen was Pepper gerade macht"-Anwendungsfall.
  int groot2_port = node->get_parameter("groot2_port").as_int();
  BT::Groot2Publisher publisher(tree, groot2_port);
  RCLCPP_INFO(node->get_logger(), "Groot2Publisher aktiv auf Port %d", groot2_port);

  double tick_rate = node->get_parameter("tick_rate_hz").as_double();
  rclcpp::Rate rate(tick_rate);

  RCLCPP_INFO(node->get_logger(), "bt_executor gestartet, tickt mit %.1f Hz.", tick_rate);

  // Der Baum laeuft dauerhaft weiter (Fallback am Root wird bei jedem
  // Tick neu ausgewertet) -- SUCCESS/FAILURE des Root-Knotens fuehrt
  // bewusst NICHT zum Abbruch der Schleife, da MainTree kein einmaliger
  // Auftrag ist, sondern Peppers fortlaufendes Verhalten modelliert.
  while (rclcpp::ok()) {
    // WICHTIG: spin_some() VOR tickOnce(), damit die Subscription-
    // Callbacks in den Condition-Knoten (IsSafetyTriggered etc.) vor dem
    // Tick aktuelle Werte haben, und async_send_goal/async_get_result-
    // Futures aus den Action-Knoten Fortschritt machen koennen.
    rclcpp::spin_some(node);
    tree.tickOnce();
    rate.sleep();
  }

  rclcpp::shutdown();
  return 0;
}
