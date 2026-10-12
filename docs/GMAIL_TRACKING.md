# Gmail Application Tracking

JobIntel can connect to Gmail using Google's OAuth 2.0 flow with the read-only Gmail scope.

## What it does

- Scans recent Gmail messages when JobIntel is open.
- Matches employer emails to applications already tracked in JobIntel.
- Detects common outcomes: Applied, Screening, Interview, Offer and Rejected.
- Updates the tracked application status only when the email signal is strong enough.
- Stores a Gmail event in JobIntel so the detected signal is visible beside the application.
- Never sends, deletes or modifies email.

## Google Cloud setup

1. Create or select a Google Cloud project.
2. Enable the Gmail API.
3. Configure the OAuth consent screen.
4. Create an OAuth 2.0 Client ID of type **Web application**.
5. Add this authorized redirect URI:

   `http://localhost:8100/api/gmail/callback`

6. Add these values to your local `.env`:

   ```env
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_GMAIL_REDIRECT_URI=http://localhost:8100/api/gmail/callback
   ```

7. Rebuild the backend:

   ```bash
   docker compose up --build
   ```

8. Open **Settings → Gmail application tracking → Connect Gmail**.

## Privacy

The integration requests only `gmail.readonly`. OAuth tokens are stored in the local JobIntel database so the application can refresh access and sync while you use the local dashboard. Do not commit your `.env` file.


## Full-email rejection detection and automatic synchronization (October 2026)

The old Gmail scanner classified only the subject and short snippet. Rejection language deep in messages such as OMMAX's 'we regret to inform you that we won’t be moving forward' could be missed. Messages now use Gmail format=full, with text/plain or nested text/html MIME decoding.

The Docker backend checks connected Gmail accounts about every 120 seconds, even when the UI tab is closed. Set GMAIL_AUTO_SYNC_INTERVAL_SECONDS (minimum 60 seconds) in .env to change this. This is periodic polling, not instant Gmail push: an update typically appears within a couple of minutes, plus up to 30 seconds for the UI refresh. Docker and a valid Gmail OAuth connection must remain active.

My Applications checks the last sync time every 30 seconds and refreshes when it changes. Rejected applications remain hidden in the active list, but a Recent rejection banner names companies and Show rejected (N) reveals the complete history. The manual Sync Gmail button remains available.

Scheduled checks scan up to 300 recent messages, using a 45-day lookback for the first connection scan and 7 days for routine checks. Existing events are deduplicated.

### Verify
1. Pull main and rebuild with docker compose up -d --build.
2. Confirm Gmail Connected under Settings.
3. Click My Applications → Sync Gmail once to backfill recent emails.
4. Click Show rejected to verify OMMAX is Rejected with a Gmail signal.
5. Leave Docker running to detect later updates automatically.
6. If needed, inspect docker compose logs --tail=100 backend for OAuth or network errors.

## Targeted Gmail outcome discovery and rejection review

When a general Gmail inbox contains hundreds of recent messages, relevant employer replies can fall outside the 300-message scan cap. JobIntel now also searches Gmail directly by company name for up to 12 recent open employers per scan, fetching up to 30 matching messages per employer and 150 *additional* unique messages in total. Trash is included, spam excluded. These results are matched to the correct application with existing safeguards. This increases the chance of finding an OMMAX-type rejection without requiring a manual email upload.

In **My Applications**, use the recent-rejection banner or **Show rejected → Review rejection** to view a source-grounded summary of the original employer email, a limited excerpt and practical suggestions. The backend retrieves the original rejection body on request with the already-authorized Gmail read-only scope. It does not archive the full email body in JobIntel. Recommendations do not claim an undisclosed ATS failure or a specific CV mistake.

This is best-effort Gmail polling, not an instantaneous Google notification. The local Docker backend must run, and the Gmail token must be valid. When debugging use My Applications → Sync Gmail and inspect the listed / matched / updated counts, then Docker backend logs. Authentication failures or unmatched company evidence still require investigation.

## October 12: Verify Gmail status per application

If a rejection is visible in Gmail but the application still says **Applied**, open
**My Applications**, find that application and click **Check Gmail Status**.
The new endpoint searches Gmail directly for that company's messages using your
already connected OAuth account, including Trash, instead of waiting for a full
mailbox-wide scan. It reports the connected Gmail address, matched rejections,
message counts, the resulting status and any API error.

If the result says no match, verify that the Gmail address is the *same*
account in which the rejection was received. Inspect Settings → Gmail and
backend logs. An OAuth connection alone does not guarantee successful syncing.

Successfully matched rejections are automatically marked **Rejected**, removed
from the default **active** view and retained under **Show rejected** for
rejection analysis. No application record or email is deleted.

Routine background scans prioritize employers before the general inbox, and
process fewer unrelated messages to reduce delay. Existing Gmail events with
confirmed outcomes are reconciled back onto the application record if the
status was changed incorrectly. This recovery does not turn unrelated mail
into rejection events.

### Repository hygiene

GitHub Actions workflow `cleanup-merged-branches.yml` checks `feature/*`
and `fix/*` branches after every `main` push. It deletes a branch only if
its exact head commit is the head of a merged pull request against `develop`
or `main`, after verifying the branch has not moved. `main`, `develop`,
protected branches and unmerged changes remain untouched.

## Automatic My Applications Gmail checks — no manual button

When **My Applications** is opened or the browser page is refreshed, JobIntel
renders saved applications immediately and asynchronously starts a **company-targeted
Gmail check**. It fetches recent messages for tracked active employers (including
Trash) without scanning a full general inbox, classifies real employer replies,
updates confirmed outcomes and redraws the list. Rejected roles move out of the
default active list automatically and stay in **Show rejected** for history.
A subtle status line shows whether the background check completed or could
not access Gmail. To avoid repeated requests on rapid navigation, same-tab
checks are debounced for 45 seconds. Reloading the browser starts a new check.
The existing server-side Gmail worker also polls periodically even when the
page is closed.

There is **no Check Gmail Status or Sync Gmail button** in My Applications.
The **Rejected** status is itself clickable when Show rejected is enabled.
It opens a rejection review with the actual employer reason where stated,
supporting email evidence, and practical non-speculative next steps. No email
or tracked application is deleted.

Gmail OAuth must be connected to the same account receiving the employer
response. Automatic checks are best-effort, not instantaneous Gmail push.
If the status indicator reports an error, open Settings → Gmail and inspect
the backend Docker logs; CI cannot connect to your personal live Gmail.

## Strict rejection evidence and revalidation (October 2026)

An application submission acknowledgment, even one stating that *other candidates
may be considered*, must never be classified as a rejection. JobIntel now
requires explicit employer language rejecting the applicant, such as
"We have decided not to move forward with your application" or the German
"Absage Ihrer Bewerbung". Vague terms like "other candidates", "leider nicht"
and "regret to inform" alone are not sufficient, and conditional hiring-process
explanations are ignored.

Older `gmail_events` rows marked Rejected by the previous classifier are
re-fetched using Gmail read-only permissions when the background worker
or My Applications page refresh runs. If the original email does not confirm
rejection, the event is corrected and the application returns to its latest
supported non-rejected state (or Applied when no other outcome exists).
If another verified rejection exists, it remains Rejected. This does not
delete messages or application history.

When you click Rejected in Show rejected, the review displays the **exact
original Gmail subject**, sender, received date, decision evidence where
available, and clearly separates employer-provided reasoning from advice.
If the email no longer supports rejection, JobIntel flags the disagreement
rather than manufacturing an employer reason. CI uses representative Workwise
submission and OMMAX genuine rejection samples; the connected Gmail account
must still be verified locally.
