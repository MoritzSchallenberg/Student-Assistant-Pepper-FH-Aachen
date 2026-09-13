// Funktionale GTests fuer RunDialogueViaBT (Entwicklungsauftrag 04-B,
// AP8.8, Commit 13/14). Nutzt einen echten rclcpp_action-Client
// (RunDialogueViaBT selbst) gegen einen minimalen, kontrollierten
// Fake-ActionServer -- kein reiner Promise-/Future-Test, echte
// ROS2-Action-Kommunikation ueber Loopback-DDS.
//
// Bestaetigter Fund (Abschnitt 3.4): RunDialogueViaBT::onHalted() gab
// bisher auf, wenn goal_handle_ noch null war (Goal-Acceptance stand
// noch aus) -- eine SPAETER eintreffende Annahme lief danach
// unbeaufsichtigt weiter, kein Cancel wurde je gestellt. Der Fix
// (SendGoalOptions::goal_response_callback + halted_before_acceptance_-
// Flag) storniert ein solches Ziel jetzt sofort bei Ankunft der
// (verspaeteten) Annahme.
#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <thread>

#include <gtest/gtest.h>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>

#include "ihk_pepper_behavior_tree/bt_nodes.hpp"
#include "ihk_pepper_interfaces/action/run_dialogue.hpp"

using RunDialogueAction = ihk_pepper_interfaces::action::RunDialogue;
using GoalHandleRunDialogue = rclcpp_action::ServerGoalHandle<RunDialogueAction>;

namespace
{

/// Minimaler, kontrollierter Fake-ActionServer fuer /run_dialogue --
/// nimmt JEDES Ziel an, haelt es dann absichtlich offen (kein
/// automatisches Ergebnis), und zaehlt eingehende Cancel-Anfragen. Kein
/// echter Dialog-/LLM-/TTS-Code, ausschliesslich fuer die
/// Goal-Lifecycle-Pruefung gedacht.
class FakeRunDialogueServer : public rclcpp::Node
{
public:
  FakeRunDialogueServer()
  : rclcpp::Node("fake_run_dialogue_server_for_bt_test")
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
        // handle_accepted -- Ziel bleibt absichtlich offen (der Test
        // steuert alles ueber Cancel/Timeout, keine echte Auto-Beendigung).
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

/// Baut eine RunDialogueViaBT-Instanz mit einem literalen session_id-
/// Port-Wert (keine XML-Baumdatei/kein Blackboard-Remapping noetig).
std::unique_ptr<ihk_pepper_bt::RunDialogueViaBT> makeNode(
  rclcpp::Node::SharedPtr client_node, const std::string & instance_name)
{
  BT::NodeConfig config;
  config.blackboard = BT::Blackboard::create();
  config.input_ports["session_id"] = "42";
  return std::make_unique<ihk_pepper_bt::RunDialogueViaBT>(instance_name, config, client_node);
}

}  // namespace

TEST(RunDialogueViaBTLifecycle, LateGoalAcceptanceAfterHaltBeforeAcceptanceIsCancelledImmediately)
{
  auto server_node = std::make_shared<FakeRunDialogueServer>();
  auto client_node = std::make_shared<rclcpp::Node>("test_client_node_late_acceptance");

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(server_node);
  executor.add_node(client_node);

  auto bt_node = makeNode(client_node, "run_dialogue_via_bt_under_test");

  // onStart() sendet das Ziel (asynchron) -- NICHTS wurde bisher gespinnt,
  // die Antwort des Servers kann also strukturell noch nicht angekommen
  // sein. onHalted() trifft deshalb GARANTIERT auf goal_handle_==nullptr.
  ASSERT_EQ(bt_node->onStart(), BT::NodeStatus::RUNNING);
  bt_node->onHalted();
  EXPECT_TRUE(bt_node->haltedBeforeAcceptance());
  EXPECT_FALSE(bt_node->lastHaltCancelConfirmed());  // es gab (noch) keinen Handle zu stornieren

  // ERST JETZT spinnen -- die (verspaetete) Annahme trifft ein, der
  // registrierte goal_response_callback muss sie sofort stornieren.
  auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
  while (server_node->cancelRequestedCount() == 0 && std::chrono::steady_clock::now() < deadline) {
    executor.spin_some(std::chrono::milliseconds(50));
  }

  EXPECT_GE(server_node->cancelRequestedCount(), 1)
    << "Ein NACH onHalted() verspaetet angenommenes Ziel wurde nicht storniert.";
}

TEST(RunDialogueViaBTLifecycle, AcceptedGoalIsCancelledDirectlyWhenHaltArrivesAfterAcceptance)
{
  auto server_node = std::make_shared<FakeRunDialogueServer>();
  auto client_node = std::make_shared<rclcpp::Node>("test_client_node_normal_halt");

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(server_node);
  executor.add_node(client_node);

  auto bt_node = makeNode(client_node, "run_dialogue_via_bt_under_test_2");

  ASSERT_EQ(bt_node->onStart(), BT::NodeStatus::RUNNING);

  // Diesmal WIRD gespinnt, bis onRunning() tatsaechlich einen Handle
  // gesehen hat (normaler Fall: Halt trifft NACH bestaetigter Annahme ein).
  auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
  BT::NodeStatus status = BT::NodeStatus::RUNNING;
  while (std::chrono::steady_clock::now() < deadline) {
    executor.spin_some(std::chrono::milliseconds(20));
    status = bt_node->onRunning();
    if (status != BT::NodeStatus::RUNNING) {
      break;
    }
    // onRunning() setzt goal_handle_ intern, sobald die Annahme
    // angekommen ist -- ein zweiter onRunning()-Aufruf reicht als
    // Nachweis, dass der Handle jetzt gesetzt ist (Ergebnis-Future noch
    // nicht fertig, da handle_accepted() das Ziel offen haelt).
    if (server_node->cancelRequestedCount() >= 0) {
      // (kein echter Abbruchgrund hier, nur Iteration weiterlaufen lassen)
    }
  }

  bt_node->onHalted();
  EXPECT_FALSE(bt_node->haltedBeforeAcceptance());
  // Ob lastHaltCancelConfirmed() true wird, haengt von der lokalen
  // CancelGoal-Service-Rundlaufzeit ab (siehe kHaltCancelConfirmTimeout,
  // 250ms) -- hier zaehlt vor allem, dass tatsaechlich EIN Cancel beim
  // Server ankam.
  auto cancel_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
  while (server_node->cancelRequestedCount() == 0 &&
    std::chrono::steady_clock::now() < cancel_deadline)
  {
    executor.spin_some(std::chrono::milliseconds(20));
  }
  EXPECT_GE(server_node->cancelRequestedCount(), 1);
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  testing::InitGoogleTest(&argc, argv);
  int result = RUN_ALL_TESTS();
  rclcpp::shutdown();
  return result;
}
