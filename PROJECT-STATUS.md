# Liviana — Project Status

_Letzte Aktualisierung: 2026-09-28 (content.json auf die neue Positionierung umgeschrieben und in S3, Kontingent bewilligt, Kontaktformular-Stack dokumentiert)_

> **Hinweis:** Dieses Dokument wird laufend aktualisiert, sobald sich am Projektstand etwas ändert. Bei jedem Fortschritt (erledigt, blockiert, neu offen) hier nachführen, nicht nur in `DECISIONS.md`. Claude pflegt es in jeder Sitzung selbstständig nach, ohne dass Javi danach fragen muss.

Bezieht sich auf `liviana-arquitectura.md` (die geschlossenen Architekturentscheidungen), `API.md` (Vertrag zum Widget) und `DECISIONS.md` (Implementierungsentscheidungen, die das Architekturdokument offen gelassen hat).

## Arbeitsmodus

- **Dieses Repo ist nur das Backend.** Das schwebende Widget lebt in `kettenki-website`. Die einzige Verbindung zwischen beiden ist `API.md`.
- **Produktion läuft** in `eu-central-1`, Stack `liviana`. Der Mock (`LIVIANA_BACKEND=mock`) bleibt die Standard-Teststufe: er braucht kein AWS-Konto und verbraucht kein Tagesbudget. Gegen die echte API nur testen, wenn es um Modellverhalten oder Infrastruktur geht.
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

- [x] **Git initialisiert und erster Commit** (`main`, 33 Dateien). Vor dem Commit Secret-Scan über Arbeitsbaum und Historie: keine AWS-Schlüssel, keine privaten Schlüssel, keine Tokens, keine `.env`. `info@kettenki.com` steht drin, ist aber die öffentliche Geschäftsadresse der Website, kein Geheimnis.
- [x] **Erster echter Deploy nach `eu-central-1`**, Stack `liviana`. API: `https://mr3w04rnrf.execute-api.eu-central-1.amazonaws.com` (`/chat`, `/health`). Bucket `kettenki-liviana-content` war frei, kein Suffix nötig. `AllowedOrigin` steht live auf `https://kettenki.com`, Modell auf `eu.anthropic.claude-haiku-4-5-20251001-v1:0` (in der Region als ACTIVE bestätigt), Tageslimit 500, TTL auf beiden Tabellen ENABLED, Budget 5 USD.
- [x] **`tools/smoke.py` gegen die echte API: alle Checks grün.** Health, erste Antwort, Verlauf beim Folgeturn, ausgestellte Session-ID, beide 400-Fälle und die Kürzung langer Nachrichten, alles gegen echtes Bedrock.
- [x] **Rate Limit gegen die echte Infrastruktur verifiziert**: 20 Nachrichten angenommen, die 21. mit `429`, `error=rate_limited`, `retryAfter=24` und passendem `Retry-After`-Header. Kein Mock.
- [x] **Vier Prompt-Defekte gefunden und behoben, die nur im echten Modell sichtbar waren.** Der Mock konnte sie prinzipiell nicht zeigen, weil er kein Sprachmodell ist:
  1. **Antworten waren viel zu lang** (drei Absätze statt vier Sätzen). Regel 3 war als weicher Hinweis formuliert. Jetzt ein hartes Limit mit Begründung ("das ist eine Chat-Blase, keine Webseite", ein Absatz, keine Leerzeilen).
  2. **Englische Preisfrage wurde auf Deutsch beantwortet.** Der Sprachblock im Prompt ist nach Sprachcode geschlüsselt, und das Modell griff sich den deutschen Eintrag. Preisregel und Ablehnungsregel sagen jetzt ausdrücklich, dass der passende Schlüssel zu wählen bzw. zu übersetzen ist.
  3. **Gedankenstriche in den Antworten**, gegen die Stilregel des Hauses. Jetzt Regel 7 im Prompt plus eine Normalisierung in `strip_markdown()`, die Halbgeviert- und Geviertstriche in Kommas umschreibt. Live nachgemessen: null Treffer.
  4. **Registerbruch du/Sie** mitten in einer Antwort. `identity.voice` im Inhaltsdokument legt das Duzen jetzt fest, samt Entsprechung für Englisch und Spanisch.
- [x] **Reserved Concurrency musste raus, weil das Konto es nicht zulässt** (siehe Entscheidungen). `ReservedConcurrency` ist im Template jetzt über eine Condition abschaltbar (`0` lässt die Eigenschaft weg), statt den Deploy scheitern zu lassen.
- [x] **`AllowedOrigin` hat keinen Default mehr.** Vorher stand `*` als Vorgabewert im Template und im Deploy-Skript, was genau der Fehler ist, den man um drei Uhr morgens macht. Jetzt Pflichtparameter mit Musterprüfung, in beiden Skripten.
- [x] **Zwei PowerShell-5.1-Fallen im Deploy-Skript behoben**, die den ersten Lauf abbrachen: `2>&1` bzw. `2>$null` auf `aws.exe` verpackt jede stderr-Zeile in einen `NativeCommandError`, der unter `$ErrorActionPreference = "Stop"` auch bei Exit-Code 0 wirft. Jetzt wird nur der Exit-Code ausgewertet, und für erwartbare Fehlschläge (Bucket-Probe) gibt es `Test-Aws`, das die Preference kurzzeitig senkt.
- [x] **58 Tests grün**, inklusive der neuen Zusicherungen für die vier Fixes.

- [x] **Repo ist auf GitHub**, öffentlich unter `https://github.com/carranza-javier/kettenki-liviana`. Drei Commits auf `main`, `origin/main` verfolgt. Vor dem Push noch einmal die vollständige Historie auf Zugangsdaten geprüft: sauber.
- [x] **Kontingenterhöhung für Lambda beantragt**: `Concurrent executions` (Quota-Code `L-B99A9384`) in `eu-central-1` von 10 auf 1000, per `aws service-quotas request-service-quota-increase`. Request-ID `554e9c57d7d24d59b0a8092fdb44dc81sDpYzldS`. Der Status wanderte innerhalb weniger Minuten von `PENDING` auf **`CASE_OPENED`**: AWS hat dafür einen Support-Fall geöffnet, die Freigabe läuft also über einen Menschen und nicht automatisch. Das effektive Kontingent steht weiterhin auf 10, deshalb konnte Reserved Concurrency in dieser Sitzung nicht nachgerüstet werden. Inzwischen bewilligt, siehe weiter unten.

- [x] **SNS-Abo bestätigt, die Alarmkette ist damit scharf.** `PendingConfirmation: false` auf `arn:...:liviana-alerts:31f2e4ae`, die doppelte Anfrage aus dem fehlgeschlagenen ersten Deploy ist verschwunden. Alle drei Alarme (`liviana-circuit-breaker-open`, `liviana-function-errors`, `liviana-function-throttles`) stehen auf `OK`, `ActionsEnabled: true`, und zeigen auf das Topic. Die beiden Budget-Benachrichtigungen (80 % Ist, 100 % Prognose) gehen ohnehin direkt per Mail an `info@kettenki.com` und brauchen keine Bestätigung.

  Am Rande, damit es beim nächsten Nachschauen nicht beunruhigt: `ConfirmationWasAuthenticated` steht auf `false`. Das heißt nur, dass per Klick auf den Link in der Mail bestätigt wurde und nicht über einen signierten API-Aufruf. Für ein E-Mail-Abo ist das der Normalfall, nicht ein halb fertiger Zustand.

- [x] **Budget von 5 auf 10 USD angehoben** (Javi, von Hand in der Konsole). 5 USD waren zu knapp, weil im selben Konto noch anderes läuft: der Ist-Wert lag beim Nachschauen schon bei 5.97 USD, die 80-Prozent-Schwelle war also dauerhaft gerissen und hätte täglich gemeldet.
- [x] **Wissensbasis und Regeln auf das heutige Angebot gebracht** (2026-08-25). Ausgelöst durch zwei Beobachtungen von Javi im Betrieb: Liviana bietet zu schnell die E-Mail an, und sie klingt zu sehr nach Bot. Beim Nachsehen kam ein dritter, schwererer Punkt dazu.
  - **Websites und Apps nach Mass fehlten komplett.** `sections.produkte` kannte nur BAMBERA, LIVIANA und FANDANGO. Die Website führt aber längst mit "KI-Chatbots, Websites und Apps", und `services.html` teilt das Angebot in zwei benannte Abschnitte. Zwei Drittel des Angebots existierten für Liviana also nicht, und sie konnte danach gar nicht gefragt werden.
  - **Der gefährliche Teil daran**: `hinweis_prototypen` sagte "Alle drei Lösungen sind Prototypen ohne Garantie". Wären die neuen Einträge einfach danebengestellt worden, hätte Liviana einen bezahlten Website-Auftrag als Prototyp ohne Garantie beschrieben. Jeder Eintrag trägt jetzt ein eigenes `art`-Feld, und das neue `zwei_arten_von_arbeit` sagt die Trennung ausdrücklich: KI-Prototypen kostenlos testbar ohne SLA, Websites und Apps normale Auftragsarbeit. Neu ist ausserdem `ablauf` mit den vier Schritten ("Du sagst mir, was du brauchst" bis "Wenn nicht, schuldest du nichts"), die vorher nirgends in der Wissensbasis standen, obwohl sie das eigentliche Verkaufsargument sind.
  - **Warum sie so schnell die E-Mail anbot**: Drei Regeln schickten zum Kontakt, und zwei davon feuerten praktisch immer. GROUNDING verwies bei **jeder** Wissenslücke dorthin, die Preisregel hängte ihn an, und CALL TO ACTION zählte "something you cannot answer" als Kaufabsicht. Zusammen bekam eine ganz normale Frage eine E-Mail-Adresse angehängt. Jetzt verweist GROUNDING nicht mehr reflexhaft, die Preisregel hängt nichts mehr an, und CALL TO ACTION verlangt ein echtes Signal (nach Kontakt fragen, nach Preis fragen, anfangen oder buchen wollen), **einmal pro Gespräch statt einmal pro Antwort**.
  - **Zwei Regeln, die es vorher gar nicht gab**: `FIT BEFORE CATALOGUE` (die eine passende Lösung nennen und in einem Satz begründen, nie das Sortiment aufsagen, bei Unklarheit eine kurze Rückfrage stellen) und `NOT A BROCHURE` (schreiben wie ein Mensch, keine Adjektive ohne Information, und es ist ausdrücklich erlaubt zu sagen, dass etwas nicht passt). Der Bot-Ton kam aus `identity.voice`, wo "freundlich, knapp und sachlich" stand; das ist neu formuliert.
  - **`pricing.statement` sprach nur von Prototypen** und passte damit nicht mehr, sobald jemand nach dem Preis einer Website fragt. Deckt jetzt beide Arten von Arbeit ab, in DE, EN und ES.
  - **Kontakt-URLs ohne `.html`** (`cta.contact_page`, `kontakt.kontaktseite`, die `seite`-Felder der Produkte), weil die Website überall extensionslos verlinkt. Die beiden neuen Einträge zeigen auf `services#custom-development`.
  - **Das Du ist jetzt konsistent.** `identity.voice` duzt seit jeher und begründet das mit "wie der Rest der Website". Das stimmte eine Zeit lang nicht mehr, weil die Website auf Sie umgestellt worden war; sie ist am selben Tag zurück aufs Du gegangen, damit passt die Begründung wieder.
  - Verifiziert: JSON gültig, Prompt baut sauber (14 352 Zeichen), Regelblock gelesen und neu durchnummeriert (jetzt 10 Regeln), **58 Tests grün**. **`content.json` ist von Javi nach S3 geladen worden**, die Änderungen sind also im Betrieb. Wie sich die neuen Regeln am echten Modell verhalten, ist damit die offene Frage, siehe Nächster Schritt.

- [x] **Kontingenterhöhung für Lambda bewilligt.** `aws lambda get-account-settings` meldet `ConcurrentExecutions: 1000` in `eu-central-1`. Damit ist Reserved Concurrency wieder möglich; gesetzt ist sie aber noch nicht (`get-function-concurrency` auf `liviana-chat` kommt leer zurück, Stand 2026-09-28). Befehl siehe Nächster Schritt.
- [x] **Widget in `kettenki-website` gebaut und live.**
- [x] **Kontaktformular als eigener Stack** (2026-09-07, Commit `71bb697`): `infra/contact.yaml`, `scripts/deploy-contact.ps1`, `src/contact/handler.py`. HTTP API, Lambda und SES, sonst nichts: keine Datenbank, keine Antwort an den Absender. Bewusst getrennt von der Liviana-Vorlage, damit ein Fehler am Formular den Chatbot nicht mitreisst und umgekehrt. Gleicher Stil wie Liviana (reines CloudFormation, nur boto3, `AllowedOrigin` ohne Default). Absender ist eine verifizierte SES-Identität, die Adresse der Kundschaft steht in `Reply-To`; SES darf im Sandkasten bleiben, weil der Empfänger immer das eigene Postfach ist.

- [x] **`content.json` auf die neue Positionierung umgeschrieben** (2026-09-28, in S3 und live geprüft). Die Wissensbasis stand noch auf "KI-Prototypen", mit BAMBERA, LIVIANA und FANDANGO gleichrangig; KettenKI positioniert sich inzwischen als "Individuelle Softwareentwicklung für KMU" mit drei gleichrangigen Bereichen.
  - **Struktur**: `produkte` heisst jetzt `angebot` und hat drei Einträge (`ki_chatbots_und_assistenten`, `websites`, `apps_nach_mass`). LIVIANA und BAMBERA hängen unter den Chatbots statt daneben. Neu sind `referenzen` (Kunde und Beispiele) und `frueheres` (nur FANDANGO). Das Format des Dokuments ist unverändert, `prompt.py` musste nicht angefasst werden: der Rollenblock nennt keine Produkte, alles steht in `identity.scope_note`.
  - **Angebotsmodell** für alle drei Bereiche gleich: erste funktionierende Version kostenlos, bezahlt wird nur, wenn es weitergeht. Die Unterscheidung "Prototyp ohne SLA" gegen "Auftragsarbeit" (`zwei_arten_von_arbeit`, `hinweis_prototypen`, `modell_der_zusammenarbeit`) ist raus. `ablauf` spricht jetzt mit "wir" wie die Website, nicht mehr mit "ich". Der Claim steht geduzt drin ("Software, die du testest, bevor du dafür bezahlst"), weil `identity.voice` und die Website duzen.
  - **BAMBERA** nur noch als abgeschlossener Pilot: drei Monate mit der Lumis Kaffeebar, nicht im Betrieb, Lumis keine aktuelle Kundin. Eine Team-Assistentin dieser Art bleibt aber Teil des Chatbot-Bereichs.
  - **FANDANGO** nur auf ausdrückliche Frage, als früherer Prototyp, der nicht angeboten wird, ohne Details. Aus der Ablehnungsantwort gestrichen.
  - **Einziges Kundenprojekt**: Spicy Feedback Tool für spicy kunstraum, im Betrieb. Dazu die ausdrückliche Zeile, dass es keine weiteren, auch keine vertraulichen Kunden gibt (siehe unten, warum).
  - **Beispiele** (`kettenki.com/templates`): Atelier Lehm, Sprachwerk Bern, Ausstellungsraum Halle Neun, jeweils mit dem Hinweis, dass die Betriebe erfunden sind.
  - **LIVIANA-Einordnung**: Termin- und Buchungsbetriebe (Fitness, Yoga, Praxen, Sprachschulen, Dienstleister, Wellness) als Beispiel für besonders guten Fit, ausdrücklich keine Grenze.
  - **Live geprüft** mit sieben Fragen in ES, DE und EN. Richtig: Positionierung, Bambera als Pilot, Fandango ohne Details, Beispiele als fiktiv markiert, Yoga-Studio bekommt LIVIANA. **Ein Defekt, der nur live auffiel**: auf "Do you have any real clients?" nannte sie Spicy und erfand dazu "I can't name other clients due to confidentiality". Das Modell füllt die Lücke "nur ein Kunde darf genannt werden" mit einer plausiblen Begründung. Die Formulierung sagt jetzt, dass es der einzige Kunde ist, und verbietet die Andeutung weiterer. Nach dem Fix nachgefragt (EN und ES): keine erfundenen weiteren Kunden mehr. Neu aufgefallen: sie verortete spicy kunstraum "en Berna", was nicht in der Wissensbasis stand. Der Kunstraum ist in Burgdorf (Kanton Bern); das steht jetzt in `referenzen.kundenprojekt.kunde`, damit sie den Ort nicht mehr raten muss.
  - **58 Tests grün.** Vorher war einer rot, unabhängig von dieser Änderung: `test_no_client_data_is_hardcoded_in_the_source` fand "kettenki" in `src/contact/handler.py` (Commit `71bb697`). Der Test scannt jetzt nur `src/liviana`, weil das Kontaktformular absichtlich KettenKI-spezifisch ist.

## Blockiert, wartet auf Input

- Nichts. Die Kontingenterhöhung ist durch (siehe Erledigt).

## Nächster Schritt

1. **Reserved Concurrency nachrüsten.** Das Kontingent steht auf 1000, die Reservierung fehlt noch. `-MonthlyBudgetUsd 10` muss mit, sonst setzt der Deploy das von Hand angehobene Budget auf 5 zurück:

   ```powershell
   ./scripts/deploy.ps1 `
     -ContentBucketName kettenki-liviana-content `
     -AlertEmail info@kettenki.com `
     -AllowedOrigin https://kettenki.com `
     -Region eu-central-1 `
     -MonthlyBudgetUsd 10 `
     -ReservedConcurrency 5
   ```

   Gegenprobe: `aws lambda get-function-concurrency --function-name liviana-chat --region eu-central-1` muss `ReservedConcurrentExecutions: 5` liefern.
2. **Länge und Kontaktangebot nachschärfen.** Beim Live-Test am 2026-09-28 hielten sich zwei Regeln sichtbar nicht: die Antwort an das Yoga-Studio hatte zwei Absätze und rund acht Sätze (Regel 3), und die Frage nach Website-Beispielen bekam die E-Mail angehängt, obwohl niemand Kaufinteresse gezeigt hatte (Regel 6). Das ist Prompt-Verhalten, kein Inhalt; die Stellschrauben sind Regel 3 und 6 in `prompt.py` bzw. `-MaxTokens`.

## Offen (noch nicht begonnen)

- [ ] **Reserved Concurrency nachrüsten.** Kontingent ist bewilligt, Befehl steht unter Nächster Schritt.
- [ ] **Bekannter Rauer Kanten: Prompt-Injektionsversuche werden auf Deutsch abgewiesen**, auch wenn sie auf Englisch oder Spanisch geschrieben sind. Normale Themenablehnungen (Javi als Kandidat, Rechtsberatung) treffen die Sprache korrekt, verifiziert in DE, EN und ES. Nur der Injektionspfad fällt in die deutsche Stimme aus `identity.voice` zurück. Drei Prompt-Fassungen haben daran nichts geändert; der Schaden ist gering (ein Angreifer bekommt eine deutsche statt einer englischen Abfuhr), deshalb bewusst so gelassen. Wieder aufmachen, wenn es ein echtes Modell-Upgrade gibt oder jemand sich daran stört.
- [ ] **Website nachziehen**: `services.html` zeigt FANDANGO noch als Karte und den Prototypen-Hinweis "ohne Garantie oder SLA" für die KI-Lösungen. Liviana sagt inzwischen etwas anderes; das gehört in `kettenki-website` angeglichen.
- [ ] **Antwortlänge im Alltag beobachten.** Nach dem Fix liegen die Antworten bei drei bis vier Sätzen, also am oberen Rand der Regel. Wenn sie im Widget zu wuchtig wirken, ist `max_sentences` in `prompt.py` bzw. `-MaxTokens` im Deploy die Stellschraube.
- [ ] Bedrock Guardrails, falls sich nach echtem Traffic zeigt, dass Prompt plus enges Inhaltsdokument nicht reichen. Bewusst zurückgestellt, siehe Verworfen.
- [ ] `.github/workflows` für die Tests, falls das Repo öffentlich wird und die grüne Suite sichtbar sein soll. Nicht dringend.

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
- **Reserved Concurrency ist zurzeit aus, nicht aus Überzeugung, sondern weil das Konto es verbietet.** Das Lambda-Kontingent für gleichzeitige Ausführungen steht auf 10, dem Wert für noch nicht hochgestufte Konten; AWS verlangt mindestens 10 unreservierte, also ist jede Reservierung unmöglich. Der Deploy scheiterte daran ("decreases account's UnreservedConcurrentExecution below its minimum value of [10]"). Praktisch wirkt das Kontingent selbst wie eine Obergrenze von 10, nur kontoweit statt pro Funktion: ein Amoklauf in Liviana könnte also andere Lambdas im selben Konto aushungern, statt nur sich selbst zu drosseln. Das Kontingent ist inzwischen auf 1000 bewilligt; der Redeploy mit `-ReservedConcurrency 5` steht noch aus.
- **Das Budget heißt `liviana-monthly`, misst aber das ganze Konto.** Es hat keine `CostFilters`, also zählt es jeden Dollar in `964907375727` mit, nicht nur Liviana. Das ist der eigentliche Grund, warum 5 USD täglich Alarm schlugen: der Betrag stammt nicht aus diesem Projekt. Wer es später sauber haben will, hängt einen Kostenfilter an die Budget-Ressource in `infra/template.yaml` (nach Tag oder nach Service) und gibt den Stack-Ressourcen ein gemeinsames Tag. Bis dahin gilt: die 10 USD sind eine Kontogrenze, keine Liviana-Grenze. Der Tagesdeckel von 500 Aufrufen ist das, was Liviana selbst begrenzt.
- **Achtung Drift: das Budget gehört CloudFormation.** Die Anhebung auf 10 USD wurde von Hand gemacht, der Stack kennt sie nicht. **Der nächste Deploy setzt sie auf den Wert des Parameters zurück**, deshalb trägt der vorbereitete Redeploy-Befehl unter Nächster Schritt `-MonthlyBudgetUsd 10`. Gleiches gilt für jede andere Änderung, die in der Konsole an Stack-Ressourcen gemacht wird: entweder im Template nachziehen oder beim Deploy mitgeben, sonst ist sie beim nächsten Lauf weg.
- **Die Kontingenterhöhung wurde per CLI beantragt, nicht über die Konsole.** `aws service-quotas request-service-quota-increase` erzeugt denselben Antrag und liefert eine Request-ID, die sich später skriptbar abfragen lässt, statt in einem Support-Fall nachschauen zu müssen. Beantragt wurde direkt 1000, der Normalwert eines regulären Kontos, statt einer knapp bemessenen Zwischenstufe: der Antrag kostet nichts und ein zweiter Anlauf in drei Monaten wäre reine Wiederholung.
- **Der Mock kann Modellverhalten nicht prüfen, nur den Ablauf.** Alle vier Prompt-Defekte dieser Sitzung waren mit 56 grünen Tests unsichtbar und fielen erst beim ersten echten Bedrock-Aufruf auf. Für künftige Prompt-Änderungen gilt deshalb: nach dem Deploy mindestens einmal in DE, EN und ES gegenprüfen, mit einer Preisfrage, einer Frage nach technischen Interna und einer nach Javi als Kandidat.
- **Ein Deploy ist billig, ein falscher Default teuer.** `AllowedOrigin` hat deshalb bewusst keinen Vorgabewert mehr. Lieber ein abgebrochener Deploy mit fehlendem Pflichtparameter als ein stiller `*` in Produktion.
- **Der Content-Bucket überlebt einen `delete-stack`** (`DeletionPolicy: Retain`). Beim Aufräumen des fehlgeschlagenen ersten Versuchs musste er deshalb von Hand gelöscht werden, sonst wäre der zweite Deploy an "bucket already exists" gescheitert. Gleiche Falle bei jedem künftigen Neuaufbau von null.

## Offene Fragen an Javi

- ~~Region und Modell-ID?~~ **Entschieden: `eu-central-1` und `eu.anthropic.claude-haiku-4-5-20251001-v1:0`** (2026-08-21), in der Region als ACTIVE bestätigt und live im Einsatz.
- ~~Monatsbudget?~~ **Entschieden: zuerst 5 USD, am selben Tag auf 10 USD korrigiert** (2026-08-21), Alarm bei 80 % Ist und 100 % Prognose an `info@kettenki.com`.
- ~~Öffentlich oder privat?~~ **Entschieden: öffentlich** (2026-08-21), wie `kettenki-bambera`.
- ~~Monatsbudget 5 USD?~~ **Korrigiert auf 10 USD** (2026-08-21), siehe Entscheidungen: 5 war für ein geteiltes Konto zu knapp.
- **Tagesdeckel 500 Aufrufe**: unverändert übernommen. Ob er für den echten Besucherstrom von kettenki.com großzügig oder knapp ist, weiß erst der erste Monat. Der Zähler steht in `liviana-limits` unter `BUDGET#<Datum>` und ist mit einem `scan` ablesbar.
- **Soll die Portfolio-Fiche `liviana.html` in `kettenki-website` jetzt einen Repo-Link bekommen?** Gleiche Frage, die dort schon für Bambera offen war.

## Session wieder aufnehmen

Kurzform für den Einstieg in eine neue Sitzung:

1. **Erst diese Datei lesen**, dann `liviana-arquitectura.md` (was geschlossen ist), dann `DECISIONS.md` (warum die Umsetzung so aussieht). `API.md` nur, wenn es um das Widget geht.
2. **Läuft es noch?** `python -m pytest tests -q` → 58 Tests grün, ohne AWS-Konto. Danach `python tools/chat.py` für einen Dialog gegen den Mock, und `python tools/smoke.py https://mr3w04rnrf.execute-api.eu-central-1.amazonaws.com` gegen die echte API (kostet ein paar Aufrufe vom Tagesbudget).
3. **Wo steht das Projekt?** Deployt und verifiziert in `eu-central-1`, Stack `liviana`, Code öffentlich auf GitHub. Offen ist an der Infrastruktur nur noch der Redeploy mit Reserved Concurrency (Kontingent ist bewilligt). Daneben läuft der Kontaktformular-Stack aus `infra/contact.yaml`. Der nächste Schritt steht oben.
4. **Was nicht wieder aufmachen:** alles unter "Verworfen". Besonders WAF, RAG, SAM/CDK und der Verlauf im Browser.
5. **Am Ende der Sitzung** diese Datei nachführen: Erledigtes nach unten in "Erledigt", Neues nach "Offen", Entscheidungen nach "Entscheidungen / Notizen", Datum in der Kopfzeile aktualisieren.
