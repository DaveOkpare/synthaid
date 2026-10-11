"""A made-up weather tool for the TOML weather example."""

from typing import Any

from synthaid import tool

_FORECASTS = {
    "lagos": {"today": "31°C, humid, clear", "tomorrow": "28°C, heavy rain"},
    "abuja": {"today": "33°C, dry, sunny", "tomorrow": "32°C, sunny"},
}


def get_weather(city: str, day: str = "today") -> dict[str, Any]:
    """Returns made-up weather for `city` on `day` ("today" or "tomorrow")."""
    forecast = _FORECASTS.get(city.lower())
    if forecast is None:
        return {"city": city, "error": "No forecast for this city."}
    return {"city": city, "day": day, "forecast": forecast[day]}


WEATHER = tool.Tool(
    name="get_weather",
    description="Gets the weather forecast for a city, today or tomorrow.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "The city name."},
            "day": {"type": "string", "enum": ["today", "tomorrow"]},
        },
        "required": ["city"],
    },
    function=get_weather,
)
