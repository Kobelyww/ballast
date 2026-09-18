# Security Policy

## Scope

Ballast is an agent **runtime and benchmark**. Its default configuration is a
simulation: `env/world.py` is a SQLite database the process owns, and there are no
network calls in the test or eval path unless you point a provider at a base URL.

Treat these as in-scope if you build on it:

- **Tool-layer authority.** The design claim is that a model can *request* an action but
  cannot *authorise* one. If you can make a mutating tool act without a preceding
  deterministic computation, that is a vulnerability — `unverified_payment`,
  `amount_mismatch` and `over_refund` are meant to be unreachable.
- **Prompt-injected arguments.** Tool arguments are untrusted model output. Anything
  that reaches `validate()` without type and enum checking is a bug.
- **Replay store.** `llm/cache.py` writes responses to disk unencrypted. Do not put it
  on shared storage: cached prompts can contain customer records.
- **Budget enforcement as denial-of-spend control.** A ceiling must be checked *before*
  the billable call. A path where a run can exceed `max_cost` by more than one call is a
  defect.

## Out of scope

Findings against a real deployment of this code with real payment rails, real customer
data, or a model with production credentials. Nothing here is designed to hold money or
PII, and no part of it should be wired to a live refund endpoint without an approval
integration that your organisation actually enforces.

## Reporting

Open a private security advisory on https://github.com/Kobelyww/ballast/security/advisories
rather than a public issue. Expect a response within a week.

## Credentials

`BALLAST_LLM_API_KEY` / `DEEPSEEK_API_KEY` are read from the environment at runtime and
never written to disk, never logged, and never included in cache keys. `Settings`-style
config files are not read.
