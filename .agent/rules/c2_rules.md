# C2 Rules: SRS Solar Daily Log

Project: SRS Solar Daily Log. The source of truth is docs/SPEC.md. Read it fully before any work and follow it.

- If anything is ambiguous, ask me before building. Do not invent requirements and do not silently skip any.
- Work only on the phase I name. Do not start later phases.
- The record date always comes from the report image, never from the system clock. All code takes time from the injected Clock.
- Only SRS KUMARAN data may be stored, shown, exported or logged. Never persist other customers' figures or the full uploaded image.
- All monthly jobs and file writes must be idempotent and atomic.
- Domain logic (totals, validation, remarks, month rules) is pure and has unit tests.
- Never hard-code secrets. Never log secrets or image content.
- Before writing code, verify third-party API details (Open-Meteo, Gemini) from their current official documentation and list what you verified.
- Every phase ends with: tests passing, a walkthrough, a list of spec items done, and a list of deviations or open questions.
- Do not delete or rewrite tests to make them pass. If a test is wrong, explain why and ask me.
- Ask before running any command that installs system software, deletes files, or touches anything outside this folder.
