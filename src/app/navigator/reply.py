"""The company's side of the pitch: opening the executive brief, replying to it, and how long its private link works.

Nothing identifying is recorded about the reader: no IP address, no browser, only when the brief was opened. Link
previews (mail scanners, chat apps) never count: the token sits after the '#', so they never call the API with it.
The officer's own preview (?preview=1) does not count either.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

from . import cases

DAYS = int(os.getenv("BRIEF_LINK_DAYS", "90"))   # how long a private link works after the pitch is prepared
MAX_REPLIES = 10                                  # per brief: the reply form is public, behind the private link only

Kind = Literal["visit", "call", "question"]


class Reply(BaseModel):
    kind: Kind
    name: str = Field("", max_length=120)
    email: str = Field("", max_length=200)
    message: str = Field("", max_length=1500)


def expires(brief: dict) -> str:
    """When the link stops working; older briefs count from when they were prepared."""
    if brief.get("expires_at"):
        return brief["expires_at"]
    return (datetime.fromisoformat(brief["at"]) + timedelta(days=DAYS)).isoformat(timespec="seconds")


def new_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=DAYS)).isoformat(timespec="seconds")


def state(brief: dict) -> Literal["ok", "expired", "revoked"]:
    if brief.get("revoked_at"):
        return "revoked"
    return "expired" if datetime.fromisoformat(expires(brief)) <= datetime.now(timezone.utc) else "ok"


def _who(case: cases.Case) -> str:
    return cases.guess_company(case) or "Company"


def record_view(case: cases.Case) -> None:
    b = case.outreach["brief"]
    now = cases._now()
    b["views"] = b.get("views", 0) + 1
    b["last_view"] = now
    if b["views"] == 1:
        b["first_view"] = now
        cases.log(case, _who(case), "brief_opened", "Opened the pitch")
    cases.save(case)


def record_reply(case: cases.Case, r: Reply) -> None:
    """A reply moves the request to "interested", also when it had been closed: the company came back."""
    replies = case.outreach.setdefault("replies", [])
    replies.append({**r.model_dump(), "name": r.name.strip(), "email": r.email.strip(), "message": r.message.strip(),
                    "at": cases._now()})
    reopened = case.status == "closed"
    case.status = "interested"
    what = {"visit": "Would like to visit Bern", "call": "Would like a call first", "question": "Has a question"}[r.kind]
    cases.log(case, r.name.strip() or _who(case), "replied",
              what + (f": {r.message.strip()[:200]}" if r.message.strip() else "") + (" (request reopened)" if reopened else ""))
    cases.save(case)


def too_many(case: cases.Case) -> bool:
    return len(case.outreach.get("replies", [])) >= MAX_REPLIES


# The reply form on the brief, in the brief's language. Served with the brief, so briefs prepared before the form
# existed get it too.
LABELS = {
    "en": {"title": "Reply to us", "lead": "Tell us what you would like to do next. {who} will get back to you.",
           "visit": "I'd like to visit Bern", "call": "Let's talk first", "question": "I have a question",
           "name": "Your name", "email": "Your email", "message": "Message (optional)",
           "hint": "Preferred dates, who would come, or what you would like to see",
           "send": "Send reply", "sent": "Thank you. {who} will get back to you shortly.",
           "privacy": "Your reply goes only to the Canton of Bern's business development team.",
           "preview": "Preview: replies are disabled here. The company sees an active form.",
           "error": "Your reply could not be sent. Please write to us by email instead.",
           "gone_revoked": "This link is no longer active.", "gone_expired": "This link has expired.",
           "gone_lead": "Please contact the Canton of Bern's business development team for a new one.",
           "team": "Our business development team"},
    "de": {"title": "Ihre Antwort", "lead": "Sagen Sie uns, wie es weitergehen soll. {who} meldet sich bei Ihnen.",
           "visit": "Ich möchte Bern besuchen", "call": "Zuerst ein Gespräch", "question": "Ich habe eine Frage",
           "name": "Ihr Name", "email": "Ihre E-Mail", "message": "Nachricht (optional)",
           "hint": "Wunschtermine, wer mitkommt oder was Sie sehen möchten",
           "send": "Antwort senden", "sent": "Vielen Dank. {who} meldet sich in Kürze bei Ihnen.",
           "privacy": "Ihre Antwort geht nur an die Wirtschaftsförderung des Kantons Bern.",
           "preview": "Vorschau: Antworten sind hier deaktiviert. Die Firma sieht ein aktives Formular.",
           "error": "Ihre Antwort konnte nicht gesendet werden. Bitte schreiben Sie uns per E-Mail.",
           "gone_revoked": "Dieser Link ist nicht mehr aktiv.", "gone_expired": "Dieser Link ist abgelaufen.",
           "gone_lead": "Bitte wenden Sie sich für einen neuen Link an die Wirtschaftsförderung des Kantons Bern.",
           "team": "Die Wirtschaftsförderung"},
    "fr": {"title": "Votre réponse", "lead": "Dites-nous comment vous souhaitez poursuivre. {who} vous recontactera.",
           "visit": "Je souhaite visiter Berne", "call": "D'abord un appel", "question": "J'ai une question",
           "name": "Votre nom", "email": "Votre e-mail", "message": "Message (facultatif)",
           "hint": "Dates souhaitées, qui viendrait, ou ce que vous aimeriez voir",
           "send": "Envoyer la réponse", "sent": "Merci. {who} vous recontactera rapidement.",
           "privacy": "Votre réponse est transmise uniquement à la promotion économique du canton de Berne.",
           "preview": "Aperçu : les réponses sont désactivées ici. L'entreprise voit un formulaire actif.",
           "error": "Votre réponse n'a pas pu être envoyée. Merci de nous écrire par e-mail.",
           "gone_revoked": "Ce lien n'est plus actif.", "gone_expired": "Ce lien a expiré.",
           "gone_lead": "Merci de contacter la promotion économique du canton de Berne pour en obtenir un nouveau.",
           "team": "L'équipe de promotion économique"},
}


def labels(lang: str, officer: str = "") -> dict:
    t = LABELS.get(lang, LABELS["en"])
    who = officer or t["team"]
    return {k: v.replace("{who}", who) for k, v in t.items()}
