# doTrack – family organizer

> **Disclaimer / Esclusione di responsabilità.** doTrack is provided *as is*, without any warranty: the authors accept **no responsibility or liability** for data loss, security problems, missed reminders, wrong information or any other consequence of using it. Read [DISCLAIMER.md](DISCLAIMER.md) before using it with real data. · Il software è fornito *così com'è*, senza garanzie: gli autori **non hanno alcuna responsabilità**. Leggi [DISCLAIMER.md](DISCLAIMER.md).

To-dos, deadlines and appointments shared by the family, in the same style as eaTrack.

- **Agenda**: everything still open, grouped by when (overdue, today, tomorrow, next 7 days, …), by list, category,
  person or priority, with a quick-add box that understands plain words: "dentista martedì alle 15:30 #salute @Sara !"
  becomes next Tuesday at 15:30, label *salute*, for Sara, high priority. Also: `oggi`, `domani`, `venerdì`, `15/11`,
  `24 dicembre`, `tra 2 settimane`, `fine mese`, `ogni lunedì`, `ogni 3 mesi`, `+lista`, `!bassa` (and the English
  equivalents). The words recognised are shown as chips while typing.
- **Lists and projects**: one level, no nesting. A *list* (shopping, packing…) is ticked off and its undated entries stay
  out of the agenda; "remove ticked" clears what was bought. A *project* ("Bathroom works") groups ordinary to-dos that
  also show in the agenda and calendar. Lists can be duplicated or saved as **templates** (the packing list, reused).
- **Shopping**: quantities ("2 kg mele", "latte x2"), grouping by supermarket aisle (guessed from the name, learned
  when you move something), suggestions of what was bought before, drag to reorder. **eaTrack** can send the weekly
  menu's foods to the list (see below).
- **Works offline**: the app and the last data stay on the device; ticks, additions, postponing and deleting made
  offline are sent when the connection is back. Changes made by the other person show up within a few seconds.
- **Quick actions**: swipe right to complete, left to postpone (tomorrow, weekend, next week…), "Undo" after
  completing, postponing or deleting; deleted things go to a **trash** for 30 days.
- **Chores in turn**: a repeating to-do can rotate between people (members or people without an account); the next one
  in turn is notified.
- **Labels**: free, coloured, several per item; filter the agenda by label.
- **Repeat from completion**: "every 3 months" can count from the day it was done instead of the due date.
- **Comments and history** on every item: who created, changed and completed it.
- **Deadlines**: car tax, insurance, inspection, driving licence, ID card… with a countdown, a repetition
  (every year, every 10 years, …) and a reminder N days before. Marking one done creates the next occurrence.
  Ready-made suggestions are one tap away.
- **Appointments**: date, time, place, the **questions to ask** and, during the visit, their **answers**;
  notes on the outcome and **attached reports** (PDF, photos, documents). Past appointments stay browsable
  per person ("about": Giulia, the car, …).
- **Calendar**: month, week and day views (with the hours; tap a free time to add an appointment).
- **Shared**: invite your partner with a link; every item can be assigned to one of you or to "anyone",
  and every list can be filtered by person.
- **Google Calendar**: each user gets a private iCal address to subscribe to from Google Calendar
  (or Apple Calendar / Outlook). Each item also has a one-off "Add to Google Calendar" link.
- **Two-way sync (CalDAV)**: Reminders and Calendar on iPhone/Mac, Tasks.org + DAVx⁵ on Android, Thunderbird… see and
  change the same items. Each list is its own calendar.
- **Notifications**: a bell in the app, and push notifications on phones and computers (Web Push, no external
  account needed): each reminder at its day and time (default: the morning, or one hour before a same-day appointment),
  and a notice when someone assigns you something, completes what was yours or comments.
- **Reminder email**: a morning email with what is due today, what is coming up (from each item's reminder day)
  and, on Mondays, what is overdue. Can be turned off per user.

- `backend/` – Flask API + SQLite (waitress, port 3001)
- `frontend/` – Svelte + Vite interface, built into the Docker image

> **Made with AI.** Like eaTrack, this project was written by an AI assistant (Anthropic's Claude) and checked
> with automated tests; review it before exposing it to the internet.

## Running with Docker

The code shared with the other family apps is in the `backend/famkit` submodule
([famkit](https://github.com/filippogiuliani/famkit)): clone with
`git clone --recurse-submodules https://github.com/filippogiuliani/dotrack.git`, or run `git submodule update --init` in a
clone made without it.

```sh
cp .env.example .env    # set DOTRACK_URL, SMTP and optionally Google sign-in
./rebuild.sh
```

Data lives in `./doTrack_data/` (mounted on `/app/data`): `dotrack.db`, `files/` (attachments) and `backups/`
(one automatic database backup a day). **Back up `files/` too**: database backups don't include attachments.
`.vapid_private.pem` is the key that signs push notifications: if it is lost a new one is created, and each device
just has to turn notifications on again.

Suggested setup for a family: sign up yourself, invite your partner from the Family page, then set
`DOTRACK_SIGNUP=closed` so nobody else can create an account.

### Google Calendar
The feed is read by Google's servers, so the app must be reachable from the internet at `DOTRACK_URL`
(e.g. behind the same reverse proxy as eaTrack). Google refreshes subscribed calendars on its own schedule,
usually every few hours, so changes are not instant. The address contains a secret token: whoever has it
can read the events. It can be regenerated from the Family page.

Why a feed and not two-way sync: the Google Calendar API needs a Google Cloud project with a verified OAuth
consent screen for the calendar scope (in "testing" mode tokens expire every 7 days). The feed needs none
of that and works with every calendar app.

### Sync with phone apps (CalDAV)
Family page → *Sync with other apps*: it shows the server address (`<DOTRACK_URL>/dav/`), the user name (the email)
and creates an **app password** per device (the account password is never used, and accounts that sign in with Google
work too). Revoking it disconnects that device only.

- iPhone/iPad: Settings › Apps › Calendar › Calendar Accounts › Add Account › Other › Add CalDAV Account.
- Android: DAVx⁵ ("Login with URL and user name") plus Tasks.org or jtx Board for the to-dos.
- Thunderbird: New calendar › On the network › CalDAV.

To-dos and deadlines are VTODOs, appointments, notices and birthdays VEVENTs; title, notes, date and time, place,
priority, repetition, labels (categories), reminder and done/not done go both ways. Who is in charge, category,
"about", questions/answers, attachments and comments stay in the app and are kept when a phone sends a change.
An item with attachments can't be deleted from a phone (the reports would go with it). The app must be reachable
over HTTPS; the reverse proxy must pass `/dav/` and `/.well-known/caldav` with any HTTP method (PROPFIND, REPORT…).

### Push notifications
Nothing to configure: the server creates its own signing key. Each person turns them on per device from the Family
page. On iPhone they only work from the app added to the Home Screen (Safari › Share › Add to Home Screen, iOS 16.4+).
HTTPS is required (or `localhost`).

### Sign-in, two-step verification, sessions
- Email and password, and/or any OpenID Connect provider: Google, Microsoft, Authentik, Authelia, Keycloak, Pocket ID,
  Zitadel… (`DOTRACK_OIDC`, see `.env.example`). With `DOTRACK_PASSWORD_LOGIN=0` sign-in and sign-up only go through
  the providers (configure at least one!).
- Two-step verification (TOTP, any authenticator app) with 10 single-use recovery codes, from the Family page. It applies
  to password sign-in; OIDC sign-ins rely on the provider's own security. App passwords (CalDAV) and API tokens are
  separate keys, revocable one by one.
- "Sign out of all other devices" in the Family page.

### Integrations (API, Home Assistant, webhooks)
- **API tokens** (Family page → Integrations): `Authorization: Bearer dt_…` gives access to the same API the app uses, for
  the family the token was created in. Not allowed with a token: account, security, sign-in keys, invitations, webhooks.
- `POST /api/lists/<id>/items` with `{"items": ["latte", "2 kg mele"]}` adds several things at once (skipping those
  already on the list); `GET /api/summary` returns overdue/today counts, today's appointments and what is left on each
  list (handy for a Home Assistant REST sensor; examples in the app).
- **Webhooks** (family admin): on every change a JSON POST `{event, family_id, actor_id, at, data}` to your address,
  signed with HMAC-SHA256 of the body in `X-doTrack-Signature: sha256=<hex>`. Events: `item.created`, `item.updated`,
  `item.done`, `item.reopened`, `item.deleted`, `comment.created`.
- **eaTrack**: create a token here, then in eaTrack → Family → "Shopping with doTrack" paste doTrack's address and
  the token and pick the list. The weekly plan gets a button that sends the menu's foods to that list.

### Reminder emails
They need a working SMTP server (`DOTRACK_SMTP_*`) and a confirmed email address. They are sent after
`DOTRACK_REMINDER_HOUR` (default 8, in `TZ`), at most once a day per user, and only when there is something to say.

## Administration (command line)
```sh
docker exec dotrack python manage.py backup          # backup right now
docker exec dotrack python manage.py backups         # list backups
docker exec dotrack python manage.py users           # users and families
```

## Development
```sh
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
cd backend && ../.venv/bin/python app.py      # API on :3001
cd frontend && npm install && npm run dev     # UI on :5173, proxying /api
.venv/bin/python -m pytest                    # tests, from the project root
cd frontend && npm test                       # quick-add parser tests (Node)
```
The tests use a fresh temporary database each time and never send email.

## Languages
Italian (default) and English. Interface: `frontend/src/lib/locales/`; server messages and emails: `backend/i18n.py`.

## License
[MIT](LICENSE). No warranty and no liability: see [DISCLAIMER.md](DISCLAIMER.md).

## weHub (one sign-in and one family for all the family apps)
Optional. With `DOTRACK_HUB_URL` and `DOTRACK_HUB_KEY` set (see `.env.example` and weHub's README), doTrack signs people in
only through the OIDC provider (the same Pocket ID as weHub), and takes the family from weHub: members, roles,
people and who may use doTrack. The family, members and people become read-only here, with a link to weHub; the copy is
refreshed every 2 minutes and keeps working if weHub is down. Existing data is adopted, not recreated: run weHub's
**Import** once (it reads `GET /api/hub/export` with the key). A family someone had made on their own can be merged into the shared one from weHub's import (`POST /api/hub/merge`: a database backup first, then everything moves; people and labels with the same name become one). Without these settings doTrack works on its own as before.
