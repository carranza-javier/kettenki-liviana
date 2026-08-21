# Liviana API contract

Everything the widget in `kettenki-website` needs. You should not have to read
any backend code to build against this.

- Base URL: the `ChatEndpoint` stack output, minus the `/chat` suffix
  (`https://<api-id>.execute-api.<region>.amazonaws.com`)
- Content type: `application/json` in both directions, UTF-8
- Auth: none. The API is public; abuse is handled by the limits below
- CORS: only the origin configured in `AllowedOrigin` may call it. Preflight is
  answered by API Gateway, so `OPTIONS` never costs an invocation

## Endpoints

| Method | Path      | Purpose                                     |
| ------ | --------- | ------------------------------------------- |
| POST   | `/chat`   | Send one visitor message, get one answer    |
| GET    | `/health` | Liveness check. Does not call the model     |

---

## POST /chat

### Request

```json
{
  "message": "Was macht Bambera?",
  "sessionId": "8f14e45fceea167a5a36dedd4bea2543"
}
```

| Field       | Type   | Required | Rules                                                                                                                                  |
| ----------- | ------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `message`   | string | yes      | Non-empty after trimming. Control characters are stripped. Anything past 1000 characters is **truncated**, not rejected — see `meta.messageTruncated` |
| `sessionId` | string | no       | 8 to 64 characters, `A-Z a-z 0-9 - _`. Omit it on the very first message and the server issues one                                       |

**Session handling.** Generate the id once when the widget opens (`crypto.randomUUID().replace(/-/g,'')` is exactly the accepted shape), keep it in `localStorage`, and send it with every message. The server does not set cookies and cannot recognise a returning visitor any other way. Server-side memory expires after 24 hours regardless, so a stale id simply starts a fresh conversation.

Alternatively: send the first message without `sessionId`, then store the
`sessionId` that comes back and reuse it. Both work; pick one and be consistent.

### Response 200

```json
{
  "answer": "BAMBERA digitalisiert Betriebshandbücher und macht daraus ...",
  "sessionId": "8f14e45fceea167a5a36dedd4bea2543",
  "meta": {
    "turnsInContext": 2,
    "elapsedMs": 812,
    "messageTruncated": false
  }
}
```

| Field                 | Type   | Notes                                                                                          |
| --------------------- | ------ | ---------------------------------------------------------------------------------------------- |
| `answer`              | string | Plain text. No markdown, no HTML. Render it as text, and convert `\n` to line breaks yourself   |
| `sessionId`           | string | Always present. Echoes what you sent, or the freshly issued one                                 |
| `meta.turnsInContext` | number | How many earlier exchanges were replayed to the model. Diagnostics only                         |
| `meta.elapsedMs`      | number | Server-side duration. Diagnostics only                                                          |
| `meta.messageTruncated` | boolean | True when the message was longer than 1000 characters and was cut. Worth telling the visitor  |

`answer` is never empty on a 200. Typical latency is one to three seconds; the
widget should show a typing indicator and allow up to 30 seconds before giving
up, because the API Gateway integration times out at 26 seconds.

### Error responses

Every error has the same shape:

```json
{
  "error": "rate_limited",
  "message": "Too many messages from this session (20 per minute).",
  "retryAfter": 34
}
```

| Status | `error`            | When                                                                         | `retryAfter` | What the widget should do                                                                                                 |
| ------ | ------------------ | ---------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------- |
| 400    | `bad_request`      | Missing or empty `message`, malformed `sessionId`, body is not JSON           | no           | A bug in the widget. Show a short local message; do not retry the same payload                                             |
| 429    | `rate_limited`     | More than 20 messages from this session inside the current minute             | yes, seconds | Show "einen Moment bitte" and disable the send button for `retryAfter` seconds. A `Retry-After` header carries the same value |
| 503    | `budget_exhausted` | The daily invocation limit (500) has been reached across all visitors         | no           | Show the fallback: the assistant is unavailable today, here is `info@kettenki.com`. Do not retry; it will not clear before midnight UTC |
| 502    | `upstream_error`   | Bedrock failed, timed out or returned nothing usable                          | no           | Transient. One retry after a couple of seconds is reasonable, then show the generic error state                             |
| 500    | `internal_error`   | Anything unexpected. Details stay in CloudWatch                               | no           | Generic error state                                                                                                        |
| 405    | `method_not_allowed` | Wrong HTTP method                                                          | no           | A bug in the widget                                                                                                        |

The `message` field is English developer-facing text. **Do not show it to
visitors** — branch on `error` and use your own localised copy.

### What counts against which limit

- A 400 costs nothing: it is rejected before any counter moves.
- The per-minute counter keys on `sessionId`. A request that arrives **without**
  one is counted against the caller's IP instead, so rotating session ids does
  not hand out a fresh allowance per message.
- A 429 does **not** consume the daily budget. The rate limit is checked first
  and, when it trips, the request stops there.
- Only requests that reach the model consume the daily budget. A 502 does
  consume one, because the invocation was attempted.

### Conversation memory

- The last **4 exchanges** of a session are replayed to the model with every
  message, oldest ones dropped first. The visitor can refer back to something
  said a few messages ago; they cannot refer to the start of a very long chat.
- Server-side memory expires **24 hours** after the last message of that
  session. Sending the same `sessionId` the next day starts from nothing.
- The widget does not need to send any history. Send only the new message.

---

## GET /health

```json
{ "status": "ok", "backend": "aws" }
```

Always 200 when the function is reachable. It does not touch Bedrock or
DynamoDB, so it is safe to poll and does not consume the daily budget. It is not
a check that Bedrock is healthy.

---

## Worked example

```js
const ENDPOINT = "https://<api-id>.execute-api.eu-central-1.amazonaws.com/chat";

function sessionId() {
  let id = localStorage.getItem("liviana-session");
  if (!id) {
    id = crypto.randomUUID().replace(/-/g, "");
    localStorage.setItem("liviana-session", id);
  }
  return id;
}

async function ask(message) {
  const response = await fetch(ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, sessionId: sessionId() }),
  });

  const body = await response.json();

  if (response.ok) return { answer: body.answer };

  switch (body.error) {
    case "rate_limited":
      return { retryAfter: body.retryAfter ?? 60 };
    case "budget_exhausted":
      return { unavailable: true };
    default:
      return { failed: true };
  }
}
```

### curl

```bash
curl -sS -X POST https://<api-id>.execute-api.eu-central-1.amazonaws.com/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Was ist KettenKI?","sessionId":"testsession0001"}'
```

---

## Behaviour of the answers

Rules enforced by the system prompt, so the widget can rely on them:

- **Language** follows the visitor's last message (German, English, Spanish),
  independent of the language the content document is written in. Nothing needs
  detecting in the widget — the model reads the message and answers in kind.
- **Scope** is KettenKI, its three solutions and how to get in touch. Anything
  outside that gets a short refusal pointing back at those topics. It never
  discusses the person behind KettenKI as a job candidate, and it speaks about
  Bambera and Fandango commercially — what they do and for whom — never about
  their technical internals. It knows it is Liviana itself, on display.
- **No prices.** Prototypes have no public price list; a price question gets
  the standard statement plus the contact address.
- **Short.** At most four sentences, plain text, no markdown.
- **Contact CTA** appears on buying intent or on anything it cannot answer, not
  on every answer.

To change any of that, edit the content document (`content/content.json`) and
re-upload it — see the README. The widget needs no change.
