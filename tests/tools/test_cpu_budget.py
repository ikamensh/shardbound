"""The fuzz and linked-campaign tools yield CPU without changing their deterministic work."""
import pytest

from saga2d.testing.cpu_budget import CpuBudget


class Clock:
    def __init__(self):
        self.wall = self.cpu = 0.0
        self.sleeps = []

    def work(self, seconds):
        self.cpu += seconds
        self.wall += seconds

    def sleep(self, seconds):
        assert seconds > 0
        self.sleeps.append(seconds)
        self.wall += seconds


def yields_without_changing_results(monkeypatch, run):
    """``run(budget)`` must give the same result at 25% as at 100% and sleep along the way."""
    expected = run(CpuBudget(100))
    clock = Clock()

    def process_time():
        clock.work(.02)  # Controlled CPU-work samples, independent of machine speed.
        return clock.cpu

    monkeypatch.setattr('saga2d.testing.cpu_budget.time.process_time', process_time)
    monkeypatch.setattr('saga2d.testing.cpu_budget.time.monotonic', lambda: clock.wall)
    monkeypatch.setattr('saga2d.testing.cpu_budget.time.sleep', clock.sleep)
    assert run(CpuBudget(25)) == expected
    assert clock.sleeps, 'The tool completed a run without honoring its CPU allowance'


@pytest.mark.parametrize('scenario', ['shardbound', 'linked_setup', 'shard_scene'])
def test_fuzzer_work_yields_inside_runs_without_changing_reproducible_results(monkeypatch, scenario):
    """Every model/scene loop, including the linked setup policy, checks its shared CPU allowance."""
    from collections import Counter
    from tools import fuzz

    def run(budget):
        metrics = Counter()
        if scenario == 'linked_setup':
            from eador.model import State
            from tools.linked_campaign import play_stage
            return play_stage(State.new_campaign(1), budget=budget).to_json()
        elif scenario == 'shardbound':
            fuzz.campaign_run(1, 2, metrics, budget=budget)
        else:
            fuzz.scene_run(0, 1, metrics, budget=budget)
        return metrics

    yields_without_changing_results(monkeypatch, run)
