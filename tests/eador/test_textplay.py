"""Text play drives the real rules: orders report their effects and forecasts are exact."""
import copy
import random
import re

import pytest

from eador.model import State
from eador.textplay import Session, main
from tools.linked_campaign import play_stage


def in_shrine_battle() -> Session:
    """A fresh campaign that explores Westwatch's own site: an ordinary rout battle."""
    session = Session()
    session.run('new 7 Commander; explore')
    assert session.state.battle is not None
    return session


def test_cli_keeps_the_game_and_a_transcript_between_invocations(tmp_path):
    save = tmp_path / 'game.json'
    assert main(['-g', str(save), 'new', '7']) == 0
    # An unquoted negative hex is a command argument, not an option.
    assert main(['-g', str(save), 'go', '-1,0']) == 0
    state = State.from_json(save.read_text())
    assert state.battle is not None and state.battle_province == (-1, 0)
    assert main(['-g', str(save), 'go', '5,5']) == 1
    transcript = (tmp_path / 'game.json.log').read_text()
    assert '> new 7' in transcript and '> go -1,0' in transcript and 'error:' in transcript


def test_orders_report_what_they_changed():
    session = Session()
    session.run('new 7')
    output, ok = session.run('build barracks; recruit swordsman')
    assert ok
    assert 'gold 100->55' in output and 'gold 55->10' in output
    assert '+Swordsman#4' in output
    assert output.splitlines()[-1].startswith('[turn 1 · actions 2 · gold 10')


def test_first_error_stops_the_chain_and_names_what_was_skipped():
    session = Session()
    session.run('new 7')
    output, ok = session.run('build barracks; build barracks; recruit swordsman')
    assert not ok
    assert 'error: That building is already built.' in output
    assert 'skipped: recruit swordsman' in output
    assert len(session.state.hero.army) == 3


def test_every_listed_attack_forecast_is_what_the_attack_does():
    """Deal/take from each listed hex equal the real attack, for each of your units."""
    session = in_shrine_battle()
    checked = 0
    for unit in [u for u in session.state.battle.units if u.team == 'player']:
        view, _ = session.run(f'unit {unit.id}')
        for target, options in re.findall(r'attack after moving: \S+#(\d+) (.*)', view):
            for deal, take, cells in re.findall(r'(\d+)/(\d+)(?: KILL| DIES)* from ([^;]+)', options):
                for cell in cells.split():
                    trial = copy.deepcopy(session)
                    battle = trial.state.battle
                    before = battle.unit(int(target)).hp, battle.unit(unit.id).hp
                    output, ok = trial.run(f'attack {unit.id} {target} from {cell.rstrip("fhmSX~")}')
                    assert ok, output
                    after = battle.unit(int(target)).hp, battle.unit(unit.id).hp
                    assert (before[0] - max(0, after[0]), before[1] - after[1]) == (int(deal), int(take)), (view, output)
                    checked += 1
    assert checked > 10


def test_a_refused_attack_from_a_hex_does_not_move_the_unit():
    session = in_shrine_battle()
    battle = session.state.battle
    militia = battle.unit(1)
    output, ok = session.run('attack 1 1005 from -3,0; end')
    assert not ok and 'error:' in output and 'skipped: end' in output
    assert militia.pos == (-2, 0) and not militia.moved and battle.round == 1


def test_a_won_battle_settles_into_the_campaign():
    session = in_shrine_battle()
    output, ok = session.run('auto all')
    assert ok
    assert session.state.battle is None
    assert 'BATTLE OVER: victory' in output and 'Explored Buried Shrine' in output
    assert 'CHOICE PENDING - Discovered Moonstone' in output


def test_departure_offers_the_next_shards_and_carries_the_chosen_retinue():
    state = play_stage(State.new_campaign(7, 'Commander'))
    assert state.campaign.phase == 'departure'
    session = Session(state)
    view, _ = session.run('look')
    assert 'rootward:' in view and 'foundries:' in view
    veterans = [troop.id for troop in state.hero.army][:2]
    relics = state.inventory[:1]
    output, ok = session.run(f'depart rootward troops {",".join(map(str, veterans))}'
                             + (f' relics {relics[0]}' if relics else ''))
    assert ok, output
    assert session.state.campaign.stage == 2 and 'Stage 2/3 Rootward' in output
    assert [troop.id for troop in session.state.hero.army][:2] == veterans
    assert session.state.inventory == relics


def candidate_commands(state: State, rng: random.Random) -> list[str]:
    """Plausible commands a player might type now, legal or not."""
    if state.battle is not None:
        battle = state.battle
        commands = ['look', 'board', 'end', 'auto', 'auto all'] * 2
        for unit in battle.units:
            if not unit.alive:
                continue
            commands.append(f'unit {unit.id}')
            if unit.team != 'player':
                continue
            enemies = [u for u in battle.units if u.alive and u.team == 'enemy']
            reach = sorted(battle.reachable(unit.id))
            if reach:
                commands.append(f'move {unit.id} {",".join(map(str, rng.choice(reach)))}')
            for enemy in enemies:
                commands.append(f'attack {unit.id} {enemy.id}')
                commands.append(f'pin {unit.id} {enemy.id}')
                if reach:
                    commands.append(f'attack {unit.id} {enemy.id} from {",".join(map(str, rng.choice(reach)))}')
                commands.append(f'cast bolt {enemy.id}')
            commands += [f'guard {unit.id}', f'cast heal {unit.id}', f'smoke {unit.id} 0,0']
        return commands
    campaign = state.campaign
    if campaign.phase == 'departure':
        return [f'depart {campaign.offers[0].id} troops {state.hero.army[0].id}', 'look']
    if campaign.phase == 'recovery':
        return ['recover', 'look']
    if state.choice is not None:
        return [f'choose {option.id}' for option in state.choice.options]
    commands = ['look', 'map', 'camp', 'rival', 'codex troops', 'codex pin', 'infuse', 'end', 'end',
                'explore', 'explore direct', 'build barracks', 'build archery', 'build market',
                'recruit militia', 'recruit swordsman', 'recruit archer', 'equip none']
    commands += [f'equip {relic}' for relic in state.inventory]
    commands += [f'replace {troop.id} pikeman' for troop in state.hero.army[:1]]
    for pos in state.grid.neighbors(state.hero.pos):
        commands += [f'go {pos[0]},{pos[1]}'] * 3 + [f'inspect {pos[0]},{pos[1]}']
    return commands


@pytest.mark.parametrize('seed,hero', [(3, 'Commander'), (11, 'Wizard'), (5, 'Scout')])
def test_random_play_through_text_never_breaks_the_game(seed, hero):
    """Any typed command either works or answers with an error; the save always reloads."""
    rng = random.Random(seed)
    session = Session()
    session.run(f'new {seed} {hero}')
    kinds = set()
    for _ in range(400):
        state = session.state
        if state.campaign.phase in ('completed', 'lost'):
            break
        command = rng.choice(candidate_commands(state, rng))
        output, ok = session.run(command)
        assert output and (ok or 'error: ' in output), (command, output)
        kinds.add(('battle' if session.state.battle else session.state.campaign.phase, ok))
        session.state = State.from_json(session.state.to_json())
    assert ('battle', True) in kinds and ('playing', True) in kinds
