"""Read-only terminal navigation and interactive input for persisted inspection."""

from typing import TextIO

from agentinstruct.inspection import VIEWS, Inspector, terminal_text


class InspectionSession:
    """Small read-only navigation model; commands change only this session's view."""

    HELP = (
        "Commands: run, trace N (1-based), next, previous, summary, conversation, "
        "participant ID, tools, reviews, verification, provenance, failures, "
        "artifacts, reasoning, "
        "page N, more, back, help, quit. Views are operator-wide except participant ID."
    )

    def __init__(self, inspector: Inspector, *, page_size: int = 40) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.inspector = inspector
        self.trace_index: int | None = None if inspector.run is not None else 0
        self.view = "summary"
        self.participant: str | None = None
        self.page = 0
        self.page_size = page_size
        self.closed = False

    def render(self) -> str:
        text = self.inspector.render(
            self.view, trace_index=self.trace_index, participant=self.participant
        )
        lines = text.splitlines()
        pages = max(1, (len(lines) + self.page_size - 1) // self.page_size)
        self.page = min(self.page, pages - 1)
        start = self.page * self.page_size
        return (
            "\n".join(lines[start : start + self.page_size])
            + f"\n[page {self.page + 1}/{pages}]"
        )

    def execute(self, command: str) -> str:
        parts = command.strip().split()
        if not parts:
            return self.render()
        verb, *arguments = parts
        try:
            if verb == "quit" and not arguments:
                self.closed = True
                return "Inspection closed."
            if verb == "help" and not arguments:
                return self.HELP
            if verb in {"more", "back", "page"}:
                if verb == "page" and len(arguments) == 1:
                    self.page = max(0, int(arguments[0]) - 1)
                elif verb in {"more", "back"} and not arguments:
                    self.page = max(0, self.page + (1 if verb == "more" else -1))
                else:
                    raise ValueError("Use page N, more or back")
                return self.render()
            if verb == "run" and not arguments and self.inspector.run is not None:
                self.trace_index, self.view = None, "summary"
            elif verb == "summary" and not arguments:
                self.view = "summary"
            elif verb == "trace" and len(arguments) == 1:
                index = int(arguments[0]) - 1
                if not 0 <= index < len(self.inspector.traces):
                    raise ValueError("Trace number is out of range")
                self.trace_index, self.view = index, "summary"
            elif verb in {"next", "previous"} and not arguments:
                index = (-1 if self.trace_index is None else self.trace_index) + (
                    1 if verb == "next" else -1
                )
                if not 0 <= index < len(self.inspector.traces):
                    raise ValueError("No further Trace in that direction")
                self.trace_index, self.view = index, "summary"
            elif verb in VIEWS and (
                len(arguments) == 1 if verb == "participant" else not arguments
            ):
                participant = arguments[0] if verb == "participant" else None
                self.inspector.view(
                    verb, trace_index=self.trace_index or 0, participant=participant
                )
                self.trace_index, self.view, self.participant = (
                    self.trace_index or 0,
                    verb,
                    participant,
                )
            else:
                raise ValueError("Unknown command; type help for navigation")
            self.page = 0
            return self.render()
        except (ValueError, IndexError) as exc:
            return terminal_text(f"{exc}")


def run_terminal(
    inspector: Inspector,
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    trace_index: int | None = None,
    view: str = "summary",
    participant: str | None = None,
) -> None:
    """Run the line-oriented terminal UI; EOF and Ctrl-C close it without effects."""
    session = InspectionSession(inspector)
    session.trace_index, session.view, session.participant = (
        0 if trace_index is None and view != "summary" else trace_index,
        view,
        participant,
    )
    print(session.HELP, file=output_stream)
    print(session.render(), file=output_stream)
    while not session.closed:
        print("inspect> ", end="", file=output_stream, flush=True)
        try:
            command = input_stream.readline()
        except KeyboardInterrupt:
            break
        if not command:
            break
        print(session.execute(command), file=output_stream)
