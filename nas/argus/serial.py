"""Da dataclass a dizionario JSON e ritorno (per salvare lo stato del motore nel database).

Usa le annotazioni dei tipi: datetime e date diventano testo ISO, le dataclass annidate e le
liste si ricostruiscono da sole.
"""

from __future__ import annotations

import types
import typing
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from typing import Any, Union, get_args, get_origin, get_type_hints

from .tempo import a_fuso


def a_dict(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: a_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, datetime):
        return a_fuso(obj).isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        return [a_dict(x) for x in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(a_dict(x) for x in obj)
    if isinstance(obj, dict):
        return {str(k): a_dict(v) for k, v in obj.items()}
    return obj


def da_dict(cls: type, dati: dict) -> Any:
    tipi = get_type_hints(cls)
    argomenti = {}
    for f in fields(cls):
        if f.name in dati:
            argomenti[f.name] = _converti(tipi[f.name], dati[f.name])
    return cls(**argomenti)


def _converti(tipo: Any, valore: Any) -> Any:
    if valore is None:
        return None
    origine = get_origin(tipo)
    if origine in (Union, types.UnionType):
        argomenti = [a for a in get_args(tipo) if a is not type(None)]
        return _converti(argomenti[0], valore) if argomenti else valore
    if origine in (list, typing.List):
        (arg,) = get_args(tipo) or (Any,)
        return [_converti(arg, x) for x in valore]
    if origine in (frozenset, set):
        (arg,) = get_args(tipo) or (Any,)
        return origine(_converti(arg, x) for x in valore)
    if origine in (dict, typing.Dict):
        args = get_args(tipo)
        arg = args[1] if len(args) == 2 else Any
        return {k: _converti(arg, v) for k, v in valore.items()}
    if tipo is datetime:
        return a_fuso(datetime.fromisoformat(valore))
    if tipo is date:
        return date.fromisoformat(valore)
    if isinstance(tipo, type) and is_dataclass(tipo):
        return da_dict(tipo, valore)
    return valore
