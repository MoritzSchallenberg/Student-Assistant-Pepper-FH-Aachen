#!/usr/bin/env python3
"""
Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 8/9: reproduzierbare
Laufzeit-Benchmarks fuer ausgewaehlte Dialog-/Gesten-Pfade. Laeuft
AUSSCHLIESSLICH offline (temporaere SQLite-Datei, MockLLMProvider, keine
echte Hardware/kein externer LLM-Aufruf, kein ROS2-Node noetig fuer die
meisten Messungen).

Aufruf (nach `colcon build`, im Workspace-Root):
    source /opt/ros/jazzy/setup.bash && source install/setup.bash
    python3 scripts/benchmark_ap8_runtime.py

Nutzt zunaechst den tatsaechlichen 24-Gesten-Katalog
(src/ihk_pepper_bridge/config/gestures/). Eine groessere synthetische
Datenmenge ist NICHT Teil dieses Skripts -- ausdruecklich als
Skalierungstest zu kennzeichnen, falls spaeter ergaenzt (Auftrag
Abschnitt 8).
"""
import gc
import json
import os
import resource
import statistics
import sys
import tempfile
import threading
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GESTURE_DIR = os.path.join(REPO_ROOT, "src", "ihk_pepper_bridge", "config", "gestures")

WARMUP_RUNS = 5
MEASURED_RUNS = 200


def _percentile(values, pct):
    values = sorted(values)
    if not values:
        return float("nan")
    k = (len(values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def _timed(fn, warmup=WARMUP_RUNS, runs=MEASURED_RUNS):
    for _ in range(warmup):
        fn()
    samples_s = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples_s.append(time.perf_counter() - start)
    return {
        "runs": runs,
        "warmup": warmup,
        "p50_ms": _percentile(samples_s, 50) * 1000.0,
        "p95_ms": _percentile(samples_s, 95) * 1000.0,
        "mean_ms": statistics.mean(samples_s) * 1000.0,
        "min_ms": min(samples_s) * 1000.0,
        "max_ms": max(samples_s) * 1000.0,
    }


def _rss_kb():
    # Entwicklungsauftrag 04-B, AP8-R3, Abschnitt 8: ru_maxrss ist unter
    # Linux in KiB (anders als macOS, wo es Bytes waeren) -- dieses
    # Skript ist ausschliesslich fuer den hier verwendeten Linux-
    # Entwicklungsrechner gedacht, keine Plattformumrechnung noetig.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def benchmark_gesture_search():
    """Kandidat A (Abschnitt 9): GestureIndexStore.search() ohne
    Suchtext, mit wiederholtem Suchtext, mit wechselnden Suchtexten --
    gegen den tatsaechlichen 24-Gesten-Katalog. Vergleicht den
    unveraenderlichen Snapshot-Cache (jetzt Standard) explizit gegen den
    vorherigen Pfad (erzwungenes Neuladen bei jeder Anfrage), um den
    tatsaechlichen Effekt zu belegen -- kein pauschal behaupteter
    Vorteil."""
    from ihk_pepper_bridge.gesture_catalog import GestureCatalog
    from ihk_pepper_gesture_memory.embedding_backend import create_embedding_backend
    from ihk_pepper_gesture_memory.gesture_index_db import GestureIndexStore
    from ihk_pepper_gesture_memory.gesture_search import GestureSearchRequest

    catalog = GestureCatalog(GESTURE_DIR)
    errors = catalog.reload()
    if errors:
        print(f"WARNUNG: {len(errors)} Katalogfehler beim Laden -- Benchmark laeuft trotzdem weiter.")

    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    os.unlink(db_path)
    embedding_backend = create_embedding_backend()
    store = GestureIndexStore(db_path, embedding_backend=embedding_backend)
    reindex_result = store.reindex(catalog, force=True)

    changing_queries = [
        "Begruessung mit Handbewegung", "erklaerende Geste nach rechts",
        "zustimmendes Nicken", "unsicher mit den Schultern zucken",
        "kurze Verabschiedung", "auf das Tablet zeigen",
    ]
    query_cycle = {"i": 0}

    def _search_no_query():
        store.search(GestureSearchRequest(query="", top_k=5))

    def _search_repeated_query():
        store.search(GestureSearchRequest(query="freundliche Begruessung", top_k=5))

    def _search_changing_query():
        q = changing_queries[query_cycle["i"] % len(changing_queries)]
        query_cycle["i"] += 1
        store.search(GestureSearchRequest(query=q, top_k=5))

    results = {
        "catalog_gesture_count": len(catalog.names()),
        "reindex_result": reindex_result,
        "search_no_query_cached": _timed(_search_no_query),
        "search_repeated_query_cached": _timed(_search_repeated_query),
        "search_changing_query_cached": _timed(_search_changing_query),
    }

    # Gegenprobe: derselbe Suchpfad OHNE Snapshot-Cache (erzwingt bei
    # jeder Anfrage ein frisches _load_all_entries()) -- exakt der vorher
    # bestehende Codepfad, hier ueber eine gezielte Invalidierung vor
    # jedem Aufruf reproduziert, KEIN zweiter Store/keine zweite
    # Implementierung.
    def _search_no_query_uncached():
        with store._snapshot_lock:
            store._cached_entries = None
        store.search(GestureSearchRequest(query="", top_k=5))

    def _search_changing_query_uncached():
        with store._snapshot_lock:
            store._cached_entries = None
        q = changing_queries[query_cycle["i"] % len(changing_queries)]
        query_cycle["i"] += 1
        store.search(GestureSearchRequest(query=q, top_k=5))

    results["search_no_query_uncached_baseline"] = _timed(_search_no_query_uncached, runs=50)
    results["search_changing_query_uncached_baseline"] = _timed(_search_changing_query_uncached, runs=50)

    store.close()
    os.unlink(db_path)
    return results


def benchmark_response_plan_executor_cancel_latency():
    """Cancel bis zur beobachteten Reaktion: die unterbrechbare
    Nachlaufpause (post_speech_pause_s) aus AP8.9 -- misst die reale
    Zeit zwischen cancel() und der tatsaechlichen Rueckkehr aus
    execute(), bei einer bewusst lang gesetzten Pause."""
    from ihk_pepper_dialog.response_plan_executor import ResponsePlanExecutor

    def _say_fn(text):
        return True

    def _gesture_fn(name, speed):
        return True

    samples_ms = []
    for _ in range(30):
        executor = ResponsePlanExecutor(
            say_fn=_say_fn, gesture_fn=_gesture_fn, post_speech_pause_s=2.0)
        plan = _make_plan("Kurzer Testsatz.")

        cancel_after_s = 0.05
        result_holder = {}

        def _run():
            result_holder["value"] = executor.execute(plan)

        t = threading.Thread(target=_run, daemon=True)
        start = time.perf_counter()
        t.start()
        time.sleep(cancel_after_s)
        executor.cancel()
        t.join(timeout=3.0)
        elapsed = time.perf_counter() - start
        samples_ms.append(elapsed * 1000.0)

    return {
        "runs": len(samples_ms),
        "post_speech_pause_s": 2.0,
        "cancel_issued_after_s": 0.05,
        "p50_ms": _percentile(samples_ms, 50),
        "p95_ms": _percentile(samples_ms, 95),
        "max_ms": max(samples_ms),
    }


def _make_plan(text):
    from ihk_pepper_llm_contracts.response_plan import ResponsePlan, ResponseSegment
    return ResponsePlan(segments=[ResponseSegment(segment_id="a", text=text)], source_ids=[])


def benchmark_repeated_session_cleanup():
    """Wiederholte Sitzung und Cleanup: konstruiert/zerstoert N
    ResponsePlanExecutor-Instanzen (derselbe Lebenszyklus wie eine echte
    Dialogrunde in run_dialogue_action_server.py) und beobachtet RSS-
    Entwicklung -- kein Speicherwachstum ueber viele Runden erwartet."""
    from ihk_pepper_dialog.response_plan_executor import ResponsePlanExecutor

    def _say_fn(text):
        return True

    def _gesture_fn(name, speed):
        return True

    rss_samples_kb = []
    n = 500
    for i in range(n):
        executor = ResponsePlanExecutor(say_fn=_say_fn, gesture_fn=_gesture_fn, post_speech_pause_s=0.0)
        plan = _make_plan(f"Testsatz Nummer {i}.")
        executor.execute(plan)
        del executor
        if i % 50 == 0:
            gc.collect()
            rss_samples_kb.append(_rss_kb())
    gc.collect()
    rss_samples_kb.append(_rss_kb())
    return {
        "sessions": n,
        "rss_kb_samples_every_50_sessions": rss_samples_kb,
        "rss_kb_first": rss_samples_kb[0],
        "rss_kb_last": rss_samples_kb[-1],
        "rss_growth_kb": rss_samples_kb[-1] - rss_samples_kb[0],
    }


def main():
    report = {
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
        },
        "gesture_search": benchmark_gesture_search(),
        "response_plan_executor_cancel_latency": benchmark_response_plan_executor_cancel_latency(),
        "repeated_session_cleanup": benchmark_repeated_session_cleanup(),
    }
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
