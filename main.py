#!/usr/bin/env python3
"""Rastreador de Portafolio Cripto en Terminal (CLI).

Consulta precios spot en la API pública de CoinGecko (sin API key), valora un
portafolio de activos y lo imprime como una tabla alineada.

Uso:
    python main.py [usd|mxn]

Códigos de salida:
    0  ejecución correcta
    1  error de red, de la API o de datos
    2  error de uso (argumentos inválidos)
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import requests

# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
API_URL = "https://api.coingecko.com/api/v3/simple/price"
REQUEST_TIMEOUT_SECONDS = 10
SUPPORTED_CURRENCIES = ("usd", "mxn")
DEFAULT_CURRENCY = "usd"

# Portafolio de ejemplo. La llave es el *id* de CoinGecko (no el ticker).
# Lista completa de ids: https://api.coingecko.com/api/v3/coins/list
PORTFOLIO: dict[str, dict[str, Any]] = {
    "bitcoin": {"symbol": "BTC", "balance": 0.5},
    "ethereum": {"symbol": "ETH", "balance": 4.25},
    "solana": {"symbol": "SOL", "balance": 120.0},
    "cardano": {"symbol": "ADA", "balance": 15000.0},
    "dogecoin": {"symbol": "DOGE", "balance": 25000.0},
}

USAGE = (
    "Uso: python main.py [usd|mxn]\n"
    "  usd   cotiza el portafolio en dólares estadounidenses (por defecto)\n"
    "  mxn   cotiza el portafolio en pesos mexicanos\n"
    "  -h, --help   muestra esta ayuda"
)


# --------------------------------------------------------------------------- #
# Modelo de datos
# --------------------------------------------------------------------------- #
@dataclass
class Position:
    """Una posición valorada del portafolio."""

    asset_id: str
    symbol: str
    balance: float  # q_i: cantidad poseída
    price: float  # p_i: precio unitario en la moneda elegida
    value: float  # V_i = q_i * p_i
    change_24h: Optional[float]  # variación % en 24 h (None si la API no la da)
    weight: float = 0.0  # w_i: ponderación % dentro del portafolio


# --------------------------------------------------------------------------- #
# Entrada y validación
# --------------------------------------------------------------------------- #
def parse_currency(argv: list[str]) -> str:
    """Devuelve la moneda pedida en la línea de comandos.

    Raises:
        ValueError: si hay argumentos de más o la moneda no está soportada.
    """
    args = argv[1:]
    if len(args) > 1:
        raise ValueError("se esperaba como máximo un argumento (la moneda).")
    if not args:
        return DEFAULT_CURRENCY

    currency = args[0].strip().lower()
    if currency not in SUPPORTED_CURRENCIES:
        soportadas = ", ".join(SUPPORTED_CURRENCIES)
        raise ValueError(f"moneda no soportada '{args[0]}'. Opciones: {soportadas}.")
    return currency


def validate_portfolio(portfolio: dict[str, dict[str, Any]]) -> None:
    """Verifica que el portafolio tenga la forma y los valores esperados.

    Raises:
        KeyError: si a un activo le falta 'symbol' o 'balance'.
        ValueError: si el portafolio está vacío o un balance es inválido.
    """
    if not portfolio:
        raise ValueError("el portafolio está vacío.")

    for asset_id, info in portfolio.items():
        for field in ("symbol", "balance"):
            if field not in info:
                raise KeyError(f"al activo '{asset_id}' le falta el campo '{field}'.")

        balance = info["balance"]
        # bool es subclase de int: se excluye explícitamente.
        if isinstance(balance, bool) or not isinstance(balance, (int, float)):
            raise ValueError(f"balance no numérico para '{asset_id}': {balance!r}.")
        if not math.isfinite(balance) or balance < 0:
            raise ValueError(f"balance inválido para '{asset_id}': {balance!r}.")


# --------------------------------------------------------------------------- #
# Acceso a la API
# --------------------------------------------------------------------------- #
def fetch_prices(asset_ids: list[str], currency: str) -> dict[str, Any]:
    """Consulta precio y variación 24 h de varios activos en una sola petición.

    Raises:
        requests.RequestException: fallos de red, timeout o respuesta HTTP != 2xx.
        ValueError: si el cuerpo no es JSON válido o no es un objeto JSON.
    """
    params = {
        "ids": ",".join(asset_ids),
        "vs_currencies": currency,
        "include_24hr_change": "true",
    }
    response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:  # JSONDecodeError hereda de ValueError
        raise ValueError("la API devolvió una respuesta que no es JSON válido.") from exc

    if not isinstance(payload, dict):
        raise ValueError("la API devolvió una estructura JSON inesperada.")
    return payload


def to_float(value: Any, label: str) -> float:
    """Convierte un valor de la API a float finito.

    Raises:
        ValueError: si el valor es None, no numérico, NaN o infinito.
    """
    if isinstance(value, bool):
        raise ValueError(f"valor no numérico para {label}: {value!r}.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"valor no numérico para {label}: {value!r}.") from exc
    if not math.isfinite(number):
        raise ValueError(f"valor no finito para {label}: {value!r}.")
    return number


# --------------------------------------------------------------------------- #
# Lógica de negocio
# --------------------------------------------------------------------------- #
def build_positions(
    portfolio: dict[str, dict[str, Any]],
    prices: dict[str, Any],
    currency: str,
) -> list[Position]:
    """Cruza el portafolio con los precios y calcula V_i = q_i * p_i.

    Raises:
        KeyError: si la API no devolvió precio para algún activo.
        ValueError: si un precio o cambio no es numérico.
    """
    change_key = f"{currency}_24h_change"
    positions: list[Position] = []

    for asset_id, info in portfolio.items():
        try:
            asset_data = prices[asset_id]
            raw_price = asset_data[currency]
        except KeyError as exc:
            raise KeyError(
                f"la API no devolvió precio para '{asset_id}' en {currency.upper()} "
                "(¿el id es correcto?)."
            ) from exc

        price = to_float(raw_price, f"el precio de '{asset_id}'")
        raw_change = asset_data.get(change_key)
        change = to_float(raw_change, f"el cambio 24h de '{asset_id}'") if raw_change is not None else None

        balance = float(info["balance"])
        positions.append(
            Position(
                asset_id=asset_id,
                symbol=str(info["symbol"]).upper(),
                balance=balance,
                price=price,
                value=balance * price,
                change_24h=change,
            )
        )
    return positions


def summarize(positions: list[Position]) -> tuple[float, float]:
    """Calcula V_total, pondera cada activo (w_i) y la variación 24 h total.

    Modifica `positions` in situ (asigna `weight` y ordena por valor descendente).

    Returns:
        (valor_total, variacion_24h_total_en_porcentaje)

    Raises:
        ValueError: si un cambio 24 h es <= -100 % (valor previo indefinido).
    """
    total = sum(p.value for p in positions)

    for p in positions:
        p.weight = (p.value / total * 100) if total > 0 else 0.0

    # V_prev_i = V_i / (1 + cambio_i/100). Sin dato de cambio se asume 0 %.
    previous_total = 0.0
    for p in positions:
        factor = 1 + (p.change_24h or 0.0) / 100
        if factor <= 0:
            raise ValueError(f"cambio 24h inválido para '{p.asset_id}': {p.change_24h}.")
        previous_total += p.value / factor

    total_change = (total - previous_total) / previous_total * 100 if previous_total > 0 else 0.0

    positions.sort(key=lambda p: p.value, reverse=True)
    return total, total_change


# --------------------------------------------------------------------------- #
# Presentación
# --------------------------------------------------------------------------- #
def format_amount(value: float) -> str:
    """Cantidad con separador de miles y hasta 8 decimales (mínimo 2)."""
    text = f"{value:,.8f}".rstrip("0")
    integer, _, decimals = text.partition(".")
    return f"{integer}.{decimals.ljust(2, '0')}"


def format_price(value: float) -> str:
    """Precio unitario; más decimales para activos de precio bajo."""
    decimals = 2 if value >= 1 else 6
    return f"${value:,.{decimals}f}"


def format_money(value: float) -> str:
    return f"${value:,.2f}"


def format_weight(value: float) -> str:
    return f"{value:.2f}%"


def format_change(value: Optional[float]) -> str:
    return "N/D" if value is None else f"{value:+.2f}%"


def render_table(
    positions: list[Position],
    total: float,
    total_change: float,
    currency: str,
) -> str:
    """Construye una tabla ASCII con anchos dinámicos y alineación estricta.

    La primera columna se alinea a la izquierda; las numéricas, a la derecha.
    """
    cur = currency.upper()
    headers = ["Activo", "Balance", f"Precio ({cur})", f"Valor ({cur})", "Peso", "24h"]
    rows = [
        [
            p.symbol,
            format_amount(p.balance),
            format_price(p.price),
            format_money(p.value),
            format_weight(p.weight),
            format_change(p.change_24h),
        ]
        for p in positions
    ]
    footer = [
        "TOTAL",
        "",
        "",
        format_money(total),
        format_weight(sum(p.weight for p in positions)),
        format_change(total_change),
    ]

    all_rows = [headers, *rows, footer]
    widths = [max(len(row[i]) for row in all_rows) for i in range(len(headers))]

    def line(cells: list[str]) -> str:
        parts = [
            cell.ljust(widths[i]) if i == 0 else cell.rjust(widths[i])
            for i, cell in enumerate(cells)
        ]
        return "| " + " | ".join(parts) + " |"

    separator = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    output = [separator, line(headers), separator]
    output.extend(line(row) for row in rows)
    output.extend([separator, line(footer), separator])
    return "\n".join(output)


# --------------------------------------------------------------------------- #
# Punto de entrada
# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    """Orquesta el flujo completo y traduce excepciones a códigos de salida."""
    argv = sys.argv if argv is None else argv

    if len(argv) > 1 and argv[1] in ("-h", "--help"):
        print(USAGE)
        return 0

    try:
        currency = parse_currency(argv)
    except ValueError as exc:
        print(f"Error de uso: {exc}\n\n{USAGE}", file=sys.stderr)
        return 2

    try:
        validate_portfolio(PORTFOLIO)
        prices = fetch_prices(list(PORTFOLIO), currency)
        positions = build_positions(PORTFOLIO, prices, currency)
        total, total_change = summarize(positions)
    except requests.HTTPError as exc:  # debe ir antes que RequestException
        status = exc.response.status_code if exc.response is not None else "desconocido"
        hint = " Límite de peticiones alcanzado; espera un minuto." if status == 429 else ""
        print(f"Error HTTP {status} al consultar CoinGecko.{hint}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"Error de red al consultar CoinGecko: {exc}", file=sys.stderr)
        return 1
    except KeyError as exc:
        print(f"Error de datos: {exc.args[0]}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error de datos: {exc}", file=sys.stderr)
        return 1

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\nPortafolio cripto - {currency.upper()} - {timestamp}\n")
    print(render_table(positions, total, total_change, currency))
    print("\nFuente: CoinGecko (API pública). Información referencial, no es asesoría financiera.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
