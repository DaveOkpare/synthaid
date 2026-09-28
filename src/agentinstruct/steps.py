"""Internal ordered Task Step state and framework-owned control Tool declarations."""

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from uuid import uuid4

from agentinstruct.plans import FrozenJsonValue, JsonValue, StepPlan, ToolPlan
from agentinstruct.store import TraceRecorder, timestamp
from agentinstruct.traces import Event

CONTROL_TOOLS = MappingProxyType(
    {
        "advance_step": ToolPlan(
            "advance_step",
            "Advance to the immediately following Task Step after finishing this step.",
            {
                "type": "object",
                "properties": {"step_id": {"type": "string"}},
                "required": ("step_id",),
                "additionalProperties": False,
            },
        ),
        "complete_task": ToolPlan(
            "complete_task",
            "Complete the Task in its final step, then provide your final reply.",
            {"type": "object", "properties": {}, "additionalProperties": False},
        ),
    }
)


class StepProgress:
    """Shared by Interactions; never exposed to extension components."""

    def __init__(self, steps: tuple[StepPlan, ...], recorder: TraceRecorder) -> None:
        self.steps = steps
        self._recorder = recorder
        self._index = 0
        self.completed = False

    @property
    def active(self) -> StepPlan | None:
        return self.steps[self._index] if self.steps else None

    @property
    def step_id(self) -> str | None:
        active = self.active
        return active.id if active else None

    @property
    def available_controls(self) -> tuple[ToolPlan, ...]:
        if not self.steps or self.completed:
            return ()
        if self._index == len(self.steps) - 1:
            return (CONTROL_TOOLS["complete_task"],)
        return (
            replace(
                CONTROL_TOOLS["advance_step"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "step_id": {"const": self.steps[self._index + 1].id}
                    },
                    "required": ("step_id",),
                    "additionalProperties": False,
                },
            ),
        )

    def start(self) -> None:
        if self.steps:
            self._recorder.event(
                Event(uuid4().hex, "step_started", timestamp(), step_id=self.step_id)
            )

    def apply(
        self,
        name: str,
        arguments: Mapping[str, FrozenJsonValue],
        *,
        actor_id: str,
        turn_id: str,
        message_id: str,
    ) -> JsonValue:
        if not self.steps or self.completed:
            raise ValueError("Task Step control is unavailable after completion")
        if name == "advance_step":
            next_index = self._index + 1
            if (
                next_index >= len(self.steps)
                or arguments["step_id"] != self.steps[next_index].id
            ):
                raise ValueError(
                    "advance_step must name the immediately following Task Step"
                )
            next_step = self.steps[next_index]
            self._recorder.event(
                Event(
                    uuid4().hex,
                    "step_started",
                    timestamp(),
                    {"previous_step_id": self.step_id, "message_id": message_id},
                    actor_id,
                    turn_id,
                    next_step.id,
                )
            )
            self._index = next_index
        elif name == "complete_task":
            if self._index != len(self.steps) - 1:
                raise ValueError("Only the final Task Step can complete the Task")
            self._recorder.event(
                Event(
                    uuid4().hex,
                    "task_completed",
                    timestamp(),
                    {"message_id": message_id},
                    actor_id,
                    turn_id,
                    self.step_id,
                )
            )
            self.completed = True
        else:
            raise ValueError("Unknown Task Step control")
        return {"step_id": self.step_id, "completed": self.completed}
