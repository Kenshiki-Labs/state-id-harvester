"""Restore a private snapshot using the shared, bounded archive verifier."""

from __future__ import annotations

import argparse

from state_id_harvester.paths import managed_path
from state_id_harvester.snapshots import restore_library


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive_directory", type=managed_path)
    parser.add_argument("destination", type=managed_path)
    args = parser.parse_args()
    restore_library(args.archive_directory, args.destination)


if __name__ == "__main__":
    main()
