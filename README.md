# Shardbound

An Eador-inspired strategy game on [Saga2D](../saga2d). Choose one of four
heroes, develop a stronghold, explore guarded ruins, recruit an army, and take
Duskspire before the rival reaches Westwatch. The 19-province campaign carries
wounds, casualties and experience between hex battles; a three-shard linked
campaign adds challenge choices, a travelling retinue and a recovery
expedition. Original content, painted artwork, procedural miniatures and
original music and sound.

## Play the latest version

Shardbound runs straight from this checkout on macOS and Windows; nothing is
installed system-wide. You need
[uv](https://docs.astral.sh/uv/getting-started/installation/) and the two
repositories Shardbound depends on, checked out beside this one:

```bash
git clone https://github.com/ikamensh/saga2d-framework.git saga2d
git clone https://github.com/ikamensh/sagaforge.git
git clone https://github.com/ikamensh/shardbound.git
cd shardbound
uv run shardbound
```

`uv run` creates `.venv`, fetches Python and the dependencies when they are
missing, and opens the title: choose a hero, a world and a difficulty, then
**Linked campaign** (three shards) or **Enter single shard**. The framework
and the asset library are editable path dependencies, so moving to a newer
version is a pull in the three checkouts and another start:

```bash
git -C ../saga2d pull && git -C ../sagaforge pull && git pull
uv run shardbound
```

Straight into a shard, and the other options:

```bash
uv run shardbound --seed 7                                        # skip the title: seed 7 in Frontier as the Commander
uv run shardbound --seed 7 --hero Wizard --theme elderwild --difficulty challenge
uv run shardbound --campaign --seed 7                             # the linked campaign
uv run shardbound --data-dir /tmp/shardbound-playtest             # a separate profile for saves and settings
uv run shardbound --help
```

Saves and settings live in `~/.shardbound` (Windows:
`%USERPROFILE%\.shardbound`); **About this build** (A) on the title shows
the exact directory. The [player guide](eador/README.md) has a tested opening
and the controls.

The installed app (`/Applications/Shardbound.app`, or the Windows installer
from [games.tachyon-ai.eu](https://games.tachyon-ai.eu/shardbound/)) is the
published **0.1.0-preview.1**, which is behind this checkout. Shardbound has
its own standalone recipe: build from the working tree, verify the archive,
then replace the app in Finder ([docs/packaging.md](docs/packaging.md);
Windows: [docs/windows-shardbound.md](docs/windows-shardbound.md)):

```bash
uv run --locked --isolated --python 3.13.2 --with-requirements packaging/requirements.txt python tools/build.py
uv run python tools/verify_package.py dist/shardbound
```

## Play together

**Co-op** (M) on the title shares one realm, hero and army between two
players; every route also exists as a command-line flag
(`uv run shardbound --help`). Both sides need the same Shardbound version.

- **Online**, the default: a room on the shared server at
  `wss://games.tachyon-ai.eu/play`, joined by code or invite link, with no
  port forwarding, VPN or account. Campaign rooms are kept for seven days, so
  a co-op campaign continues another day. A checkout connects there today.
  Guide: [online multiplayer](../tribes/docs/online-multiplayer.md).

  ```bash
  uv run shardbound --online-host --campaign --seed 7 --hero Commander   # prints the room code
  uv run shardbound --online-join CODE
  ```

- **Your own server**, run from this checkout (`--host 0.0.0.0` lets other
  computers in), with both clients pointed at it through `--server` or
  `SAGA2D_SERVER_URL`:

  ```bash
  uv run python -m saga2d.server --games eador.multiplayer:ONLINE      # ws://127.0.0.1:8765
  uv run shardbound --online-host --server ws://127.0.0.1:8765
  uv run shardbound --online-join CODE --server ws://127.0.0.1:8765
  ```

- **LAN or VPN**, without a server; the host's process is the authority
  ([LAN guide](../saga2d/docs/multiplayer.md)):

  ```bash
  uv run shardbound --host                               # prints the port and room code
  uv run shardbound --join 192.168.1.20 --room CODE      # two processes on one computer: --join 127.0.0.1
  ```

## Code

The Python package is `eador`, the game's codename. The
[reference research](docs/eador-research.md) records the source material and
deliberate simplifications; the [Early Access criteria](docs/early-access-criteria.md)
define the release goal and [progress](docs/early-access-progress.md) tracks
the remaining gaps.

```bash
uv run pytest -q                     # headless suite, long (well over a thousand tests)
uv run python tools/fuzz.py          # seeded checks, 25% of one core by default
uv run python tools/verify.py        # real input + PNGs in /tmp/shardbound
```

Audit, fuzz and stress CLIs in `tools/` target 25% of one CPU core by
sleeping between short work blocks; choose `--cpu-percent 100` explicitly for
an unrestricted run, and run heavy checks one at a time. [AGENTS.md](AGENTS.md)
lists the rest of the commands and the rules for changing the game.
