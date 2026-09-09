# Shardbound

An Eador-inspired strategy game on [Saga2D](../saga2d). Choose one of four
heroes, develop a stronghold, explore guarded ruins, recruit an army, and take
Duskspire before the rival reaches Westwatch. The 19-province campaign carries
wounds, casualties and experience between hex battles; a three-shard linked
campaign adds challenge choices, a travelling retinue and a recovery
expedition. Original content, painted artwork, procedural miniatures and
original music and sound.

```bash
uv sync --extra dev
uv run shardbound                    # title and hero selection; --seed 7 --hero Wizard skips the title
uv run pytest -q
uv run python tools/fuzz.py          # seeded checks, 25% of one core by default
uv run python tools/verify.py        # real input + PNGs in /tmp/shardbound
```

The Python package is `eador`, the game's codename. The
[player guide](eador/README.md) includes a tested opening and controls; the
[reference research](docs/eador-research.md) records the source material and
deliberate simplifications; the [Early Access criteria](docs/early-access-criteria.md)
define the release goal and [progress](docs/early-access-progress.md) tracks
the remaining gaps. Co-op and PvP rooms run on the shared server (**Co-op** on
the title). Standalone builds: [docs/packaging.md](docs/packaging.md) and
[Windows](docs/windows-shardbound.md).

Audit, fuzz and stress CLIs in `tools/` target 25% of one CPU core by
sleeping between short work blocks; choose `--cpu-percent 100` explicitly for
an unrestricted run, and run heavy checks one at a time.
