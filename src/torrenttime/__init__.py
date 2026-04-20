#! /usr/bin/env python3

import argparse
import datetime
import glob
import logging
import os
import sqlite3
import sys

import bencodepy
import platformdirs

NS_PER_S = 1_000_000_000

QBITTORRENT_PATH = platformdirs.PlatformDirs("qBittorrent").user_data_dir
QBITTORRENT_STATE_PATH_GLOB = os.path.join(
    QBITTORRENT_PATH, "BT_backup", "*.fastresume"
)
QBITTORRENT_TORRENT_PATH_FORMAT = os.path.join(
    QBITTORRENT_PATH, "BT_backup", "{}.torrent"
)

QBITTORRENT_DB_PATH = os.path.join(QBITTORRENT_PATH, "torrents.db")
QBITTORRENT_DB_STATES_QUERY = """
  select torrent_id,
         libtorrent_resume_data,
         metadata
    from torrents
   where has_seed_status = 1
order by queue_position desc
""".strip()
QBITTORRENT_DB_TORRENT_QUERY = """
select metadata
  from torrents
 where torrent_id = ?
""".strip()

_logger = logging.getLogger(__name__)


def read_torrent_by_infohash_from_db(infohash: str) -> bytes:
    """Retrieve a binary torrent from the database."""

    _logger.debug(f"looking for torrent in the DB ({infohash=})")
    with sqlite3.connect(f"file:{QBITTORRENT_DB_PATH}?mode=rw", uri=True) as con:
        cur = con.cursor()
        res = cur.execute(QBITTORRENT_DB_TORRENT_QUERY, (infohash,))
        row = res.fetchone()
        cur.close()
        if row:
            _logger.debug(f"found torrent in the DB ({infohash=})")
            return row[0]


def read_torrent_by_infohash_from_file(infohash: str) -> bytes:
    """Retrieve a binary torrent from the filesystem."""

    _logger.debug(f"looking for torrent on disk ({infohash=})")
    with open(QBITTORRENT_TORRENT_PATH_FORMAT.format(infohash), "rb") as torrent_file:
        _logger.debug(f"found torrent on disk ({infohash=})")
        return torrent_file.read()


def read_torrent_by_infohash(infohash: str):
    """Retrieve a decoded torrent."""

    for reader in (
        read_torrent_by_infohash_from_db,
        read_torrent_by_infohash_from_file,
    ):
        try:
            torrent = reader(infohash)

            if torrent:
                return bencodepy.decode(torrent)

            return None
        except:
            continue


def torrent_states_from_db():
    """Yields a tuple of the binary (state, torrent) of each torrent in the
    database."""

    _logger.debug(f"looking for states in the DB")
    with sqlite3.connect(f"file:{QBITTORRENT_DB_PATH}?mode=rw", uri=True) as con:
        cur = con.cursor()
        res = cur.execute(QBITTORRENT_DB_STATES_QUERY)
        while row := res.fetchone():
            infohash, state, torrent = row
            _logger.debug(f"found state in the DB ({infohash=})")
            yield (state, torrent)
        cur.close()


def torrent_states_from_files():
    """Yields a tuple of the binary (state, torrent) of each torrent in the
    filesystem."""

    for state_filename in glob.glob(QBITTORRENT_STATE_PATH_GLOB):
        _logger.debug(f"found state on disk ({state_filename=})")

        infohash, _ = os.path.splitext(os.path.basename(state_filename))

        with open(state_filename, "rb") as file:
            state = file.read()

        torrent = read_torrent_by_infohash_from_file(infohash)

        yield (state, torrent)


def torrent_states():
    """Yields a tuple of the decoded (state, torrent) of each torrent."""
    for generator in (
        torrent_states_from_db,
        torrent_states_from_files,
    ):
        try:
            for state, torrent in generator():
                yield (bencodepy.decode(state), bencodepy.decode(torrent))

            return None
        except GeneratorExit:
            return
        except:
            continue


def torrent_files():
    """Yields a (filename, infohash) tuple for each torrented file."""
    for state, torrent in torrent_states():
        infohash = bytes.hex(state[b"info-hash"])
        save_path = state[b"save_path"]
        torrent_name = torrent[b"info"][b"name"]

        if b"mapped_files" in state:
            for filename in state[b"mapped_files"]:
                yield (os.path.join(save_path, filename), infohash)
        else:
            path = os.path.join(save_path, torrent_name)

            if b"files" in torrent[b"info"]:
                for file in torrent[b"info"][b"files"]:
                    filenames = file[b"path"]
                    yield (os.path.join(path, *filenames), infohash)
            else:
                yield (path, infohash)


def torrent_inodes():
    """Generates a (inode, infohash) tuple for each torrented file."""
    for filename, infohash in torrent_files():
        try:
            stat = os.stat(filename)
            yield (stat.st_ino, infohash)
        except FileNotFoundError:
            _logger.debug(f"{filename} of torrent {infohash} not found")
            continue
        except GeneratorExit:
            return


def read_torrent_by_inode(inode: int):
    for maybe_inode, infohash in torrent_inodes():
        if maybe_inode == inode:
            _logger.debug(f"inode {inode} belongs to torrent {infohash}")
            return read_torrent_by_infohash(infohash)

    return None


def _error(message: str, fatal: bool = True) -> None:
    print(f"{os.path.basename(sys.argv[0])}: {message}", file=sys.stderr)
    if fatal:
        sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    source_group = parser.add_argument_group("source")
    source_excl = source_group.add_mutually_exclusive_group()

    source_excl.add_argument(
        "-H",
        "--infohash",
        help="update the mtime of all files with the creation time of the "
        + "torrent with this infohash",
    )
    source_excl.add_argument(
        "-r",
        "--reference",
        help="update the mtime of all files with the creation time of the "
        + "torrent that this file belongs to",
    )

    parser.description = """
Update files' modification times (mtimes) from the creation date of a torrent
file.
        """.strip()
    parser.epilog = """
If neither --infohash nor --reference are given, each file is individually
correlated with a torrent and has its mtime adjusted accordingly.

File correlation (for both --reference and positional files) is performed by
looking for a hardlinked file which is tracked by qBittorrent fastresume state.
        """.strip()

    parser.add_argument(
        "-l",
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
    )

    parser.add_argument("-v", "--verbose", action="store_true")

    parser.add_argument(
        "filenames", metavar="file", nargs="+", help="file to trace and re-mtime"
    )

    args = parser.parse_args()

    logging.basicConfig(level=args.log_level.upper())

    default_reference = None
    if args.infohash:
        default_reference = read_torrent_by_infohash(args.infohash)

        if not default_reference:
            _error(f"could not find a torrent with infohash {args.infohash}")
    elif args.reference:
        try:
            stat = os.stat(args.reference)
        except FileNotFoundError:
            _error(f"{args.reference} not found")

        default_reference = read_torrent_by_inode(stat.st_ino)

        if not default_reference:
            _error(f"{args.reference}: could not find a containing torrent")

    if default_reference and b"creation date" not in default_reference:
        _error(f"reference torrent does not have a creation date")

    for filename in args.filenames:
        try:
            stat = os.stat(filename)
        except FileNotFoundError:
            _error(f"{filename}: not found", fatal=False)
            continue

        file_reference = default_reference
        if not file_reference:
            if stat.st_nlink < 2:
                _error(f"{filename}: no other file links", fatal=False)
                continue

            file_reference = read_torrent_by_inode(stat.st_ino)

        if not file_reference:
            _error(f"{filename}: could not find a containing torrent ", fatal=False)
            continue
        elif b"creation date" not in file_reference:
            _error(
                f"{filename}: related torrent does not have a creation date",
                fatal=False,
            )
            continue

        mtime = file_reference[b"creation date"]
        mtime_datetime = datetime.datetime.fromtimestamp(
            mtime, tz=datetime.timezone.utc
        )
        _logger.debug(f"found new mtime ({filename=}, mtime='{mtime_datetime}')")
        if args.verbose:
            print(f"{filename}: {mtime_datetime}")

        os.utime(filename, ns=(stat.st_atime_ns, mtime * NS_PER_S))

    return 0
