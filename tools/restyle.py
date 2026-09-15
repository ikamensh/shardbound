"""Re-render Shardbound's battle miniatures with an image model (see ``sagaforge.restyle``).

    uv run python tools/restyle.py dump DIR         # every unit kind and hero class on one sheet, plus the prompt
    uv run python tools/restyle.py render DIR       # repaint it (Codex by default; --provider openrouter --model ...)
    uv run python tools/restyle.py cut DIR          # key, register, check; install into eador/assets/images/pieces
    uv run python tools/restyle.py refresh DIR OUT.png  # dump, render, cut and preview in one go
    uv run python tools/restyle.py preview DIR OUT.png   # both teams, original row above restyled row

The sheet shows the player's team (teal); the enemy's pieces are the same frames recoloured red.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["SHARDBOUND_ART"] = "procedural"  # the sheets are always built from the drawn figures

from PIL import Image, ImageDraw  # noqa: E402

from eador import art  # noqa: E402
from eador.entities import HERO_CLASSES, UNITS  # noqa: E402
from eador.style import RED, TEAL  # noqa: E402
from sagaforge import restyle  # noqa: E402

CELL = (256, 256)
PIECE_SCALE = 2.4  # art.piece scale that fills the cell
ORIGIN = (CELL[0] / 2, CELL[1] * 0.72)  # where piece()'s (x, y) lands in the cell
SUPERSAMPLE = 4
DESCRIPTIONS = {"militia": "militia (spear)", "swordsman": "swordsman", "archer": "archer", "healer": "acolyte (healer)",
                "brigand": "brigand", "goblin": "goblin", "wolf": "wolf", "guard": "dread guard (heavy dark armour)",
                "warden": "warden (tower shield)", "ranger": "ranger (hood, bow)", "pikeman": "pikeman", "sapper": "sapper",
                "adept": "rune adept (mage)", "skyrider": "skyrider (winged mount)", "commander": "the commander hero (ochre cloak)",
                "warrior": "the warrior hero", "scout": "the scout hero", "wizard": "the wizard hero"}


class Recorder:
    """The part of the saga2d Scene draw API that ``art.piece`` uses, painted with Pillow."""

    def __init__(self, size: tuple[int, int]) -> None:
        self.image = Image.new("RGBA", (size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE), (0, 0, 0, 0))

    def _paint(self, painter) -> None:
        layer = Image.new("RGBA", self.image.size, (0, 0, 0, 0))
        painter(ImageDraw.Draw(layer))
        self.image.alpha_composite(layer)

    @staticmethod
    def _color(color) -> tuple[int, ...]:
        c = tuple(int(v) for v in color)
        return c if len(c) == 4 else c + (255,)

    def draw_polygon(self, points, color, **_):
        self._paint(lambda d: d.polygon([(x * SUPERSAMPLE, y * SUPERSAMPLE) for x, y in points], fill=self._color(color)))

    def draw_line(self, x1, y1, x2, y2, color, width=1.0, **_):
        self._paint(lambda d: d.line([(x1 * SUPERSAMPLE, y1 * SUPERSAMPLE), (x2 * SUPERSAMPLE, y2 * SUPERSAMPLE)],
                                     fill=self._color(color), width=max(1, round(width * SUPERSAMPLE))))

    def draw_circle(self, x, y, radius, color, **_):
        s = SUPERSAMPLE
        self._paint(lambda d: d.ellipse(((x - radius) * s, (y - radius) * s, (x + radius) * s, (y + radius) * s), fill=self._color(color)))

    def draw_rect(self, x, y, w, h, color, **_):
        s = SUPERSAMPLE
        self._paint(lambda d: d.rectangle((x * s, y * s, (x + w) * s, (y + h) * s), fill=self._color(color)))

    def result(self, size: tuple[int, int]) -> Image.Image:
        return self.image.resize(size, Image.LANCZOS)


def kinds() -> list[str]:
    return list(UNITS) + [hero.lower() for hero in HERO_CLASSES]


def build_sheet() -> tuple[restyle.Sheet, dict[str, Image.Image]]:
    keys = [(f"piece.{kind}", {"kind": kind}) for kind in kinds()]
    sheet = restyle.Sheet.layout(keys, cols=6, cell=CELL, origin=ORIGIN, scale=PIECE_SCALE)
    images = {}
    for key, tags in keys:
        recorder = Recorder(CELL)
        art.piece(recorder, ORIGIN[0], ORIGIN[1], tags["kind"], "player", scale=PIECE_SCALE)
        images[key] = recorder.result(CELL)
    return sheet, images


def prompt(sheet: restyle.Sheet) -> str:
    w, h = sheet.size
    names = [DESCRIPTIONS[k] for k in kinds()]
    rows = "; ".join(f"row {r + 1}: " + ", ".join(names[r * sheet.cols:(r + 1) * sheet.cols]) for r in range(sheet.rows))
    return (f"Edit target: the attached sprite sheet of battle miniatures from a dark-fantasy turn-based strategy game inspired by "
            f"Eador (hex battles, painted tabletop feel). It is {w}x{h} px: {sheet.rows} rows x {sheet.cols} columns of "
            f"{sheet.cell[0]}x{sheet.cell[1]} px cells surrounded by an empty margin, on a flat magenta #FF00FF background; thin dark "
            f"grey lines mark the cell borders, keep the lines and the margin exactly where they are and keep each figure centred in "
            f"its own cell. Left to right, {rows}.\n\n"
            f"Each figure stands on a dark oval base with a teal rim (teal is the player's team colour; keep the rim and cloth accents "
            f"this teal). Re-render every cell as a polished, appealing painted miniature: hand-painted gouache and oil-glaze look, "
            f"restrained ink-navy, deep teal, muted moss, cold slate and old-gold palette, tangible worn materials, believable anatomy, "
            f"confident brushwork, light from the upper left, not cartoon and not photo. Sprites will be shown at about a quarter of "
            f"this size, so keep silhouettes bold and edges crisp.\n\n"
            f"Keep exactly: each figure's position, scale, pose, facing and equipment, and the base's size and position. Every cell "
            f"keeps the flat #FF00FF background with nothing else on it: no gradients, glows, text, borders or extra objects. Output "
            f"the same {w}x{h} layout.")


def cmd_dump(args: argparse.Namespace) -> None:
    args.dir.mkdir(parents=True, exist_ok=True)
    sheet, images = build_sheet()
    sheet.save(args.dir / "pieces", images)
    (args.dir / "pieces.prompt.txt").write_text(prompt(sheet))
    print(f"pieces: {sheet.size[0]}x{sheet.size[1]}, {len(sheet.cells)} cells")


def cmd_render(args: argparse.Namespace) -> None:
    out = args.dir / "pieces" / f"{args.provider}.png"
    text = (args.dir / "pieces.prompt.txt").read_text()
    if args.provider == "codex":
        restyle.render_with_codex(args.dir / "pieces.png", text, out)
    else:
        usage = restyle.render_with_openrouter(args.dir / "pieces.png", text, out, model=args.model, api_key=restyle.openrouter_api_key(), aspect_ratio="16:9")
        (args.dir / "pieces" / "usage.json").write_text(json.dumps(usage, indent=1))
    print(f"wrote {out}")


def cmd_cut(args: argparse.Namespace) -> None:
    sheet = restyle.Sheet.load(args.dir / "pieces")
    result = restyle.cut(sheet, Image.open(args.dir / "pieces" / f"{args.provider}.png"), Image.open(args.dir / "pieces.png"))
    print(f"scale {result.registration.scale:.2f} shift ({result.registration.dx:.0f}, {result.registration.dy:.0f}), "
          f"{len(result.flagged)} of {len(result.report)} cells flagged")
    for r in result.flagged:
        print(f"   {r.key}: coverage {r.coverage:.3f} vs {r.original_coverage:.3f}, drift {r.drift:.0f}px, edge {r.touches_edge}")
    if result.flagged:
        print("   rejected; re-render")
        return
    art.PIECES.mkdir(parents=True, exist_ok=True)
    for cell in sheet.cells:
        kind = cell.tags["kind"]
        frame = result.frames[cell.key]
        frame.save(art.PIECES / f"player.{kind}.png")
        restyle.recolor(frame, TEAL[:3], RED[:3]).save(art.PIECES / f"enemy.{kind}.png")
    (art.PIECES / "layout.json").write_text(json.dumps({"size": list(sheet.logical_size), "origin": [ORIGIN[0] / PIECE_SCALE, ORIGIN[1] / PIECE_SCALE]}, indent=1))
    print(f"   installed {len(sheet.cells)} kinds x 2 teams into {art.PIECES}")


def cmd_preview(args: argparse.Namespace) -> None:
    sheet, original = build_sheet()
    keys = [c.key for c in sheet.cells]
    rows = []
    for team in ("player", "enemy"):
        if team == "enemy":
            original = {k: restyle.recolor(v, TEAL[:3], RED[:3]) for k, v in original.items()}
        restyled = {c.key: Image.open(art.PIECES / f"{team}.{c.tags['kind']}.png").convert("RGBA") for c in sheet.cells}
        for frames in (original, restyled):
            rows.append(restyle.strip(frames, keys[:9], scale=0.5, background=(28, 36, 44)))
            rows.append(restyle.strip(frames, keys[9:], scale=0.5, background=(28, 36, 44)))
    out = Image.new("RGBA", (rows[0].size[0], sum(r.size[1] for r in rows)))
    y = 0
    for row in rows:
        out.paste(row, (0, y))
        y += row.size[1]
    out.convert("RGB").save(args.out)
    print(f"wrote {args.out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("dump"); p.add_argument("dir", type=Path); p.set_defaults(run=cmd_dump)
    p = sub.add_parser("render"); p.add_argument("dir", type=Path); p.add_argument("--provider", default="codex", choices=["codex", "openrouter"])
    p.add_argument("--model", default="google/gemini-3.1-flash-image"); p.set_defaults(run=cmd_render)
    p = sub.add_parser("cut"); p.add_argument("dir", type=Path); p.add_argument("--provider", default="codex"); p.set_defaults(run=cmd_cut)
    p = sub.add_parser("preview"); p.add_argument("dir", type=Path); p.add_argument("out", type=Path); p.set_defaults(run=cmd_preview)
    p = sub.add_parser("refresh"); p.add_argument("dir", type=Path); p.add_argument("out", type=Path)
    p.add_argument("--provider", default="codex", choices=["codex", "openrouter"]); p.add_argument("--model", default="google/gemini-3.1-flash-image"); p.set_defaults(run=cmd_refresh)
    p = sub.add_parser("showcase"); p.add_argument("out", type=Path); p.add_argument("--seed", type=int, default=7); p.set_defaults(run=cmd_showcase)
    args = parser.parse_args()
    args.run(args)



def cmd_refresh(args: argparse.Namespace) -> None:
    """Dump, render, cut and preview in one go: the whole procedure."""
    cmd_dump(args)
    cmd_render(args)
    cmd_cut(args)
    cmd_preview(args)


def cmd_showcase(args: argparse.Namespace) -> None:
    """The first site battle through the real renderer, saved as a GIF: the player's
    troops close in and attack, with the painted miniatures.  The display must be awake."""
    import tempfile

    from eador.app import create_game
    from eador.model import State
    from eador.scene import BattleScene, ShardScene

    os.environ.pop("SHARDBOUND_ART")  # the showcase shows what the game shows
    with tempfile.TemporaryDirectory() as temporary:
        game = create_game(backend="pyglet", visible=False, save_dir=Path(temporary) / "saves", resolution=(1280, 800))
        try:
            state = State.new(seed=args.seed, hero_class="Warrior")
            shard = ShardScene(state)
            game.push(shard)
            for _ in range(10):
                game.tick(1 / 30)
            shard.act(lambda: shard.order("explore"))
            for _ in range(10):
                game.tick(1 / 30)
            if not isinstance(game.scene, BattleScene):
                raise RuntimeError(f"expected a battle, the game shows {type(game.scene).__name__}: {shard.message!r}")
            battle_scene = game.scene
            battle = state.battle
            frames = []

            def record(seconds: float) -> None:
                for tick in range(int(seconds * 30)):
                    game.tick(1 / 30)
                    if tick % 2 == 0:
                        frame = game.backend.capture_frame().convert("RGB")
                        frames.append(frame.resize((frame.size[0] // 2, frame.size[1] // 2), Image.LANCZOS) if frame.size[0] > 1400 else frame)

            record(0.6)
            for _round in range(3):
                for unit in [u for u in battle.units if u.team == "player" and u.alive]:
                    if battle.outcome:
                        break
                    targets = battle.targets(unit.id)
                    if targets:
                        target = targets[0].id
                        battle_scene.act(lambda unit=unit, target=target: battle_scene.root.order("attack", unit.id, target, target="battle"))
                        record(1.4)
                        continue
                    enemies = [e for e in battle.units if e.team != "player" and e.alive]
                    reachable = battle.reachable(unit.id)
                    if enemies and reachable:
                        nearest = min(reachable, key=lambda p: min(abs(p[0] - e.pos[0]) + abs(p[1] - e.pos[1]) for e in enemies))
                        battle_scene.act(lambda unit=unit, nearest=nearest: battle_scene.root.order("move", unit.id, nearest, target="battle"), cue="move")
                        record(0.5)
                        if battle.targets(unit.id):
                            target = battle.targets(unit.id)[0].id
                            battle_scene.act(lambda unit=unit, target=target: battle_scene.root.order("attack", unit.id, target, target="battle"))
                            record(1.4)
                if battle.outcome:
                    break
                battle_scene.act(lambda: battle_scene.root.order("end_turn", target="battle"), cue=None)
                while type(game.scene) is not BattleScene:  # the enemy's playback
                    game.tick(1 / 30)
                    if len(frames) < 400:
                        frames.append(game.backend.capture_frame().convert("RGB"))
                record(0.4)
            frames = [f.resize((f.size[0] // 2, f.size[1] // 2), Image.LANCZOS) if f.size[0] > 1400 else f for f in frames]
            frames[0].save(args.out, save_all=True, append_images=frames[1:], duration=66, loop=0)
            print(f"wrote {args.out}: {len(frames)} frames of {frames[0].size[0]}x{frames[0].size[1]}")
        finally:
            game.close()

if __name__ == "__main__":
    main()
