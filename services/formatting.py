"""Small display helpers shared by services and Jinja templates."""
import re


def with_dr(name):
    """'Priya Nair' -> 'Dr. Priya Nair'; 'Dr. Priya Nair' stays unchanged (no 'Dr. Dr.')."""
    name = (name or "").strip()
    if not name:
        return "Dr."
    if re.match(r"^dr\.?\s", name, re.IGNORECASE):
        return name
    return f"Dr. {name}"
