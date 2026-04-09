"""Nexus Energy — power management, battery modeling, budget allocation.

Battery simulation, power source management (solar, recharge, fuel cell),
power budget allocation, and energy-aware task scheduling.
"""
import math, random, time
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from enum import Enum


class PowerSource(Enum):
    BATTERY = "battery"
    SOLAR = "solar"
    FUEL_CELL = "fuel_cell"
    THERMOELECTRIC = "thermoelectric"
    TETHERED = "tethered"


@dataclass
class BatteryModel:
    capacity_wh: float = 100.0     # Watt-hours
    current_charge: float = 100.0  # Current charge (Wh)
    voltage_nominal: float = 14.8  # Volts
    voltage_min: float = 12.0
    charge_efficiency: float = 0.92
    discharge_efficiency: float = 0.95
    temp_coefficient: float = -0.005  # capacity loss per degree above 25C
    cycle_count: int = 0
    max_cycles: int = 500

    @property
    def soc(self) -> float:
        return (self.current_charge / self.capacity_wh * 100) if self.capacity_wh > 0 else 0

    @property
    def health(self) -> float:
        degradation = self.cycle_count / self.max_cycles if self.max_cycles > 0 else 0
        return max(0, 1.0 - degradation * 0.3)

    def discharge(self, watts: float, seconds: float, temp_c: float = 25) -> float:
        actual_watts = watts / self.discharge_efficiency
        temp_factor = 1.0 + self.temp_coefficient * max(0, temp_c - 25)
        energy = actual_watts * seconds / 3600 * temp_factor
        energy = min(energy, self.current_charge)
        self.current_charge -= energy
        return energy

    def charge(self, watts: float, seconds: float) -> float:
        energy = watts * seconds / 3600 * self.charge_efficiency
        space = self.capacity_wh * self.health - self.current_charge
        energy = min(energy, max(0, space))
        self.current_charge += energy
        return energy


@dataclass
class PowerSourceConfig:
    source_type: PowerSource
    max_output_w: float
    efficiency: float = 1.0
    available: bool = True
    # Solar-specific
    panel_area_m2: float = 0
    efficiency_solar: float = 0
    # Fuel cell specific
    fuel_capacity_wh: float = 0
    fuel_remaining_wh: float = 0


class PowerBudget:
    """Allocate power budget across subsystems."""

    def __init__(self, total_budget_w: float):
        self.total_budget_w = total_budget_w
        self.allocations: Dict[str, float] = {}
        self.priorities: Dict[str, int] = {}

    def allocate(self, subsystem: str, watts: float, priority: int = 1) -> bool:
        current_total = sum(self.allocations.values())
        if current_total + watts > self.total_budget_w:
            # Try to steal from lower-priority subsystems
            for name in sorted(self.priorities, key=lambda n: self.priorities[n]):
                if self.priorities[name] < priority and self.allocations.get(name, 0) > 0:
                    steal = min(self.allocations[name], watts - (self.total_budget_w - current_total))
                    if steal > 0:
                        self.allocations[name] -= steal
                        current_total -= steal
                        if current_total + watts <= self.total_budget_w:
                            break
            if current_total + watts > self.total_budget_w:
                return False
        self.allocations[subsystem] = watts
        self.priorities[subsystem] = priority
        return True

    def reallocate(self, remaining_wh: float, time_remaining_s: float) -> Dict[str, float]:
        max_draw = remaining_wh * 3600 / time_remaining_s if time_remaining_s > 0 else 0
        available = min(self.total_budget_w, max_draw)
        total_requested = sum(self.allocations.values())
        if total_requested <= available:
            return dict(self.allocations)
        ratio = available / total_requested
        return {k: v * ratio for k, v in sorted(self.allocations.items(),
                key=lambda x: -self.priorities.get(x[0], 0))}


class SolarModel:
    """Simple solar power generation model."""

    def __init__(self, panel_area_m2: float, efficiency: float = 0.22):
        self.panel_area = panel_area_m2
        self.efficiency = efficiency

    def irradiance_w_m2(self, hour: float, cloud_cover: float = 0) -> float:
        """Approximate solar irradiance based on hour (0-24)."""
        if hour < 6 or hour > 18:
            return 0
        peak = 1000 * (1 - cloud_cover)
        solar_elevation = math.sin(math.pi * (hour - 6) / 12)
        return peak * solar_elevation

    def power_output(self, hour: float, cloud_cover: float = 0) -> float:
        return self.irradiance_w_m2(hour, cloud_cover) * self.panel_area * self.efficiency

    def daily_energy_wh(self, cloud_cover: float = 0) -> float:
        total = 0
        for h_10 in range(60, 181, 1):
            hour = h_10 / 10
            total += self.power_output(hour, cloud_cover) * 0.1  # 6-min intervals
        return total


def demo():
    print("=== Energy Management ===\n")
    random.seed(42)

    # Battery simulation
    battery = BatteryModel(capacity_wh=200, current_charge=180)
    print("--- Battery Simulation ---")
    print(f"  SOC: {battery.soc:.1f}%, Health: {battery.health:.1%}")

    for t in range(0, 60, 10):
        consumed = battery.discharge(15, 600)  # 15W for 10min
        print(f"  t={t}min: consumed={consumed:.2f}Wh, SOC={battery.soc:.1f}%")

    # Solar model
    solar = SolarModel(panel_area_m2=0.5, efficiency=0.22)
    print(f"\n--- Solar Generation (0.5m2, 22% eff) ---")
    for hour in [6, 8, 10, 12, 14, 16, 18]:
        power = solar.power_output(hour)
        print(f"  {hour:02d}:00 — {power:.1f}W")
    print(f"  Daily total: {solar.daily_energy_wh():.1f}Wh (clear)")
    print(f"  Daily total: {solar.daily_energy_wh(0.5):.1f}Wh (50% cloud)")

    # Power budget
    print("\n--- Power Budget ---")
    budget = PowerBudget(total_budget_w=30)
    budget.allocate("navigation", 5, priority=5)
    budget.allocate("sensors", 8, priority=4)
    budget.allocate("comms", 3, priority=3)
    budget.allocate("compute", 10, priority=2)
    budget.allocate("payload", 4, priority=1)
    print(f"  Allocated: {sum(budget.allocations.values()):.0f}W / {budget.total_budget_w}W budget")
    print(f"  Subsystems: {dict(budget.allocations)}")

    # Reallocate with low battery
    print("\n  Low battery reallocation (10Wh remaining, 2hr):")
    reallocated = budget.reallocate(10, 7200)
    for name, watts in reallocated.items():
        priority = budget.priorities.get(name, 0)
        print(f"    {name:12s}: {watts:.1f}W (priority {priority})")


if __name__ == "__main__":
    demo()
