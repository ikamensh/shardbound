# Text play

`shardbound-text` plays the real rules without the GUI, so an agent can play a
whole campaign and report on balance and pacing. It is `eador/textplay.py`: a
`Session` runs command lines against a `State`, and `main` loads and saves a
JSON save around it.

```bash
uv run shardbound-text -g /tmp/run/game.json 'new 7 Commander challenge'
uv run shardbound-text -g /tmp/run/game.json 'help; help rules'
uv run shardbound-text -g /tmp/run/game.json 'build barracks; recruit swordsman; explore'
```

Without `-g`, the save is `$SHARDBOUND_GAME` or `./shardbound-game.json`. Every
command and its output is appended to `SAVE.log`, and `note TEXT` writes the
player's reasoning into it, so the transcript is the playtest record.

## Design

- **Orders report what they changed.** Battle orders print the traced events
  (moves, hits with HP before and after, retaliations, the enemy phase).
  Campaign orders print the new log lines and the changes to gold, crystals,
  actions, hero, army, owners and the rival's plan. A battle that starts or
  finishes is shown or settled in the same output. A `[status]` line ends
  each run of orders, so the player rarely needs to look again.
- **Chains.** `'move 3 0,1; attack 3 1004; end'` runs in order. The first
  error stops the chain and names the skipped commands. `attack ID T from Q,R`
  checks the whole order before it moves, so a refused attack moves nothing.
  A refusal names its cause where the rules' message is generic: what
  occupies a hex, which hexes an out-of-range target can be struck from,
  why a spell target is illegal.
- **Observations show what the GUI shows.** `look` is the overview (campaign,
  battle or transition), `map` lists provinces with their neighbours,
  `inspect` gives a province's briefing, `plan` the campaign plan (what
  travels to the next shard), `rival` the rival panel, `camp` the
  build and recruit catalogues with the rules' own refusal reasons, and
  `codex` the field codex (`eador/reference.py`, shared with the codex scene).
- **Forecasts are the rules' own.** `unit ID` lists reachable hexes and the
  exact deal/take of an attack from each one. The GUI shows these one hovered
  hex at a time; for an enemy unit, it lists whom it could hit. There is no
  undo and no save slot, as in a committed human run.

## A blind playtest

Give the agent only the command line, not the repository, or it will read the
AI and rules instead of playing. The prompt that ran the first playtest:

> You are playtesting Shardbound through its text interface. Do not read any
> source or docs. The only command you run is `<path>/shardbound-text -g
> <dir>/game.json 'COMMANDS'`. Start with `help` and `help rules`, then `new 7
> Commander challenge`. Play to win; `auto` is allowed for routine battles.
> Use `note` for rationale and moments that felt interesting, boring, unclear
> or unfair. Report on the interface (friction, missing information) and on
> the game (decisions, difficulty, dominant strategies, fun or tedium).

An LLM reads every number and never tires, so its difficulty reports describe
a careful expert. It cannot judge presentation, feel or first-run
comprehension, and it does not count toward G09's human playtests.
