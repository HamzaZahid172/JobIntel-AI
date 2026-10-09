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
