# Shardbound — agent notes

An Eador-inspired campaign: a province map, a stronghold, persistent armies
and separate hex battles. The Python package is `eador` (the game's codename;
the product is Shardbound). Third reference game of the Saga stack (`~/saga/`,
see `../AGENTS.md`). Saga2D is a pinned PyPI release; its source lives in
`../saga2d`. Upgrade it deliberately in `pyproject.toml` and `uv.lock`, then
run this suite. Procedural assets come from `../sagaforge` as an editable
path dependency, so run this suite after changing that library.

## Commands

```bash
uv sync --extra dev
uv run shardbound --seed 7                 # play (python -m eador works too); --hero Wizard --theme elderwild
uv run pytest -q                           # headless suite, long (well over a thousand tests)
uv run pytest tests/eador/test_model.py -q # iterate on a slice
uv run python tools/fuzz.py                # seeded model/scene fuzz, 25% of one core by default
uv run python tools/verify.py              # real input + PNGs to look at
uv run python tools/build_audio.py         # regenerate shipping WAVs and the audio manifest
uv run python tools/build_icons.py --check # (and build_art.py) verify prebuilt PNGs against their manifest
uv run python tools/restyle.py refresh DIR    # painted battle miniatures: the whole procedure; see ../sagaforge/docs/restyle.md
uv run --locked --isolated --python 3.13.2 --with-requirements packaging/requirements.txt python tools/build.py --version 0.1.0
uv run python tools/verify_package.py dist/shardbound
```

## Layout

- `eador/model.py`, `battle.py`, `economy.py`, `campaign.py`, `realm.py`,
  `rival.py`, `worldgen.py`, `encounters.py`, `adventures.py`, `content.py`,
  `difficulty.py`, `orders.py`, `persistence.py` — rules, pure Python; the
  concurrent PvP campaign is `concurrent_campaign.py`.
- `eador/scene.py`, `campaign_scene.py`, `encounter_scene.py`, `*_scene.py`,
  `ui.py`, `reading.py`, `style.py`, `app.py`, `sound.py`, `battle_audio.py`,
  `battle_effects.py` — the saga2d side. `multiplayer.py`'s `ONLINE` registers
  `shardbound-v1` (co-op) and `shardbound-pvp-v1` with `saga2d.server`.
- `eador/art.py`, `icon_art.py`, `landscape.py` compose the original art;
  `eador/assets/` holds the prebuilt PNGs and WAVs with provenance manifests
  that hash their generator sources (`tools/sources.py` finds the framework
  files). Rebuild the manifest after touching a generator.
- `tools/` — one script per verification or audit: `verify_*.py` drive the
  real UI through `tools/ui.py`'s `PlayerInput`, `audit_*.py` and
  `stress_*.py` measure the economy and tactics, `*_campaign.py` prepare
  states, `prototype_*.py` are retained proposals. `tests/tools/` pins their
  CPU budgets and inputs.
- `packaging/` — the standalone recipe (`shardbound.spec`, `entry.py`,
  `campaign_check.py`, `credits.md`, pinned build tools); the packaging tests
  are in `tests/packaging/`.
- `docs/` — the Early Access criteria (`early-access-criteria.md`, gates
  G01–G19) and progress, the research notes, and one design note per feature.

## Rules

- Game code imports from `saga2d` and `sagaforge` only, never from
  `saga2d.backends`. Framework changes belong in `../saga2d` and need a
  concrete game need (Shardbound added only `HexGrid` and
  `Scene.draw_paragraph`).
- Keep every Early Access gate incomplete until its full evidence passes;
  evidence goes under `docs/evidence/` (git-ignored; the pre-split evidence
  lives in the archived monorepo). The recorded journals, reports and audio sampler that
  replay tests read are tracked there deliberately (`git ls-files docs/evidence`);
  add a new input with `git add -f`. Verifiers write source fingerprints through
  `tools/sources.py`, which labels framework files `saga2d/...`/`sagaforge/...`.
- Visual changes must be looked at (`tools/verify.py` or
  `saga2d.testing.render_scene`, then open the PNG). The display must be awake.
- Run at most one expensive local job at a time; audit, fuzz and stress CLIs
  default to `--cpu-percent 25`; native `PlayerInput` caps at 30 FPS.
- Tests use the mock backend (`game`/`backend` fixtures from
  `saga2d.testing.fixtures`), public behaviour only; a regression test for
  every bug found.
- Clear exceptions over silent fallbacks. Delete rather than deprecate.
  Commit each working increment.
