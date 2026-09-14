"""Validated contracts shared by discovery, replay, and human intervention."""

from computer_use.schemas.action import Action, Target, action_adapter, target_adapter
from computer_use.schemas.capability import Capability, TargetIdentity
from computer_use.schemas.intervention import ControlSnapshot, ControlTransition, Intervention
from computer_use.schemas.observation import Observation
from computer_use.schemas.result import ExecutionResult, result_adapter

__all__ = [
    "Action",
    "Target",
    "Capability",
    "TargetIdentity",
    "ControlSnapshot",
    "ControlTransition",
    "Intervention",
    "Observation",
    "ExecutionResult",
    "action_adapter",
    "target_adapter",
    "result_adapter",
]
