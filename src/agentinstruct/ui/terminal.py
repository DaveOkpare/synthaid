"""Read-only terminal navigation for recorded Episode inspection."""

from typing import TextIO

from agentinstruct.inspection import VIEWS, Inspector, terminal_text


class InspectionSession:
    HELP = (
        "Commands: run, trace N (1-based), next, previous, summary, conversation, "
        "participant ID, tools, reviews, verification, provenance, failures, "
        "artifacts, reasoning, page N, more, back, help, quit. "
        "Views are operator-wide except participant ID."
    )

    def __init__(self, inspector: Inspector, *, page_size: int = 40) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.inspector = inspector
        self.trace_index: int | None = None if inspector.run is not None else 0
        self.view = "summary"
        self.participant: str | None = None
        self.page, self.page_size, self.closed = 0, page_size, False

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
            if verb == "help" and not arguments:
                return self.HELP
            if verb == "quit" and not arguments:
                self.closed = True
                return "Inspection closed."
            if verb in {"more", "back", "page"}:
                self._paginate(verb, arguments)
            else:
                self._navigate(verb, arguments)
                self.page = 0
            return self.render()
        except (ValueError, IndexError) as exc:
            return terminal_text(str(exc))

    def _paginate(self, verb: str, arguments: list[str]) -> None:
        if verb == "page" and len(arguments) == 1:
            self.page = max(0, int(arguments[0]) - 1)
        elif verb in {"more", "back"} and not arguments:
            self.page = max(0, self.page + (1 if verb == "more" else -1))
        else:
            raise ValueError("Use page N, more or back")

    def _navigate(self, verb: str, arguments: list[str]) -> None:
        if verb == "run" and not arguments and self.inspector.run is not None:
            self.trace_index, self.view = None, "summary"
        elif verb == "trace" and len(arguments) == 1:
            self._select_trace(int(arguments[0]) - 1)
        elif verb in {"next", "previous"} and not arguments:
            index = -1 if self.trace_index is None else self.trace_index
            self._select_trace(index + (1 if verb == "next" else -1))
        elif verb in VIEWS and (
            len(arguments) == 1 if verb == "participant" else not arguments
        ):
            self._select_view(verb, arguments[0] if arguments else None)
        else:
            raise ValueError("Unknown command; type help for navigation")

    def _select_trace(self, index: int) -> None:
        if not 0 <= index < len(self.inspector.traces):
            raise ValueError("Trace number is out of range")
        self.trace_index, self.view, self.participant = index, "summary", None

    def _select_view(self, view: str, participant: str | None) -> None:
        self.inspector.view(
            view, trace_index=self.trace_index or 0, participant=participant
        )
        self.trace_index, self.view = self.trace_index or 0, view
        self.participant = participant


def run_terminal(
    inspector: Inspector,
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    trace_index: int | None = None,
    view: str = "summary",
    participant: str | None = None,
) -> None:
    session = InspectionSession(inspector)
    session.trace_index = (
        0 if trace_index is None and view != "summary" else trace_index
    )
    session.view, session.participant = view, participant
    print(session.HELP, file=output_stream)
    print(session.render(), file=output_stream)
    _read_commands(session, input_stream, output_stream)


def _read_commands(session: InspectionSession, source: TextIO, output: TextIO) -> None:
    while not session.closed:
        print("inspect> ", end="", file=output, flush=True)
        try:
            command = source.readline()
        except KeyboardInterrupt:
            break
        if not command:
            break
        print(session.execute(command), file=output)
