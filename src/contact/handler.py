"""Kontaktformular von kettenki.com.

Nimmt eine Anfrage vom Formular auf contact.html entgegen und schickt sie per
SES an das Postfach von KettenKI. Mehr macht sie nicht: keine Datenbank, keine
Warteschlange, keine Antwort an den Absender. Eine Anfrage pro Woche oder zehn
am Tag rechtfertigen nichts davon, und jedes Teil, das nicht da ist, kann auch
nicht ausfallen.

Bewusst wie die Liviana-Funktion gebaut, damit im selben Repo nicht zwei Stile
nebeneinander stehen: reines CloudFormation, Python-Runtime, und keine
Abhängigkeit ausser dem boto3, das in der Laufzeit ohnehin liegt. Damit
braucht der Versand keinen Build-Schritt.

Zwei Dinge, die beim Lesen sofort auffallen sollen:

* **Reply-To trägt die Adresse des Absenders, From nicht.** From muss eine in
  SES verifizierte Identität sein, sonst lehnt SES ab; die Adresse eines
  Fremden ist das nie. Wer im Postfach auf Antworten drückt, schreibt trotzdem
  direkt an die Kundschaft.
* **SES darf im Sandkasten bleiben.** Der Sandkasten verbietet nur den Versand
  an unverifizierte Empfänger. Hier ist der Empfänger immer das eigene
  Postfach, also fällt die Einschränkung nicht ins Gewicht. Erst eine
  automatische Empfangsbestätigung an die Kundschaft würde den Produktionszugang
  nötig machen — die gibt es hier absichtlich nicht.
"""

from __future__ import annotations

import json
import os
import re

import boto3
from botocore.exceptions import ClientError

# Obergrenzen. Sie schützen nicht vor einem entschlossenen Angreifer — dafür
# ist die Drosselung am API Gateway da — sondern halten die Mail lesbar und
# verhindern, dass jemand ein Buch ins Postfach kippt.
LIMITS = {"name": 120, "email": 254, "company": 160, "message": 4000, "interest": 40}

# Grosszügig mit Absicht, dieselbe Regel wie im Formular: alles mit @ und einem
# Punkt dahinter. Strengere Muster weisen echte Adressen ab, und eine
# abgewiesene Anfrage kostet mehr als eine Mail, die nicht ankommt.
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

ALLOWED_ORIGIN = os.environ["CONTACT_ALLOWED_ORIGIN"]
SENDER = os.environ["CONTACT_SENDER"]
RECIPIENT = os.environ["CONTACT_RECIPIENT"]

ses = boto3.client("sesv2")


def _cors() -> dict:
    return {
        "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "86400",
    }


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **_cors()},
        "body": json.dumps(body),
    }


def _clean(value, limit: int) -> str:
    """Auf Text, getrimmt und gekappt. Alles andere wird zur leeren Zeichenkette."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def handler(event, _context):
    if (event.get("requestContext", {}).get("http", {}).get("method")) == "OPTIONS":
        return {"statusCode": 204, "headers": _cors(), "body": ""}

    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "invalid_json"})
    if not isinstance(payload, dict):
        return _response(400, {"error": "invalid_json"})

    fields = {key: _clean(payload.get(key), limit) for key, limit in LIMITS.items()}

    # Dieselben Pflichtfelder wie im Formular. Die Prüfung im Browser ist eine
    # Bequemlichkeit für die Besucherin, keine Zusicherung: Wer den Endpunkt
    # direkt aufruft, umgeht sie mühelos.
    if not fields["name"] or not fields["message"]:
        return _response(400, {"error": "missing_fields"})
    if not EMAIL.match(fields["email"]):
        return _response(400, {"error": "invalid_email"})

    subject = (
        f"Anfrage zu {fields['interest']} — {fields['name']}"
        if fields["interest"]
        else f"Anfrage von {fields['name']}"
    )
    lines = [
        fields["message"],
        "",
        "—",
        f"Name: {fields['name']}",
        f"E-Mail: {fields['email']}",
    ]
    if fields["company"]:
        lines.append(f"Unternehmen: {fields['company']}")
    if fields["interest"]:
        lines.append(f"Interesse: {fields['interest']}")
    lines.append(f"Sprache: {_clean(payload.get('lang'), 5) or 'de'}")

    try:
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            # Antworten geht damit direkt an die Kundschaft, ohne dass die
            # Adresse aus dem Text herausgesucht werden muss.
            ReplyToAddresses=[fields["email"]],
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": "\n".join(lines), "Charset": "UTF-8"}},
                }
            },
        )
    except ClientError as exc:
        # Der Grund gehört ins Log, nicht in die Antwort: Was SES genau bemängelt
        # (nicht verifizierte Identität, Sandkasten, Kontingent) verrät einem
        # Fremden mehr über die Einrichtung, als er wissen muss. Die Nachricht
        # der Besucherin steht nie im Log — sie ist der Inhalt, nicht der Fehler.
        print("ses_send_failed:", exc.response.get("Error", {}).get("Code", "unknown"))
        return _response(502, {"error": "send_failed"})

    return _response(200, {"ok": True})
