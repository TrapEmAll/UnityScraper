import argparse
import json
import logging
import sys
from pathlib import Path

# IMPORTANT:
# If your UnityScraper class is in downloader.py, this import is correct.
from downloader import UnityScraper


def emit(ok: bool, data=None, error: str = None, exit_code: int = 0):
    """
    Emit a single JSON object to stdout.
    C# depends on stdout being JSON ONLY.
    """
    print(json.dumps({
        "ok": ok,
        "data": data,
        "error": error
    }, ensure_ascii=False))
    sys.exit(exit_code)


def main():
    parser = argparse.ArgumentParser(prog="unityscraper_cli")

    parser.add_argument("--verbose", action="store_true", help="Enable backend logging to stderr")
    parser.add_argument("--base-dir", default="unityscrape")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--min-interval", type=float, default=0.35)

    sub = parser.add_subparsers(dest="cmd", required=True)

    # ------------------ Covers ------------------
    covers = sub.add_parser("covers")
    covers_sub = covers.add_subparsers(dest="covers_cmd", required=True)

    covers_list = covers_sub.add_parser("list")
    covers_list.add_argument("--titleid", required=True)

    covers_dl = covers_sub.add_parser("download")
    covers_dl.add_argument("--titleid", required=True)
    covers_dl.add_argument("--coverid", required=True)
    covers_dl.add_argument("--out", required=True)

    # ------------------ Title Updates ------------------
    tu = sub.add_parser("tu")
    tu_sub = tu.add_subparsers(dest="tu_cmd", required=True)

    tu_list = tu_sub.add_parser("list")
    tu_list.add_argument("--titleid", required=True)

    tu_dl = tu_sub.add_parser("download")
    tu_dl.add_argument("--tuid", required=True)
    tu_dl.add_argument("--out", required=True)
    
    args = parser.parse_args()
    # Default: silence all logging so stdout stays JSON-only (C# code depends on it)
    if args.verbose:
        logging.disable(logging.NOTSET)
    
    else:
        logging.disable(logging.CRITICAL)

    scraper = UnityScraper(
        base_dir=args.base_dir,
        max_workers=args.workers,
        min_request_interval=args.min_interval
    )

    try:
        # -------- Covers: list --------
        if args.cmd == "covers" and args.covers_cmd == "list":
            payload = scraper.get_covers_info(args.titleid)
            if payload is None:
                emit(False, error="Failed to fetch cover info", exit_code=1)

            covers = payload.get("Covers", [])
            out = []

            for c in covers:
                if not isinstance(c, dict):
                    continue
                out.append({
                    "TitleId": args.titleid.upper(),
                    "CoverID": str(c.get("CoverID", "")).strip(),
                    "Type": c.get("Type"),
                    "Description": c.get("Description"),
                })

            emit(True, data=out)

        # -------- Covers: download --------
        if args.cmd == "covers" and args.covers_cmd == "download":
            path = scraper.download_cover_by_id(
                args.titleid,
                args.coverid,
                out_dir=args.out
            )
            if not path:
                emit(False, error="Cover download failed", exit_code=1)

            emit(True, data={"Path": path})

        # -------- Title Updates: list --------
        if args.cmd == "tu" and args.tu_cmd == "list":
            payload = scraper.get_updates_info(args.titleid)
            if payload is None:
                emit(False, error="Failed to fetch update info", exit_code=1)

            tasks = scraper._extract_update_tasks(payload)

            out = []
            for media_id, upd in tasks:
                tuid = str(
                    upd.get("TitleUpdateID")
                    or upd.get("TitleUpdateId")
                    or upd.get("tuid")
                    or ""
                ).strip()

                if not tuid:
                    continue

                out.append({
                    "TitleId": args.titleid.upper(),
                    "MediaId": str(media_id),
                    "TitleUpdateId": tuid,
                    "Version": str(upd.get("Version") or ""),
                    "Hash": str(upd.get("hash") or ""),
                    "Size": str(upd.get("Size") or ""),
                    "UploadDate": str(upd.get("UploadDate") or ""),
                    "Name": str(upd.get("Name") or ""),
                    "BaseVersion": str(upd.get("BaseVersion") or ""),
                })

            emit(True, data=out)

        # -------- Title Updates: download --------
        if args.cmd == "tu" and args.tu_cmd == "download":
            out_dir = str(Path(args.out))
            path = scraper.download_update_by_id(args.tuid, out_dir=out_dir)
            if not path:
                emit(False, error="TU download failed", exit_code=1)

            emit(True, data={"Path": path})

        emit(False, error="Unknown command", exit_code=1)

    except Exception as ex:
        emit(False, error=f"{type(ex).__name__}: {ex}", exit_code=1)


if __name__ == "__main__":
    main()
