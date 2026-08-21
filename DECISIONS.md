# Decisions

What `liviana-arquitectura.md` closes is not re-argued here — stack, Claude
Haiku on Bedrock via Converse, JSON content in S3, sliding window of 3-4 pairs
in DynamoDB with TTL, no RAG, no WAF, the five free protection layers with 20
msg/min and 500 invocations/day, low temperature, and the system prompt rules.
This file records the implementation choices that document left open, and the
one place where it and `kettenki-website/SPEC.md` disagree.

## 1. Plain CloudFormation, not SAM or CDK

The function imports only the standard library and boto3, which the Lambda
Python runtime already provides. That makes packaging a plain zip of
`src/liviana` and removes any build step. SAM would add a required CLI install
(not present on this machine) and a build phase to solve a problem this project
does not have; CDK would add Node, a bootstrap stack and a synth step.

What is kept from those tools is the part that matters: the whole stack is one
declarative file and `scripts/deploy.ps1` / `deploy.sh` is idempotent, so
"deployable and reproducible" holds.

## 2. Two DynamoDB tables, not one

The document describes a `liviana-conversations` table keyed by `sessionId`,
and separately "a counter in DynamoDB" for each of the two limits. That is what
is built:

| Table                    | Key         | Item                                            |
| ------------------------ | ----------- | ----------------------------------------------- |
| `liviana-conversations`  | `sessionId` | `turns: [...]`, `expires_at`                    |
| `liviana-limits`         | `id`        | `hits`, `expires_at`; `RATE#<key>#<minute>` and `BUDGET#<day>` |

A single-table design would work too, and costs the same on-demand. Two tables
win on one operational point: wiping conversations is `delete-table` on one of
them and cannot disturb the counters, and vice versa.

An earlier draft of this backend stored one item per turn with a sort key. That
is a fine DynamoDB pattern but it is not what the document specifies, and it
changes the failure mode: turns accumulate until TTL instead of being bounded by
construction. Reverted to one item per session.

## 3. The window is trimmed on write, in the service

The service appends the new pair and keeps the last N, then writes the whole
window. DynamoDB cannot drop the oldest element of a list server-side, so this
is a read-modify-write — but the read already happened in step 3 of the flow, so
a whole exchange still costs one read and one write.

Consequence: two messages of the *same* session arriving at the same instant
could lose one turn. Visitors type serially and the rate limiter bounds the
rest, so this is accepted rather than defended against with a version attribute.

## 4. Both counters are enforced with a conditional update

`ADD hits :one` with `ConditionExpression: attribute_not_exists(hits) OR hits <
:limit`. One round trip, atomic, and when the condition fails nothing was
written — so a rejected request cannot consume budget. A read-then-write would
let two concurrent invocations both pass a limit.

## 5. Fixed windows, not sliding

The minute bucket comes from the clock, so a visitor can in the worst case send
2x the limit across a window boundary. A sliding window costs an extra read per
message to defend against an edge case that a public marketing chatbot does not
care about. The daily budget behaves the same way and resets at midnight UTC.

DynamoDB TTL deletes lazily, up to 48 hours late, so nothing relies on a row
being gone the instant it expires: every counter key contains its own window,
and an expired conversation item is treated as empty on read.

## 6. Order of checks: rate limit, history, circuit breaker, model

The cheapest rejection runs first. The circuit breaker is incremented
immediately before the paid call, so a 429 never spends one of the day's
invocations, while a failed Bedrock call does — the invocation was attempted and
may well have been billed.

## 7. Rate-limit key: the session, or the IP when there is no session

The document says "counter per `sessionId` (or IP if there is no session)". The
first message of a conversation genuinely has no session, so that branch is
real: a request without a `sessionId` is counted against the caller's IP.

This also blunts the obvious bypass. Rotating session ids only buys a fresh
allowance while the caller also rotates addresses — and the API Gateway throttle
and the daily circuit breaker are what cover that case.

Two visitors behind one NAT still get their own allowance, because a supplied
session id always wins over the IP.

## 8. Long messages are truncated, not refused

The document lists "trim the user's message if it is absurdly long" under the
`max_tokens` protections. So a message over 1000 characters is cut to 1000 and
the response carries `meta.messageTruncated: true`, rather than a 400 that would
make the visitor retype their question. Empty or malformed input is still a 400.

## 9. The session id is opaque and validated, and may be issued by the server

It becomes a DynamoDB partition key, so it is constrained to 8-64 characters of
`[A-Za-z0-9_-]` — which is exactly the shape of `crypto.randomUUID()` with the
dashes removed, as the document specifies for the frontend. The widget may also
omit it on the first message and keep whatever comes back. No cookie, no stored
IP, nothing that identifies a person.

## 10. `localStorage`, per the architecture document

`SPEC.md` §7.6 in the website repo says the history lives in the browser
(`sessionStorage`) and is replayed from the client; this document says DynamoDB
with TTL, and stores only the id on the client, in `localStorage`. **This
document wins** — it is the later decision and the safer one, since a
client-supplied history is a free way for anyone to inflate the input token
count of every request. The widget sends only the new message. API.md documents
`localStorage`; the 24-hour server-side TTL means a stale id simply starts a new
conversation.

## 11. CORS is configured on the API, not in the function

A preflight is answered by API Gateway and never reaches Lambda. The handler
still emits the same headers from the same configured value, so the function
also behaves correctly behind a Function URL or when invoked directly.

## 12. `GET /health` exists

It returns without touching Bedrock or DynamoDB, so it costs nothing to poll and
makes "is the deploy alive" a one-liner rather than a paid invocation. It is not
a check that Bedrock is healthy.

## 13. Instruction scaffolding in English, knowledge in the client's language

The system prompt's rules are model-facing product logic and are written in
English; the knowledge sections are passed through verbatim in whatever language
the content document is written in (German, here). Answer language is decided by
rule 1 — the language of the visitor's last message — which is what makes one
German document serve German, English and Spanish visitors, exactly as the
document intends.

## 14. "Not Bambera, not Fandango" lives in the content document

The rule that Liviana speaks as itself, is the live demo, and discusses the
other two solutions commercially rather than technically is a fact about this
client, so it sits in `identity.scope_note` in the content document and is
rendered into the role block. Changing it is a content edit, not a deploy.

## 15. Markdown is stripped from answers on the way out

The prompt asks the model for plain text, but models drift. Stripping in
`bedrock_model.py` means stray asterisks never reach the widget, which renders
text rather than HTML.

## 16. Answers and questions are not logged by default

`LIVIANA_LOG_MESSAGES` is off. Visitor messages are free text on a public site;
whether they end up in CloudWatch is a deliberate decision, not a debugging
convenience. Same reasoning as Bambera's `BAMBERA_LOG_QUERIES`.

## 17. Nothing client-specific in `src/`

Infrastructure names come from environment variables, and everything about
KettenKI — identity, knowledge, refusal topics, contact details, pricing stance
— lives in the content document. A test
(`test_no_client_data_is_hardcoded_in_the_source`) fails if a client string
appears anywhere under `src/`.

The consequence is that the shipped document is `content/content.json`, not
`content/kettenki.json`: the default path in `config.py` has to be
client-neutral. Which client it is, is stated inside the document.

## 18. `history_pairs` defaults to 4

The document says 3-4 pairs. Four is the top of that range. It is a single
environment variable, so lowering it is a one-line change if input cost turns
out to matter more than recall.

## 19. Content is cached in the execution environment for five minutes

A warm Lambda then costs one S3 GET every few minutes rather than one per
message — the document's "reads it at startup, or caches it". The price is that
a content edit takes up to five minutes to appear, which is documented in the
README and fine for a marketing document.

## 20. Bedrock Guardrails are not wired in

The document lists them as optional, to reconsider later. The system prompt plus
the deliberately narrow content document cover the same ground today at no extra
per-request cost. Adding them later is a parameter on the Converse call and no
change to the flow.
