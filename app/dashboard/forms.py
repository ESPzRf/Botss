"""Разбор HTML-форм и CSRF без внешних зависимостей."""

from __future__ import annotations

import re
from urllib.parse import parse_qs

from fastapi import HTTPException, Request

from app.core.models import WebSession


class FormError(ValueError):
    pass


async def read_form(request: Request) -> dict[str, list[str]]:
    body = (await request.body()).decode("utf-8", errors="replace")
    return parse_qs(body, keep_blank_values=True)


def one(form: dict[str, list[str]], key: str, default: str = "") -> str:
    values = form.get(key)
    return values[0].strip() if values else default


def many(form: dict[str, list[str]], key: str) -> list[str]:
    return [value.strip() for value in form.get(key, []) if value.strip()]


def as_bool(form: dict[str, list[str]], key: str) -> bool:
    return one(form, key) in {"1", "on", "true", "yes"}


def as_int(
    form: dict[str, list[str]],
    key: str,
    *,
    default: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
    label: str,
) -> int | None:
    raw = one(form, key)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise FormError(f"«{label}» должно быть числом.") from exc
    if minimum is not None and value < minimum:
        raise FormError(f"«{label}» не может быть меньше {minimum}.")
    if maximum is not None and value > maximum:
        raise FormError(f"«{label}» не может быть больше {maximum}.")
    return value


def as_id_list(form: dict[str, list[str]], key: str) -> list[int]:
    result: list[int] = []
    for raw in many(form, key):
        try:
            result.append(int(raw))
        except ValueError:
            continue
    return result


def parse_id_text(raw: str) -> list[int]:
    return [int(match) for match in re.findall(r"\d{5,20}", raw or "")]


def check_csrf(session: WebSession, form: dict[str, list[str]]) -> None:
    token = one(form, "_csrf")
    if not token or token != session.csrf:
        raise HTTPException(status_code=400, detail="Истекла сессия формы. Обновите страницу.")
