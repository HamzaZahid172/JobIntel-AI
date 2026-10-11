# Enable Gmail Send for approved follow-up messages

JobIntel already reads application emails using `gmail.readonly`. Sending uses an **additional, optional** Google OAuth permission, `https://www.googleapis.com/auth/gmail.send`.

## One-time Google Cloud configuration

1. Open [Google Cloud Console](https://console.cloud.google.com/) and select the **same project** already used by JobIntel.
2. Open **APIs & Services → Library**. Search for **Gmail API**; enable it if it is not already enabled. No extra Gmail API library is required for Send.
3. Open **Google Auth Platform → Data Access → Add or remove scopes**. Add the scope **`https://www.googleapis.com/auth/gmail.send`**, in addition to the existing **`https://www.googleapis.com/auth/gmail.readonly`**. Save.
4. Under **Audience**, if External / Testing, ensure the Gmail address connected to JobIntel is a test user. Google's verification requirements may apply for broader distribution.
5. Under **Clients**, keep the existing **Web application** OAuth client with authorized redirect URI exactly **`http://localhost:8100/api/gmail/callback`**.

## Activate in JobIntel

1. Run `docker compose up -d --build` from the project root.
2. Open `http://localhost:3100` → **Action Center** → a due **Recruiter follow-up** card.
3. Click **Enable Gmail sending**. Sign in to the **same Gmail account** already connected to JobIntel. Approve the requested send permission.
4. Return to the existing Action Center tab and click **Check Gmail Permission**. The button should change to **Review & Send via Gmail**, without deleting your edits to the recipient, subject or body.
5. Verify the employer recipient (ideally from matched Gmail correspondence), edit the message, then click **Review & Send via Gmail** and confirm the destination.
6. A successful Gmail API response records that the message was sent; verify it in the Gmail **Sent** folder.

No email is sent by activating a permission or checking the account. **Only** the final explicit user-approved sending request calls Gmail `POST /gmail/v1/users/me/messages/send`.

The backend uses `httpx` (already in requirements) to make the REST API call; installing `google-api-python-client` is **not necessary**.

## Known limitations

- No sender/recruiter email can be safely guessed when the employer uses only a no-reply address or publishes no human hiring contact.
- OAuth errors may require reconnecting; Google's testing refresh tokens can expire.
- Gmail Send is a sensitive scope; public apps may need Google OAuth verification.
- The existing read-only scope remains separate. JobIntel must never use a different Google account to silently upgrade send permission.
- A Gmail API success result confirms acceptance by Gmail, not guaranteed delivery or an employer response.
- OAuth credentials, including client secrets, must be kept out of GitHub and screenshots.
