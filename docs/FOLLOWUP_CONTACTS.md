# Follow-up contact discovery

JobIntel finds actual contact addresses supported by sources, rather than guessing recruiter email patterns.

## Action Center

A follow-up can show contacts from previously matched Gmail correspondence and explicitly listed job-description emails. The Find Contact Email button checks relevant Gmail messages, including Trash, for their From and Reply-To headers. Each option displays its source. A single strong employer-domain Gmail match may be prefilled.

Addresses from no-reply mailboxes, unrelated companies, third-party job boards, marketing, support, and unrelated roles are filtered out. If no dependable contact exists, no email address is invented, and the UI offers a Google research link.

## Optional web search

Gmail and job-description contact discovery works without an external search API. Optionally provide your own Brave Search API key in the local .env file as BRAVE_SEARCH_API_KEY, then rebuild/restart the backend. Brave may require payment details even when covered by monthly credits. A published address found in an apparent employer-domain search result is only a candidate for manual verification. Public-web addresses are never silently auto-sent.

Google Custom Search JSON API is closed to new customers in 2026, so JobIntel does not depend on it.

## Sending

The application still requires separate Gmail Send permission. After selecting a verified recruiting contact, review the recipient and message, click Review & Send via Gmail, and confirm. A successful Gmail API response does not guarantee the employer read or received it; check Sent and any delivery failures.

## Acceptance tests

- A Gmail application reply's Reply-To header is recommended for the correct tracked role.
- No-reply and unrelated-role addresses are not suggested.
- No reliable contact means a blank recipient, not an invented address.
- No contact search sends an email; every Send action remains explicit.
