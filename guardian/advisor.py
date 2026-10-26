"""Advice is always available even if a model replay is absent or malformed."""
from .language import detect_language
from .llm import NemotronClient
from .models import Level, Turn, Verdict


def _fallback(verdict: Verdict, language: str = "en") -> dict[str, str]:
    tactic = verdict.signals[0].tactic.replace("_", " ") if verdict.signals else "unusual request"
    if language == "pl":
        if verdict.level == Level.SCAM:
            warning = "To wygląda na oszustwo. Rozłącz się teraz. Nie wysyłaj pieniędzy, kodów ani nie instaluj żadnych aplikacji."
            action = "Rozłącz się. Zadzwoń do banku lub na policję pod zaufany numer, nie pod numer dzwoniącego."
        elif verdict.level == Level.CAUTION:
            warning = "Zachowaj ostrożność. Nie wysyłaj pieniędzy, kodów ani haseł i nie instaluj aplikacji. Najpierw sprawdź to samodzielnie."
            action = "Przerwij rozmowę i potwierdź wszystko pod zaufanym numerem lub u kogoś z rodziny."
        else:
            warning = "Brak oznak oszustwa. Nie podawaj kodów ani haseł, jeśli rozmowa stanie się podejrzana."
            action = "Kontynuuj normalnie, ale każdą niespodziewaną prośbę sprawdź samodzielnie."
        relative = f"Guardian wykrył ryzyko ({verdict.level.value.lower()}): {tactic}. Zadzwoń do tej osoby teraz."
    else:
        if verdict.level == Level.SCAM:
            warning = "This looks like a scam. Hang up now. Do not send money, codes, or install anything."
            action = "Hang up. Call your bank or police using a trusted number, not the caller's number."
        elif verdict.level == Level.CAUTION:
            warning = "Be careful. Do not share money, codes, passwords, or install apps. Verify independently first."
            action = "Pause the call and verify through a trusted number or a family member."
        else:
            warning = "No scam evidence yet. Do not share codes or passwords if the call changes."
            action = "Continue normally, but verify any unexpected request independently."
        relative = f"Guardian detected {verdict.level.value.lower()} risk: {tactic}. Please call them now."
    return {
        "warning": warning,
        "relative_alert": relative,
        "safe_action": action,
        "advice_source": "fallback",
        "advice_language": detect_language(warning),
    }


def advise(client: NemotronClient, verdict: Verdict, transcript: list[Turn]) -> dict[str, str]:
    caller_text = " ".join(turn.text for turn in transcript if turn.speaker == "caller")
    fallback_lang = detect_language(caller_text)
    try:
        message = client.advise(verdict, transcript)
        if len(message["warning"].split()) <= 25:
            res = {**message, "advice_source": "seeded" if getattr(client, "last_advice_seeded", False) else "nemotron"}
            res["advice_language"] = detect_language(res["warning"])
            return res
    except Exception:
        pass
    res = _fallback(verdict, language=fallback_lang)
    res["advice_language"] = detect_language(res["warning"])
    return res

