"""Feste Liste der angemeldeten Module; die Reihenfolge ist die der Navigation."""

from moarcoal.modules.work import REGISTRATION as WORK
from moarcoal.registration import ModuleRegistration, ModuleState

MODULES: tuple[ModuleRegistration, ...] = (WORK,)

__all__ = ["MODULES", "ModuleRegistration", "ModuleState"]
