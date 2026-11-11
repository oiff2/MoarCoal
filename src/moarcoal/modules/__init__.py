"""Feste Liste der angemeldeten Module; die Reihenfolge ist die der Navigation."""

from moarcoal.modules.tax_year import REGISTRATION as TAX_YEAR
from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.registration import ModuleRegistration, ModuleState

MODULES: tuple[ModuleRegistration, ...] = (WORK, TAX_YEAR)

__all__ = ["MODULES", "ModuleRegistration", "ModuleState"]
