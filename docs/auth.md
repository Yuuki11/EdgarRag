# Authentication And Session Security

FinEdgar uses local email/password accounts with durable Postgres sessions. It
is designed to be safe to put behind HTTPS for public internet deployments while
remaining easy to test on a local network.

## Passwords

- Passwords are never stored in plaintext.
- The backend uses `pwdlib`'s recommended Argon2id password hash.
- Registration requires at least 12 characters.
- Password reset replaces the hash and revokes active sessions.

## Sessions

- Login creates a random opaque token.
- Only a keyed SHA-256 hash of the token is stored in Postgres.
- The browser receives `finedgar_session` as an HttpOnly cookie.
- Cookie defaults:
  - `HttpOnly=true`
  - `SameSite=Lax`
  - `Secure` from `FINEDGAR_AUTH_COOKIE_SECURE`
  - max age from `FINEDGAR_SESSION_DAYS`

Use `FINEDGAR_AUTH_COOKIE_SECURE=0` only for local HTTP testing. Public HTTPS
deployments should keep it at `1`.

## Email Verification And Reset

Registration creates an unverified user and an email verification token. Login
is rejected until the token is consumed. Forgot-password creates a separate
reset token.

Token properties:

- Stored as hashes, never raw values.
- Single-use.
- Expire according to `FINEDGAR_EMAIL_TOKEN_HOURS` or
  `FINEDGAR_PASSWORD_RESET_MINUTES`.
- Printed to logs in `console` email mode.
- Sent by SMTP in `smtp` email mode.

## Required Configuration

```text
FINEDGAR_AUTH_SECRET=long-random-secret
FINEDGAR_PUBLIC_BASE_URL=https://your-domain.example
FINEDGAR_AUTH_COOKIE_SECURE=1
FINEDGAR_EMAIL_MODE=smtp
FINEDGAR_EMAIL_FROM=FinEdgar <noreply@example.com>
FINEDGAR_SMTP_HOST=smtp.example.com
FINEDGAR_SMTP_PORT=587
FINEDGAR_SMTP_USERNAME=...
FINEDGAR_SMTP_PASSWORD=...
FINEDGAR_SMTP_STARTTLS=1
```

`FINEDGAR_AUTH_SECRET` is used when hashing session and email tokens. Rotating it
invalidates outstanding sessions and email/reset links.

## CSRF And Origins

The app uses same-origin cookies and `SameSite=Lax`. For unsafe authenticated
requests, the backend rejects present `Origin` or `Referer` headers that do not
match the request host, `FINEDGAR_PUBLIC_BASE_URL`, or
`FINEDGAR_ALLOWED_ORIGINS`.

For public deployments, run behind HTTPS and configure the proxy to preserve:

- `Host`
- `X-Forwarded-For`
- scheme/HTTPS behavior expected by your proxy stack

## Out Of Scope

- OAuth/OIDC
- Organization/team membership
- MFA
- Full rate-limit infrastructure

The `auth_events` table records auth activity and is intended as the future
anchor for rate limiting and audit views.

The standalone admin log console is documented separately in
[docs/admin.md](admin.md). It monitors Docker logs and does not grant access to
FinEdgar user accounts or chat data directly.
