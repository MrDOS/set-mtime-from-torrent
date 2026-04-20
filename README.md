# set-mtime-from-torrent

Given some files,
this script figures out which (qBittorrent-managed) torrents they correspond to
by comparing hardlinks,
and resets the mtime of the file
to the creation date/time of the torrent.

## Development

The project uses [src layout],
so it can't be run without installation.
To hack on the codebase,
create a virtual environment,
and install the package into it,
along with extra dependencies useful for development:

```
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install --editable ".[dev]"
```

Then you can run the script:

```
set-mtime-from-torrent /path/to/foo.mkv
```

By making the installation _editable_,
the venv references the source in its original location
(i.e., in `./src/torrenttime`, rather than copying it into `.venv`),
so changes made to the source tree
are immediately reflected in use.

When returning to work on the project
after the venv has been created:

```
. .venv/bin/activate
```

After changing `pyproject.toml`,
reinstall the editable package:

```
pip install --editable ".[dev]"
```

[src layout]: https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/
