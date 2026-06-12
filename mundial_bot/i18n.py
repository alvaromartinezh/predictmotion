"""Traducción ES-ES de nombres de equipo y descripciones de jugada de ESPN.

Sin IA: diccionario + reglas. Ampliable sin tocar la lógica:
  - Añadir un equipo  → una línea en TEAMS.
  - Añadir un término → una entrada en _MANNER / _LOCATION.

Funciones públicas:
  translate_team(name)   -> nombre en español (o el original si no está)
  parse_scorer(text)     -> nombre del goleador extraído del relato ESPN
  translate_play(text)   -> descripción corta en español ("" si no se reconoce)
"""

from __future__ import annotations
import re

# ── Selecciones (English ESPN → Español de España) ─────────────────────────────
# Las 48 del Mundial 2026 + variantes que ESPN suele devolver (USA, Korea Republic…)
# y un colchón de selecciones habituales para que nunca quede inglés colado.
TEAMS: dict[str, str] = {
    # Anfitriones / CONCACAF
    "Mexico": "México", "Canada": "Canadá", "United States": "Estados Unidos",
    "USA": "Estados Unidos", "Costa Rica": "Costa Rica", "Panama": "Panamá",
    "Honduras": "Honduras", "Jamaica": "Jamaica", "El Salvador": "El Salvador",
    "Guatemala": "Guatemala", "Haiti": "Haití", "Curacao": "Curazao",
    "Curaçao": "Curazao", "Trinidad and Tobago": "Trinidad y Tobago",
    # CONMEBOL
    "Brazil": "Brasil", "Argentina": "Argentina", "Uruguay": "Uruguay",
    "Colombia": "Colombia", "Ecuador": "Ecuador", "Peru": "Perú", "Chile": "Chile",
    "Paraguay": "Paraguay", "Venezuela": "Venezuela", "Bolivia": "Bolivia",
    # UEFA
    "Spain": "España", "France": "Francia", "Germany": "Alemania",
    "England": "Inglaterra", "Portugal": "Portugal", "Italy": "Italia",
    "Netherlands": "Países Bajos", "Belgium": "Bélgica", "Croatia": "Croacia",
    "Switzerland": "Suiza", "Denmark": "Dinamarca", "Sweden": "Suecia",
    "Norway": "Noruega", "Poland": "Polonia", "Austria": "Austria",
    "Serbia": "Serbia", "Ukraine": "Ucrania", "Wales": "Gales",
    "Scotland": "Escocia", "Turkey": "Turquía", "Türkiye": "Turquía",
    "Greece": "Grecia", "Czechia": "Chequia", "Czech Republic": "Chequia",
    "Hungary": "Hungría", "Romania": "Rumanía", "Slovakia": "Eslovaquia",
    "Slovenia": "Eslovenia", "Albania": "Albania", "Finland": "Finlandia",
    "Iceland": "Islandia", "Ireland": "Irlanda", "Republic of Ireland": "Irlanda",
    "Northern Ireland": "Irlanda del Norte", "Russia": "Rusia",
    "Bosnia and Herzegovina": "Bosnia y Herzegovina",
    "Bosnia-Herzegovina": "Bosnia y Herzegovina", "Georgia": "Georgia",
    "North Macedonia": "Macedonia del Norte", "Montenegro": "Montenegro",
    "Kosovo": "Kosovo", "Bulgaria": "Bulgaria", "Israel": "Israel",
    # CAF
    "Morocco": "Marruecos", "Senegal": "Senegal", "Ghana": "Ghana",
    "Nigeria": "Nigeria", "Cameroon": "Camerún", "Ivory Coast": "Costa de Marfil",
    "Côte d'Ivoire": "Costa de Marfil", "Cote d'Ivoire": "Costa de Marfil",
    "Egypt": "Egipto", "Algeria": "Argelia", "Tunisia": "Túnez",
    "Mali": "Malí", "Burkina Faso": "Burkina Faso", "Cape Verde": "Cabo Verde",
    "Cabo Verde": "Cabo Verde", "South Africa": "Sudáfrica",
    "DR Congo": "RD Congo", "Congo DR": "RD Congo", "Gabon": "Gabón",
    "Zambia": "Zambia", "Angola": "Angola", "Guinea": "Guinea",
    "Equatorial Guinea": "Guinea Ecuatorial", "Mozambique": "Mozambique",
    "Namibia": "Namibia", "Benin": "Benín",
    # AFC
    "Japan": "Japón", "South Korea": "Corea del Sur", "Korea Republic": "Corea del Sur",
    "North Korea": "Corea del Norte", "Korea DPR": "Corea del Norte",
    "Australia": "Australia", "Saudi Arabia": "Arabia Saudí", "Iran": "Irán",
    "IR Iran": "Irán", "Qatar": "Catar", "Iraq": "Irak", "Jordan": "Jordania",
    "United Arab Emirates": "Emiratos Árabes Unidos", "Uzbekistan": "Uzbekistán",
    "China": "China", "China PR": "China", "India": "India",
    "Indonesia": "Indonesia", "Thailand": "Tailandia", "Vietnam": "Vietnam",
    "Bahrain": "Baréin", "Oman": "Omán", "Palestine": "Palestina",
    # OFC
    "New Zealand": "Nueva Zelanda", "New Caledonia": "Nueva Caledonia",
    "Fiji": "Fiyi", "Tahiti": "Tahití", "Papua New Guinea": "Papúa Nueva Guinea",
    "Solomon Islands": "Islas Salomón",
}


def translate_team(name: str | None) -> str:
    """Nombre de selección en español. Si no está en el diccionario, lo devuelve tal cual."""
    if not name:
        return ""
    return TEAMS.get(name.strip(), name.strip())


# ── Descripción de la jugada (relato ESPN en inglés → frase corta en español) ──
# Forma del gesto. Orden = prioridad (penalti antes que pie, etc.).
_MANNER: list[tuple[str, str]] = [
    ("own goal", "en propia puerta"),
    ("penalt", "de penalti"),
    ("header", "de cabeza"),
    ("right foot", "con la derecha"),
    ("right-foot", "con la derecha"),
    ("left foot", "con la izquierda"),
    ("left-foot", "con la izquierda"),
]

# Localización del disparo.
_LOCATION: list[tuple[str, str]] = [
    ("outside the box", "desde fuera del área"),
    ("very close range", "a bocajarro"),
    ("long range", "desde lejos"),
    ("centre of the box", "desde el área"),
    ("center of the box", "desde el área"),
    ("inside the box", "dentro del área"),
    ("six yard box", "a bocajarro"),
]


def translate_play(text: str | None) -> str:
    """Frase corta en español que describe la jugada (p.ej. 'de cabeza desde el área').
    Devuelve '' si no se reconoce nada — así nunca se cuela inglés en el tweet."""
    if not text:
        return ""
    low = text.lower()
    if "own goal" in low:
        return "en propia puerta"
    manner = next((es for en, es in _MANNER if en in low), "")
    location = next((es for en, es in _LOCATION if en in low), "")
    return " ".join(p for p in (manner, location) if p)


def parse_scorer(text: str | None) -> str:
    """Extrae el nombre del goleador del relato ESPN ('… Player (Team) …').
    Devuelve '' si no se puede identificar con seguridad."""
    if not text:
        return ""
    m = re.search(r"own goal by\s+([^.()]+?)\s*\(", text, re.I)
    if m:
        return m.group(1).strip()
    # Nombre justo antes del '(Equipo)', sin cruzar dígitos ni puntos
    m = re.search(r"(?:^|\.\s*)([^.()\d]+?)\s*\(", text)
    if not m:
        return ""
    name = re.sub(r"^\s*goal!?\s*", "", m.group(1), flags=re.I).strip()
    return name
