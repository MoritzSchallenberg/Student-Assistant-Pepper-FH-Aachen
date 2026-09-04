// ihk_pepper_behavior_tree: laedt trees/pepper_main.xml, registriert die
// Custom-Knoten aus bt_nodes.hpp/.cpp und tickt den Baum in einer
// Schleife. Verbindet einen Groot2Publisher fuer Live-Monitoring/-Steuerung
// in Groot2 (Verbinden ueber "localhost:1667", siehe README.md).
//
// Erstmals erfolgreich gegen behaviortree_cpp 4.9.0 gebaut und lokal
// (ohne Pepper/RealSense) gestartet+beendet -- siehe
// docs/DEVELOPMENT_ORDER_01_REPORT.md fuer den genauen Nachweis.
#include <csignal>

#include <atomic>
#include <chrono>
#include <memory>

#include <behaviortree_cpp/bt_factory.h>
#include <behaviortree_cpp/loggers/groot2_publisher.h>
#include <rclcpp/rclcpp.hpp>
#include <ament_index_cpp/get_package_share_directory.hpp>

#include "ihk_pepper_behavior_tree/bt_nodes.hpp"

using namespace std::chrono_literals;

// rclcpp installiert selbst einen SIGINT-Handler (macht rclcpp::ok()
// false), aber KEINEN fuer SIGTERM -- das braucht der Auftrag
// ausdruecklich ("sauber auf SIGINT/SIGTERM reagieren"). Ein simples
// atomic-Flag statt eines direkten rclcpp::shutdown()-Aufrufs im
// Handler, da Letzteres nicht async-signal-safe ist.
std::atomic<bool> g_shutdown_requested{false};

void handle_sigterm([[maybe_unused]] int signum)
{
  g_shutdown_requested.store(true);
}

int main(int argc, char ** argv)
{
  std::signal(SIGTERM, handle_sigterm);

  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>("bt_executor");

  node->declare_parameter<std::string>("tree_file", "");
  node->declare_parameter<double>("tick_rate_hz", 10.0);
  node->declare_parameter<int>("groot2_port", 1667);

  std::string tree_file = node->get_parameter("tree_file").as_string();
  if (tree_file.empty()) {
    tree_file = ament_index_cpp::get_package_share_directory("ihk_pepper_behavior_tree") +
      "/trees/pepper_main.xml";
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

  // Entwicklungsauftrag 1, Abschnitt 6: neuer Begruessen-und-Annaehern-Ablauf.
  factory.registerBuilder<ihk_pepper_bt::IsSystemReady>(
    "IsSystemReady",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::IsSystemReady>(name, config, node);
    });
  factory.registerBuilder<ihk_pepper_bt::IsApproachAllowed>(
    "IsApproachAllowed",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::IsApproachAllowed>(name, config, node);
    });
  factory.registerBuilder<ihk_pepper_bt::SelectStablePerson>(
    "SelectStablePerson",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::SelectStablePerson>(name, config, node);
    });
  factory.registerNodeType<ihk_pepper_bt::HasGreetingCooldownExpired>("HasGreetingCooldownExpired");
  factory.registerBuilder<ihk_pepper_bt::WaitForGestureFromTrack>(
    "WaitForGestureFromTrack",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::WaitForGestureFromTrack>(name, config, node);
    });
  factory.registerBuilder<ihk_pepper_bt::ApproachSelectedPerson>(
    "ApproachSelectedPerson",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::ApproachSelectedPerson>(name, config, node);
    });
  factory.registerBuilder<ihk_pepper_bt::SetInteractionState>(
    "SetInteractionState",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::SetInteractionState>(name, config, node);
    });
  factory.registerNodeType<ihk_pepper_bt::ClearSelectedPerson>("ClearSelectedPerson");

  factory.registerBuilder<ihk_pepper_bt::SpeakText>(
    "SpeakText",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::SpeakText>(name, config, node);
    });
  factory.registerBuilder<ihk_pepper_bt::PlayCatalogGesture>(
    "PlayCatalogGesture",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::PlayCatalogGesture>(name, config, node);
    });
  factory.registerBuilder<ihk_pepper_bt::PlayDailyPresentation>(
    "PlayDailyPresentation",
    [node](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<ihk_pepper_bt::PlayDailyPresentation>(name, config, node);
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
  // welcher Knoten gerade laeuft. Ein fehlendes/nicht verbundenes Groot2
  // darf den Executor NICHT blockieren -- der Publisher wartet passiv
  // auf eine Verbindung, blockiert also ohnehin nicht; zusaetzlich wird
  // ein Bind-Fehler (z.B. Port belegt durch eine zweite Executor-Instanz)
  // abgefangen, statt den ganzen Prozess abstuerzen zu lassen.
  int groot2_port = node->get_parameter("groot2_port").as_int();
  std::unique_ptr<BT::Groot2Publisher> groot2_publisher;
  try {
    groot2_publisher = std::make_unique<BT::Groot2Publisher>(tree, groot2_port);
    RCLCPP_INFO(node->get_logger(), "Groot2Publisher aktiv auf Port %d", groot2_port);
  } catch (const std::exception & e) {
    RCLCPP_WARN(
      node->get_logger(),
      "Groot2Publisher konnte nicht gestartet werden (%s) -- Executor laeuft trotzdem weiter, "
      "nur ohne Live-Monitoring.", e.what());
  }

  double tick_rate = node->get_parameter("tick_rate_hz").as_double();
  rclcpp::Rate rate(tick_rate);

  RCLCPP_INFO(node->get_logger(), "bt_executor gestartet, tickt mit %.1f Hz.", tick_rate);

  // Der Baum laeuft dauerhaft weiter (Fallback am Root wird bei jedem
  // Tick neu ausgewertet) -- SUCCESS/FAILURE des Root-Knotens fuehrt
  // bewusst NICHT zum Abbruch der Schleife, da MainTree kein einmaliger
  // Auftrag ist, sondern Peppers fortlaufendes Verhalten modelliert.
  while (rclcpp::ok() && !g_shutdown_requested.load()) {
    // WICHTIG: spin_some() VOR tickOnce(), damit die Subscription-
    // Callbacks in den Condition-Knoten (IsSafetyTriggered etc.) vor dem
    // Tick aktuelle Werte haben, und async_send_goal/async_get_result-
    // Futures aus den Action-Knoten Fortschritt machen koennen.
    rclcpp::spin_some(node);
    tree.tickOnce();
    rate.sleep();
  }

  RCLCPP_INFO(node->get_logger(), "bt_executor faehrt sauber herunter.");
  rclcpp::shutdown();
  return 0;
}
