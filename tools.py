"""Standard tools available to SAGE.

These tools are intentionally provider-light: time uses the server's standard
library, weather uses Open-Meteo, search uses DuckDuckGo, and calculations use
Python's AST instead of eval().
"""

from __future__ import annotations

import ast
import datetime as dt
import html
import html.parser
import math
import operator
import re
from typing import Any
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_datetime",
            "description": "Get the exact current local date and time. Use this for questions about today, the current date, the current time, now, or time in a location. timezone should be an IANA timezone such as Asia/Dhaka or America/New_York.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {"type": "string", "description": "IANA timezone name. Use the user's timezone when no location is specified."}
                },
                "required": ["timezone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the public web and read the returned webpages for current or factual information. Use this for current events, news, recent facts, or when verification is needed. Do not treat search-result titles alone as the answer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The web search query."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Calculate arithmetic expressions accurately. Supports +, -, *, /, %, **, parentheses and common math functions such as sqrt, sin, cos, tan, log, log10, exp, floor, ceil, abs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "A mathematical expression to calculate."}
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather and today's forecast for a location. Use this when the user asks about weather, temperature, rain, wind, or forecast.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City, town, or place name."}
                },
                "required": ["location"],
            },
        },
    },
]


def _safe_calculate(expression: str) -> float | int:
    expression = expression.strip()
    if len(expression) > 300:
        raise ValueError("Expression is too long")

    allowed_binary = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.FloorDiv: operator.floordiv,
    }
    allowed_unary = {ast.UAdd: operator.pos, ast.USub: operator.neg}
    functions = {
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "log": math.log, "log10": math.log10, "exp": math.exp,
        "floor": math.floor, "ceil": math.ceil, "abs": abs,
    }
    constants = {"pi": math.pi, "e": math.e, "tau": math.tau}

    def evaluate(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Name) and node.id in constants:
            return constants[node.id]
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_unary:
            return allowed_unary[type(node.op)](evaluate(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_binary:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("Exponent is too large")
            return allowed_binary[type(node.op)](left, right)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions and not node.keywords:
            args = [evaluate(a) for a in node.args]
            return functions[node.func.id](*args)
        raise ValueError("Unsupported expression")

    tree = ast.parse(expression, mode="eval")
    result = evaluate(tree)
    if isinstance(result, float) and (math.isnan(result) or math.isinf(result)):
        raise ValueError("Result is not finite")
    return result


def get_current_datetime(timezone: str) -> dict[str, Any]:
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise ValueError(f"Unknown IANA timezone: {timezone}")
    now = dt.datetime.now(tz)
    return {
        "timezone": timezone,
        "date": now.strftime("%A, %B %-d, %Y"),
        "time": now.strftime("%-I:%M %p"),
        "iso": now.isoformat(),
        "utc_offset": now.strftime("UTC%z"),
    }


class _SearchParser:
    """Extract search-result links from DuckDuckGo HTML."""
    def __init__(self):
        self.results = []

    def feed(self, page: str):
        for match in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            page, flags=re.I | re.S,
        ):
            url, title = match.groups()
            title = html.unescape(re.sub(r"<[^>]+>", " ", title))
            title = re.sub(r"\s+", " ", title).strip()
            if url.startswith("//"):
                url = "https:" + url
            if url.startswith("http"):
                self.results.append({"title": title, "url": url})
            if len(self.results) >= 8:
                break


class _PageTextParser(html.parser.HTMLParser):
    """Small dependency-free HTML-to-text extractor for search result pages."""
    BLOCK_TAGS = {
        "p", "div", "article", "section", "main", "li", "h1", "h2", "h3",
        "h4", "h5", "h6", "br", "tr", "blockquote"
    }
    SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
        elif self.skip_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif self.skip_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth == 0:
            text = html.unescape(data).strip()
            if text:
                self.parts.append(text)

    def text(self):
        text = " ".join(self.parts)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


def _extract_page_text(url: str) -> str:
    """Fetch and extract readable text from a result page."""
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SAGE/1.0)"},
            timeout=12,
            allow_redirects=True,
        )
        r.raise_for_status()
        content_type = r.headers.get("content-type", "").lower()
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return ""
        parser = _PageTextParser()
        parser.feed(r.text[:2_000_000])
        text = parser.text()
        # Avoid feeding giant pages into the LLM. Keep enough context to answer questions.
        return text[:7000]
    except Exception:
        return ""


def web_search(query: str) -> dict[str, Any]:
    """Search the web and return both results and readable page content."""
    query = query.strip()
    if not query:
        raise ValueError("Search query is empty")

    response = requests.get(
        "https://html.duckduckgo.com/html/?q=" + quote_plus(query),
        headers={"User-Agent": "Mozilla/5.0 (compatible; SAGE/1.0)"},
        timeout=12,
    )
    response.raise_for_status()
    parser = _SearchParser()
    parser.feed(response.text)

    results = []
    for result in parser.results[:5]:
        content = _extract_page_text(result["url"])
        results.append({
            "title": result["title"],
            "url": result["url"],
            "content": content,
        })

    return {
        "query": query,
        "results": results,
        "instruction": "Use the page content when present. Cite the source title/URL in the answer when useful. Do not claim information that is not supported by the returned content.",
    }


_WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog", 51: "light drizzle", 53: "moderate drizzle",
    55: "dense drizzle", 61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow", 80: "slight rain showers",
    81: "moderate rain showers", 82: "violent rain showers", 95: "thunderstorm",
    96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}


def get_weather(location: str) -> dict[str, Any]:
    location = location.strip()
    if not location:
        raise ValueError("Location is empty")

    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": location, "count": 1, "language": "en", "format": "json"},
        timeout=10,
    )
    geo.raise_for_status()
    places = geo.json().get("results") or []
    if not places:
        raise ValueError(f"Could not find weather location: {location}")
    place = places[0]

    weather = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": place["latitude"], "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "timezone": "auto", "forecast_days": 1,
        },
        timeout=10,
    )
    weather.raise_for_status()
    data = weather.json()
    current = data.get("current", {})
    daily = data.get("daily", {})
    code = current.get("weather_code")
    daily_code = (daily.get("weather_code") or [code])[0]

    return {
        "location": ", ".join(filter(None, [place.get("name"), place.get("admin1"), place.get("country")])),
        "timezone": data.get("timezone"),
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "humidity_percent": current.get("relative_humidity_2m"),
        "wind_kmh": current.get("wind_speed_10m"),
        "conditions": _WEATHER_CODES.get(code, f"weather code {code}"),
        "today_high_c": (daily.get("temperature_2m_max") or [None])[0],
        "today_low_c": (daily.get("temperature_2m_min") or [None])[0],
        "rain_probability_percent": (daily.get("precipitation_probability_max") or [None])[0],
        "forecast_conditions": _WEATHER_CODES.get(daily_code, f"weather code {daily_code}"),
    }


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "get_current_datetime":
        return get_current_datetime(arguments["timezone"])
    if name == "web_search":
        return web_search(arguments["query"])
    if name == "calculator":
        result = _safe_calculate(arguments["expression"])
        return {"expression": arguments["expression"], "result": result}
    if name == "get_weather":
        return get_weather(arguments["location"])
    raise ValueError(f"Unknown tool: {name}")
