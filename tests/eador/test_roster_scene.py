"""Control recruits disclose both currencies and execute their saved capabilities."""
from dataclasses import replace

import pytest
from saga2d import Label

from eador.app import create_game
from eador.model import State, UNITS
from eador.scene import ShardScene
from tools.ui import PlayerInput
from tools.verify_shard_reading import check_metric


@pytest.mark.parametrize('kind', ['sapper', 'adept', 'skyrider'])
def test_recruit_buttons_require_crystals_and_deduct_both_displayed_costs(tmp_path, kind):
    """Gold alone cannot activate a special recruit's button or number shortcut."""
    for crystals in (0, 8):
        # Isolate affordability with a valid funded save; paid campaign routes
        # separately exercise earning the buildings and these resources.
        state = replace(State.new(7), gold=200, crystals=crystals,
                        buildings={'market', 'mage_tower', 'temple'})
        game = create_game(backend='mock', save_dir=tmp_path / str(crystals))
        player = PlayerInput(game)
        try:
            game.push(ShardScene(state))
            player.press('r')
            while kind not in game.scene.visible_items:
                assert game.scene.page + 1 < game.scene.pages
                player.press('right')
            number = str(game.scene.visible_items.index(kind) + 1)
            before = state.to_json()
            gold_cost, crystal_cost = state.recruit_cost(kind), state.recruit_crystal_cost(kind)
            offer = game.scene.ui.find(lambda item: isinstance(item, Label) and item.text == UNITS[kind].name).parent
            check_metric(game.scene, 'gold', gold_cost, 'Gold', within=offer)
            check_metric(game.scene, 'crystals', crystal_cost, 'Crystals', within=offer)
            player.press(number)
            if crystals == 0:
                assert state.to_json() == before
            else:
                assert state.hero.army[-1].kind == kind
                assert state.gold == 200 - gold_cost
                assert state.crystals == crystals - crystal_cost
                player.press('escape')
                player.reload(state.to_json())
        finally:
            game._teardown()


@pytest.mark.parametrize('scenario', ['smoke', 'rally', 'repulse', 'watch'])
def test_paid_control_orders_have_exact_previews_and_saved_finite_effects(tmp_path, scenario):
    """The native input journey buys the army, aims/cancels the order and checks its complete saved effect."""
    from tools.verify_control import verify
    report = verify(tmp_path, backend='mock', scenario=scenario)
    assert report['exact_save_reloads'] >= 1


def test_ranged_order_guidance_matches_the_battles_saved_sight_rules(tmp_path):
    """An in-range blocked shot explains sight and leaves all campaign fields unchanged."""
    from tools.verify_control import verify
    verify(tmp_path, backend='mock', scenario='sight')
