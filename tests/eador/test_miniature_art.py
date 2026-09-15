"""Every miniature, drawn or painted, fits the existing battle/retinue geometry through Scene drawing."""

import numpy as np
import pytest
from PIL import Image

from eador import art
from eador.model import UNITS
from saga2d import Game, Scene

KINDS = ('archer', *UNITS, 'Warrior', 'Wizard', 'Scout', 'Commander')


def test_all_miniatures_scale_uniformly_inside_the_existing_cell_footprint(monkeypatch):
    """Retinue scaling must shrink equipment and contour strokes along with the body, without clipping."""
    monkeypatch.setenv('SHARDBOUND_ART', 'procedural')  # the authored strokes, whether or not painted pieces are installed
    game = Game('Miniature geometry', backend='mock', resolution=(240, 240))

    class Piece(Scene):
        kind = 'archer'
        scale = 1

        def draw(self):
            art.piece(self, 120, 120, self.kind, 'player', scale=self.scale)

    def geometry(scale):
        scene.scale = scale
        game.tick(0)
        backend = game.backend
        result = []
        bounds = []
        for shape in backend.polygons:
            for x, y in shape['points']:
                result.extend(((x - 120) / scale, (y - 120) / scale))
                bounds.append(((x - 120) / scale, (y - 120) / scale))
        for shape in backend.lines:
            result.extend(((shape['x1'] - 120) / scale, (shape['y1'] - 120) / scale,
                           (shape['x2'] - 120) / scale, (shape['y2'] - 120) / scale, shape['width'] / scale))
            for end in (1, 2):
                radius = shape['width'] / scale / 2
                px, py = (shape[f'x{end}'] - 120) / scale, (shape[f'y{end}'] - 120) / scale
                bounds.extend(((px - radius, py - radius), (px + radius, py + radius)))
        for shape in backend.circles:
            cx, cy, radius = (shape['x'] - 120) / scale, (shape['y'] - 120) / scale, shape['radius'] / scale
            result.extend((cx, cy, radius))
            bounds.extend(((cx - radius, cy - radius), (cx + radius, cy + radius)))
        for shape in backend.rects:
            x, y = (shape['x'] - 120) / scale, (shape['y'] - 120) / scale
            w, h = shape['width'] / scale, shape['height'] / scale
            result.extend((x, y, w, h))
            bounds.extend(((x, y), (x + w, y + h)))
        assert result and not backend.texts and not backend.images
        assert all(-40 <= x <= 40 and -64 <= y <= 28 for x, y in bounds), scene.kind
        return result

    try:
        scene = Piece()
        game.push(scene)
        for kind in KINDS:
            scene.kind = kind
            full = geometry(1)
            assert geometry(.53) == pytest.approx(full), kind
    finally:
        game.close()


def test_painted_miniatures_draw_one_image_inside_the_same_footprint(monkeypatch):
    """A painted piece is one image whose opaque pixels stay inside the footprint the strokes used,
    at retinue scale as at full scale; nothing is drawn around it."""
    monkeypatch.delenv('SHARDBOUND_ART', raising=False)
    if art.restyled_piece('archer', 'player') is None:
        pytest.skip('no painted pieces installed')
    game = Game('Painted miniature geometry', backend='mock', resolution=(240, 240))

    class Piece(Scene):
        kind = 'archer'
        scale = 1

        def draw(self):
            art.piece(self, 120, 120, self.kind, 'player', scale=self.scale)

    def geometry(scale):
        scene.scale = scale
        game.tick(0)
        backend = game.backend
        assert len(backend.images) == 1 and not backend.polygons and not backend.lines and not backend.circles and not backend.rects, scene.kind
        image = backend.images[0]
        path, _, _ = art.restyled_piece(art.piece_kind(scene.kind), 'player')
        alpha = np.asarray(Image.open(path).convert('RGBA'))[..., 3] > 32
        ys, xs = np.nonzero(alpha)
        sx, sy = image['width'] / alpha.shape[1] / scale, image['height'] / alpha.shape[0] / scale
        left, top = (image['x'] - 120) / scale, (image['y'] - 120) / scale
        bounds = (left + xs.min() * sx, top + ys.min() * sy, left + (xs.max() + 1) * sx, top + (ys.max() + 1) * sy)
        assert -40 <= bounds[0] and bounds[2] <= 40 and -64 <= bounds[1] and bounds[3] <= 28, (scene.kind, bounds)
        return (left, top, image['width'] / scale, image['height'] / scale)

    try:
        scene = Piece()
        game.push(scene)
        for kind in KINDS:
            scene.kind = kind
            assert geometry(.53) == pytest.approx(geometry(1)), kind
    finally:
        game.close()
