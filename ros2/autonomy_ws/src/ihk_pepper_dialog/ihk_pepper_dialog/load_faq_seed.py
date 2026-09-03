#!/usr/bin/env python3
"""Einmalig ausfuehren, um die Beispiel-FAQ-Eintraege in die SQLite-DB zu
laden: `ros2 run ihk_pepper_dialog load_faq_seed`"""
import json
import os
import sys

from ament_index_python.packages import get_package_share_directory

from .faq_cache import FaqCache


def main():
    seed_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        get_package_share_directory("ihk_pepper_dialog"), "data", "faq_seed.json"
    )
    db_path = sys.argv[2] if len(sys.argv) > 2 else os.environ.get(
        "PEPPER_FAQ_DB_PATH", os.path.expanduser("~/.ihk_pepper/faq_cache.sqlite")
    )

    with open(seed_path) as f:
        entries = json.load(f)

    cache = FaqCache(db_path)
    for entry in entries:
        cache.add_entry(
            canonical_question=entry["canonical_question"],
            answer=entry["answer"],
            language=entry.get("language", "de"),
            topic=entry.get("topic"),
            approved=entry.get("approved", False),
        )
    print(f"{len(entries)} FAQ-Eintraege geladen nach {db_path}")
    cache.close()


if __name__ == "__main__":
    main()
