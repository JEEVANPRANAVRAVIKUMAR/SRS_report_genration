"""Pure domain logic for weather classification and remark building from docs/SPEC.md Section B7."""

from typing import Optional


def classify_sky(mean_daytime_cloud_pct: float) -> str:
    """Classify daytime mean cloud cover (06:00 to 18:00 IST).
    
    Boundaries:
    - below 20%: Sunny
    - 20% to under 50%: Partly cloudy
    - 50% to under 80%: Mostly cloudy
    - 80% or more: Overcast
    """
    if mean_daytime_cloud_pct < 20.0:
        return "Sunny"
    elif mean_daytime_cloud_pct < 50.0:
        return "Partly cloudy"
    elif mean_daytime_cloud_pct < 80.0:
        return "Mostly cloudy"
    else:
        return "Overcast"


def classify_rain(rain_24h_mm: float) -> Optional[str]:
    """Classify 24-hour rainfall according to IMD categories.
    
    Boundaries:
    - below 0.1 mm: None
    - 0.1 to 2.4 mm: Drizzle
    - 2.5 to 15.5 mm: Light rain
    - 15.6 to 64.4 mm: Moderate rain
    - 64.5 mm or more: Heavy rain
    """
    if rain_24h_mm < 0.1:
        return None
    elif rain_24h_mm <= 2.4:
        return "Drizzle"
    elif rain_24h_mm <= 15.5:
        return "Light rain"
    elif rain_24h_mm <= 64.4:
        return "Moderate rain"
    else:
        return "Heavy rain"


def build_weather_remark(
    mean_daytime_cloud_pct: float,
    rain_24h_mm: float,
    max_temp_c: float,
) -> str:
    """Build an automatic weather remark string (at most 40 characters).
    
    Rules:
    - Rain >= 2.5 mm replaces sky wording (or pairs with Overcast if overcast).
    - Format: wording, then rain amount if any, then max temperature.
    - Examples: 'Sunny, 35°C', 'Partly cloudy, 33°C', 'Overcast, rain 14 mm, 29°C'.
    """
    sky = classify_sky(mean_daytime_cloud_pct)
    rain_class = classify_rain(rain_24h_mm)
    temp_str = f"{round(max_temp_c)}°C"

    if rain_24h_mm >= 2.5:
        rain_amount_str = f"rain {round(rain_24h_mm)} mm"
        if sky == "Overcast":
            remark = f"Overcast, {rain_amount_str}, {temp_str}"
        else:
            # Rain replaces sky wording or states rain category
            remark = f"{rain_class}, {round(rain_24h_mm)} mm, {temp_str}"
    elif rain_class == "Drizzle":
        remark = f"{sky}, drizzle, {temp_str}"
    else:
        remark = f"{sky}, {temp_str}"

    # Ensure length never exceeds 40 characters
    if len(remark) > 40:
        remark = remark[:40]

    return remark


def combine_remarks(
    manual_remark: Optional[str],
    auto_remark: Optional[str],
    remark_mode: str = "both",
) -> str:
    """Combine manual and automatic remarks based on remark_mode setting."""
    manual = (manual_remark or "").strip()
    auto = (auto_remark or "").strip()

    if remark_mode == "manual_only":
        return manual
    elif remark_mode == "auto_only":
        return auto
    else:  # "both"
        if manual and auto:
            return f"{manual}. {auto}"
        return manual or auto
