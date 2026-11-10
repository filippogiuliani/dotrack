"""Server-side translations: error messages, emails and calendar/reminder texts.
Source texts are in English; Italian translations below."""
import re

from flask import g, has_request_context, request

LANGUAGES = ['it', 'en']
DEFAULT = 'it'


def normalize(value):
    v = str(value or '').lower()[:2]
    return v if v in LANGUAGES else None


def language():
    """Request language: user profile > X-Language header (from the frontend) > Accept-Language > default."""
    if not has_request_context():
        return DEFAULT
    user = getattr(g, 'user', None)
    if user and normalize(user.get('language')):
        return user['language']
    return (normalize(request.headers.get('X-Language'))
            or request.accept_languages.best_match(LANGUAGES)
            or DEFAULT)


IT = {
    'The family is managed in weHub': 'La famiglia si gestisce in weHub',
    'You cannot use this app: ask the family admin in weHub': "Non puoi usare quest'app: chiedi all'amministratore della famiglia in weHub",
    'weHub is not reachable, please try again in a moment': 'weHub non è raggiungibile, riprova tra poco',
    'To sign up you must accept the privacy notice': "Per registrarti devi accettare l'informativa privacy",
    "You're the only member: to delete the family, delete your account": "Sei l'unico membro: per eliminare la famiglia elimina l'account",
    'Sign in or sign up to accept': 'Accedi o registrati per accettare',
    'Sign-in failed, please try again': 'Accesso non riuscito, riprova',
    'Sign-in required': 'Accesso richiesto',
    'Sign-up expired: please try again': 'Registrazione scaduta: riprova',
    'Invalid email': 'Email non valida',
    'Wrong email or password': 'Email o password errati',
    'An account with this email already exists': 'Esiste già un account con questa email',
    'Family not found': 'Famiglia non trovata',
    'Name is required': 'Il nome è obbligatorio',
    'The provider did not return an identifier': 'Il provider non ha fornito un identificativo',
    'The provider did not return a verified email address': 'Il provider non ha fornito un indirizzo email verificato',
    "Set a password first, otherwise you couldn't sign in anymore": 'Imposta prima una password, altrimenti non potresti più accedere',
    'Invalid or expired invitation': 'Invito non valido o scaduto',
    'Sign-up is by invitation only': 'La registrazione è possibile solo su invito',
    'Invalid or expired link': 'Link non valido o scaduto',
    'Member not found': 'Membro non trovato',
    'No file uploaded': 'Nessun file caricato',
    'No family associated': 'Nessuna famiglia associata',
    'No sign-up in progress': 'Nessuna registrazione in corso',
    'Origin not allowed': 'Origine non consentita',
    'Current password is wrong': 'Password attuale errata',
    'Password too long': 'Password troppo lunga',
    'Provider not configured': 'Provider non configurato',
    'This account is already linked to another user': 'Questo account è già collegato a un altro utente',
    'Only the family admin can do this': "Solo l'amministratore della famiglia può farlo",
    'Too many attempts, try again in a few minutes': 'Troppi tentativi, riprova tra qualche minuto',
    'Type your email to confirm': 'Scrivi la tua email per confermare',
    'Invalid request (JSON expected)': 'Richiesta non valida (atteso JSON)',
    'invalid family_id': 'family_id non valido',
    "{name}'s family": 'Famiglia di {name}',
    # Items
    'Title is required': 'Il titolo è obbligatorio',
    'Item not found': 'Elemento non trovato',
    'Invalid type': 'Tipo non valido',
    'Invalid category': 'Categoria non valida',
    'Invalid member': 'Persona non valida',
    'Invalid repetition': 'Ripetizione non valida',
    'A repeating item needs a date': 'Per ripetersi serve una data',
    'Invalid reminder': 'Promemoria non valido',
    'Invalid questions': 'Domande non valide',
    'Invalid priority': 'Priorità non valida',
    'A date is required': 'Serve una data',
    'The period ends before it starts': 'Il periodo finisce prima di iniziare',
    'Name is required': 'Il nome è obbligatorio',
    'There is already someone with this name': "C'è già qualcuno con questo nome",
    'Too many people': 'Troppe persone',
    'Person not found': 'Persona non trovata',
    'File type not allowed': 'Tipo di file non consentito (PDF, immagini, documenti)',
    'Too many attachments': 'Troppi allegati',
    'File not found': 'File non trovato',
    'Calendar not found': 'Calendario non trovato',
    'Invalid scope': 'Valore non valido',
    'Request Entity Too Large': 'File troppo grande (massimo 20 MB)',
    # Calendar and reminders
    'About': 'Riguarda',
    'Category': 'Categoria',
    'Questions to ask': 'Domande da fare',
    'Checklist': 'Checklist',
    'Today': 'Oggi',
    'Coming up': 'In arrivo',
    'Overdue': 'Scaduti',
    'turns {n}': 'compie {n} anni',
    'anyone': 'chiunque',
    'Hi {name}, here is what needs attention:': 'Ciao {name}, ecco cosa ti aspetta:',
    'You can turn off these emails in the Family page of the app.': "Puoi disattivare queste email dalla pagina Famiglia dell'app.",
    'doTrack: {n} things to remember': 'doTrack: {n} cose da ricordare',
    'doTrack: 1 thing to remember': 'doTrack: 1 cosa da ricordare',
    'doTrack: overdue items': 'doTrack: cose scadute',
    # Lists, labels, comments
    'List not found': 'Lista non trovata',
    'Too many lists': 'Troppe liste',
    'Invalid colour': 'Colore non valido',
    'Invalid labels': 'Etichette non valide',
    'Label not found': 'Etichetta non trovata',
    'Too many labels': 'Troppe etichette',
    'A label with this name already exists': "Esiste già un'etichetta con questo nome",
    'Write something first': 'Scrivi prima qualcosa',
    'Comment not found': 'Commento non trovato',
    'You can only delete your own comments': 'Puoi eliminare solo i tuoi commenti',
    # Notifications
    'Tomorrow': 'Domani',
    '{name} assigned you: {title}': '{name} ti ha assegnato: {title}',
    '{name} completed: {title}': '{name} ha completato: {title}',
    '{name} commented on: {title}': '{name} ha commentato: {title}',
    'Invalid subscription': 'Iscrizione non valida',
    'No device with notifications turned on': 'Nessun dispositivo con le notifiche attive',
    'Notifications are working.': 'Le notifiche funzionano.',
    # Shopping, turns, quick actions, trash
    'Invalid aisle': 'Reparto non valido',
    'Invalid turns': 'Turni non validi',
    'Your turn: {title}': 'Tocca a te: {title}',
    'Birthdays cannot be moved': 'I compleanni non si spostano',
    # Security and integrations
    'Not allowed with an API token': 'Non consentito con un token API',
    'Sign-in with a password is disabled: use one of the providers': "L'accesso con password è disattivato: usa uno dei provider",
    'Sign-up with a password is disabled: use one of the providers': 'La registrazione con password è disattivata: usa uno dei provider',
    'Sign-in expired: please enter your password again': 'Accesso scaduto: inserisci di nuovo la password',
    'Wrong code': 'Codice errato',
    'Start the setup again': 'Ricomincia la configurazione',
    'Wrong code: check the time on your phone and try again': "Codice errato: controlla l'ora del telefono e riprova",
    'Wrong code or password': 'Codice o password errati',
    'Two-step verification is off': 'La verifica in due passaggi non è attiva',
    'Too many tokens': 'Troppi token',
    'Invalid address': 'Indirizzo non valido',
    'Invalid events': 'Eventi non validi',
    'Too many webhooks': 'Troppi webhook',
    'Webhook not found': 'Webhook non trovato',
    # CalDAV
    'Too many app passwords': 'Troppe password per app',
    # Field names inside patterns
    'date': 'data', 'time': 'ora', 'end time': 'ora di fine', 'end date': 'data di fine', 'reminder time': 'ora del promemoria',
}

IT_PATTERNS = [
    (r'^Password must be at least (\d+) characters$', r'La password deve avere almeno \1 caratteri'),
    (r'^(.+): invalid date$', r'\1: data non valida'),
    (r'^(.+): invalid time$', r'\1: ora non valida'),
]

MESSAGES = {'it': (IT, IT_PATTERNS)}


def tr(text, lang=None, **values):
    lang = lang or language()
    if lang in MESSAGES:
        dictionary, patterns = MESSAGES[lang]
        if text in dictionary:
            text = dictionary[text]
        else:
            for pattern, template in patterns:
                if m := re.match(pattern, text):
                    parts = [dictionary.get(p, p) for p in m.groups()]
                    text = re.sub(r'\\(\d)', lambda ref: parts[int(ref.group(1)) - 1], template)
                    break
    return text.format(**values) if values else text


# Names of the values stored in the database
LABELS = {
    'en': {'task': 'To-do', 'deadline': 'Deadline', 'appointment': 'Appointment', 'note': 'Notice', 'birthday': 'Birthday',
           'home': 'Home', 'shopping': 'Shopping', 'car': 'Car', 'health': 'Health', 'kids': 'Kids', 'school': 'School',
           'documents': 'Documents', 'money': 'Money', 'work': 'Work', 'leisure': 'Free time', 'other': 'Other'},
    'it': {'task': 'Attività', 'deadline': 'Scadenza', 'appointment': 'Appuntamento', 'note': 'Avviso', 'birthday': 'Compleanno',
           'home': 'Casa', 'shopping': 'Acquisti', 'car': 'Auto', 'health': 'Salute', 'kids': 'Bambini', 'school': 'Scuola',
           'documents': 'Documenti', 'money': 'Soldi', 'work': 'Lavoro', 'leisure': 'Tempo libero', 'other': 'Altro'},
}


def label(key, lang=None):
    return LABELS.get(lang or language(), LABELS['en']).get(key, key or '')


EMAILS = {
    'verify': {
        'it': ('Conferma il tuo indirizzo email – doTrack',
               'Ciao!\n\nConferma il tuo indirizzo email aprendo questo link:\n{link}\n\n'
               'Il link vale 3 giorni. Se non ti sei registrato su doTrack ignora questo messaggio.'),
        'en': ('Confirm your email address – doTrack',
               'Hi!\n\nConfirm your email address by opening this link:\n{link}\n\n'
               "The link is valid for 3 days. If you didn't sign up for doTrack, ignore this message."),
    },
    'reset': {
        'it': ('Reimposta la password – doTrack',
               'Per scegliere una nuova password apri questo link (vale 2 ore):\n{link}\n\n'
               'Se non hai chiesto tu il cambio password ignora questo messaggio.'),
        'en': ('Reset your password – doTrack',
               'To choose a new password open this link (valid for 2 hours):\n{link}\n\n'
               "If you didn't request a password change, ignore this message."),
    },
}


def email(kind, lang, **values):
    subject, text = EMAILS[kind].get(lang) or EMAILS[kind][DEFAULT]
    return subject, text.format(**values)
