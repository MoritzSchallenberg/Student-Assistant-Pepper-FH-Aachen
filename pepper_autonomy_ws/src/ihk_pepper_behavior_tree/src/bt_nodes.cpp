// NICHT KOMPILIERT/GETESTET in dieser Session, siehe bt_nodes.hpp.
#include "ihk_pepper_behavior_tree/bt_nodes.hpp"

namespace ihk_pepper_bt
{

// ---- IsSafetyTriggered ---------------------------------------------------

IsSafetyTriggered::IsSafetyTriggered(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: TopicWatchingCondition(name, config)
{
  sub_ = node->create_subscription<ihk_pepper_interfaces::msg::SafetyState>(
    "/safety_state", 10,
    [this](const ihk_pepper_interfaces::msg::SafetyState::SharedPtr msg) {
      triggered_ = msg->emergency_stop || msg->bumper_active;
    });
}

BT::NodeStatus IsSafetyTriggered::tick()
{
  return triggered_ ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

// ---- IsBatteryLow ---------------------------------------------------------

IsBatteryLow::IsBatteryLow(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: TopicWatchingCondition(name, config)
{
  sub_ = node->create_subscription<ihk_pepper_interfaces::msg::SystemHealth>(
    "/pepper_bridge/system_health", 10,
    [this](const ihk_pepper_interfaces::msg::SystemHealth::SharedPtr msg) {
      battery_percent_ = msg->battery_percent;
      have_reading_ = true;
    });
}

BT::NodeStatus IsBatteryLow::tick()
{
  double threshold = getInput<double>("threshold").value_or(15.0);
  // Ohne jemals empfangene Messung (battery_percent koennte auch -1.0
  // sein, wenn Pepper unerreichbar ist, siehe bridge_node.py) bewusst
  // FAILURE -- kein Alarm ohne echte Daten (gleiches Prinzip wie
  // SafetyGate: fehlende Daten sind nie automatisch "alles ok").
  if (!have_reading_ || battery_percent_ < 0.0) {
    return BT::NodeStatus::FAILURE;
  }
  return battery_percent_ < threshold ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

// ---- InteractionStateCondition --------------------------------------------

InteractionStateCondition::InteractionStateCondition(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node, uint8_t expected_state)
: TopicWatchingCondition(name, config), expected_state_(expected_state)
{
  sub_ = node->create_subscription<std_msgs::msg::UInt8>(
    "/interaction_state", 10,
    [this](const std_msgs::msg::UInt8::SharedPtr msg) {
      current_state_ = msg->data;
      have_reading_ = true;
    });
}

BT::NodeStatus InteractionStateCondition::tick()
{
  if (!have_reading_) {
    return BT::NodeStatus::FAILURE;
  }
  return current_state_ == expected_state_ ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

// ---- SpeakText --------------------------------------------------------------

SpeakText::SpeakText(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = rclcpp_action::create_client<SayAction>(node_, "/pepper_bridge/say");
}

BT::NodeStatus SpeakText::onStart()
{
  auto text = getInput<std::string>("text");
  if (!text || text.value().empty()) {
    return BT::NodeStatus::FAILURE;
  }
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    RCLCPP_WARN(node_->get_logger(), "SpeakText: Say-Action nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  SayAction::Goal goal;
  goal.text = text.value();
  goal.allow_interrupt = true;
  goal.max_duration_s = 0.0;
  goal_handle_.reset();
  goal_future_ = client_->async_send_goal(goal);
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus SpeakText::onRunning()
{
  if (!goal_handle_) {
    if (goal_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
      return BT::NodeStatus::RUNNING;
    }
    goal_handle_ = goal_future_.get();
    if (!goal_handle_) {
      return BT::NodeStatus::FAILURE;   // Ziel abgelehnt
    }
    result_future_ = client_->async_get_result(goal_handle_);
    return BT::NodeStatus::RUNNING;
  }
  if (result_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto result = result_future_.get();
  return result.result->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void SpeakText::onHalted()
{
  if (goal_handle_) {
    client_->async_cancel_goal(goal_handle_);
  }
}

// ---- WaveGesture --------------------------------------------------------

WaveGesture::WaveGesture(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = rclcpp_action::create_client<GestureAction>(node_, "/pepper_bridge/play_gesture");
}

BT::NodeStatus WaveGesture::onStart()
{
  auto gesture_name = getInput<std::string>("gesture_name").value_or("wave_right");
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    RCLCPP_WARN(node_->get_logger(), "WaveGesture: PlayGesture-Action nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  GestureAction::Goal goal;
  goal.gesture_name = gesture_name;
  goal.speed_scale = 1.0;
  goal_handle_.reset();
  goal_future_ = client_->async_send_goal(goal);
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus WaveGesture::onRunning()
{
  if (!goal_handle_) {
    if (goal_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
      return BT::NodeStatus::RUNNING;
    }
    goal_handle_ = goal_future_.get();
    if (!goal_handle_) {
      return BT::NodeStatus::FAILURE;
    }
    result_future_ = client_->async_get_result(goal_handle_);
    return BT::NodeStatus::RUNNING;
  }
  if (result_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto result = result_future_.get();
  return result.result->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void WaveGesture::onHalted()
{
  if (goal_handle_) {
    client_->async_cancel_goal(goal_handle_);
  }
}

// ---- PlayDailyPresentation ------------------------------------------------

PlayDailyPresentation::PlayDailyPresentation(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = rclcpp_action::create_client<PresentationAction>(node_, "/play_presentation");
}

BT::NodeStatus PlayDailyPresentation::onStart()
{
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    RCLCPP_WARN(node_->get_logger(), "PlayDailyPresentation: Action nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  PresentationAction::Goal goal;
  goal.topic_id = getInput<std::string>("topic_id").value_or("");
  goal.allow_qa = getInput<bool>("allow_qa").value_or(true);
  goal_handle_.reset();
  goal_future_ = client_->async_send_goal(goal);
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus PlayDailyPresentation::onRunning()
{
  if (!goal_handle_) {
    if (goal_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
      return BT::NodeStatus::RUNNING;
    }
    goal_handle_ = goal_future_.get();
    if (!goal_handle_) {
      return BT::NodeStatus::FAILURE;
    }
    result_future_ = client_->async_get_result(goal_handle_);
    return BT::NodeStatus::RUNNING;
  }
  if (result_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto result = result_future_.get();
  return result.result->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void PlayDailyPresentation::onHalted()
{
  if (goal_handle_) {
    client_->async_cancel_goal(goal_handle_);
  }
}

// ---- ApproachTargetPerson -------------------------------------------------

ApproachTargetPerson::ApproachTargetPerson(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::StatefulActionNode(name, config), node_(node)
{
  client_ = rclcpp_action::create_client<ApproachAction>(node_, "/approach_person");
}

BT::NodeStatus ApproachTargetPerson::onStart()
{
  auto track_id = getInput<int>("track_id");
  if (!track_id) {
    // Blackboard-Feld "target_track_id" wird aktuell von NIEMANDEM
    // automatisch befuellt (siehe README.md) -- das ist der erwartete,
    // haeufigste Fall in dieser Session.
    return BT::NodeStatus::FAILURE;
  }
  if (!client_->wait_for_action_server(std::chrono::seconds(1))) {
    RCLCPP_WARN(node_->get_logger(), "ApproachTargetPerson: Action nicht erreichbar");
    return BT::NodeStatus::FAILURE;
  }
  ApproachAction::Goal goal;
  goal.track_id = static_cast<uint32_t>(track_id.value());
  goal.target_distance_m = static_cast<float>(getInput<double>("target_distance_m").value_or(1.0));
  goal_handle_.reset();
  goal_future_ = client_->async_send_goal(goal);
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus ApproachTargetPerson::onRunning()
{
  if (!goal_handle_) {
    if (goal_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
      return BT::NodeStatus::RUNNING;
    }
    goal_handle_ = goal_future_.get();
    if (!goal_handle_) {
      return BT::NodeStatus::FAILURE;
    }
    result_future_ = client_->async_get_result(goal_handle_);
    return BT::NodeStatus::RUNNING;
  }
  if (result_future_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
    return BT::NodeStatus::RUNNING;
  }
  auto result = result_future_.get();
  return result.result->success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
}

void ApproachTargetPerson::onHalted()
{
  if (goal_handle_) {
    client_->async_cancel_goal(goal_handle_);
  }
}

// ---- SafeStopAll ------------------------------------------------------------

SafeStopAll::SafeStopAll(
  const std::string & name, const BT::NodeConfig & config,
  rclcpp::Node::SharedPtr node)
: BT::SyncActionNode(name, config), node_(node)
{
  cancel_interaction_client_ =
    node_->create_client<ihk_pepper_interfaces::srv::CancelInteraction>("/cancel_interaction");
  cancel_presentation_client_ =
    node_->create_client<action_msgs::srv::CancelGoal>("/play_presentation/_action/cancel_goal");
}

BT::NodeStatus SafeStopAll::tick()
{
  if (cancel_interaction_client_->service_is_ready()) {
    auto req = std::make_shared<ihk_pepper_interfaces::srv::CancelInteraction::Request>();
    req->reason = "behavior_tree_safety_stop";
    cancel_interaction_client_->async_send_request(req);
  }
  if (cancel_presentation_client_->service_is_ready()) {
    auto req = std::make_shared<action_msgs::srv::CancelGoal::Request>();
    cancel_presentation_client_->async_send_request(req);
  }
  RCLCPP_WARN(node_->get_logger(), "SafeStopAll ausgeloest (Sicherheitsereignis erkannt)");
  return BT::NodeStatus::SUCCESS;
}

}  // namespace ihk_pepper_bt
