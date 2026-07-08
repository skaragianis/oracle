import argparse

from oracle.common.ingest import ingest_file


def main() -> None:
    parser = argparse.ArgumentParser(prog="oracle-cli")
    parser.add_argument(
        "--add",
        "-a",
        metavar="FILE_PATH",
        help="Add a PDF or DOCX file for later searching",
    )
    args = parser.parse_args()

    if args.add:
        destination_path = ingest_file(args.add)
        print(f"Added {args.add} -> {destination_path}")
        return

    parser.print_usage()


if __name__ == "__main__":
    main()
