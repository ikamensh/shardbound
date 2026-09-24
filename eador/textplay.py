"""Shardbound as text: observe and command the real rules from a terminal or an agent.

``shardbound-text [-g SAVE] 'cmd; cmd; ...'`` loads the save, runs the commands in
order, prints what each one changed and saves. Orders call the same model methods
as the scenes; observations show what the GUI shows, in compact lines. The first
failing command stops the rest. Every command and its output is appended to
``SAVE.log``; ``note`` adds the player's own remarks to that transcript.
"""
from __future__ import annotations

import copy
import os
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from saga2d import HexGrid

from eador.battle import SPELLS, Battle, BattleUnit
from eador.campaign import campaign_targets
from eador.content import RELICS, SITES, SKILLS
from eador.difficulty import DIFFICULTIES
from eador.encounters import ENCOUNTERS
from eador.entities import BUILDINGS, HERO_CLASSES, RECRUITABLE, UNITS, RuleError
from eador.model import State
from eador.reference import CATEGORIES, codex_entries
from eador.rival import RECRUIT_COSTS, rival_order
from eador.worldgen import THEMES


class UsageError(ValueError):
    """A command the text interface cannot parse or run in this situation."""


TERRAIN_MARK = {'plains': '', 'forest': 'f', 'hills': 'h', 'marsh': 'm'}
OWNERS = {'player': 'yours', 'rival': 'rival', 'neutral': 'neutral'}

RULES = """\
Goal: win three linked shards. On each, capture Duskspire (2,0) and keep your capital
Westwatch (-2,0). The first lost capital offers one recovery; a second ends the campaign.
Campaign turn: travelling and exploring spend an action (Scout 3 per turn, others 2).
Building and recruiting spend none; recruit where your hero stands, in your territory.
End turn: income, upkeep (unpaid troops desert), the army rests, then the rival acts.
Encirclement: while every neighbour of Westwatch is held by the rival, the capital's income,
the Marketplace, rest and infusion there stop; retake any neighbour to reopen supply.
The rival expedition is finite; its next operation and timing are public (rival).
Hexes are q,r. Neighbours of q,r: q+1,r q-1,r q,r+1 q,r-1 q+1,r-1 q-1,r+1.
Distance: max(|dq|, |dr|, |dq+dr|).
Battle round: each unit may move, then act once (attack, ability or spell); acting
usually ends its move. Units cannot move through other units (flyers can).
A surviving adjacent defender retaliates once per round.
Forest and marsh cost 2 movement. Forest and hills give cover. Intervening forest
blocks ranged sight. Forecasts are exact: 'deal/take' is damage dealt/taken.
Your hero falling loses the battle. Wounds carry over between battles.
Hex marks: f forest, h hills, m marsh (no mark: plains), S seal, X exit, ~ smoke."""


def at(pos) -> str:
    return f'{pos[0]},{pos[1]}'


def parse_pos(text: str) -> tuple[int, int]:
    try:
        q, r = text.strip('()').split(',')
        return int(q), int(r)
    except ValueError:
        raise UsageError(f'expected a hex like 1,-2, got {text!r}') from None


def parse_int(text: str, what: str) -> int:
    try:
        return int(text.lstrip('#'))
    except ValueError:
        raise UsageError(f'expected {what} (a number), got {text!r}') from None


def resolve(words: list[str], table: dict, what: str) -> str:
    """An id from its id or its display name in any case: 'Moonstone', 'merchant seal', 'Acolyte'."""
    def key(text):
        return text.lower().replace(' ', '_').replace('-', '_').replace("'", '').replace('\u2019', '')
    wanted = key('_'.join(words))
    for ident, spec in table.items():
        if wanted in (key(ident), key(spec.name)):
            return ident
    raise UsageError(f'unknown {what} {" ".join(words)!r}; one of: {" ".join(table)}')


def troop_name(troop) -> str:
    return f'{UNITS[troop.kind].name}#{troop.id}'


def unit_name(unit: BattleUnit) -> str:
    return f'{unit.name}#{unit.id}'


def stats(spec_or_unit) -> str:
    unit = spec_or_unit
    return f'atk{unit.attack} def{unit.defense} mv{unit.move_range} rng{unit.attack_range}'


# ---------------------------------------------------------------- campaign views

def province_label(state: State, pos) -> str:
    return f'{state.provinces[pos].name} {at(pos)}'


def defenders(province) -> str:
    counts = Counter(UNITS[kind].name for kind in province.guards)
    return ', '.join(f'{name}' + (f' x{n}' if n > 1 else '') for name, n in counts.items())


def travel_outcome(state: State, pos) -> str:
    """What entering a province does, as the travel button and briefing describe it."""
    province = state.provinces[pos]
    if pos == (2, 0) and state.assault_blocked_reason:
        return f'blocked: {state.assault_blocked_reason}'
    if state.rival.army and state.rival.pos == pos:
        return f'intercept the rival expedition ({len(state.rival.army)} troops): battle'
    if province.owner == 'player':
        return 'travel (your province)'
    if province.guards:
        return f'invade: battle vs {defenders(province)}'
    return 'claim (undefended)'


def choice_text(state: State) -> str | None:
    choice = state.choice
    if choice is None:
        return None
    options = '; '.join(f'{option.id} = {option.name}: {option.description}' for option in choice.options)
    after = f' A kept relic works once equipped: equip {choice.context}.' if choice.kind == 'relic' else ''
    return f'CHOICE PENDING - {choice.title}: {choice.description} Options: {options} (choose ID).{after}'


def hero_lines(state: State) -> list[str]:
    hero = state.hero
    lines = [f'Hero {hero.name} the {hero.hero_class} L{hero.level} xp {hero.xp}/{hero.level * 12}'
             f'{" (max rank here)" if state.hero_level_cap and hero.level >= state.hero_level_cap else ""}'
             f' · hp {hero.hp}/{hero.max_hp} · mana {hero.mana}/{hero.max_mana}'
             f' · at {province_label(state, hero.pos)}']
    skills = ', '.join(f'{SKILLS[k].name} {n}' for k, n in hero.skill_ranks.items()) or 'none'
    relic = RELICS[hero.relic].name if hero.relic else 'none'
    owned = ', '.join(state.inventory) or 'none'
    lines.append(f'  skills: {skills} · relic: {relic} (owned: {owned}) · spells: {", ".join(sorted(state.spells)) or "none"}')
    army = ', '.join(f'{troop_name(t)} L{t.level} {t.hp}/{t.max_hp}' for t in hero.army) or 'none'
    lines.append(f'Army {len(hero.army)}/{hero.max_army}: {army}')
    return lines


def carry_line(state: State) -> str:
    if state.campaign.stage == 3:
        return 'Final shard: its victory completes the campaign.'
    gold, crystals = state.expedition_funding()
    return ('Next shard: your skills, up to two veterans and two relics travel (Militia refill the levy to three); '
            f'buildings and provinces stay behind; you would arrive with {gold} gold and {crystals} crystals '
            f'(base {state.rules.starting_gold} and {state.rules.starting_crystals}, plus up to 40 gold and 2 crystals you carry).')


def plan_view(state: State) -> str:
    campaign = state.campaign
    if campaign is None:
        return 'A single shard: capture Duskspire (2,0) and protect Westwatch (-2,0).'
    lines = [f'Stage {campaign.stage}/3 {campaign.title}: {campaign.objective}']
    lines += [f'  {"done" if complete else "todo"}: {name} {at(pos)}' for pos, name, complete in campaign_targets(state)]
    lines.append(state.assault_blocked_reason or 'Duskspire is open to assault.')
    lines.append(carry_line(state))
    lines.append(f'Rank limits this stage: hero {state.hero_level_cap}, troops {state.troop_level_cap}; '
                 'experience pauses at the limit.')
    if campaign.recovery_used:
        lines.append('Recovery spent: another lost capital ends the campaign.')
    else:
        gold, crystals = state.expedition_funding(recovery=True)
        lines.append(f'One recovery if Westwatch falls: restart this shard with {gold} gold and {crystals} crystals, '
                     'your skills and a chosen retinue.')
    return '\n'.join(lines)


def campaign_view(state: State) -> str:
    campaign = state.campaign
    if campaign and campaign.phase != 'playing':
        return transition_view(state)
    lines = []
    if campaign:
        lines.append(f'Stage {campaign.stage}/3 {campaign.title}: {campaign.objective}')
    else:
        lines.append('Capture Duskspire (2,0); protect Westwatch (-2,0).')
    lines.append(f'{THEMES[state.theme].name} shard {state.seed} · {state.rules.title} · turn {state.turn}'
                 + (f' · status {state.status.upper()}' if state.status != 'playing' else ''))
    lines.append(f'Gold {state.gold} (income +{state.income}, upkeep -{state.upkeep}) · crystals {state.crystals}'
                 f' (+{state.crystal_income}) · actions {state.actions_left}')
    if state.upkeep_shortfall:
        lines.append(f'WARNING: {state.upkeep_shortfall} gold short of upkeep; unpaid troops desert at end of turn.')
    if state.encircled:
        lines.append('WARNING: Westwatch is encircled: capital income, Marketplace and recovery are blocked.')
    lines += hero_lines(state)
    lines.append('Stronghold: ' + (', '.join(sorted(state.buildings)) or 'nothing built'))
    if campaign:
        lines.append(carry_line(state) + ' (plan)')
    rival = state.rival
    lines.append(f'Rival: {rival_order(state)} · {len(rival.army)} troops at {province_label(state, rival.pos)} (rival for details)')
    here = state.provinces[state.hero.pos]
    if here.site and not here.explored and here.owner == 'player':
        lines.append(f'Here: {here.site} is unexplored (inspect {at(here.pos)}, explore)')
    lines.append('Adjacent (go Q,R):')
    for pos in state.grid.neighbors(state.hero.pos):
        province = state.provinces[pos]
        lines.append(f'  {at(pos)} {province.name} {province.terrain} {OWNERS[province.owner]}: {travel_outcome(state, pos)}')
    if choice := choice_text(state):
        lines.append(choice)
    lines.append('Recent: ' + ' | '.join(state.log[-3:]))
    return '\n'.join(lines)


def transition_view(state: State) -> str:
    campaign = state.campaign
    records = '; '.join(f'stage {r.stage} {r.contract} in {r.turns} turns, hero L{r.hero_level}, '
                        f'{r.casualties} fallen' for r in campaign.completed)
    lines = [f'Completed shards: {records or "none"}']
    carry = ('Up to two troops and two relics travel (the levy refills to three with Militia; '
             'travellers heal). Troops: ' + (', '.join(f'{troop_name(t)} L{t.level}' for t in state.hero.army) or 'none')
             + ' · relics: ' + (', '.join(state.inventory) or 'none'))
    if campaign.phase == 'departure':
        gold, crystals = state.expedition_funding()
        lines.append(f'SHARD WON. Choose the next challenge; you arrive with {gold} gold and {crystals} crystals.')
        for offer in campaign.offers:
            lines.append(f'  {offer.id}: {offer.title} ({THEMES[offer.theme].name}) - {offer.description}')
        lines.append(carry)
        lines.append('Order: depart OFFER [troops ID,ID] [relics NAME,NAME]')
    elif campaign.phase == 'recovery':
        gold, crystals = state.expedition_funding(recovery=True)
        lines.append(f'WESTWATCH FELL. One recovery restarts this shard with {gold} gold and {crystals} crystals; '
                     'another lost capital ends the campaign.')
        lines.append(carry)
        lines.append('Order: recover [troops ID,ID] [relics NAME,NAME], or abandon')
    elif campaign.phase == 'completed':
        lines.append('CAMPAIGN COMPLETE: all three shards are won.')
    else:
        lines.append('CAMPAIGN LOST.')
    return '\n'.join(lines)


def map_view(state: State) -> str:
    lines = ['Provinces: Q,R name terrain owner income(+crystals) | defenders | site | neighbours']
    for pos, province in sorted(state.provinces.items(), key=lambda item: (item[0][1], item[0][0])):
        marks = []
        if pos == state.hero.pos:
            marks.append('HERO')
        if state.rival.army and pos == state.rival.pos:
            marks.append(f'RIVAL EXPEDITION ({len(state.rival.army)})')
        if pos == state.rival.target and state.rival.intent in ('march', 'attack', 'return'):
            marks.append('rival target')
        crystals = f'+{province.crystals}c' if province.crystals else ''
        site = (f'{province.site}{" (cleared)" if province.explored else ""}') if province.site else '-'
        neighbours = ' '.join(at(n) for n in state.grid.neighbors(pos))
        lines.append(f'{at(pos)} {province.name}{" (capital)" if province.capital else ""} {province.terrain} '
                     f'{OWNERS[province.owner]} {province.income}{crystals} | {defenders(province) or "-"} | {site}'
                     f' | {neighbours}' + (f'  <{", ".join(marks)}>' if marks else ''))
    return '\n'.join(lines)


def objective_text(definition) -> str:
    if definition.objective == 'extract':
        return (f'extract: the hero evacuates at exit {" ".join(at(p) for p in definition.exits)} '
                f'by round {definition.deadline}, or rout all defenders')
    if definition.objective == 'hold':
        return (f'hold: occupy seal {at(definition.seal)} with no enemy adjacent for {definition.hold_turns} '
                f'enemy phases by round {definition.deadline}, or rout all defenders')
    return 'rout all defenders'


def inspect_view(state: State, pos) -> str:
    province = state.provinces[pos]
    lines = [f'{province.name} {at(pos)}{" (capital)" if province.capital else ""}: {OWNERS[province.owner]}, '
             f'{province.terrain}, income {province.income}, crystals {province.crystals}']
    if province.guards:
        guards = ', '.join(f'{UNITS[kind].name} {hp}/{UNITS[kind].hp}' for kind, hp in zip(province.guards, province.guard_hp or
                                                                                    [UNITS[k].hp for k in province.guards]))
        lines.append(f'Defenders: {guards}')
    encounter = state.encounter_at(pos)
    if encounter:
        lines.append(f'Assault battle: {ENCOUNTERS[encounter].name}: {objective_text(ENCOUNTERS[encounter])}')
    if pos == state.hero.pos:
        lines.append('Your hero is here.')
    elif pos in state.grid.neighbors(state.hero.pos):
        lines.append(f'Adjacent: go {at(pos)} -> {travel_outcome(state, pos)}')
    else:
        lines.append(f'Not adjacent (distance {HexGrid.distance(pos, state.hero.pos)}).')
    if province.site:
        spec = SITES[province.site_kind]
        lines.append(f'Site: {province.site}{" (cleared)" if province.explored else ""} - {spec.description}')
        if not province.explored:
            hps = province.site_guard_hp or [UNITS[k].hp for k in province.site_guards]
            lines.append('  Guards: ' + ', '.join(f'{UNITS[k].name} {hp}/{UNITS[k].hp}' for k, hp in zip(province.site_guards, hps)))
            relic = f', relic {RELICS[province.site_relic].name}' if province.site_relic else ''
            lines.append(f'  Reward: {province.site_gold} gold, {province.site_crystals} crystals{relic}')
            if spec.approaches:
                for approach in spec.approaches:
                    fee = ', '.join(part for part in (f'{approach.gold_cost} gold' if approach.gold_cost else '',
                                                      f'{approach.crystals_cost} crystals' if approach.crystals_cost else '') if part)
                    lines.append(f'  explore {approach.id}: {approach.title} - {approach.description}'
                                 f'{" Fee " + fee + "." if fee else ""} Battle: {objective_text(ENCOUNTERS[approach.encounter])}')
            else:
                battle = objective_text(ENCOUNTERS[spec.encounter]) if spec.encounter else 'rout all defenders'
                lines.append(f'  explore: battle ({battle}); owned province, one action')
    return '\n'.join(lines)


def rival_view(state: State) -> str:
    rival = state.rival
    costs = ', '.join(f'{UNITS[kind].name} {cost}' for kind, cost in RECRUIT_COSTS.items())
    lines = [f'Rival expedition: {rival_order(state)} · at {province_label(state, rival.pos)} · '
             f'gold {rival.gold} (income +{rival.income(state)}, upkeep -{rival.upkeep}) · defeats {rival.defeats}',
             'Troops: ' + (', '.join(f'{UNITS[t.kind].name}#{t.id} {t.hp}/{t.max_hp}' for t in rival.army) or 'none (broken)'),
             f'Refits at Duskspire: {costs} gold; healing 1 gold per health. After a defeat its first paid '
             f'replacement waits {state.rules.replacement_delay} turns. Weakened expeditions return to heal.']
    return '\n'.join(lines)


def trial(state: State, order: Callable[[State], None]) -> str | None:
    """Why an order would be refused right now, using the rules' own checks on a copy."""
    probe = copy.deepcopy(state)
    try:
        order(probe)
    except RuleError as error:
        return str(error)
    return None


def camp_view(state: State) -> str:
    here = state.provinces[state.hero.pos]
    lines = ['Build (no action, permanent, from anywhere):']
    for kind, spec in BUILDINGS.items():
        price = f'{spec.cost}g' + (f'+{spec.crystals}c' if spec.crystals else '')
        status = 'built' if kind in state.buildings else trial(state, lambda s, kind=kind: s.build(kind)) or 'ok'
        lines.append(f'  {kind} {price}: {spec.description} [{status}]')
    lines.append(f'Recruit at {here.name} (no action; army {len(state.hero.army)}/{state.hero.max_army}):')
    for kind in RECRUITABLE:
        spec = UNITS[kind]
        price = f'{state.recruit_cost(kind)}g' + (f'+{spec.crystals}c' if spec.crystals else '')
        extras = ' '.join(filter(None, (' '.join(spec.abilities), 'skirmisher' if spec.skirmisher else '')))
        status = trial(state, lambda s, kind=kind: s.recruit(kind)) or 'ok'
        lines.append(f'  {kind} {price} upkeep {spec.upkeep}: hp{spec.hp} {stats(spec)}{" " + extras if extras else ""} [{status}]')
    lines.append('Replace (1 action): replace TROOP_ID KIND retires a troop for a fresh recruit in its slot.')
    infusion = state.infusion_preview()
    lines.append(f'Infuse (1 action, {infusion.crystals} crystals, up to +{infusion.mana} mana): '
                 f'[{infusion.blocked_reason or "ok"}]')
    if state.inventory:
        lines.append('Equip (free, between battles): ' + '; '.join(
            f'{kind}{" (equipped)" if kind == state.hero.relic else ""}: {RELICS[kind].description}'
            for kind in state.inventory) + ' · equip none unequips')
    return '\n'.join(lines)


# ---------------------------------------------------------------- battle views

def hex_text(battle: Battle, pos) -> str:
    mark = TERRAIN_MARK[battle.terrain[pos]]
    if battle.objective.kind == 'hold' and pos == battle.objective.target:
        mark += 'S'
    if pos in battle.objective.exits:
        mark += 'X'
    if any(cloud.pos == pos for cloud in battle.smoke_clouds):
        mark += '~'
    return at(pos) + mark


def unit_status(battle: Battle, unit: BattleUnit) -> str:
    flags = []
    if not unit.alive:
        return 'dead'
    if unit.team == battle.active_team and battle.outcome is None:
        if not unit.moved and not unit.acted:
            flags.append('ready')
        elif not unit.acted:
            flags.append('moved, can act')
        elif battle.reachable(unit.id):
            flags.append('acted, can move')
        else:
            flags.append('done')
    if unit.pinned:
        flags.append('pinned(-2 mv)')
    if unit.stance:
        flags.append(unit.stance)
    if unit.pin_cooldown:
        flags.append(f'pin cooldown {unit.pin_cooldown}')
    if unit.safe_attacks:
        flags.append(f'{unit.safe_attacks} attack(s) without retaliation')
    if unit.cargo_penalty:
        flags.append(f'cargo -{unit.cargo_penalty} mv')
    if unit.spent_abilities:
        flags.append('spent ' + ','.join(unit.spent_abilities))
    return ', '.join(flags)


def unit_line(battle: Battle, unit: BattleUnit) -> str:
    extras = ' '.join(filter(None, (' '.join(unit.abilities), 'skirmisher' if unit.skirmisher else '',
                                    'terrain-walk' if unit.terrain_walk else '')))
    status = unit_status(battle, unit)
    return (f'{unit_name(unit)} {hex_text(battle, unit.pos)} {unit.hp}/{unit.max_hp} {stats(unit)} L{unit.level}'
            + (f' {extras}' if extras else '') + (f' | {status}' if status else ''))


def forecast(deal: int, take: int, target: BattleUnit, attacker: BattleUnit) -> str:
    notes = ' KILL' if deal >= target.hp else ''
    notes += ' DIES' if take >= attacker.hp else ''
    return f'{deal}/{take}{notes}'


def objective_line(battle: Battle) -> str:
    objective = battle.objective
    if objective.kind == 'hold':
        return (f'hold seal {at(objective.target)} (a unit on it, no enemy adjacent) for {objective.required} enemy phases '
                f'by round {objective.deadline}: {objective.progress}/{objective.required}; or rout all defenders')
    if objective.kind == 'extract':
        return (f'evacuate the hero at exit {" ".join(at(p) for p in objective.exits)} by round {objective.deadline} '
                '(unspent action, no adjacent enemy); or rout all defenders')
    return 'rout all defenders (forced retreat after round 80)'


def spell_line(battle: Battle) -> str:
    spells = ', '.join(f'{spell} {battle.spell_cost(spell)} mana {battle.spell_power[spell]} '
                       f'{"dmg" if spell == "bolt" else "heal"} range 4' for spell in sorted(battle.spells))
    return f'Mana {battle.mana}' + (f' · {spells}' if spells else ' · no hero spells') + (
        ' · Acolytes heal with the shared mana' if any(u.alive and u.team == 'player' and u.can_heal for u in battle.units) else '')


def battle_view(state: State) -> str:
    battle = state.battle
    kind = {'conquest': 'invasion', 'site': 'adventure', 'intercept': 'interception', 'defense': 'defense'}[state.battle_kind]
    place = state.provinces[state.battle_province]
    where = place.site if state.battle_kind == 'site' else place.name
    lines = [f'BATTLE ({kind}) at {where} {at(place.pos)} · round {battle.round} · '
             + ('your turn' if battle.outcome is None else f'over: {battle.outcome}'),
             'Objective: ' + objective_line(battle), spell_line(battle)]
    rough = {}
    for pos, terrain in sorted(battle.terrain.items(), key=lambda item: (item[0][1], item[0][0])):
        if terrain != 'plains':
            rough.setdefault(terrain, []).append(at(pos))
    lines.append('Terrain: ' + '; '.join(f'{terrain} {" ".join(cells)}' for terrain, cells in rough.items())
                 + ('; ' if rough else '') + 'rest plains')
    if battle.smoke_clouds:
        lines.append('Smoke: ' + ' '.join(at(cloud.pos) for cloud in battle.smoke_clouds))
    for team, title in (('player', 'YOURS'), ('enemy', 'ENEMY')):
        lines.append(title)
        for unit in battle.units:
            if unit.team != team or not unit.alive:
                continue
            line = '  ' + unit_line(battle, unit)
            if team == battle.active_team and not unit.acted:
                shots = [f'{unit_name(t)} {forecast(*battle.preview(unit.id, t.id), t, unit)}' for t in battle.targets(unit.id)]
                if shots:
                    line += ' | attack now: ' + ', '.join(shots)
            lines.append(line)
    fallen = [unit_name(u) for u in battle.units if not u.alive]
    if fallen:
        lines.append('Fallen: ' + ', '.join(fallen))
    return '\n'.join(lines)


def board_view(battle: Battle) -> str:
    """A sheared hex map: each row is one r, cells run west to east by q."""
    labels = {}
    for unit in battle.units:
        if unit.alive:
            labels[unit.pos] = (f'e{unit.id - 1000}' if unit.team == 'enemy' and unit.id >= 1000 else
                                'H' if unit.id == battle.hero_id else str(unit.id))
    lines = ['Board: numbers are your troop ids, H your hero, eN enemy #(1000+N); '
             '. plains f forest h hills m marsh S seal X exit ~ smoke']
    rows = sorted({r for _, r in battle.terrain})
    for r in rows:
        cells = sorted(q for q, rr in battle.terrain if rr == r)
        offset = 2 * cells[0] + r - min(2 * q + rr for q, rr in battle.terrain)
        tokens = []
        for q in cells:
            pos = (q, r)
            token = labels.get(pos) or (hex_text(battle, pos)[len(at(pos)):] or '.')
            tokens.append(f'{token:<3}')
        lines.append(f'r={r:<2} q{cells[0]}..{cells[-1]}'.ljust(14) + ' ' * (2 * offset) + ' '.join(tokens).rstrip())
    return '\n'.join(lines)


def strike_options(battle: Battle, unit: BattleUnit) -> dict[int, list[tuple[int, int, tuple]]]:
    """Targets only a move brings in range: target id -> [(deal, take, hex)], forecast by the rules."""
    now = {target.id for target in battle.targets(unit.id)}
    options = {}
    for pos in sorted(battle.reachable(unit.id), key=lambda p: (p[1], p[0])):
        probe = copy.deepcopy(battle)
        probe.unit(unit.id).pos = pos
        for target in probe.targets(unit.id):
            if target.id not in now:
                options.setdefault(target.id, []).append((*probe.preview(unit.id, target.id), pos))
    return options


def move_refusal(battle: Battle, unit: BattleUnit, pos) -> str | None:
    """Why your unit cannot move to a hex, more specifically than the rules' shared refusal."""
    if unit.team != battle.active_team or not unit.alive or pos in battle.reachable(unit.id):
        return None
    if pos not in battle.terrain:
        return f'{at(pos)} is off the battlefield'
    occupant = next((u for u in battle.units if u.alive and u.pos == pos and u.id != unit.id), None)
    if occupant is not None:
        return f'{at(pos)} is occupied by {unit_name(occupant)}'
    if unit.moved:
        return f'{unit_name(unit)} already moved this round'
    if unit.acted:
        return f'{unit_name(unit)} already acted, which ends its movement'
    blockers = path_blockers(battle, unit, pos)
    if blockers:
        return (f'{at(pos)} is within {unit_name(unit)}\'s movement, but units stand on every route: '
                + ', '.join(f'{unit_name(u)} at {at(u.pos)}' for u in blockers))
    return (f'{at(pos)} is out of reach for {unit_name(unit)}: mv {unit.effective_move_range}, forest and marsh '
            f'cost 2 (unit {unit.id} lists its reach)')


def path_blockers(battle: Battle, unit: BattleUnit, pos) -> list[BattleUnit]:
    """Units standing on the routes that would reach pos if their hexes were empty."""
    budget = unit.effective_move_range

    def cost(cell):
        return battle.move_cost(unit, cell)
    ahead = battle.grid.reachable(unit.pos, budget, cost=cost)
    if pos not in ahead:
        return []
    back = battle.grid.reachable(pos, budget, cost=cost)
    return [other for other in battle.units if other.alive and other.id != unit.id and other.pos in ahead
            and other.pos in back and ahead[other.pos] + back[other.pos] - cost(other.pos) + cost(pos) <= budget]


def spell_refusal(battle: Battle, spell: str, caster: BattleUnit, target: BattleUnit) -> str | None:
    """The target-side reason a spell is refused: side, health, range or sight."""
    if not target.alive:
        return f'{unit_name(target)} has fallen'
    if (spell == 'bolt') == (target.team == caster.team):
        return 'bolt targets enemies' if spell == 'bolt' else 'heal targets allies'
    if spell == 'heal' and target.hp >= target.max_hp:
        return f'{unit_name(target)} is unhurt'
    distance = HexGrid.distance(caster.pos, target.pos)
    if distance > 4:
        return f'{unit_name(target)} is {distance} hexes from {unit_name(caster)}; spells reach 4'
    if not battle.has_sight(caster.pos, target.pos):
        return f'no line of sight from {unit_name(caster)} at {at(caster.pos)} (intervening forest or smoke)'
    return None


def unit_view(battle: Battle, unit_id: int) -> str:
    unit = battle.unit(unit_id)
    lines = [unit_line(battle, unit)]
    if not unit.alive:
        return lines[0]
    reach = sorted(battle.reachable(unit.id), key=lambda p: (p[1], p[0]))
    lines.append(f'reach ({len(reach)}, mv {unit.effective_move_range}): ' + (' '.join(hex_text(battle, p) for p in reach) or 'none'))
    ours = unit.team == battle.active_team and battle.outcome is None
    who = 'attack' if ours else 'could attack'
    now = battle.targets(unit.id)
    if now:
        lines.append(f'{who} now (deal/take): ' + ', '.join(
            f'{unit_name(t)} {forecast(*battle.preview(unit.id, t.id), t, unit)}' for t in now))
    for target_id, options in sorted(strike_options(battle, unit).items()):
        target, cells = battle.unit(target_id), {}
        for deal, take, pos in options:
            cells.setdefault((deal, take), []).append(hex_text(battle, pos))
        lines.append(f'{who} after moving: {unit_name(target)} ' + '; '.join(
            f'{forecast(deal, take, target, unit)} from {" ".join(hexes)}' for (deal, take), hexes in cells.items()))
    if not ours:
        return '\n'.join(lines)
    orders = []
    pins = battle.pin_targets(unit.id)
    if pins:
        orders.append('pin: ' + ', '.join(f'{unit_name(t)} {forecast(*battle.pin_preview(unit.id, t.id), t, unit)}' for t in pins))
    for spell in ('bolt', 'heal'):
        targets = battle.spell_targets(spell, caster_id=unit.id)
        if targets:
            orders.append(f'cast {spell} ({battle.spell_cost(spell)} mana): ' + ', '.join(
                f'{unit_name(t)} {battle.spell_preview(spell, t.id, caster_id=unit.id)}' for t in targets))
    for name, finder in (('repulse', battle.repulse_targets), ('rally', battle.rally_targets), ('swap', battle.swap_targets)):
        targets = finder(unit.id)
        if targets:
            if name == 'repulse':
                orders.append('repulse: ' + ', '.join(f'{unit_name(t)} to {at(battle.repulse_preview(unit.id, t.id))}' for t in targets))
            else:
                orders.append(f'{name}: ' + ', '.join(unit_name(t) for t in targets))
    smoke = sorted(battle.smoke_targets(unit.id), key=lambda p: (p[1], p[0]))
    if smoke:
        orders.append('smoke: ' + ' '.join(at(p) for p in smoke))
    if not unit.acted:
        orders.append('brace' if unit.can_brace else 'guard (+2 def)')
    if unit.id == battle.hero_id and battle.objective.kind == 'extract':
        orders.append('evacuate: ' + (battle.evacuation_blocked_reason or 'ready'))
    if orders:
        lines.append('orders: ' + ' · '.join(orders))
    return '\n'.join(lines)


# ---------------------------------------------------------------- change reports

VERBS = {'attack': 'hits', 'pin': 'pins', 'retaliation': 'retaliates on', 'brace': 'brace-strikes',
         'bolt': 'casts bolt on', 'heal': 'casts heal on', 'repulse': 'repulses', 'rally': 'rallies',
         'swap': 'swaps with', 'escape': 'evacuates'}


def trace_lines(battle: Battle, trace) -> list[str]:
    names = {unit.id: unit_name(unit) for unit in battle.units}
    teams = {unit.id: unit.team for unit in battle.units}
    lines, acting = [], battle.active_team if trace.events else None
    for event in trace.events:
        if event.kind not in ('retaliation', 'brace', 'phase', 'objective', 'result') and teams[event.actor_id] != acting:
            acting = teams[event.actor_id]
            lines.append(f'-- {"enemy" if acting == "enemy" else "your"} phase --')
        changes = []
        for after in event.after.units:
            before = event.before.unit(after.id)
            parts = []
            if after.pos != before.pos and event.kind != 'move':
                parts.append(f'{at(before.pos)}->{at(after.pos)}')
            if after.hp != before.hp:
                parts.append(f'hp {before.hp}->{max(0, after.hp)}' + (' DEAD' if after.hp <= 0 else ''))
            if after.pinned and not before.pinned:
                parts.append('pinned')
            if parts:
                changes.append(f'{names[after.id]} ' + ' '.join(parts))
        if event.kind in ('phase', 'result'):
            if event.text == 'Your turn.':
                lines.append(f'-- round {event.after.round}: your turn --')
            lines += changes
        elif event.kind == 'objective':
            lines.append(event.text)
        elif event.kind == 'move':
            actor = event.before.unit(event.actor_id)
            lines.append(f'{names[event.actor_id]} moves {at(actor.pos)}->{at(event.after.unit(event.actor_id).pos)}')
        else:
            actor = names[event.actor_id]
            if event.kind == 'guard':
                head = actor + (' braces' if event.after.unit(event.actor_id).stance == 'brace' else ' guards')
            elif event.kind == 'smoke':
                clouds = sorted(set(event.after.smoke) - set(event.before.smoke))
                head = f'{actor} smokes ' + ' '.join(at(pos) for pos, _ in clouds)
            else:
                head = f'{actor} {VERBS[event.kind]}' + (f' {names[event.target_id]}' if event.target_id is not None else '')
            lines.append(head + (': ' + '; '.join(changes) if changes else ''))
    return lines


@dataclass(frozen=True)
class Snapshot:
    """The campaign facts whose changes an order reports."""
    values: dict  # label -> number, reported as 'label old->new'
    hero_at: tuple
    army: dict  # troop id -> (name, hp, level)
    owners: dict
    rival: tuple
    log: int

    @classmethod
    def take(cls, state: State) -> Snapshot:
        hero = state.hero
        values = {'gold': state.gold, 'crystals': state.crystals, 'actions': state.actions_left,
                  'hero hp': hero.hp, 'mana': hero.mana, 'hero level': hero.level, 'hero xp': hero.xp}
        return cls(values, hero.pos, {t.id: (troop_name(t), t.hp, t.level) for t in hero.army},
                   {pos: p.owner for pos, p in state.provinces.items()},
                   (state.rival.pos, rival_order(state), tuple((t.id, t.hp) for t in state.rival.army)),
                   len(state.log))

    def report(self, state: State) -> list[str]:
        after = Snapshot.take(state)
        lines = state.log[self.log:]
        deltas = [f'{label} {old}->{after.values[label]}' for label, old in self.values.items()
                  if old != after.values[label]]
        if self.hero_at != after.hero_at:
            deltas.append(f'hero at {province_label(state, after.hero_at)}')
        if deltas:
            lines.append(' · '.join(deltas))
        army = []
        for ident, (name, hp, level) in after.army.items():
            if ident not in self.army:
                army.append(f'+{name} {hp}hp')
                continue
            _, old_hp, old_level = self.army[ident]
            changes = ([f'hp {old_hp}->{hp}'] if hp != old_hp else []) + ([f'L{level}'] if level != old_level else [])
            if changes:
                army.append(f'{name} ' + ' '.join(changes))
        army += [f'-{name} (gone)' for ident, (name, _, _) in self.army.items() if ident not in after.army]
        if army:
            lines.append('Army: ' + ', '.join(army))
        lines += [f'{province_label(state, pos)}: {OWNERS[self.owners[pos]]} -> {OWNERS[owner]}'
                  for pos, owner in after.owners.items() if self.owners[pos] != owner]
        if self.rival != after.rival:
            lines.append(f'Rival: {rival_order(state)} · {len(state.rival.army)} troops at '
                         f'{province_label(state, state.rival.pos)}')
        return lines


# ---------------------------------------------------------------- commands

@dataclass(frozen=True)
class Command:
    usage: str
    summary: str
    where: str  # 'any' (even without a game), 'shard', 'battle' or 'both'
    observes: bool  # an observation changes nothing, so no [status] line follows it
    run: Callable[[Session, list[str]], str]


COMMANDS: dict[str, Command] = {}
ALIASES = {'l': 'look', 'm': 'map', 'i': 'inspect', 'u': 'unit', 'b': 'board', '?': 'help'}


def command(usage: str, summary: str, *, where: str = 'shard', observes: bool = False):
    def register(func):
        COMMANDS[usage.split()[0]] = Command(usage, summary, where, observes, func)
        return func
    return register


def split_commands(line: str) -> list[str]:
    """Split on ';' except inside a trailing note, which keeps the rest of the line."""
    commands = []
    for part in line.split(';'):
        if commands and commands[-1].split()[0].lower() == 'note':
            commands[-1] += ';' + part
        elif part.strip():
            commands.append(part.strip())
    return commands


def retinue(args: list[str]) -> dict:
    """Parse `[troops 4,7] [relics moonstone,iron_crown]` for depart and recover."""
    chosen = {'troop_ids': (), 'relic_ids': ()}
    words = iter(args)
    for word in words:
        values = next(words, None)
        if word not in ('troops', 'relics') or values is None:
            raise UsageError('expected [troops ID,ID] [relics NAME,NAME]')
        items = [v for v in values.split(',') if v]
        chosen['troop_ids' if word == 'troops' else 'relic_ids'] = (
            tuple(parse_int(v, 'a troop id') for v in items) if word == 'troops'
            else tuple(resolve([v], RELICS, 'relic') for v in items))
    return chosen


class Session:
    """One player's game: runs command lines against the state and reports their effects."""

    def __init__(self, state: State | None = None):
        self.state = state

    def run(self, line: str) -> tuple[str, bool]:
        """Run ';'-separated commands, stopping at the first error. Returns (output, success)."""
        commands = split_commands(line) or ['look']
        blocks, changed = [], False
        for index, text in enumerate(commands):
            name, *args = text.split()
            name = ALIASES.get(name.lower(), name.lower())
            prefix = f'> {text}\n' if len(commands) > 1 else ''
            try:
                spec = COMMANDS.get(name)
                if spec is None:
                    raise UsageError(f'unknown command {name!r}; see help')
                if self.state is None and spec.where != 'any':
                    raise UsageError('no game in this save yet: new [SEED] [HERO] [DIFFICULTY]')
                if spec.where == 'battle' and (self.state.battle is None):
                    raise UsageError('there is no battle in progress')
                if spec.where == 'shard' and self.state.battle is not None:
                    raise UsageError('finish the battle first (look, end, auto, retreat)')
                output = spec.run(self, args)
            except (RuleError, UsageError) as error:
                blocks.append(prefix + f'error: {error}')
                if index + 1 < len(commands):
                    blocks.append('skipped: ' + '; '.join(commands[index + 1:]))
                if changed:
                    blocks.append(self.footer())
                return '\n'.join(blocks), False
            changed |= not spec.observes
            blocks.append(prefix + output if output else prefix.rstrip())
        if changed:
            blocks.append(self.footer())
        return '\n'.join(block for block in blocks if block), True

    def footer(self) -> str:
        state = self.state
        if state.battle is not None:
            battle = state.battle
            ready = [unit_name(u) for u in battle.units if u.alive and u.team == battle.active_team
                     and not u.acted]
            enemies = sum(u.alive and u.team == 'enemy' for u in battle.units)
            return f'[round {battle.round} · mana {battle.mana} · can act: {" ".join(ready) or "nobody (end)"} · enemies left {enemies}]'
        if state.campaign and state.campaign.phase != 'playing':
            return f'[campaign: {state.campaign.phase} - look]'
        parts = [f'turn {state.turn}', f'actions {state.actions_left}', f'gold {state.gold}', f'crystals {state.crystals}',
                 f'hero {state.hero.hp}/{state.hero.max_hp}hp', f'at {province_label(state, state.hero.pos)}']
        if state.choice:
            parts.append('CHOICE PENDING (look)')
        return '[' + ' · '.join(parts) + ']'

    # Campaign orders report the diff, then any battle that began.
    def order(self, action: Callable[[], object]) -> str:
        before = Snapshot.take(self.state)
        result = action()
        lines = before.report(self.state)
        if isinstance(result, str) and result not in lines:
            lines.append(result)
        if self.state.battle is not None:
            lines.append(battle_view(self.state))
        elif (text := choice_text(self.state)):
            lines.append(text)
        if self.state.campaign and self.state.campaign.phase != 'playing':
            lines.append(transition_view(self.state))
        return '\n'.join(lines)

    # Battle orders report the traced events, then settle a finished battle.
    def battle_order(self, action: Callable[[Battle], None]) -> str:
        battle = self.state.battle
        lines = trace_lines(battle, battle.trace(lambda: action(battle)))
        return '\n'.join(lines + self.settle())

    def settle(self) -> list[str]:
        battle = self.state.battle
        if battle is None or battle.outcome is None:
            return []
        reason = f' ({battle.outcome_reason})' if battle.outcome_reason else ''
        header = f'BATTLE OVER: {"victory" if battle.outcome == "player" else "defeat"}{reason}'
        return [header, self.order(self.state.resolve_battle)]


@command('help [COMMAND|rules]', 'command reference, or the rules primer', where='any', observes=True)
def _help(session, args):
    if args and args[0] == 'rules':
        return RULES
    if args:
        spec = COMMANDS.get(ALIASES.get(args[0], args[0]))
        if spec is None:
            raise UsageError(f'unknown command {args[0]!r}')
        return f'{spec.usage} - {spec.summary}'
    groups = {'any': 'Anywhere', 'shard': 'On the shard map', 'battle': 'In battle', 'both': 'Map or battle'}
    lines = ['shardbound-text [-g SAVE] "cmd; cmd; ...": commands run in order; the first error stops the rest.',
             'Orders print what changed; a [status] line follows. Names match ids or display names in any case.',
             'note must come last in a chain; double-quote a chain whose note has an apostrophe. Aliases: '
             + ' '.join(f'{k}={v}' for k, v in ALIASES.items()) + '. See also: help rules.']
    for where, title in groups.items():
        lines.append(title + ':')
        lines += [f'  {spec.usage} - {spec.summary}' for spec in COMMANDS.values() if spec.where == where]
    return '\n'.join(lines)


@command('new [SEED] [HERO] [DIFFICULTY]', 'start a three-shard campaign (heroes: Commander Warrior Scout Wizard; '
         'difficulty: accessible standard challenge; defaults 7 Commander standard)', where='any')
def _new(session, args):
    seed = parse_int(args[0], 'a seed') if args else 7
    hero = args[1].capitalize() if len(args) > 1 else 'Commander'
    difficulty = args[2].lower() if len(args) > 2 else 'standard'
    if hero not in HERO_CLASSES:
        raise UsageError(f'hero is one of {" ".join(HERO_CLASSES)}')
    if difficulty not in DIFFICULTIES:
        raise UsageError(f'difficulty is one of {" ".join(DIFFICULTIES)}')
    session.state = State.new_campaign(seed, hero, difficulty=difficulty)
    return f'{hero}: {HERO_CLASSES[hero].description}\n' + campaign_view(session.state)


@command('look', 'the situation now: shard overview, battle, or campaign transition',
         where='both', observes=True)
def _look(session, args):
    return battle_view(session.state) if session.state.battle else campaign_view(session.state)


@command('codex [TOPIC]', 'the in-game codex: ' + ' '.join(c.lower() for c in CATEGORIES) + ', or any entry name',
         where='both', observes=True)
def _codex(session, args):
    topic = ' '.join(args).lower()
    categories = {category.lower(): category for category in CATEGORIES}
    if not topic:
        return 'Codex categories: ' + ', '.join(categories) + '. codex CATEGORY lists it; codex NAME finds entries.'
    if topic in categories:
        chosen = [(categories[topic], entry) for entry in codex_entries(session.state, categories[topic])]
    else:
        entries = [(category, entry) for category in CATEGORIES for entry in codex_entries(session.state, category)]
        chosen = ([(c, e) for c, e in entries if topic in e.title.lower()]
                  or [(c, e) for c, e in entries if topic in f'{e.facts} {e.description}'.lower()])
    if not chosen:
        raise UsageError(f'no codex entry matches {topic!r}')
    absent = 'No recorded source on this shard.'
    elsewhere = list(dict.fromkeys(entry.title.split(':')[0] for category, entry in chosen
                                   if category == 'Sites' and absent in entry.description))
    lines = [f'{entry.title} [{entry.facts}] {entry.description}' for category, entry in chosen
             if not (category == 'Sites' and absent in entry.description)]
    if elsewhere:
        lines.append('Sites not on this shard (codex NAME for details): ' + ', '.join(elsewhere))
    return '\n'.join(lines)


@command('note TEXT', 'write your remark into the transcript (must be last in a chain)', where='any', observes=True)
def _note(session, args):
    if not args:
        raise UsageError('note what?')
    return 'noted (everything after "note", including any ";", is the note)' if any(';' in a for a in args) else 'noted'


@command('map', 'every province: owner, defenders, site, neighbours', where='both', observes=True)
def _map(session, args):
    return map_view(session.state)


@command('inspect Q,R', 'one province: defenders, site, reward, approaches, what entering does',
         where='both', observes=True)
def _inspect(session, args):
    if len(args) != 1:
        raise UsageError('usage: inspect Q,R')
    pos = parse_pos(args[0])
    if pos not in session.state.provinces:
        raise UsageError(f'{at(pos)} is not on this shard (q and r within -2..2)')
    return inspect_view(session.state, pos)


@command('plan', 'campaign objectives, what travels to the next shard, rank limits, recovery',
         where='both', observes=True)
def _plan(session, args):
    return plan_view(session.state)


@command('rival', 'the rival expedition: plan, troops, treasury', where='both', observes=True)
def _rival(session, args):
    return rival_view(session.state)


@command('camp', 'build, recruit, replace, infuse and equip options with prices and blockers', observes=True)
def _camp(session, args):
    return camp_view(session.state)


@command('go Q,R', 'travel to, invade or intercept at an adjacent province (1 action)')
def _go(session, args):
    if len(args) != 1:
        raise UsageError('usage: go Q,R')
    pos = parse_pos(args[0])
    if pos not in session.state.provinces:
        raise UsageError(f'{at(pos)} is not on this shard')
    return session.order(lambda: session.state.travel(pos))


@command('explore [APPROACH]', 'explore the site where your hero stands (1 action; some sites need an approach)')
def _explore(session, args):
    state = session.state
    province = state.provinces[state.hero.pos]
    approaches = SITES[province.site_kind].approaches if province.site_kind and not province.explored else ()
    if approaches and not args:
        raise UsageError('choose an approach: ' + ', '.join(f'explore {a.id}' for a in approaches)
                         + f' (inspect {at(province.pos)})')
    return session.order(lambda: state.explore(approach=args[0] if args else None))


RECRUITS = {kind: UNITS[kind] for kind in RECRUITABLE}


@command('build KIND', 'build a stronghold building (see camp)')
def _build(session, args):
    kind = resolve(args, BUILDINGS, 'building')
    return session.order(lambda: session.state.build(kind))


@command('recruit KIND', 'recruit a troop where your hero stands (see camp)')
def _recruit(session, args):
    kind = resolve(args, RECRUITS, 'troop')
    return session.order(lambda: session.state.recruit(kind))


@command('replace TROOP_ID KIND', 'retire a troop and recruit KIND in its slot (1 action)')
def _replace(session, args):
    if len(args) < 2:
        raise UsageError('usage: replace TROOP_ID KIND')
    ident, kind = parse_int(args[0], 'a troop id'), resolve(args[1:], RECRUITS, 'troop')
    return session.order(lambda: session.state.replace_troop(ident, kind))


@command('infuse', 'spend 3 crystals and 1 action for up to 8 mana (needs a Mage Tower)')
def _infuse(session, args):
    return session.order(session.state.infuse)


@command('equip RELIC|none', 'equip an owned relic, or none')
def _equip(session, args):
    if not args:
        raise UsageError('usage: equip RELIC|none')
    relic = None if args == ['none'] else resolve(args, RELICS, 'relic')
    return session.order(lambda: session.state.equip(relic))


@command('choose OPTION', 'answer the pending skill or relic choice')
def _choose(session, args):
    if len(args) != 1:
        raise UsageError('usage: choose OPTION')
    return session.order(lambda: session.state.choose(args[0]))


@command('end', 'end the campaign turn, or end your battle round (the enemy then acts)', where='both')
def _end(session, args):
    if session.state.battle is not None:
        return session.battle_order(Battle.end_turn)
    return session.order(session.state.end_turn)


@command('depart OFFER [troops ID,ID] [relics NAME,NAME]', 'after a won shard, travel to the next one')
def _depart(session, args):
    if not args:
        raise UsageError('usage: depart OFFER [troops ID,ID] [relics NAME,NAME]')
    chosen = retinue(args[1:])
    session.state.advance(args[0], **chosen)
    return campaign_view(session.state)


@command('recover [troops ID,ID] [relics NAME,NAME]', 'after the first lost capital, restart this shard once')
def _recover(session, args):
    session.state.recover(**retinue(args))
    return campaign_view(session.state)


@command('abandon', 'after the first lost capital, end the campaign instead of recovering')
def _abandon(session, args):
    session.state.abandon_campaign()
    return transition_view(session.state)


def battle_unit(session, text: str) -> int:
    ident = parse_int(text, 'a unit id')
    session.state.battle.unit(ident)
    return ident


@command('unit ID', 'one unit: reach, attack forecasts from each hex, ability and spell targets',
         where='battle', observes=True)
def _unit(session, args):
    if len(args) != 1:
        raise UsageError('usage: unit ID')
    return unit_view(session.state.battle, battle_unit(session, args[0]))


@command('board', 'the battlefield drawn as a hex map', where='battle', observes=True)
def _board(session, args):
    return board_view(session.state.battle)


@command('move ID Q,R', 'move a unit', where='battle')
def _move(session, args):
    if len(args) != 2:
        raise UsageError('usage: move ID Q,R')
    ident, pos = battle_unit(session, args[0]), parse_pos(args[1])
    if reason := move_refusal(session.state.battle, session.state.battle.unit(ident), pos):
        raise UsageError(reason)
    return session.battle_order(lambda b: b.move(ident, pos))


def ordered_from(session, ident: int, source, act: Callable[[Battle], None]) -> str:
    """Move to source first when given; the whole order is checked on a copy, so a refusal moves nothing."""
    battle = session.state.battle
    unit = battle.unit(ident)
    moving = source is not None and source != unit.pos
    if moving:
        if reason := move_refusal(battle, unit, source):
            raise UsageError(reason)
        probe = copy.deepcopy(battle)
        probe.move(ident, source)
        act(probe)

    def order(battle):
        if moving:
            battle.move(ident, source)
        act(battle)
    return session.battle_order(order)


def strike(session, args, kind: str) -> str:
    """attack/pin ID TARGET [from Q,R]."""
    if len(args) not in (2, 4) or len(args) == 4 and args[2] != 'from':
        raise UsageError(f'usage: {kind} ID TARGET [from Q,R]')
    ident, target = battle_unit(session, args[0]), battle_unit(session, args[1])
    source = parse_pos(args[3]) if len(args) == 4 else None
    battle, unit, enemy = session.state.battle, session.state.battle.unit(ident), session.state.battle.unit(target)
    if (source is None and kind == 'attack' and unit.team == battle.active_team and unit.alive and not unit.acted
            and enemy.alive and enemy.team != unit.team and enemy.id not in {t.id for t in battle.targets(ident)}):
        distance = HexGrid.distance(unit.pos, enemy.pos)
        cause = (f'{distance} hexes away, range {unit.attack_range}' if distance > unit.attack_range
                 else 'no line of sight (intervening forest or smoke)')
        cells = [pos for _, _, pos in strike_options(battle, unit).get(target, [])]
        raise UsageError(f'{unit_name(enemy)} cannot be attacked from {at(unit.pos)}: {cause}; '
                         + (f'add "from Q,R", one of: {" ".join(at(pos) for pos in cells)}' if cells
                            else 'no reachable hex brings it in range'))
    return ordered_from(session, ident, source, lambda b: getattr(b, kind)(ident, target))


@command('attack ID TARGET [from Q,R]', 'attack, optionally moving to Q,R first', where='battle')
def _attack(session, args):
    return strike(session, args, 'attack')


@command('pin ID TARGET [from Q,R]', 'half-damage shot that slows the target (-2 mv next turn)', where='battle')
def _pin(session, args):
    return strike(session, args, 'pin')


@command('guard ID|all', 'spend the order on Guard (+2 def), or Brace for a Pikeman; all: every unit that can act',
         where='battle')
def _guard(session, args):
    if len(args) != 1:
        raise UsageError('usage: guard ID|all')
    battle = session.state.battle
    if args[0] == 'all':
        ids = [u.id for u in battle.units if u.alive and u.team == battle.active_team and not u.acted]
        if not ids:
            raise UsageError('no unit can act')
    else:
        ids = [battle_unit(session, args[0])]
    return session.battle_order(lambda b: [b.guard(ident) for ident in ids])


def targeted(name: str):
    def run(session, args):
        if len(args) != 2:
            raise UsageError(f'usage: {name} ID TARGET')
        ident, target = battle_unit(session, args[0]), battle_unit(session, args[1])
        return session.battle_order(lambda b: getattr(b, name)(ident, target))
    return run


command('repulse ID TARGET', 'push an adjacent enemy one hex away (one charge)', where='battle')(targeted('repulse'))
command('rally ID TARGET', "clear an adjacent ally's Pin", where='battle')(targeted('rally'))
command('swap ID TARGET', 'exchange places with an adjacent ally', where='battle')(targeted('swap'))


@command('smoke ID Q,R', "screen a hex from both sides' fire until your next turn (one charge)", where='battle')
def _smoke(session, args):
    if len(args) != 2:
        raise UsageError('usage: smoke ID Q,R')
    ident, pos = battle_unit(session, args[0]), parse_pos(args[1])
    return session.battle_order(lambda b: b.smoke(ident, pos))


@command('cast SPELL TARGET [by ID] [from Q,R]',
         'cast bolt or heal (hero by default; an Acolyte can heal), optionally moving the caster first', where='battle')
def _cast(session, args):
    options = dict(zip(args[2::2], args[3::2]))
    if len(args) < 2 or len(args) % 2 or set(options) - {'by', 'from'}:
        raise UsageError('usage: cast SPELL TARGET [by ID] [from Q,R]')
    battle, spell = session.state.battle, args[0].lower()
    if spell not in SPELLS:
        raise UsageError('spell is bolt or heal')
    target = battle_unit(session, args[1])
    caster = battle_unit(session, options['by']) if 'by' in options else None
    source = parse_pos(options['from']) if 'from' in options else None
    ident = battle.hero_id if caster is None else caster
    try:
        return ordered_from(session, ident, source, lambda b: b.cast(spell, target, caster_id=caster))
    except RuleError as error:
        if 'within 4 hexes' not in str(error):
            raise
        view = copy.deepcopy(battle)
        view.unit(ident).pos = source or view.unit(ident).pos
        refusal = spell_refusal(view, spell, view.unit(ident), view.unit(target))
        cells = []
        for pos in sorted(battle.reachable(ident), key=lambda p: (p[1], p[0])):
            view.unit(ident).pos = pos
            if target in {t.id for t in view.spell_targets(spell, caster_id=caster)}:
                cells.append(at(pos))
        hint = f'; cast from one of: {" ".join(cells)}' if cells else ''
        raise RuleError(f'{error} ({refusal}){hint}' if refusal else f'{error}{hint}') from None


@command('evacuate', 'the hero leaves with the cargo from a marked exit', where='battle')
def _evacuate(session, args):
    return session.battle_order(Battle.evacuate)


@command('auto [all]', 'let the battle AI command your army for one round, or until the battle ends', where='battle')
def _auto(session, args):
    if args and args != ['all']:
        raise UsageError('usage: auto [all]')
    battle = session.state.battle
    if not args:
        return session.battle_order(Battle.auto_turn)
    start = battle.round
    alive = {u.id for u in battle.units if u.alive}
    while battle.outcome is None:
        battle.auto_turn()
    dead = [unit_name(u) for u in battle.units if u.id in alive and not u.alive]
    lines = [f'auto: rounds {start}-{battle.round}; fell: {", ".join(dead) or "nobody"}']
    lines += [unit_line(battle, u) for u in battle.units if u.team == 'player' and u.alive]
    return '\n'.join(lines + session.settle())


@command('retreat', 'abandon the battle: lose it, keep the survivors', where='battle')
def _retreat(session, args):
    return session.order(session.state.retreat)


# ---------------------------------------------------------------- entry point

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    save = Path(os.environ.get('SHARDBOUND_GAME', 'shardbound-game.json'))
    if argv[:1] in (['-g'], ['--game']):
        if len(argv) < 2:
            print('error: -g needs a save path')
            return 2
        save, argv = Path(argv[1]), argv[2:]
    if argv[:1] in (['-h'], ['--help']):
        argv = ['help']
    line = ' '.join(argv)
    state = State.from_json(save.read_text()) if save.exists() else None
    session = Session(state)
    output, ok = session.run(line)
    print(output)
    if session.state is not None:
        save.write_text(session.state.to_json())
    with save.with_name(save.name + '.log').open('a') as transcript:
        transcript.write(f'> {line}\n{output}\n')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
