# P2 — Google Sign-In and account interface

JobIntel supports optional Google account sign-in **separately from the Gmail tracking/sending authorization**. The sign-in request uses `openid email profile` only. It never asks for Gmail read, modify or send scopes.

## Required one-time Google Cloud setup

1. In your existing Google Cloud project, open **Google Auth Platform → Clients** and edit the OAuth Web application used by JobIntel.
2. Add **Authorized redirect URI:** `http://localhost:8100/api/auth/google/callback` (different from the existing Gmail callback).
3. Under Audience → Test users, add the Google account used for login if the app is in Testing mode.
4. Keep your existing `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` values private in root `.env`. The same OAuth Web client may be used for both flows when both exact redirect URIs are registered.
5. Make sure:
    ```ini
    GOOGLE_LOGIN_REDIRECT_URI=http://localhost:8100/api/auth/google/callback
    GOOGLE_LOGIN_FRONTEND_ORIGIN=http://localhost:3100
    ```
6. Rebuild the backend and frontend with `docker compose up -d --build --force-recreate backend frontend`.

## Existing JobIntel password account (important)

If you already have a local email/password JobIntel account, **sign in normally first** and go to **Settings → Google Sign-In → Link my Google account**. Google will ask for permission to verify your identity. Your Google email must match your JobIntel account email. The new Google subject is permanently mapped to that account. Once linked, you can sign out and use **Continue with Google** from Login.

An email match alone cannot create or claim a pre-existing password account. Google accounts with previously unused email addresses may create a new JobIntel profile. Local password login/create account remains available. Google OAuth for Gmail tracking is not a replacement for account sign-in.

## Security
- Cryptographically verify Google's signed OIDC ID token (issuer, audience, expiration) and email verification.
- Use random, one-time, eight-minute OAuth state and nonce; link states require an existing authenticated JobIntel account.
- Return a two-minute, one-use exchange ticket via postMessage to the configured exact frontend origin and registered popup window; the original Google identity token is never stored as a JobIntel session token.
- Browser exchanges one-use ticket for JobIntel's existing session token. No Google password, Gmail access token or other Google email access is saved by this feature.
- Google OAuth callback and local frontend must remain `localhost` during local testing; using a different origin or domain requires updating the configured redirect and trusted origin.

These backend unit tests simulate Google identity; **live Google Sign-In requires your real Google Cloud consent and redirect setup**, and cannot be claimed functional solely from CI.
