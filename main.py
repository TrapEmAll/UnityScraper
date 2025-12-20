#!/usr/bin/env python3
import argparse
import logging
import sys
from typing import List

from downloader import UnityScraper


def _split_title_ids(raw: str) -> List[str]:
    """
    Split a comma-separated string into TitleID tokens.
    """
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download Xbox cover art & title updates for given Xbox Title IDs "
            "via xboxunity.net. Outputs default to 'unityscrape/{title_id}/...'."
        )
    )

    # Make it optional so "python main.py" matches your README flow (prompt)
    parser.add_argument(
        "title_ids",
        nargs="?",
        default="",
        help="Comma-separated Title IDs, e.g. '555308C5,00000155'.",
    )

    parser.add_argument(
        "--out",
        default="unityscrape",
        help="Output base directory (default: unityscrape).",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=UnityScraper.DEFAULT_MAX_WORKERS,
        help=f"Parallel worker threads per TitleID (default: {UnityScraper.DEFAULT_MAX_WORKERS}).",
    )

    parser.add_argument(
        "--rate",
        type=float,
        default=0.35,
        help="Minimum seconds between HTTP requests across all threads (default: 0.35).",
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO).",
    )

    args = parser.parse_args()

    # Configure logging level
    logging.getLogger("downloader").setLevel(getattr(logging, args.log_level))

    raw_ids = args.title_ids.strip()
    if not raw_ids:
        # Matches README: prompt if not provided
        try:
            raw_ids = input("Enter TitleIDs separated by commas: ").strip()
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(1)

    title_ids = _split_title_ids(raw_ids)
    if not title_ids:
        print("No TitleIDs provided. Exiting.")
        return

    scraper = UnityScraper(
        base_dir=args.out,
        max_workers=args.workers,
        min_request_interval=args.rate,
    )

    failed = scraper.scrape_multiple(title_ids)

    if failed:
        print(f"\nThe following TitleIDs had failures: {', '.join(failed)}")
        sys.exit(2)

    print("\nAll TitleIDs processed successfully.")


if __name__ == "__main__":
    main()
