// ihk_pepper_behavior_tree: Custom-BT.CPP-Knoten, die die bereits
// existierenden, getesteten ROS2-Actions/Services/Topics aufrufen (Say,
// PlayGesture, PlayPresentation, ApproachPerson, /safety_state,
// /interaction_state, /system_health).
//
// NICHT KOMPILIERT/GETESTET in dieser Session -- behaviortree_cpp ist auf
// diesem Entwicklungsrechner nicht installiert (kein sudo-Zugriff), siehe
// README.md in diesem Paket und IMPLEMENTATION_REPORT.md. Geschrieben
// gegen die dokumentierte BehaviorTree.CPP-4.x-API (StatefulActionNode/
// ConditionNode/PortsList), aber vor dem ersten `colcon build` mit
// installierter Bibliothek koennen noch Kompilierfehler auftreten.
#pragma once

#include <behaviortree_cpp/behavior_tree.h>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>

#include <ihk_pepper_interfaces/action/say.hpp>
#include <ihk_pepper_interfaces/action/play_gesture.hpp>
#include <ihk_pepper_interfaces/action/play_presentation.hpp>
#include <ihk_pepper_interfaces/action/approach_person.hpp>
#include <ihk_pepper_interfaces/msg/safety_state.hpp>
#include <ihk_pepper_interfaces/msg/system_health.hpp>
#include <ihk_pepper_interfaces/srv/cancel_interaction.hpp>
#include <action_msgs/srv/cancel_goal.hpp>
#include <std_msgs/msg/u_int8.hpp>

namespace ihk_pepper_bt
{

// ---- Bedingungen (lesen nur, keine Seiteneffekte) ----------------------

/// Basisklasse fuer Bedingungen, die einen einzelnen Topic-Wert
/// beobachten. Haelt selbst KEINE Executor-Instanz -- bt_executor_node.cpp
/// spinnt den gemeinsamen rclcpp::Node in der Tick-Schleife
/// (executor.spin_some()), siehe dortige Kommentare.
class TopicWatchingCondition : public BT::ConditionNode
{
public:
  TopicWatchingCondition(const std::string & name, const BT::NodeConfig & config)
  : BT::ConditionNode(name, config) {}
};

class IsSafetyTriggered : public TopicWatchingCondition
{
public:
  IsSafetyTriggered(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus tick() override;

private:
  rclcpp::Subscription<ihk_pepper_interfaces::msg::SafetyState>::SharedPtr sub_;
  bool triggered_ {false};
};

class IsBatteryLow : public TopicWatchingCondition
{
public:
  IsBatteryLow(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<double>("threshold", 15.0, "Akku-Prozent-Schwelle")};
  }
  BT::NodeStatus tick() override;

private:
  rclcpp::Subscription<ihk_pepper_interfaces::msg::SystemHealth>::SharedPtr sub_;
  double battery_percent_ {100.0};
  bool have_reading_ {false};
};

/// Gemeinsame Basis fuer die drei interaction_state-basierten Bedingungen
/// (IsPersonEngaged/ShouldShowPresentation/IsPersonAttracted/
/// IsNavigationTaskActive) -- alle lesen denselben UInt8-Topic
/// /interaction_state (siehe ihk_pepper_interaction/supervisor_node.py).
class InteractionStateCondition : public TopicWatchingCondition
{
public:
  InteractionStateCondition(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node, uint8_t expected_state);
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus tick() override;

private:
  rclcpp::Subscription<std_msgs::msg::UInt8>::SharedPtr sub_;
  uint8_t expected_state_;
  uint8_t current_state_ {0};   // 0 == IDLE (InteractionState-IntEnum)
  bool have_reading_ {false};
};

// Werte aus ihk_pepper_interaction/interaction_state.py::InteractionState
constexpr uint8_t INTERACTION_STATE_IDLE = 0;
constexpr uint8_t INTERACTION_STATE_ATTRACT = 1;
constexpr uint8_t INTERACTION_STATE_ENGAGED = 2;
constexpr uint8_t INTERACTION_STATE_NAVIGATING = 4;

// ---- Aktionen (rufen echte ROS2-Actions/Services auf) -------------------

/// Ruft /pepper_bridge/say auf und wartet auf das Ergebnis.
class SpeakText : public BT::StatefulActionNode
{
public:
  SpeakText(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<std::string>("text")};
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  using SayAction = ihk_pepper_interfaces::action::Say;
  using GoalHandle = rclcpp_action::ClientGoalHandle<SayAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<SayAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
};

/// Ruft /pepper_bridge/play_gesture auf.
class WaveGesture : public BT::StatefulActionNode
{
public:
  WaveGesture(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<std::string>("gesture_name", "wave_right", "Name aus dem Gesten-Katalog")};
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  using GestureAction = ihk_pepper_interfaces::action::PlayGesture;
  using GoalHandle = rclcpp_action::ClientGoalHandle<GestureAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<GestureAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
};

/// Ruft /play_presentation auf (ihk_pepper_presentation).
class PlayDailyPresentation : public BT::StatefulActionNode
{
public:
  PlayDailyPresentation(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<std::string>("topic_id", "", "Leer = automatische Auswahl"),
      BT::InputPort<bool>("allow_qa", true, "")
    };
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  using PresentationAction = ihk_pepper_interfaces::action::PlayPresentation;
  using GoalHandle = rclcpp_action::ClientGoalHandle<PresentationAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<PresentationAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
};

/// Ruft /approach_person auf (ihk_pepper_navigation). track_id kommt aus
/// dem Blackboard ("{target_track_id}") -- WICHTIG: aktuell befuellt KEIN
/// Node dieses Blackboard-Feld automatisch, siehe README.md.
class ApproachTargetPerson : public BT::StatefulActionNode
{
public:
  ApproachTargetPerson(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<int>("track_id"),
      BT::InputPort<double>("target_distance_m", 1.0, "")
    };
  }
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  using ApproachAction = ihk_pepper_interfaces::action::ApproachPerson;
  using GoalHandle = rclcpp_action::ClientGoalHandle<ApproachAction>;
  rclcpp::Node::SharedPtr node_;
  rclcpp_action::Client<ApproachAction>::SharedPtr client_;
  std::shared_future<GoalHandle::SharedPtr> goal_future_;
  std::shared_future<GoalHandle::WrappedResult> result_future_;
  GoalHandle::SharedPtr goal_handle_;
};

/// Ruft /cancel_interaction UND den generischen Action-Cancel-Service
/// fuer /play_presentation auf -- exakt derselbe Pfad wie der
/// Tablet-Stop-Button (siehe flask_wrapper/tablet/ros_bridge.py
/// request_stop()). Kehrt sofort mit SUCCESS zurueck (fire-and-forget,
/// wie beim Tablet-Button).
class SafeStopAll : public BT::SyncActionNode
{
public:
  SafeStopAll(
    const std::string & name, const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr node);
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus tick() override;

private:
  rclcpp::Node::SharedPtr node_;
  rclcpp::Client<ihk_pepper_interfaces::srv::CancelInteraction>::SharedPtr cancel_interaction_client_;
  rclcpp::Client<action_msgs::srv::CancelGoal>::SharedPtr cancel_presentation_client_;
};

/// No-op, immer SUCCESS -- letzter Ausweg im IdleAttractSubtree, damit
/// der Baum immer terminiert (Pepper bleibt einfach ruhig stehen).
class AlwaysSuccessIdle : public BT::SyncActionNode
{
public:
  AlwaysSuccessIdle(const std::string & name, const BT::NodeConfig & config)
  : BT::SyncActionNode(name, config) {}
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus tick() override {return BT::NodeStatus::SUCCESS;}
};

}  // namespace ihk_pepper_bt
