// Tests fuer waitForBoundedCancelConfirmation() (Entwicklungsauftrag
// 04-B, AP5B, Abschnitt 13). Bewusst OHNE rclcpp_action/Action-Server --
// die Funktion ist rein ueber std::future formuliert (siehe Kommentar in
// bt_nodes.hpp), deshalb reicht hier ein einfaches std::promise, um
// sowohl den "rechtzeitig bestaetigt"- als auch den
// "Bestaetigung steht noch aus"-Pfad deterministisch und schnell zu
// pruefen -- kein rclcpp::init(), kein echter Action-Client noetig.
#include <chrono>
#include <future>
#include <thread>

#include <gtest/gtest.h>
#include <rclcpp/rclcpp.hpp>

#include "ihk_pepper_behavior_tree/bt_nodes.hpp"

TEST(WaitForBoundedCancelConfirmation, ReturnsTrueWhenFutureIsAlreadyReady)
{
  std::promise<int> promise;
  promise.set_value(42);
  auto future = promise.get_future().share();

  bool confirmed = ihk_pepper_bt::waitForBoundedCancelConfirmation(
    future, std::chrono::milliseconds(50), rclcpp::get_logger("test"), "TestNode");

  EXPECT_TRUE(confirmed);
}

TEST(WaitForBoundedCancelConfirmation, ReturnsFalseWhenTimeoutElapsesBeforeConfirmation)
{
  std::promise<int> promise;   // wird absichtlich NIE erfuellt
  auto future = promise.get_future().share();

  auto start = std::chrono::steady_clock::now();
  bool confirmed = ihk_pepper_bt::waitForBoundedCancelConfirmation(
    future, std::chrono::milliseconds(50), rclcpp::get_logger("test"), "TestNode");
  auto elapsed = std::chrono::steady_clock::now() - start;

  EXPECT_FALSE(confirmed);
  // Begrenzt heisst begrenzt -- die Funktion darf nicht wesentlich
  // laenger als die uebergebene Frist blockieren (grosszuegige Toleranz
  // fuer langsame CI-Maschinen).
  EXPECT_LT(elapsed, std::chrono::milliseconds(500));
}

TEST(WaitForBoundedCancelConfirmation, ReturnsTrueWhenConfirmationArrivesJustWithinTheWindow)
{
  std::promise<int> promise;
  auto future = promise.get_future().share();

  std::thread confirmer([&promise]() {
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
      promise.set_value(1);
    });

  bool confirmed = ihk_pepper_bt::waitForBoundedCancelConfirmation(
    future, std::chrono::milliseconds(500), rclcpp::get_logger("test"), "TestNode");

  confirmer.join();
  EXPECT_TRUE(confirmed);
}

int main(int argc, char ** argv)
{
  testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
