# Dashboard refresh and account navigation

## What changed
- Removed the non-actionable sidebar **Local-first / Free job feeds + local CV analysis** banner. The sidebar now ends with an account control.
- Clicking the profile at the bottom-left or the top-right avatar opens a **real account menu** showing the signed-in email, Account & Settings, Switch account / Sign in, and Log out. Switching accounts safely invalidates the current session through the existing `/api/auth/logout` endpoint before presenting the existing Login / Create Account forms.
- Added a dashboard-only **Update dashboard** control and an automatically updating status line. The dashboard refreshes its PostgreSQL-backed application and vacancy snapshot every 45 seconds while the Dashboard is visible and the browser tab is active; after returning to the tab, it refreshes if more than 45 seconds have elapsed.
- Dashboard metrics show **Applications Tracked**, **Awaiting Replies**, **Interview Stages**, **Rejections**, **Offers**, posted-today jobs, relevant jobs and ATS readiness. Rejections remain in the user's application history. The pipeline shows Rejected explicitly instead of inaccurately describing all tracking as manual.
- Stale employer job feed snapshots are labeled as potentially stale. **Update dashboard** reads saved data; it does not fetch new employer postings. **Refresh Current Jobs** still runs external source collection only on explicit user action.

## Login scope
JobIntel currently supports existing local email/password **Login** and **Create account**. Gmail OAuth is **for email tracking/send permissions**, not login. Google Sign-In is not implied or advertised by the new account menu. Adding a separate login provider requires a complete sign-in OAuth/security migration and is not part of this user-interface fix.

## Verify locally
1. Pull main and rebuild with `docker compose up -d --build --force-recreate frontend backend`, without `-v` or deleting the PostgreSQL/data volumes.
2. Open `http://localhost:3100/#dashboard`. There should be no blue Local-first sidebar banner, and the status line should show the time of the last successful data check.
3. Check Dashboard's Rejections value against **My Applications → Show rejected**. The dashboard displays all tracked applications including rejected.
4. Open the top-right avatar or bottom-left account control. Verify Account & Settings navigation, Switch Account, Login / Create Account and Logout; save any work before switching.
5. Leave the dashboard open, verify the last-checked time changes after roughly 45 seconds. Return to the tab after >45 seconds and verify it updates. Backend Gmail sync continues independently while Docker is running; the Dashboard does not promise instant employer responses.
6. CI runs backend tests, JavaScript syntax checks, and dedicated dashboard/account contract tests. An end-to-end live browser session still requires local verification.

