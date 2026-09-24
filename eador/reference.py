"""The field codex's rule reference, built from the game's current rule tables.

The codex scene pages these entries; text play prints them.
"""
from collections import Counter
from dataclasses import dataclass

from eador.battle import Battle, SPELLS
from eador.content import RELICS, SITES, SKILLS
from eador.encounters import ENCOUNTERS
from eador.model import BUILDINGS, RECRUITABLE, UNITS


CATEGORIES = ("Troops", "Abilities", "Buildings", "Skills", "Sites", "Relics")


INTRODUCTIONS = (
    "Each troop offers different orders. See Abilities for timing and limits. Base stats exclude veteran and hero bonuses.",
    "Hero and Acolytes share mana. Spell values include skills and relics; counts use this battle's saved capabilities.",
    "Stronghold buildings are permanent. Each can be constructed once, even while your hero is away.",
    "Each earned hero level offers a discipline. Deepen one path or develop both; skills belong to a hero class.",
    "Explore an owned, uncleared site using one action. Approach choices follow their site; the active choice shows its saved reward.",
    "Equip one relic between battles. Replacing Moonstone or Ember Lens removes its spell unless learned elsewhere. Sources belong to this saved shard.",
)


@dataclass(frozen=True)
class Entry:
    title: str
    facts: str
    description: str


def _source_locations(provinces, *, with_site=False):
    """Locate the saved sources, retaining cleared places without promising another reward."""
    sources = sorted((f'{province.site} at ' if with_site else '') + province.name
                     + (' (cleared)' if province.explored else '') for province in provinces)
    return 'Recorded sources: ' + '; '.join(sources) + '.' if sources else 'No recorded source on this shard.'


def codex_entries(state, category: str) -> list[Entry]:
    """One codex category's entries for this saved state, as the scene and text play read them."""
    older_acolytes = state.battle and any(unit.team == 'player' and unit.alive
                                         and unit.kind == 'healer' and not unit.can_heal
                                         for unit in state.battle.units)
    saved_healing_note = "This older battle retains its noncasting Acolytes."
    if category == "Troops":
        entries = []
        for kind, spec in UNITS.items():
            facts = (f"Base: {spec.hp} health · {spec.attack} attack · {spec.defense} defense · "
                     f"{spec.move_range} movement · {spec.attack_range} range")
            role = "Ranged attacker." if spec.attack_range > 1 else "Melee fighter."
            if kind in RECRUITABLE:
                requirement = f"Requires {BUILDINGS[spec.building].name}." if spec.building else "No building required."
                description = (f"{role} Recruit for {state.recruit_cost(kind)} gold now (base {spec.cost}); "
                               f"upkeep {spec.upkeep} gold/turn. {requirement}")
                if kind in ('sapper', 'adept', 'skyrider'):
                    crystals = state.recruit_crystal_cost(kind)
                    price = f"{state.recruit_cost(kind)} gold + {crystals} crystal{'s' if crystals != 1 else ''}"
                    roles = {
                        'sapper': "One Smoke charge screens a hex from both sides' fire and magic.",
                        'adept': "One Repulse charge pushes an unanchored adjacent enemy without damage.",
                        'skyrider': "Flight crosses rough and occupied hexes; land empty. Pin and Brace still counter it.",
                    }
                    description = (f"Recruit for {price}; upkeep {spec.upkeep} gold/turn. {requirement} "
                                   + roles[kind] + " See Abilities.")
                elif kind == "militia":
                    older = state.battle and any(unit.alive and unit.team == 'player' and unit.kind == kind
                                                and not unit.can_rally for unit in state.battle.units)
                    description += (" This older battle's Militia cannot Rally." if older else
                                    " Rally clears an adjacent ally's Pin without refreshing orders. See Abilities.")
                elif kind == "healer":
                    description = (f"Recruit for {state.recruit_cost(kind)} gold (base {spec.cost}); upkeep {spec.upkeep}. {requirement} "
                                   "Heal uses its order and shared mana. Adds 2 army recovery per resting turn. "
                                   + (saved_healing_note if older_acolytes else "See Abilities for costs and timing."))
                elif kind == "archer":
                    description += " Pin trades half damage for -2 movement on the target’s next turn. See Abilities for timing and counters."
                elif kind == "ranger":
                    description += " Shoot before moving to reposition; moving first gives no extra move. No Pin. See Abilities for limits."
                elif kind == "warden":
                    description += " Swap into an adjacent ally’s place to extract it. Spends both moves and the Warden’s action. See Abilities for exact costs."
                elif kind == "pikeman":
                    description = (f"Costs {state.recruit_cost(kind)} gold (base {spec.cost}); upkeep {spec.upkeep}. "
                                   "Requires Barracks. Brace hits once before melee, through retaliation protection. "
                                   "Replaces retaliation; ranged fire avoids it. Expires next turn.")
            else:
                description = f"{role} Encountered as a guardian; cannot be recruited."
            entries.append(Entry(spec.name, facts, description))
        return entries
    if category == "Abilities":
        # The public battle factory applies current skills/equipment without mutating the hero.
        battle = state.battle or Battle.create(state.hero, [], "plains", state.spells)
        sources = {"bolt": "Wizard, Mage Tower or equipped Ember Lens",
                   "heal": "Wizard, Temple or equipped Moonstone"}
        entries = [Entry(spec.name,
                      f"Your hero: {battle.spell_cost(kind)} mana · {battle.spell_power[kind]} "
                      f"{'damage' if kind == 'bolt' else 'healing'} · {'Learned' if kind in battle.spells else 'Not learned'}",
                      f"Base cost: {spec.cost} mana. {spec.description} Requires {sources[kind]}. "
                      "Casting spends the hero's action and movement.")
                for kind, spec in SPELLS.items()]
        capable = [unit for unit in battle.units if unit.team == 'player' and unit.alive and unit.can_pin]
        ready = sum(not unit.acted and unit.pin_cooldown == 0 for unit in capable)
        cooling = sum(unit.pin_cooldown > 0 for unit in capable)
        hero = battle.unit(0)
        pin_hero = "Hero equipped" if hero.can_pin else "Hero needs Storm Quiver"
        brace_hero = "Hero equipped" if hero.can_brace else "Hero needs Watch Bell"
        acolytes = [unit for unit in battle.units if unit.team == 'player' and unit.alive and unit.kind == 'healer']
        healers = sum(unit.can_heal for unit in acolytes)
        context = "Current battle" if state.battle else "Next battle"
        def orders(ability):
            capable = [unit for unit in battle.units if unit.alive and unit.team == 'player'
                       and ability in unit.abilities]
            unspent = sum(not unit.acted for unit in capable)
            facts = f"{context} · {ability.title()}: {len(capable)} capable / {unspent} unspent order{'s' if unspent != 1 else ''}"
            if ability in ('smoke', 'repulse'):
                charges = sum(ability not in unit.spent_abilities for unit in capable)
                facts += f" · {charges} charge{'s' if charges != 1 else ''} left"
            if hero.alive and ability in hero.abilities:
                facts += " · Hero included"
            return facts + " · No mana"

        entries += [
            Entry("Pin", f"Range 3 · No mana · Army: {len(capable)} capable / {ready} ready · {cooling} cooling · {pin_hero}",
                   "Half damage after defense/cover (round up); forecast includes reactions. "
                   "-2 movement (minimum 1) next own turn; attacks and Guard still work. "
                   "Cannot stack or extend; skip the following turn before reuse. Avoids Brace."),
            Entry("Ranger: shoot then move", "Ordinary attack · No mana · No Pin",
                   "Shoot before moving to keep the Ranger's unused movement. Moving first gives no second move. "
                   "Pin still slows the escape; occupied hexes and normal terrain costs still apply."),
            Entry("Swap", orders('swap'),
                   "Warden or Mirror Badge hero: swap with an adjacent ally. Spend your action and both remaining moves; "
                   "preserve the ally's action, spent or unspent. May move then Swap. "
                   "Guard/Brace and Pin stay unchanged."),
            Entry("Acolyte Heal",
                   f"{context}: {healers} of {len(acolytes)} Acolytes have Heal · "
                   f"{battle.spell_cost('heal')} mana / up to {battle.spell_power['heal']} healing · Shared mana: {battle.mana}",
                   "Heal a wounded living ally within 4 hexes; spends the Acolyte's action and movement. "
                   "The hero's action is untouched; the hero need not know Heal. "
                   + (saved_healing_note if older_acolytes
                      else "Skills and relics modify the cost and healing.")),
            Entry("Brace", f"Pikemen and Watch Bell heroes · No mana · {brace_hero}",
                   "Guard spends the order. The first adjacent melee attacker takes a normal hit before striking; lethal damage cancels its attack. "
                   "One reaction, expiring next own turn. Ranged fire avoids it. Other units gain +2 defense."),
        ]
        flying = sum(unit.alive and unit.team == 'player' and unit.can_fly for unit in battle.units)
        sight = (f"{context}: terrain sight · Smoke clouds: {len(battle.smoke_clouds)}" if battle.sight_rules == 'terrain'
                 else "This older battle uses open sight · New battles use terrain sight")
        entries += [
            Entry("Rally", orders('rally'),
                   "Militia or Vanguard Drum hero clears an adjacent ally's Pin. Spends the acting unit's action and move; "
                   "never refreshes the ally's orders or clears cargo. Can be used each turn; not a battle charge."),
            Entry("Smoke", orders('smoke'),
                   "Sapper or Veil Censer hero: once per battle; spends action and move. Range 3 in sight; self-targeting works. "
                   "Blocks both sides' fire and magic, endpoints too, until your next turn even if the caster dies."),
            Entry("Repulse", orders('repulse'),
                   "Adept or Porter’s Rune hero: one charge per battle. Spends action and move. Push an adjacent foe one hex directly away without damage or retaliation. "
                   "Guard/Brace anchors it; landing must be empty and on the board."),
            Entry("After a Repulse", "Position changes · No replacement orders · No immediate objective progress",
                   "Target orders, retaliation and Pin stay unchanged. Seal progress waits for its normal checkpoint. "
                   "Clearing an exit does not Evacuate the hero; that still needs its own unspent action."),
            Entry("Flight", f"{context} · Flight: {flying} capable · Skyrider passive · No charge",
                   "Cross occupied and rough hexes; land on an empty hex. Pin still slows flight. "
                   "No extra move or free attack: melee still triggers Brace. Flight cannot carry the hero to an exit."),
            Entry("Sight", sight,
                   "Ranged attacks, Pin and spells need sight. Intervening forest blocks; endpoint forest gives cover. "
                   "Hills, marsh and units do not block. A shot along a hex edge needs either whole side clear."),
        ]
        extraction = battle.objective.kind == 'extract'
        escape_status = (battle.evacuation_blocked_reason or "Ready: the hero can Evacuate now.") if extraction else "Only extraction adventures use this order."
        deadline = (f"Round {battle.round} of {battle.objective.deadline} · {len(battle.objective.exits)} marked exits"
                    if extraction else "See each site for its deadline and exits")
        movement = (f"Hero move allowance: {hero.effective_move_range} · Cargo: {-hero.cargo_penalty} · Pin: {-2 if hero.pinned else 0}"
                    if extraction else "Full Cache cargo: -1 hero movement · Pin: -2 movement")
        entries += [
            Entry("Evacuate", escape_status,
                   "Arrival alone never wins. Hero on exit, unspent action, no adjacent living enemy: Evacuate spends action and movement. "
                   "An ally's Swap preserves the hero's action; the hero's active orders spend it."),
            Entry("Cargo and the escape clock", deadline + " · " + movement,
                   "Pin and cargo reduce movement (minimum 1), but cannot block Evacuate. Escape before the last enemy phase ends, "
                   "or rout every defender for the same reward. Hero death loses; all other survivors escape."),
        ]
        return entries
    if category == "Buildings":
        return [Entry(spec.name, f"{spec.cost} gold · {spec.crystals} crystals · "
                      f"{'Built' if kind in state.buildings else 'Not built'}", spec.description)
                for kind, spec in BUILDINGS.items()]
    if category == "Skills":
        return [Entry(spec.name, f"{spec.hero_class} only · {spec.max_rank} ranks · "
                      f"Your rank: {state.hero.skill_ranks.get(kind, 0)}", spec.description)
                for kind, spec in SKILLS.items()]
    if category == "Sites":
        def reward_text(gold, crystals, relic):
            return f"{gold} gold / {crystals} crystal{'s' if crystals != 1 else ''}" + (f" / {RELICS[relic].name}" if relic else "")

        entries = []
        for kind, spec in SITES.items():
            locations = _source_locations(p for p in state.provinces.values() if p.site_kind == kind)
            variable = spec.inherited_reward
            base = (spec.gold, spec.crystals, spec.relic)
            if variable:
                recorded = next((p for p in state.provinces.values() if p.site_kind == kind), None)
                if recorded:
                    base = (recorded.site_gold, recorded.site_crystals, recorded.site_relic)
                    base_facts = 'Recorded reward: ' + reward_text(*base)
                else:
                    base_facts = f'Reward varies by shard; no {spec.name} source is recorded here.'
            else:
                base_facts = (f"Base reward: {spec.gold} gold · {spec.crystals} "
                              f"{'crystal' if spec.crystals == 1 else 'crystals'}" +
                              (f" · {RELICS[spec.relic].name}" if spec.relic else ''))
            entries.append(Entry(spec.name, base_facts,
                                  f"{spec.description} Base guardians: " + ", ".join(
                                      f"{UNITS[kind].name} ×{count}" for kind, count in Counter(spec.guards).items())
                                  + '. ' + locations))
            for option in spec.approaches:
                attempt = state.battle_adventure
                current = (attempt is not None and state.provinces[state.battle_province].site_kind == kind
                           and attempt.approach == option.id)
                gold, crystals, relic = ((attempt.gold, attempt.crystals, attempt.relic) if current
                                         else (base[0] + option.bonus_gold, base[1], base[2]))
                fee = f"{option.gold_cost} gold" + (f" / {option.crystals_cost} crystals" if option.crystals_cost else "")
                reward = reward_text(gold, crystals, relic)
                facts = ((f"Current attempt · Paid at entry: {fee} · Saved reward: {reward}") if current
                         else f"Entry fee: {fee} · {base_facts}" if variable
                         else f"Entry fee: {fee} · Base reward: {reward}")
                definition = ENCOUNTERS[option.encounter]
                objective = (f'Evacuate by round {definition.deadline}, or rout all defenders.'
                             if definition.objective == 'extract' else
                             f'Hold the seal for {definition.hold_turns} turns by round {definition.deadline}, or rout all defenders.'
                             if definition.objective == 'hold' else
                             'Rout every defender before exhaustion after 80 rounds.')
                description = option.description + ' ' + objective
                if option.gold_cost or option.crystals_cost:
                    description += " The fee is not refunded after retreat or defeat."
                entries.append(Entry(f"{spec.name}: {option.title}", facts, description + ' ' + locations))
        entries.append(Entry("Failure, retry and finite rewards", "One site · One reward · Wounded defenders persist",
                              "A retry spends one campaign action and its chosen fee; surviving defenders keep their wounds. "
                              "Failure gives no reward or victory XP and loses up to 20 more gold. Success pays the chosen reward once and closes the site."))
        return entries
    entries = []
    for kind, spec in RELICS.items():
        equipped = state.hero.relic == kind
        facts = f"Sell when found: {spec.value} gold · " + ("Equipped" if equipped else "Owned" if kind in state.inventory else "Not owned")
        if equipped and spec.battle_ability and state.battle:
            recorded = spec.battle_ability in state.battle.unit(0).abilities
            facts += f" · Saved hero: {spec.battle_ability.title()} {'recorded' if recorded else 'not recorded'}"
        entries.append(Entry(spec.name, facts, spec.description + " " + _relic_sources(state, kind)))
    return entries

def _relic_sources(state, kind):
    return _source_locations((p for p in state.provinces.values()
                              if p.site_relic == kind and p.site), with_site=True)
