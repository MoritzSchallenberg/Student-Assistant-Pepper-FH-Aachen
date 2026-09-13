// Funktionaler GTest fuer die Gruppenverlust-Praeemption im Behavior
// Tree (Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 6/7 -- Testpunkte
// "Ein Mitglied verlaesst eine weiterhin gueltige Gruppe: kein
// vollstaendiger Gruppenabbruch", "Gruppe wird ungueltig:
// MonitorParticipants praeemptiert den laufenden Dialog", "Nach
// Gruppenverlust startet kein alter Antwortplan neu").
//
// Baut die REALE Baumstruktur aus pepper_main.xml direkt nach (ohne den
// vollen XML-Factory-Umweg -- dieselbe Direktkonstruktion wie in
// test_bt_dialogue_gesture_lifecycle.cpp):
//   ReactiveSequence
//     MonitorParticipants(group_id, minimum_members=2)
//     RunDialogueViaBT(session_id)
//
// Ein Helper-Test oder die blosse Existenz des AP7-Gruppencodes genuegt
// laut Auftrag NICHT -- dieser Test tickt einen ECHTEN Teilbaum mit den
// tatsaechlichen Projektknoten gegen einen echten rclcpp_action-
// Fake-Server (kein reiner Promise-/String-Test).
#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

#include <gtest/gtest.h>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>

#include <behaviortree_cpp/controls/reactive_sequence.h>

#include "ihk_pepper_behavior_tree/bt_nodes.hpp"
#include "ihk_pepper_interfaces/action/run_dialogue.hpp"
#include "ihk_pepper_interfaces/msg/conversation_group_array.hpp"

using RunDialogueAction = ihk_pepper_interfaces::action::RunDialogue;
using GoalHandleRunDialogue = rclcpp_action::ServerGoalHandle<RunDialogueAction>;
using ConversationGroupArray = ihk_pepper_interfaces::msg::ConversationGroupArray;
using ConversationGroup = ihk_pepper_interfaces::msg::ConversationGroup;

namespace
{

/// Derselbe minimale, kontrollierte Fake-ActionServer wie in
/// test_bt_dialogue_gesture_lifecycle.cpp -- nimmt jedes Ziel an, haelt
/// es offen, zaehlt Cancel-Anfragen.
class FakeRunDialogueServer : public rclcpp::Node
{
public:
  FakeRunDialogueServer()
  : rclcpp::Node("fake_run_dialogue_server_for_group_loss_test")
  {
    action_server_ = rclcpp_action::create_server<RunDialogueAction>(
      this,
      "/run_dialogue",
      [](const rclcpp_action::GoalUUID &, std::shared_ptr<const RunDialogueAction::Goal>) {
        return rclcpp_action::GoalResponse::ACCEPT_AND_EXECUTE;
      },
      [this](const std::shared_ptr<GoalHandleRunDialogue>) {
        cancel_requested_count_.fetch_add(1);
        return rclcpp_action::CancelResponse::ACCEPT;
      },
      [this](const std::shared_ptr<GoalHandleRunDialogue> goal_handle) {
        std::lock_guard<std::mutex> lock(mutex_);
        held_goal_handles_.push_back(goal_handle);
      });
  }

  int cancelRequestedCount() const {return cancel_requested_count_.load();}

private:
  rclcpp_action::Server<RunDialogueAction>::SharedPtr action_server_;
  std::atomic<int> cancel_requested_count_{0};
  std::mutex mutex_;
  std::vector<std::shared_ptr<GoalHandleRunDialogue>> held_goal_handles_;
};

/// Testtreiber: veroeffentlicht /perception/conversation_groups mit
/// steuerbarer Mitgliederzahl/Stabilitaet -- exakt das Topic/die
/// Feldsemantik, die MonitorParticipants::tick() tatsaechlich liest
/// (siehe bt_nodes.cpp).
class GroupPublisherDriver : public rclcpp::Node
{
public:
  GroupPublisherDriver()
  : rclcpp::Node("group_publisher_driver_for_group_loss_test")
  {
    pub_ = create_publisher<ConversationGroupArray>("/perception/conversation_groups", 10);
  }

  void publishGroup(
    const std::string & group_id, std::vector<uint32_t> member_track_ids,
    bool stable)
  {
    ConversationGroupArray msg;
    ConversationGroup group;
    group.group_id = group_id;
    group.member_track_ids = member_track_ids;
    group.stable = stable;
    msg.groups.push_back(group);
    pub_->publish(msg);
  }

  void publishNoGroups()
  {
    ConversationGroupArray msg;  // groups bleibt leer -- Gruppe "aufgeloest"
    pub_->publish(msg);
  }

private:
  rclcpp::Publisher<ConversationGroupArray>::SharedPtr pub_;
};

std::unique_ptr<ihk_pepper_bt::RunDialogueViaBT> makeDialogueNode(
  rclcpp::Node::SharedPtr client_node, const std::string & instance_name)
{
  BT::NodeConfig config;
  config.blackboard = BT::Blackboard::create();
  config.input_ports["session_id"] = "77";
  return std::make_unique<ihk_pepper_bt::RunDialogueViaBT>(instance_name, config, client_node);
}

std::unique_ptr<ihk_pepper_bt::MonitorParticipants> makeMonitorNode(
  rclcpp::Node::SharedPtr node, const std::string & instance_name, const std::string & group_id)
{
  BT::NodeConfig config;
  config.blackboard = BT::Blackboard::create();
  config.input_ports["group_id"] = group_id;
  config.input_ports["minimum_members"] = "2";
  return std::make_unique<ihk_pepper_bt::MonitorParticipants>(instance_name, config, node);
}

}  // namespace

TEST(GroupLossPreemption, StableGroupWithEnoughMembersDoesNotPreemptTheRunningDialogue)
{
  // "Ein Mitglied verlaesst eine weiterhin gueltige Gruppe: kein
  // vollstaendiger Gruppenabbruch" -- hier die Gegenprobe: eine
  // durchgehend stabile, ausreichend grosse Gruppe darf NIE zu einem
  // Cancel fuehren.
  auto server_node = std::make_shared<FakeRunDialogueServer>();
  auto client_node = std::make_shared<rclcpp::Node>("test_client_node_stable_group");
  auto driver = std::make_shared<GroupPublisherDriver>();

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(server_node);
  executor.add_node(client_node);
  executor.add_node(driver);

  auto monitor = makeMonitorNode(client_node, "monitor_participants_under_test", "group-A");
  auto dialogue = makeDialogueNode(client_node, "run_dialogue_via_bt_under_test");

  BT::ReactiveSequence root("GroupConversationLoop");
  root.addChild(monitor.get());
  root.addChild(dialogue.get());

  // Wiederholt publizieren + ticken, bis RUNNING erreicht ist (siehe
  // Kommentar im naechsten Test zur ROS2-Discovery-Verzoegerung).
  BT::NodeStatus status = BT::NodeStatus::FAILURE;
  auto start_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
  while (status != BT::NodeStatus::RUNNING && std::chrono::steady_clock::now() < start_deadline) {
    driver->publishGroup("group-A", {1, 2}, /*stable=*/true);
    executor.spin_some(std::chrono::milliseconds(100));
    status = root.executeTick();
  }
  ASSERT_EQ(status, BT::NodeStatus::RUNNING);

  // Weiter ticken -- die Gruppe bleibt durchgehend stabil,
  // RunDialogueViaBT muss ungestoert weiterlaufen (kein Cancel).
  for (int i = 0; i < 5; ++i) {
    driver->publishGroup("group-A", {1, 2}, /*stable=*/true);
    root.executeTick();
    executor.spin_some(std::chrono::milliseconds(50));
  }

  EXPECT_EQ(server_node->cancelRequestedCount(), 0)
    << "Eine durchgehend stabile, ausreichend grosse Gruppe darf keinen Cancel ausloesen.";
}

TEST(GroupLossPreemption, GroupBecomingInvalidPreemptsTheRunningDialogue)
{
  // "Gruppe wird ungueltig: MonitorParticipants praeemptiert den
  // laufenden Dialog." Start mit einer gueltigen Gruppe (2 Mitglieder,
  // stabil), dann Verlust unter minimum_members -- der laufende
  // RunDialogueViaBT-Knoten MUSS ueber die umgebende ReactiveSequence
  // gehaltet werden, was ein echtes Cancel an den Fake-Server ausloest.
  auto server_node = std::make_shared<FakeRunDialogueServer>();
  auto client_node = std::make_shared<rclcpp::Node>("test_client_node_group_loss");
  auto driver = std::make_shared<GroupPublisherDriver>();

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(server_node);
  executor.add_node(client_node);
  executor.add_node(driver);

  auto monitor = makeMonitorNode(client_node, "monitor_participants_under_test_2", "group-B");
  auto dialogue = makeDialogueNode(client_node, "run_dialogue_via_bt_under_test_2");

  BT::ReactiveSequence root("GroupConversationLoop2");
  root.addChild(monitor.get());
  root.addChild(dialogue.get());

  // Wiederholt (Gruppe erneut) publizieren + ticken, bis die Sequenz
  // tatsaechlich RUNNING liefert -- ein einzelner publish()/tick() kann
  // durch die uebliche ROS2-Discovery-Verzoegerung (Publisher/
  // Abonnent muessen sich erst finden, ebenso der Action-Client von
  // RunDialogueViaBT) verloren gehen bzw. zu frueh kommen.
  BT::NodeStatus status = BT::NodeStatus::FAILURE;
  auto start_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
  while (status != BT::NodeStatus::RUNNING && std::chrono::steady_clock::now() < start_deadline) {
    driver->publishGroup("group-B", {10, 11}, /*stable=*/true);
    executor.spin_some(std::chrono::milliseconds(100));
    status = root.executeTick();
  }
  ASSERT_EQ(status, BT::NodeStatus::RUNNING)
    << "RunDialogueViaBT haette bei einer gueltigen Gruppe RUNNING erreichen muessen.";

  // Gruppe verliert ein Mitglied -- nur noch 1 uebrig (< minimum_members=2).
  driver->publishNoGroups();  // Gruppe "aufgeloest" (nicht mehr in der Liste)
  executor.spin_some(std::chrono::milliseconds(100));

  // Weiter ticken (Gruppenverlust erneut publizieren), bis die Sequenz
  // FAILURE liefert -- MonitorParticipants haltet dabei das noch
  // laufende RunDialogueViaBT-Kind, BEVOR die Sequenz selbst FAILURE
  // nach oben meldet.
  auto fail_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
  while (status != BT::NodeStatus::FAILURE && std::chrono::steady_clock::now() < fail_deadline) {
    driver->publishNoGroups();
    executor.spin_some(std::chrono::milliseconds(100));
    status = root.executeTick();
  }
  ASSERT_EQ(status, BT::NodeStatus::FAILURE)
    << "MonitorParticipants haette nach Gruppenverlust FAILURE liefern muessen.";

  auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
  while (server_node->cancelRequestedCount() == 0 && std::chrono::steady_clock::now() < deadline) {
    executor.spin_some(std::chrono::milliseconds(50));
  }
  EXPECT_GE(server_node->cancelRequestedCount(), 1)
    << "Gruppenverlust (MonitorParticipants FAILURE) muss den laufenden Dialog praeemptieren.";
}

TEST(GroupLossPreemption, NoNewAnswerPlanStartsAfterGroupLossHalt)
{
  // "Nach Gruppenverlust startet kein alter Antwortplan neu" -- nach dem
  // Halt (siehe voriger Test) darf ein erneuter Tick der Sequenz (die
  // Gruppe bleibt ungueltig) KEINEN neuen RunDialogue-Goal ausloesen,
  // solange MonitorParticipants weiterhin FAILURE liefert (die
  // ReactiveSequence erreicht ihr zweites Kind dann gar nicht erst).
  auto server_node = std::make_shared<FakeRunDialogueServer>();
  auto client_node = std::make_shared<rclcpp::Node>("test_client_node_no_restart");
  auto driver = std::make_shared<GroupPublisherDriver>();

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(server_node);
  executor.add_node(client_node);
  executor.add_node(driver);

  auto monitor = makeMonitorNode(client_node, "monitor_participants_under_test_3", "group-C");
  auto dialogue = makeDialogueNode(client_node, "run_dialogue_via_bt_under_test_3");

  BT::ReactiveSequence root("GroupConversationLoop3");
  root.addChild(monitor.get());
  root.addChild(dialogue.get());

  // Gruppe von Anfang an bereits ungueltig (nie stabil genug).
  driver->publishGroup("group-C", {20}, /*stable=*/true);  // nur 1 Mitglied < minimum_members
  executor.spin_some(std::chrono::milliseconds(100));

  for (int i = 0; i < 3; ++i) {
    auto status = root.executeTick();
    EXPECT_EQ(status, BT::NodeStatus::FAILURE);
    executor.spin_some(std::chrono::milliseconds(50));
  }

  // Kein einziges RunDialogue-Ziel wurde je gestartet (MonitorParticipants
  // liess die ReactiveSequence nie bis zum zweiten Kind kommen) --
  // folglich auch kein Cancel noetig/moeglich.
  EXPECT_EQ(server_node->cancelRequestedCount(), 0);
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  testing::InitGoogleTest(&argc, argv);
  int result = RUN_ALL_TESTS();
  rclcpp::shutdown();
  return result;
}
