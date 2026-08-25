"""Slurm dispatcher for queued annotation jobs."""

from dispatcher.loop import DispatcherConfig, dispatch_once, plan_launches

__all__ = ["DispatcherConfig", "dispatch_once", "plan_launches"]
