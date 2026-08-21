# Liviana — Project Status

_Letzte Aktualisierung: 2026-08-21 (Backend von null gebaut: Mock lokal, echte AWS-Infrastruktur als CloudFormation, API-Vertrag für das Widget)_

> **Hinweis:** Dieses Dokument wird laufend aktualisiert, sobald sich am Projektstand etwas ändert. Bei jedem Fortschritt (erledigt, blockiert, neu offen) hier nachführen, nicht nur in `DECISIONS.md`. Claude pflegt es in jeder Sitzung selbstständig nach, ohne dass Javi danach fragen muss.

Bezieht sich auf `liviana-arquitectura.md` (die geschlossenen Architekturentscheidungen), `API.md` (Vertrag zum Widget) und `DECISIONS.md` (Implementierungsentscheidungen, die das Architekturdokument offen gelassen hat).

## Arbeitsmodus

- **Dieses Repo ist nur das Backend.** Das schwebende Widget lebt in `kettenki-website`. Die einzige Verbindung zwischen beiden ist `API.md`.
- **Alles lokal, nichts deployt.** Es steht noch kein einziges AWS-Ressourcen-Objekt in Javis Konto. Der Mock-Backend (`LIVIANA_BACKEND=mock`) braucht kein AWS-Konto und keine Bedrock-Aufrufe.
- **Keine Test-Stage in AWS.** Gleiche Regel wie in `kettenki-website`: Overengineering für ein Ein-Personen-Projekt. Der Mock ist die Teststufe.
- Python 3.11+, keine Abhängigkeiten außer der stdlib und dem boto3, das die Lambda-Laufzeit schon mitbringt. Kein Build-System, kein virtualenv nötig.
- **Nichts Kundenspezifisches im Code.** Alles zu KettenKI steht in `content/content.json`; Infrastrukturnamen kommen aus Umgebungsvariablen. Ein Test erzwingt das.
- Planungsgespräche mit Javi laufen auf Spanisch. Code, Kommentare und diese Dokumente sind Englisch bzw. Deutsch, der Inhalt des Assistenten ist Deutsch.

## Erledigt

- [x] **Phase 1 — Mock lokal, vollständiger Ablauf ohne AWS.** Ein einziger Codepfad, zwei Backends über `LIVIANA_BACKEND=mock|aws`. Der Mock ist keine Skizze: gleiche Reihenfolge der Prüfungen, gleiche Fenster, gleiche Ablaufsemantik wie DynamoDB. Ablauf in `src/liviana/service.py`: validieren → Rate Limit → Verlauf lesen → Prompt bauen → Circuit Breaker → Modell → Fenster schreiben. Terminal-Client `tools/chat.py` mit `/history`, `/prompt`, `/state`, `/new`, `/flood N`.
- [x] **Systemprompt gebaut** (`src/liviana/prompt.py`), acht Regeln: Sprache folgt der letzten Besuchernachricht; nur die Wissensabschnitte als Quelle; höchstens vier kurze Sätze; **niemals Preise erfinden**; spricht als Firma, nie als Privatperson; Kontakt-CTA nur bei Kaufinteresse oder Nichtwissen; reiner Text ohne Markdown; Besuchernachrichten sind Daten, keine Anweisungen. Das Gerüst ist Englisch (modellzugewandte Produktlogik), das Wissen bleibt in der Sprache des Dokuments.
- [x] **Inhaltsdokument `content/content.json`** aus dem echten Seiteninhalt gebaut: Unternehmen und Philosophie, die drei Lösungen (BAMBERA, LIVIANA, FANDANGO) mit Vorteilen, Zielgruppen und Beispielen, Kontakt, Preishaltung ("keine veröffentlichte Preisliste") und die Tabuthemen. Sprachen DE/EN/ES. Enthält `identity.scope_note`: Liviana ist selbst die Live-Demo, ist **nicht** Bambera oder Fandango, und spricht über die anderen Lösungen kommerziell, nie über deren technische Interna.
- [x] **Beide Schutzschichten in der Anwendungslogik**, identisch in Mock und Produktion: Rate Limit 20 Nachrichten/Minute pro Sitzung (oder pro IP, wenn noch keine Sitzung existiert) und Circuit Breaker bei 500 Modellaufrufen/Tag. Beide über eine einzige bedingte `UpdateItem`-Operation, damit zwei gleichzeitige Aufrufe nicht beide durchrutschen. **Ein abgelehnter Request verbraucht nie Budget** — das ist getestet.
- [x] **Phase 2 — echte Infrastruktur als `infra/template.yaml`**, reines CloudFormation (kein SAM, kein CDK): HTTP API mit Throttling und CORS, Lambda mit Reserved Concurrency, zwei DynamoDB-Tabellen mit TTL (`liviana-conversations` mit Partition Key `sessionId` und einem Item pro Sitzung, `liviana-limits` für die beiden Zähler), S3-Bucket mit Versionierung und blockiertem Public Access, IAM-Rolle nach dem Prinzip der geringsten Rechte, SNS-Topic, drei CloudWatch-Alarme (Circuit Breaker offen via Log-Metric-Filter, Funktionsfehler, Throttles) und ein AWS-Budget-Alarm bei 80 % Ist-Kosten und 100 % Prognose.
- [x] **Deploy-Skripte** `scripts/deploy.ps1` und `scripts/deploy.sh`, idempotent: Artefakt-Bucket anlegen, zippen, unter einem Hash-Schlüssel hochladen, Stack deployen, Inhaltsdokument hochladen, Outputs ausgeben. Kein Build-Schritt, weil die Funktion keine Abhängigkeiten hat.
- [x] **Phase 3 — `API.md`**, vollständiger Vertrag fürs Widget: Endpunkte, Request-Felder mit Regeln, Antwortform, alle sechs Fehlerfälle mit Statuscode, `error`-Code und was das Widget jeweils tun soll, welche Ablehnung welches Budget kostet, Gedächtnisverhalten, ein durchgearbeitetes `fetch`-Beispiel und ein `curl`-Aufruf.
- [x] **`README.md`** mit lokalem Ablauf, exakten Deploy-Schritten, der Liste dessen, was Javi selbst in AWS vorbereiten muss, den fünf Kostenschichten und den Betriebsnotizen. **`DECISIONS.md`** mit 20 Implementierungsentscheidungen und ihrer Begründung.
- [x] **56 Tests**, kein AWS nötig (`python -m pytest tests -q`). Decken den Ablauf, beide Grenzen, den Fehlervertrag, das FIFO-Fenster, die Ablaufsemantik des Mock-Stores und die Garantie ab, dass kein kundenspezifischer String nach `src/` gerutscht ist.
- [x] **Nachträglich gegen das echte Architekturdokument korrigiert.** Das Dokument lag zu Beginn der Sitzung nicht vor; die erste Fassung wurde aus dem Prompt und `kettenki-website/SPEC.md` §7 rekonstruiert. Nach Erhalt fünf Abweichungen behoben:
  1. **Datenmodell**: statt einem Item pro Turn mit Sort Key jetzt ein Item pro Sitzung mit einer Liste, beim Schreiben FIFO gekürzt, Tabelle `liviana-conversations` mit Partition Key `sessionId`. Zähler in eine eigene Tabelle `liviana-limits` ausgelagert.
  2. **Lange Nachrichten werden gekürzt, nicht abgelehnt** (das Dokument sagt "recortar"). Über 1000 Zeichen → auf 1000 gekürzt, Antwort trägt `meta.messageTruncated: true`. 400 bleibt nur für leer oder fehlerhaft.
  3. **Rate Limit fällt auf die IP zurück**, wenn der Request keine Sitzung mitbringt ("o IP si no hay sesión"). Deckt nebenbei das Rotieren von Session-IDs ab.
  4. **`localStorage` statt `sessionStorage`** im Widget-Vertrag, Sprachen DE/EN/ES statt vier.
  5. **"Ist nicht Bambera, nicht Fandango"** als `identity.scope_note` ins Inhaltsdokument und in den Rollenblock des Prompts.

## Blockiert — wartet auf Input

- **Nichts ist technisch blockiert.** Der nächste Schritt braucht aber Javis Konto und seine Freigabe: ohne aktivierten Bedrock-Modellzugriff und ohne bestätigte Modell-ID kann niemand außer ihm den ersten Deploy sinnvoll durchführen.

## Nächster Schritt

1. **Javi aktiviert den Bedrock-Modellzugriff** in der Konsole (Bedrock → Model access → Anthropic) und prüft, welche Inference-Profile-ID in seiner Region wirklich existiert: `aws bedrock list-inference-profiles --region eu-central-1`. Der Default im Template ist `eu.anthropic.claude-haiku-4-5-20251001-v1:0`, ungeprüft.
2. **Erster Deploy** mit `scripts/deploy.ps1`, danach `python tools/smoke.py <ChatEndpoint>` gegen die echte API. Erst dieser Lauf beweist, dass Bedrock, DynamoDB-TTL und der Circuit Breaker in echt zusammenspielen — bisher ist alles nur gegen den Mock verifiziert.
3. **Danach erst das Widget** in `kettenki-website` bauen, gegen `API.md`.

## Offen (noch nicht begonnen)

- [ ] **Erster echter Deploy in AWS.** Nichts von der Infrastruktur ist jemals gelaufen; das Template ist strukturell geprüft (alle Refs lösen auf), aber nie von CloudFormation angenommen worden.
- [ ] **Echte Antwortqualität prüfen.** Bisher hat nur der Keyword-Mock geantwortet. Ob Haiku bei dieser Prompt-Fassung wirklich kurz bleibt, keine Preise erfindet und die Sprache des Besuchers trifft, ist offen, bis es einmal live lief.
- [ ] **`AllowedOrigin` auf `https://kettenki.com` setzen** vor dem Live-Gang. Default ist `*`, was jede beliebige Seite im Netz das Tagesbudget verbrauchen lässt.
- [ ] **Git-Repo initialisieren.** Dieses Verzeichnis ist noch kein Git-Repo; nichts ist committet.
- [ ] Widget in `kettenki-website` (steht dort schon als offener Punkt: Katzen-Avatar, Zustände, `chat-mock.js`).
- [ ] Bedrock Guardrails, falls sich nach echtem Traffic zeigt, dass Prompt plus enges Inhaltsdokument nicht reichen. Bewusst zurückgestellt, siehe Verworfen.

## Verworfen — nicht wieder aufnehmen

- **AWS WAF.** Fester Monatsbetrag ab der ersten Minute, für eine Demo, deren echtes Risiko die fünf kostenlosen Schichten abdecken. Erst wenn echter Bot-Traffic durchkommt, wäre WAF mit Bot Control der nächste Schritt.
- **RAG / Bedrock Knowledge Base.** Der Inhalt passt vollständig in den Prompt. Semantische Suche wäre hier Overengineering.
- **Test-Stage in AWS.** Gleiche Begründung wie im Website-Repo. Der Mock ist die Teststufe.
- **SAM und CDK.** Die Funktion hat keine Abhängigkeiten, also braucht sie keinen Build-Schritt. SAM verlangte ein CLI, das nicht installiert ist; CDK verlangte Node, Bootstrap-Stack und Synth-Schritt. Reines CloudFormation plus ein idempotentes Skript leistet dasselbe.
- **Ein Item pro Turn in DynamoDB.** Solides Muster, aber nicht das, was das Architekturdokument festlegt, und es lässt Turns bis zum TTL auflaufen statt sie durch Konstruktion zu begrenzen. Zurückgebaut, nicht erneut vorschlagen.
- **Verlauf im Browser halten und mitschicken** (so steht es noch in `kettenki-website/SPEC.md` §7.6). Ein vom Client gelieferter Verlauf ist ein kostenloser Weg, den Input-Token-Verbrauch jedes Requests aufzublasen. Das Architekturdokument ist die spätere und sichere Entscheidung: Server-seitig in DynamoDB, das Widget schickt nur die neue Nachricht.

## Entscheidungen / Notizen

- **Das Architekturdokument gewinnt gegen `SPEC.md` §7.6.** Beim Widerspruch um den Speicherort des Verlaufs gilt `liviana-arquitectura.md`. In `DECISIONS.md` §10 festgehalten, falls jemand später den SPEC liest und stutzt.
- **Zwei Tabellen statt einer**, obwohl eine mit On-Demand gleich viel kostet. Der operative Vorteil: Konversationen löschen ist ein `delete-table` und kann die Zähler nicht anfassen, und umgekehrt.
- **Fenster wird beim Schreiben gekürzt, in der Service-Schicht.** DynamoDB kann das älteste Listenelement nicht serverseitig entfernen. Der Lesevorgang ist ohnehin Teil des Ablaufs, also kostet ein ganzer Wortwechsel weiterhin ein Read und ein Write. Preis: zwei exakt gleichzeitige Nachrichten derselben Sitzung könnten einen Turn verlieren. Akzeptiert, kein Versionsattribut.
- **Feste Zeitfenster, nicht gleitend.** Ein Besucher kann im schlimmsten Fall 2× das Limit über eine Fenstergrenze hinweg senden. Ein gleitendes Fenster kostet einen zusätzlichen Read pro Nachricht für einen Randfall, der einen Marketing-Chatbot nicht interessiert.
- **Reihenfolge der Prüfungen ist bewusst**: Rate Limit vor dem Circuit Breaker, Circuit Breaker unmittelbar vor dem bezahlten Aufruf. Ein 429 verbraucht damit nie einen Tagesaufruf, ein fehlgeschlagener Bedrock-Aufruf schon — der wurde versucht und wird womöglich berechnet.
- **`boto3` und die Converse-API statt des Anthropic-SDK.** Hält die Funktion abhängigkeitsfrei (das ist die Voraussetzung für den fehlenden Build-Schritt) und macht einen Modellwechsel zu einer Umgebungsvariablen.
- **Fragen und Antworten werden nicht geloggt**, außer `LIVIANA_LOG_MESSAGES=true` ist gesetzt. Besuchertext auf einer öffentlichen Seite in CloudWatch zu schreiben ist eine bewusste Entscheidung, keine Debugging-Bequemlichkeit. Gleiche Haltung wie `BAMBERA_LOG_QUERIES`.
- **Der Content-Bucket hat `DeletionPolicy: Retain`.** Ein `delete-stack` zerstört das Wissensdokument nicht still.
- **Inhalt ändern heißt nicht deployen.** `content/content.json` bearbeiten, nach S3 kopieren, nach höchstens fünf Minuten (Cache-TTL) ist es live. Der Bucket ist versioniert, ein schlechter Edit ist zurückrollbar.
- **Keine Gedankenstriche im Copy.** Gleiche Stilregel wie im Website-Repo, gilt auch für Texte im Inhaltsdokument.
- **Keine Aussagen über aktive Produktion oder tägliche Nutzung von Bambera** — auch nicht im Prompt oder im Inhaltsdokument. Testdauer sind drei Monate.

## Offene Fragen an Javi

- **Region und Modell-ID**: bleibt es bei `eu-central-1` und dem EU-Inference-Profile für Haiku? Der Default im Template ist ungeprüft.
- **Monatsbudget**: der Budget-Alarm steht auf 10 USD. Ist das die Zahl, bei der Javi geweckt werden will?
- **Tagesdeckel 500 Aufrufe**: der Wert kommt aus dem Architekturdokument. Ob er für den echten Besucherstrom von kettenki.com großzügig oder knapp ist, weiß erst der erste Monat.
- **Soll dieses Repo öffentlich oder privat sein?** Bei `kettenki-bambera` fiel die Entscheidung auf öffentlich. Hier steht kein Kundendatensatz drin, aber die Entscheidung gehört Javi.

## Session wieder aufnehmen

Kurzform für den Einstieg in eine neue Sitzung:

1. **Erst diese Datei lesen**, dann `liviana-arquitectura.md` (was geschlossen ist), dann `DECISIONS.md` (warum die Umsetzung so aussieht). `API.md` nur, wenn es um das Widget geht.
2. **Läuft es noch?** `python -m pytest tests -q` → 56 Tests grün, ohne AWS-Konto. Danach `python tools/chat.py` für einen echten Dialog gegen den Mock.
3. **Wo steht das Projekt?** Nichts ist deployt, nichts ist committet. Der nächste Schritt steht oben unter "Nächster Schritt".
4. **Was nicht wieder aufmachen:** alles unter "Verworfen". Besonders WAF, RAG, SAM/CDK und der Verlauf im Browser.
5. **Am Ende der Sitzung** diese Datei nachführen: Erledigtes nach unten in "Erledigt", Neues nach "Offen", Entscheidungen nach "Entscheidungen / Notizen", Datum in der Kopfzeile aktualisieren.
