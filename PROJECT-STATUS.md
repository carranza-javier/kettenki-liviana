# Liviana — Project Status

_Letzte Aktualisierung: 2026-08-21 (in `eu-central-1` deployt und gegen echtes Bedrock verifiziert, Git initialisiert, vier Prompt-Defekte nach den Live-Tests behoben)_

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

## Blockiert — wartet auf Input

- **SNS-Bestätigung durch Javi.** Das Topic `liviana-alerts` hat zwei ausstehende Bestätigungen an `info@kettenki.com` (eine stammt aus dem fehlgeschlagenen ersten Deploy, CloudFormation legte beim Update eine zweite an). **Bis Javi eine davon per Mail bestätigt, sind alle Alarme stumm** — Circuit Breaker offen, Funktionsfehler, Throttles. Die zweite verfällt nach drei Tagen von selbst.
- **GitHub-Repo anlegen.** Die `gh` CLI ist auf dieser Maschine nicht installiert, das Remote kann also nicht von hier aus erzeugt werden. Der Commit liegt lokal und wartet auf ein leeres Repo unter `carranza-javier/kettenki-liviana`.

## Nächster Schritt

1. **SNS-Mail bestätigen** und das GitHub-Repo anlegen, dann `git push -u origin main`. Beides steht unter Blockiert.
2. **Lambda-Kontingent erhöhen lassen** (Service Quotas → Lambda → "Concurrent executions", von 10 auf 1000), danach einmal mit `-ReservedConcurrency 5` neu deployen. Bis dahin fehlt eine der fünf Schutzschichten, siehe Entscheidungen.
3. **Danach das Widget** in `kettenki-website` bauen, gegen `API.md`. Die API ist live und der Vertrag ist verifiziert, das ist keine Vorarbeit mehr, die hier passieren muss.

## Offen (noch nicht begonnen)

- [ ] **Reserved Concurrency nachrüsten**, sobald das Lambda-Kontingent erhöht ist. Aktuell mit `0` deployt, weil das Konto es nicht anders zulässt.
- [ ] **Bekannter Rauer Kanten: Prompt-Injektionsversuche werden auf Deutsch abgewiesen**, auch wenn sie auf Englisch oder Spanisch geschrieben sind. Normale Themenablehnungen (Javi als Kandidat, Rechtsberatung) treffen die Sprache korrekt, verifiziert in DE, EN und ES. Nur der Injektionspfad fällt in die deutsche Stimme aus `identity.voice` zurück. Drei Prompt-Fassungen haben daran nichts geändert; der Schaden ist gering (ein Angreifer bekommt eine deutsche statt einer englischen Abfuhr), deshalb bewusst so gelassen. Wieder aufmachen, wenn es ein echtes Modell-Upgrade gibt oder jemand sich daran stört.
- [ ] **Antwortlänge im Alltag beobachten.** Nach dem Fix liegen die Antworten bei drei bis vier Sätzen, also am oberen Rand der Regel. Wenn sie im Widget zu wuchtig wirken, ist `max_sentences` in `prompt.py` bzw. `-MaxTokens` im Deploy die Stellschraube.
- [ ] Widget in `kettenki-website` (steht dort schon als offener Punkt: Katzen-Avatar, Zustände, `chat-mock.js`).
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
- **Reserved Concurrency ist zurzeit aus, nicht aus Überzeugung, sondern weil das Konto es verbietet.** Das Lambda-Kontingent für gleichzeitige Ausführungen steht auf 10, dem Wert für noch nicht hochgestufte Konten; AWS verlangt mindestens 10 unreservierte, also ist jede Reservierung unmöglich. Der Deploy scheiterte daran ("decreases account's UnreservedConcurrentExecution below its minimum value of [10]"). Praktisch wirkt das Kontingent selbst wie eine Obergrenze von 10, nur kontoweit statt pro Funktion: ein Amoklauf in Liviana könnte also andere Lambdas im selben Konto aushungern, statt nur sich selbst zu drosseln. Nach der Kontingenterhöhung mit `-ReservedConcurrency 5` neu deployen.
- **Der Mock kann Modellverhalten nicht prüfen, nur den Ablauf.** Alle vier Prompt-Defekte dieser Sitzung waren mit 56 grünen Tests unsichtbar und fielen erst beim ersten echten Bedrock-Aufruf auf. Für künftige Prompt-Änderungen gilt deshalb: nach dem Deploy mindestens einmal in DE, EN und ES gegenprüfen, mit einer Preisfrage, einer Frage nach technischen Interna und einer nach Javi als Kandidat.
- **Ein Deploy ist billig, ein falscher Default teuer.** `AllowedOrigin` hat deshalb bewusst keinen Vorgabewert mehr. Lieber ein abgebrochener Deploy mit fehlendem Pflichtparameter als ein stiller `*` in Produktion.
- **Der Content-Bucket überlebt einen `delete-stack`** (`DeletionPolicy: Retain`). Beim Aufräumen des fehlgeschlagenen ersten Versuchs musste er deshalb von Hand gelöscht werden, sonst wäre der zweite Deploy an "bucket already exists" gescheitert. Gleiche Falle bei jedem künftigen Neuaufbau von null.

## Offene Fragen an Javi

- ~~Region und Modell-ID?~~ **Entschieden: `eu-central-1` und `eu.anthropic.claude-haiku-4-5-20251001-v1:0`** (2026-08-21), in der Region als ACTIVE bestätigt und live im Einsatz.
- ~~Monatsbudget?~~ **Entschieden: 5 USD** (2026-08-21), Alarm bei 80 % Ist und 100 % Prognose an `info@kettenki.com`.
- ~~Öffentlich oder privat?~~ **Entschieden: öffentlich** (2026-08-21), wie `kettenki-bambera`.
- **Tagesdeckel 500 Aufrufe**: unverändert übernommen. Ob er für den echten Besucherstrom von kettenki.com großzügig oder knapp ist, weiß erst der erste Monat. Der Zähler steht in `liviana-limits` unter `BUDGET#<Datum>` und ist mit einem `scan` ablesbar.
- **Soll die Portfolio-Fiche `liviana.html` in `kettenki-website` jetzt einen Repo-Link bekommen?** Gleiche Frage, die dort schon für Bambera offen war.

## Session wieder aufnehmen

Kurzform für den Einstieg in eine neue Sitzung:

1. **Erst diese Datei lesen**, dann `liviana-arquitectura.md` (was geschlossen ist), dann `DECISIONS.md` (warum die Umsetzung so aussieht). `API.md` nur, wenn es um das Widget geht.
2. **Läuft es noch?** `python -m pytest tests -q` → 58 Tests grün, ohne AWS-Konto. Danach `python tools/chat.py` für einen Dialog gegen den Mock, und `python tools/smoke.py https://mr3w04rnrf.execute-api.eu-central-1.amazonaws.com` gegen die echte API (kostet ein paar Aufrufe vom Tagesbudget).
3. **Wo steht das Projekt?** Deployt und verifiziert in `eu-central-1`, Stack `liviana`. Lokal committet auf `main`, aber noch nicht auf GitHub. Der nächste Schritt steht oben.
4. **Was nicht wieder aufmachen:** alles unter "Verworfen". Besonders WAF, RAG, SAM/CDK und der Verlauf im Browser.
5. **Am Ende der Sitzung** diese Datei nachführen: Erledigtes nach unten in "Erledigt", Neues nach "Offen", Entscheidungen nach "Entscheidungen / Notizen", Datum in der Kopfzeile aktualisieren.
