from __future__ import annotations


def delovi(tekst: str, n: int = 4000) -> list[str]:
    """Telegram ima limit 4096 znakova; seče po novom redu gde može."""
    out = []
    while len(tekst) > n:
        i = tekst.rfind("\n", 0, n)
        i = i if i > n // 2 else n
        out.append(tekst[:i].rstrip())
        tekst = tekst[i:].lstrip()
    if tekst:
        out.append(tekst)
    return out
