import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather-mcp-server")

# ─── helpers ─────────────────────────────────────────────────────────────────

async def geocode(city: str) -> dict | None:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "en", "format": "json"},
        )
        data = r.json()
        return data["results"][0] if data.get("results") else None

WMO_CODES: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

def wmo_description(code: int) -> str:
    return WMO_CODES.get(code, f"WMO code {code}")

# ─── tool 1: current weather ─────────────────────────────────────────────────

@mcp.tool()
async def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    geo = await geocode(city)
    if not geo:
        return f'City "{city}" not found.'

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": geo["latitude"], "longitude": geo["longitude"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                           "wind_speed_10m,precipitation,rain,showers,cloud_cover,weather_code",
                "temperature_unit": "celsius", "wind_speed_unit": "kmh",
            },
        )
    c = r.json()["current"]

    return "\n".join([
        f"📍 {geo['name']}, {geo.get('admin1', '')} {geo['country']}",
        f"🌡️  Temperature: {c['temperature_2m']}°C (feels like {c['apparent_temperature']}°C)",
        f"💧 Humidity: {c['relative_humidity_2m']}%",
        f"💨 Wind: {c['wind_speed_10m']} km/h",
        f"🌧️  Precipitation: {c['precipitation']} mm",
        f"☁️  Cloud cover: {c['cloud_cover']}%",
        f"🌤️  Condition: {wmo_description(c['weather_code'])}",
    ])

# ─── tool 2: 7-day daily forecast ────────────────────────────────────────────

@mcp.tool()
async def get_forecast(city: str, days: int = 7) -> str:
    """Get the daily weather forecast for a city. days: number of days 1-7 (default 7)."""
    days = max(1, min(7, days))
    geo = await geocode(city)
    if not geo:
        return f'City "{city}" not found.'

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": geo["latitude"], "longitude": geo["longitude"],
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                         "weather_code,wind_speed_10m_max",
                "temperature_unit": "celsius", "wind_speed_unit": "kmh",
                "forecast_days": days, "timezone": "auto",
            },
        )
    d = r.json()["daily"]

    rows = [
        f"📅 {d['time'][i]}  {wmo_description(d['weather_code'][i]):<25} "
        f"🌡️ {d['temperature_2m_min'][i]}–{d['temperature_2m_max'][i]}°C  "
        f"🌧️ {d['precipitation_sum'][i]}mm  💨 {d['wind_speed_10m_max'][i]}km/h"
        for i in range(len(d["time"]))
    ]
    return "\n".join([f"📍 {days}-day forecast for {geo['name']}, {geo['country']}", *rows])

# ─── tool 3: hourly forecast ──────────────────────────────────────────────────

@mcp.tool()
async def get_hourly_forecast(city: str) -> str:
    """Get today's hour-by-hour weather forecast for a city."""
    geo = await geocode(city)
    if not geo:
        return f'City "{city}" not found.'

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": geo["latitude"], "longitude": geo["longitude"],
                "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
                "temperature_unit": "celsius", "wind_speed_unit": "kmh",
                "forecast_days": 1, "timezone": "auto",
            },
        )
    h = r.json()["hourly"]

    rows = [
        f"{h['time'][i].split('T')[1]}  {wmo_description(h['weather_code'][i]):<22} "
        f"{h['temperature_2m'][i]}°C  🌧️{h['precipitation_probability'][i]}%  "
        f"💨{h['wind_speed_10m'][i]}km/h"
        for i in range(len(h["time"]))
    ]
    return "\n".join([f"📍 Hourly forecast for {geo['name']}, {geo['country']}", *rows])

# ─── tool 4: compare cities ───────────────────────────────────────────────────

@mcp.tool()
async def compare_cities_weather(cities: list[str]) -> str:
    """Compare current weather across 2-5 cities side by side. cities: list of city names."""
    import asyncio

    async def fetch_city(city: str) -> dict:
        geo = await geocode(city)
        if not geo:
            return {"city": city, "error": "not found"}
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": geo["latitude"], "longitude": geo["longitude"],
                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                               "wind_speed_10m,weather_code",
                    "temperature_unit": "celsius", "wind_speed_unit": "kmh",
                },
            )
        c = r.json()["current"]
        return {
            "city": f"{geo['name']}, {geo['country']}",
            "temp": c["temperature_2m"], "feels_like": c["apparent_temperature"],
            "humidity": c["relative_humidity_2m"], "wind": c["wind_speed_10m"],
            "condition": wmo_description(c["weather_code"]),
        }

    results = await asyncio.gather(*[fetch_city(c) for c in cities[:5]])

    lines = []
    for r in results:
        if "error" in r:
            lines.append(f"❌ {r['city']}: not found")
        else:
            lines.append(
                f"📍 {r['city']}\n"
                f"   🌡️ {r['temp']}°C (feels {r['feels_like']}°C)  "
                f"💧{r['humidity']}%  💨{r['wind']}km/h\n"
                f"   {r['condition']}"
            )
    return "\n\n".join(lines)

# ─── tool 5: umbrella check ───────────────────────────────────────────────────

@mcp.tool()
async def should_i_bring_umbrella(city: str) -> str:
    """Check if you need an umbrella in a city today."""
    geo = await geocode(city)
    if not geo:
        return f'City "{city}" not found.'

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": geo["latitude"], "longitude": geo["longitude"],
                "hourly": "precipitation_probability,precipitation",
                "forecast_days": 1, "timezone": "auto",
            },
        )
    h = r.json()["hourly"]

    max_prob = max(h["precipitation_probability"])
    total_rain = sum(h["precipitation"])
    rainy_hours = sum(1 for p in h["precipitation_probability"] if p >= 50)

    if max_prob >= 70 or total_rain > 5:
        advice = f"🌂 Yes, definitely bring an umbrella! (max rain chance: {max_prob}%, total: {total_rain:.1f}mm)"
    elif max_prob >= 30:
        advice = f"☂️ Maybe bring one just in case. (max rain chance: {max_prob}%, {rainy_hours}h with >50% chance)"
    else:
        advice = f"☀️ No umbrella needed today! (max rain chance: only {max_prob}%)"

    return f"📍 {geo['name']}, {geo['country']}\n{advice}"

# ─── tool 6: air quality ──────────────────────────────────────────────────────

@mcp.tool()
async def get_air_quality(city: str) -> str:
    """Get current air quality index (AQI) and pollutant levels for a city."""
    geo = await geocode(city)
    if not geo:
        return f'City "{city}" not found.'

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            params={
                "latitude": geo["latitude"], "longitude": geo["longitude"],
                "current": "european_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,ozone",
            },
        )
    c = r.json()["current"]

    def aqi_label(aqi: float) -> str:
        if aqi <= 20: return "Good 🟢"
        if aqi <= 40: return "Fair 🟡"
        if aqi <= 60: return "Moderate 🟠"
        if aqi <= 80: return "Poor 🔴"
        if aqi <= 100: return "Very Poor 🟣"
        return "Extremely Poor ⚫"

    return "\n".join([
        f"📍 Air quality in {geo['name']}, {geo['country']}",
        f"🌬️  AQI (European): {c['european_aqi']} — {aqi_label(c['european_aqi'])}",
        f"   PM2.5:  {c['pm2_5']} µg/m³",
        f"   PM10:   {c['pm10']} µg/m³",
        f"   NO₂:    {c['nitrogen_dioxide']} µg/m³",
        f"   O₃:     {c['ozone']} µg/m³",
        f"   CO:     {c['carbon_monoxide']} µg/m³",
    ])

# ─── tool 7: weather alerts ───────────────────────────────────────────────────

SEVERE_CODES = {55, 65, 67, 75, 77, 82, 85, 86, 95, 96, 99}
MODERATE_CODES = {53, 63, 73, 80, 81}

@mcp.tool()
async def get_weather_alerts(city: str) -> str:
    """Get weather alerts and warnings for the next 7 days for a city."""
    geo = await geocode(city)
    if not geo:
        return f'City "{city}" not found.'

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": geo["latitude"], "longitude": geo["longitude"],
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                         "wind_speed_10m_max,precipitation_sum,precipitation_probability_max",
                "temperature_unit": "celsius", "wind_speed_unit": "kmh",
                "forecast_days": 7, "timezone": "auto",
            },
        )
    d = r.json()["daily"]

    alerts: list[dict] = []
    icons = {"WARNING": "🔴", "WATCH": "🟡", "ADVISORY": "🔵"}

    for i in range(len(d["time"])):
        date = d["time"][i]
        code = d["weather_code"][i]
        temp_max = d["temperature_2m_max"][i]
        temp_min = d["temperature_2m_min"][i]
        wind = d["wind_speed_10m_max"][i]
        precip = d["precipitation_sum"][i]
        rain_prob = d["precipitation_probability_max"][i]
        condition = wmo_description(code)

        if code in SEVERE_CODES:
            kind = "Thunderstorm" if code >= 95 else "Heavy Snow" if code >= 71 else "Heavy Rain/Storms"
            alerts.append({"date": date, "severity": "WARNING", "type": kind, "detail": f"{condition} expected."})
        elif code in MODERATE_CODES:
            alerts.append({"date": date, "severity": "WATCH", "type": "Precipitation",
                           "detail": f"{condition} expected ({rain_prob}% chance, {precip:.1f}mm)."})

        if wind >= 75:
            alerts.append({"date": date, "severity": "WARNING", "type": "High Wind",
                           "detail": f"Dangerous wind speeds up to {wind} km/h."})
        elif wind >= 50:
            alerts.append({"date": date, "severity": "WATCH", "type": "Wind",
                           "detail": f"Strong winds up to {wind} km/h."})

        if temp_max >= 40:
            alerts.append({"date": date, "severity": "WARNING", "type": "Extreme Heat",
                           "detail": f"High of {temp_max}°C — dangerous heat."})
        elif temp_max >= 35:
            alerts.append({"date": date, "severity": "ADVISORY", "type": "Heat",
                           "detail": f"High of {temp_max}°C — stay hydrated."})

        if temp_min <= -15:
            alerts.append({"date": date, "severity": "WARNING", "type": "Extreme Cold",
                           "detail": f"Low of {temp_min}°C — dangerous wind chill risk."})
        elif temp_min <= -5:
            alerts.append({"date": date, "severity": "ADVISORY", "type": "Cold",
                           "detail": f"Low of {temp_min}°C — dress in layers."})

        if precip >= 30:
            alerts.append({"date": date, "severity": "WARNING", "type": "Flooding Risk",
                           "detail": f"{precip:.1f}mm of precipitation — flooding possible."})

    if not alerts:
        return f"✅ No weather alerts for {geo['name']}, {geo['country']} in the next 7 days."

    lines = [f"⚠️  Weather alerts for {geo['name']}, {geo['country']}", ""]
    for a in alerts:
        lines.append(f"{icons[a['severity']]} [{a['severity']}] {a['date']} — {a['type']}\n   {a['detail']}")

    return "\n".join(lines)

# ─── tool 8: UV index ────────────────────────────────────────────────────────

@mcp.tool()
async def get_uv_index(city: str) -> str:
    """Get UV index forecast and sun protection advice for a city (3-day outlook)."""
    geo = await geocode(city)
    if not geo:
        return f'City "{city}" not found.'

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": geo["latitude"], "longitude": geo["longitude"],
                "daily": "uv_index_max,uv_index_clear_sky_max",
                "forecast_days": 3, "timezone": "auto",
            },
        )
    d = r.json()["daily"]

    def uv_advice(uv: float) -> str:
        if uv < 3:  return "Low 🟢 — no protection needed"
        if uv < 6:  return "Moderate 🟡 — SPF 30+, seek shade at noon"
        if uv < 8:  return "High 🟠 — SPF 50+, hat & sunglasses required"
        if uv < 11: return "Very High 🔴 — minimize midday exposure"
        return "Extreme 🟣 — avoid going outside 10am–4pm"

    lines = [f"☀️  UV Index for {geo['name']}, {geo['country']}"]
    for i in range(len(d["time"])):
        uv = d["uv_index_max"][i]
        lines.append(f"📅 {d['time'][i]}  UV Max: {uv:.1f}  — {uv_advice(uv)}")

    return "\n".join(lines)

# ─── tool 9: sunrise / sunset ─────────────────────────────────────────────────

@mcp.tool()
async def get_sunrise_sunset(city: str) -> str:
    """Get sunrise, sunset times and daylight duration for a city (7-day)."""
    geo = await geocode(city)
    if not geo:
        return f'City "{city}" not found.'

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": geo["latitude"], "longitude": geo["longitude"],
                "daily": "sunrise,sunset,daylight_duration",
                "forecast_days": 7, "timezone": "auto",
            },
        )
    d = r.json()["daily"]

    lines = [f"🌅 Sunrise & Sunset for {geo['name']}, {geo['country']}"]
    for i in range(len(d["time"])):
        sunrise = d["sunrise"][i].split("T")[1]
        sunset  = d["sunset"][i].split("T")[1]
        daylight = d["daylight_duration"][i] / 3600
        lines.append(
            f"📅 {d['time'][i]}  🌅 {sunrise}  🌇 {sunset}  ☀️ {daylight:.1f}h daylight"
        )

    return "\n".join(lines)

# ─── tool 10: historical weather ──────────────────────────────────────────────

@mcp.tool()
async def get_historical_weather(city: str, date: str) -> str:
    """Get historical weather for a city on a past date. date must be in YYYY-MM-DD format."""
    geo = await geocode(city)
    if not geo:
        return f'City "{city}" not found.'

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": geo["latitude"], "longitude": geo["longitude"],
                "start_date": date, "end_date": date,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                         "wind_speed_10m_max,weather_code",
                "temperature_unit": "celsius", "wind_speed_unit": "kmh",
                "timezone": "auto",
            },
        )
    data = r.json()

    if "error" in data:
        return f"⚠️ {data.get('reason', 'No historical data for that date.')}"

    d = data["daily"]
    if not d.get("time"):
        return f"No historical data available for {city} on {date}."

    return "\n".join([
        f"📍 Historical weather — {geo['name']}, {geo['country']} on {date}",
        f"🌡️  High: {d['temperature_2m_max'][0]}°C   Low: {d['temperature_2m_min'][0]}°C",
        f"🌧️  Precipitation: {d['precipitation_sum'][0]} mm",
        f"💨 Max wind: {d['wind_speed_10m_max'][0]} km/h",
        f"🌤️  Condition: {wmo_description(d['weather_code'][0])}",
    ])

# ─── tool 11: pollen forecast ─────────────────────────────────────────────────

@mcp.tool()
async def get_pollen_forecast(city: str) -> str:
    """Get pollen forecast for allergy sufferers. Best coverage in Europe and North America."""
    geo = await geocode(city)
    if not geo:
        return f'City "{city}" not found.'

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            params={
                "latitude": geo["latitude"], "longitude": geo["longitude"],
                "hourly": "alder_pollen,birch_pollen,grass_pollen,"
                          "mugwort_pollen,olive_pollen,ragweed_pollen",
                "forecast_days": 3, "timezone": "auto",
            },
        )
    data = r.json()

    if "error" in data:
        return f"⚠️ Pollen data not available for {geo['name']}, {geo['country']}."

    h = data.get("hourly", {})

    def pollen_level(val: float) -> str:
        if val == 0:    return "None"
        if val < 10:    return f"Low ({val:.0f} grains/m³)"
        if val < 50:    return f"Moderate ({val:.0f} grains/m³)"
        if val < 200:   return f"High ({val:.0f} grains/m³)"
        return f"Very High ({val:.0f} grains/m³)"

    pollen_types = {
        "🌳 Alder":   "alder_pollen",
        "🌲 Birch":   "birch_pollen",
        "🌿 Grass":   "grass_pollen",
        "🌾 Mugwort": "mugwort_pollen",
        "🫒 Olive":   "olive_pollen",
        "🌻 Ragweed": "ragweed_pollen",
    }

    lines = [f"🤧 Pollen forecast for {geo['name']}, {geo['country']} (today's peak)"]
    any_pollen = False
    for label, key in pollen_types.items():
        vals = [v for v in (h.get(key) or [])[:24] if v is not None]
        if not vals:
            continue
        peak = max(vals)
        if peak > 0:
            lines.append(f"   {label}: {pollen_level(peak)}")
            any_pollen = True

    if not any_pollen:
        lines.append("   ✅ No significant pollen detected today.")

    return "\n".join(lines)

# ─── tool 12: marine weather ──────────────────────────────────────────────────

@mcp.tool()
async def get_marine_weather(city: str) -> str:
    """Get marine weather — wave height, swell, and sea conditions for coastal cities."""
    geo = await geocode(city)
    if not geo:
        return f'City "{city}" not found.'

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": geo["latitude"], "longitude": geo["longitude"],
                "current": "wave_height,wave_direction,wave_period,"
                           "wind_wave_height,swell_wave_height,swell_wave_period",
                "daily": "wave_height_max,wind_wave_height_max,swell_wave_height_max",
                "forecast_days": 3, "timezone": "auto",
            },
        )
    data = r.json()

    if "error" in data:
        return (f"⚠️ Marine data unavailable for {geo['name']}, {geo['country']}. "
                f"Try a coastal city (e.g. Sydney, Miami, Lisbon).")

    c = data.get("current", {})
    d = data.get("daily", {})

    def sea_state(h: float) -> str:
        if h < 0.1:  return "Glassy"
        if h < 0.5:  return "Calm"
        if h < 1.25: return "Slight"
        if h < 2.5:  return "Moderate"
        if h < 4.0:  return "Rough"
        if h < 6.0:  return "Very Rough"
        return "High / Dangerous ⚠️"

    def compass(deg: float) -> str:
        dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        return dirs[round(deg / 45) % 8]

    wh = c.get("wave_height", 0) or 0
    lines = [
        f"⛵ Marine weather for {geo['name']}, {geo['country']}",
        f"🌊 Wave height:  {wh}m — {sea_state(wh)}",
        f"   Direction:   {compass(c.get('wave_direction', 0))} ({c.get('wave_direction', 'N/A')}°)",
        f"   Period:      {c.get('wave_period', 'N/A')}s",
        f"🌬️  Wind waves:  {c.get('wind_wave_height', 'N/A')}m",
        f"🌀 Swell height: {c.get('swell_wave_height', 'N/A')}m  "
        f"({c.get('swell_wave_period', 'N/A')}s period)",
    ]

    if d.get("time"):
        lines.append("\n📅 3-day wave forecast:")
        for i in range(len(d["time"])):
            lines.append(
                f"   {d['time'][i]}  "
                f"Max: {d['wave_height_max'][i]}m  "
                f"Wind: {d['wind_wave_height_max'][i]}m  "
                f"Swell: {d['swell_wave_height_max'][i]}m"
            )

    return "\n".join(lines)

# ─── run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
