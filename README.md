# Liviana

Backend for the public website assistant: an HTTP API that takes one visitor
message plus a session id and returns one short, grounded answer.

The widget that calls it lives in the `kettenki-website` repo and is not part
of this one. The contract between the two is [API.md](API.md); the decisions it
implements are in [liviana-arquitectura.md](liviana-arquitectura.md), and the
implementation choices that document left open are in [DECISIONS.md](DECISIONS.md).

```
browser widget
      |
      v
API Gateway (HTTP API)  --- throttling, CORS
      |
      v
Lambda (Python, no dependencies)
      |         \
      |          \--> S3          content document (who the assistant is, what it knows)
      |          \--> DynamoDB    liviana-conversations: the sliding window, TTL 24h
      |          \--> DynamoDB    liviana-limits: rate limit + daily counter, TTL
      |           \-> Bedrock     Claude Haiku via Converse, low temperature
```

Two backends, one code path:

| `LIVIANA_BACKEND` | Content    | State                | Model            | Needs AWS |
| ----------------- | ---------- | -------------------- | ---------------- | --------- |
| `mock`            | local file | one local JSON file  | keyword matcher  | no        |
| `aws`             | S3         | two DynamoDB tables  | Bedrock Converse | yes       |

The mock is not a sketch: same flow, same limits, same windows, same expiry
semantics. What you see in the terminal is what the widget gets.

---

## Layout

```
content/content.json      the KettenKI knowledge document -> uploaded to S3
src/liviana/
  app.py                  Lambda handler: parse, delegate, map errors to statuses
  service.py              the conversation flow (the only place it is written down)
  prompt.py               system prompt construction and the safety rules
  config.py               every environment variable, one place
  ports.py                the seams: content, conversations, limits, model
  errors.py               error -> HTTP status, the source of truth for API.md
  factory.py              wires the ports to the selected backend
  adapters/               local + AWS implementation of each port
infra/template.yaml       the whole stack, plain CloudFormation
scripts/deploy.ps1|.sh    package, deploy, upload content
tools/chat.py             terminal client
tools/smoke.py            verifies a deployed API against API.md
tests/                    58 tests, no AWS needed
```

---

## Running it locally

Python 3.11 or newer. No install step, no virtualenv needed for the mock
backend — it uses only the standard library.

```powershell
python tools/chat.py
```

```
Liviana [mock]
  model=mock-model temp=0.2 history=4 pairs  limits=20/min, 500/day
  session 3616319564c8439397c78c051546ad8b  (/quit to leave)

you> Was ist Bambera?
  Digitale Assistentin für dein Team. BAMBERA digitalisiert Betriebshandbücher ...
  (0 turns in context, 78 ms)

you> Und was noch?
  Zu BAMBERA: Sofortiger Zugriff auf operatives Wissen; Effiziente Kundenberatung ...
  (1 turns in context, 103 ms)
```

One question and out:

```powershell
python tools/chat.py -m "Was kostet Liviana?"
```

### Commands inside the session

| Command    | Shows                                                        |
| ---------- | ------------------------------------------------------------ |
| `/history` | what is stored for this session right now                     |
| `/prompt`  | the exact system prompt being sent to the model               |
| `/state`   | session count and today's invocation count                    |
| `/new`     | a fresh session id, which drops the memory                    |
| `/flood N` | N messages in a row, to watch the rate limiter trip           |
| `/quit`    | leave                                                         |

### Watching the protections work

```powershell
# rate limit: the 21st message inside one minute is refused
python tools/chat.py
you> /flood 22
  ...
  #21   [429 rate_limited] Too many messages from this session (20 per minute). (retry in 24s)

# circuit breaker: lower the daily ceiling and blow through it
$env:LIVIANA_DAILY_INVOCATION_LIMIT=3
python tools/chat.py -s testsession01 -m "Was ist KettenKI?"   # x4 -> the 4th is 503
```

Local state lives in `.liviana-state.json` (gitignored). Delete it to start clean.

### Tests

```powershell
python -m pytest tests -q
```

They cover the flow, both limits, the error contract and the guarantee that no
client-specific string has crept into `src/`.

---

## Deploying to AWS

### What you need to prepare, once

1. **AWS CLI configured** with credentials that can create IAM roles, Lambda,
   API Gateway, DynamoDB, S3, CloudWatch, SNS and Budgets.
   Check with `aws sts get-caller-identity`.
2. **Bedrock model access enabled** for Claude Haiku in your region. Bedrock
   console → *Model access* → enable the Anthropic models. This is a one-off
   manual step that no template can do for you, and the deploy will look fine
   while every request fails with `AccessDeniedException` until it is done.
3. **The model id that actually exists in your region.** The default is
   `eu.anthropic.claude-haiku-4-5-20251001-v1:0` (an EU cross-region inference
   profile). Verify before deploying and override `-ModelId` if it differs:
   ```powershell
   aws bedrock list-inference-profiles --region eu-central-1 `
     --query "inferenceProfileSummaries[?contains(inferenceProfileId,'haiku')].inferenceProfileId"
   ```
4. **A globally unique bucket name** for the content document, e.g.
   `kettenki-liviana-content`.
5. **An email address** for budget and alarm notifications. AWS sends a
   confirmation mail for the SNS subscription; until you click it, the alarms
   are silent.

Nothing else. No SAM CLI, no Docker, no `pip install -t`: the function imports
only the standard library and the boto3 that the Lambda runtime already
provides, so packaging is a zip of `src/liviana`.

### Deploy

```powershell
./scripts/deploy.ps1 `
  -ContentBucketName kettenki-liviana-content `
  -AlertEmail info@kettenki.com `
  -AllowedOrigin https://kettenki.com `
  -MonthlyBudgetUsd 5 `
  -ReservedConcurrency 0
```

> `-ReservedConcurrency 0` leaves the reservation unset. It is needed on an
> account whose Lambda "Concurrent executions" quota is still the
> unverified-account default of 10, because AWS refuses any reservation that
> drops unreserved capacity below 10. Raise that quota, then redeploy with `5`.

or, on bash:

```bash
CONTENT_BUCKET=kettenki-liviana-content \
ALERT_EMAIL=info@kettenki.com \
ALLOWED_ORIGIN=https://kettenki.com \
./scripts/deploy.sh
```

The script creates an artifact bucket if needed, zips and uploads the function
under a hash-named key, deploys the stack, uploads the content document and
prints the outputs, including the URL the widget needs. It is idempotent —
re-run it after any change.

Useful overrides: `-Region`, `-ModelId`, `-RateLimitPerMinute`,
`-DailyInvocationLimit`, `-ReservedConcurrency`, `-MonthlyBudgetUsd`,
`-StackName`, `-AwsProfile`.

> `-AllowedOrigin` is mandatory and has no default. It is the one parameter
> where a convenient `*` would quietly let any page on the internet spend the
> daily budget, so the deploy refuses to guess it.

### Verify

```powershell
python tools/smoke.py https://<api-id>.execute-api.eu-central-1.amazonaws.com
```

It checks health, a first answer, that the follow-up sees the previous turn,
session issuing, and the 400 cases. `--flood 25` also exercises the rate limit;
each message costs one real invocation, so use it deliberately.

**The smoke suite proves the plumbing, not the answers.** The mock model is a
keyword matcher, so nothing local can tell you whether the model keeps to four
sentences, refuses to invent a price, or answers in the visitor's language.
After any change to `prompt.py` or to the content document, ask the live API at
least one question in each supported language, plus a price question, a
"what's inside Bambera" question and one about the person behind the company.
Four real defects were found exactly that way, with the whole test suite green.

### Changing the content afterwards

Editing `content/content.json` is how you change what the assistant knows and
how it behaves — no code change, no redeploy:

```powershell
aws s3 cp content/content.json s3://kettenki-liviana-content/content.json `
  --content-type application/json
```

Live within five minutes (the in-process cache TTL), sooner on a cold start.
The bucket is versioned, so a bad edit is one `aws s3api list-object-versions`
away from being rolled back.

---

## The five cost protections

| Layer                     | Where                       | Default        | Stops                                                     |
| ------------------------- | --------------------------- | -------------- | --------------------------------------------------------- |
| Reserved concurrency      | Lambda                      | 5, or 0 to skip | Runaway parallelism, and isolates the account pool        |
| API Gateway throttling    | stage route settings        | 10 rps, 20 burst | Floods from any number of sessions, before Lambda runs    |
| Rate limit per session    | DynamoDB conditional update | 20 / minute    | One visitor hammering the widget                          |
| Daily circuit breaker     | DynamoDB conditional update | 500 / day      | The total spend of one day, whatever the traffic          |
| Message length cap        | Lambda                      | 1000 chars     | An enormous paste inflating the input token count         |
| Budget alarm              | AWS Budgets + SNS           | 10 USD / month | Nothing — it tells you, at 80% actual and 100% forecast   |

No WAF: a fixed monthly charge from the first minute, for a demo whose real
risk these free layers already cover. If real bot traffic ever gets past them,
WAF with Bot Control is the next step.

The two counters use a single conditional `UpdateItem`, so two concurrent
invocations cannot both slip past a limit, and a rejected request never consumes
budget. The per-minute counter keys on the session id, or on the caller's IP
when the request carries no session yet. Both windows are fixed, not sliding —
see the note in `adapters/dynamo_store.py` for why.

**Bedrock Guardrails** are deliberately not wired in: the architecture document
lists them as optional, to be reconsidered later. The system prompt plus the
scoped content document do the same job today at no extra per-request cost. If
they are added, it is one parameter on the Converse call and no change to the
flow.

Alarms also fire when the circuit breaker opens (a log metric filter), when the
function errors three times in five minutes, and when reserved concurrency
throttles anything.

### Rough cost at the defaults

500 invocations a day is the ceiling, not the expectation. At that ceiling, with
~2500 input and ~200 output tokens per call on Claude Haiku, Bedrock is the only
line item that matters; Lambda, DynamoDB on-demand, S3 and the HTTP API stay in
cents at this volume. Set `-MonthlyBudgetUsd` to a number you would be annoyed
but not hurt by, and let the alarm tell you if reality disagrees.

---

## Operating notes

- **Logs**: `/aws/lambda/liviana-chat`, 14-day retention. One line per request
  with session prefix, turns replayed and latency. Questions and answers are
  *not* logged unless you set `LIVIANA_LOG_MESSAGES=true` — that is a privacy
  decision, not a debugging convenience.
- **Stack deletion**: the content bucket has `DeletionPolicy: Retain`, so
  `cloudformation delete-stack` will not silently destroy the knowledge
  document. Empty and delete it by hand if you really mean it.
- **Wiping conversations** is `aws dynamodb delete-table` on
  `liviana-conversations` plus a redeploy, and it never touches the counters —
  that is why they live in `liviana-limits` instead of the same table.
- **Rolling back code**: every deploy uploads a hash-named zip, so pointing the
  `LambdaCodeKey` parameter at a previous key redeploys that exact build.

Every configuration knob is listed with its meaning in
[.env.example](.env.example); the decisions behind the design are in
[DECISIONS.md](DECISIONS.md).
