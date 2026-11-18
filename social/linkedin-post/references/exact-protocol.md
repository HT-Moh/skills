# Exact scheduling preview protocol

`post_linkedin.py --protocol storyproof.linkedin/1` reads one bounded JSON request
from stdin and writes one JSON result. Protocol mode cannot be mixed with legacy flags.
Current operations: `capabilities`, `preview_exact`. **`schedule_exact` is unavailable.**
This boundary never submits a post.

## Capabilities

```json
{"protocol":"storyproof.linkedin/1","op":"capabilities","request_id":"cap-1"}
```

Response includes `operations`, `payload_types: ["text"]`, `schedule_exact: false`
and `runtime_digest`. Capabilities make no browser call. Node must be installed.
Runtime identity hashes the captured local Python/JS sources, package manifests,
Node dependency files and Python/Node version strings. A preview executes a private
copy of those admitted files, so editing the installed sources cannot change that run.
Capture uses descriptor-relative, no-follow reads and bounded file, byte, directory,
entry, depth and elapsed-time budgets. Interpreter binaries, standard libraries and OS
remain trusted; version strings are identifiers, not binary attestation.
The browser is external; its authenticated identity and timezone are observed separately.

## Exact preview request

```json
{
  "protocol": "storyproof.linkedin/1",
  "op": "preview_exact",
  "request_id": "preview-1",
  "text": "Exact approved text.\n",
  "text_sha256": "<SHA256 of exact UTF-8 text>",
  "account_url": "https://www.linkedin.com/in/concrete-member/",
  "scheduled_at": "2026-11-24T07:30:00Z",
  "account_timezone": "Europe/Zurich",
  "audience_timezone": "Europe/Zurich",
  "min_lead_hours": 12,
  "runtime_digest": "<digest returned by capabilities>"
}
```

Required: whole-minute UTC instant, known IANA zones, sufficient remaining lead,
unambiguous wall clock in both zones, exact content digest and unchanged runtime.
Only plain text, personal accounts and public audience are currently supported.
Unknown fields, media, documents, company actors and retained nonempty drafts refuse.
No whitespace trimming or normalization is performed.

`preview_verified` means:

- Authenticated feed's concrete own-profile URL matches the requested account.
- Composer's current checked actor option identifies the personal `Self` actor.
- The actor popup's DOM portal and React references both identify the specific
  composer control opened by this invocation.
- Supported ProseMirror paragraphs serialize to the exact requested text, including
  blank paragraphs, repeated spaces and trailing newline.
- Full date/time fields match the request.
- LinkedIn's correlated `ConfirmSchedulePost` response sets the expected UTC
  milliseconds through an unconditional state update. Only the request created
  during the intended Confirm action can qualify; contradictory or duplicate
  responses observed before final verification refuse the preview.
- Browser timezone matches the requested account timezone; minimum lead still holds.

The protocol observes current LinkedIn SDUI structures. This is a version-specific
browser adapter, not a stable LinkedIn API or server identity attestation.
Unsupported structure returns `refused_pre_effect`; it never falls back to legacy
success rules or guesses from display name.

Response includes `evidence`, `runtime_digest` and `artifacts_dir`. Inspect screenshots
there. Temporary runtime copies are removed; screenshots are retained for review.
Use `TMPDIR` to select artifact parent directory. Receipt storage and package approval
belong to the caller. Persist this evidence before final package approval because its
addition changes the reviewed package.

**A verified preview is not scheduling authority or a scheduling receipt.** Future
dispatch requires durable operation-bound intent, a pre-submit handshake and positive
remote acknowledgment. Missing replies after a submit must remain uncertain.

## Process and profile ownership

Machine mode requires Linux pidfds and subreaping. A writable delegated cgroup-v2
scope contains descendants when available; otherwise a dedicated synchronous CLI
scope is admitted only with no preexisting descendants. Unsupported nested fallback
scopes refuse before launching children, rather than guessing adopted-child ownership.
Both Python worker and
Node driver use the same bounded collector (1 MiB combined stdout/stderr). Teardown
shares a 10-second TERM phase and 2-second KILL/reap phase across owned descendants.
These deadlines are cooperative; discovery and kernel/filesystem operations must return.

Run and login acquire the same kept-profile lease. Ownership is recorded before launch.
Successful teardown clears the marker; incomplete cleanup leaves the profile quarantined.
An abrupt supervisor SIGKILL can leave descendants alive, but closing every inherited
lease descriptor does not clear the persistent marker or permit another browser run.
Active or quarantined profiles refuse instead of killing a browser based on its command line.

The lease file is `.linkedin-poster.lease` inside the configured profile. A nonempty
marker requires investigation of the previous run and its processes before explicit
operator recovery. Do not automatically delete the lease or singleton files to retry:
absence of a live flock alone does not establish that the earlier browser stopped.
