// Privacy notice texts, one entry per language: a draft banner, sections [title, html] and the "last updated" line.
// DRAFT: for a private family instance this is mostly a formality; if you open the app to others, complete the
// fields in [SQUARE BRACKETS] and have it reviewed. The html strings are written by the developers only (never user input).
export default {
  it: {
    draft: 'Bozza – da completare prima di aprire l\'app ad altre persone.',
    sections: [
      ['Titolare del trattamento', '[NOME], [INDIRIZZO], email: [EMAIL DI CONTATTO].'],
      ['Quali dati trattiamo', "Dati dell'account (nome, email, password cifrata o identificativo del provider di accesso) e ciò che inserisci: attività, scadenze, appuntamenti, note, domande e risposte, file allegati. Questi possono comprendere <b>dati relativi alla salute</b>, anche di minori (es. referti, visite pediatriche – art. 9 GDPR): li trattiamo solo sulla base del tuo consenso esplicito, che dai alla registrazione e puoi revocare eliminando l'account."],
      ['Perché li trattiamo', 'Solo per fornirti il servizio: organizzare le cose da fare, condividerle con i membri della famiglia che inviti tu, mandarti i promemoria via email se li attivi e pubblicare il calendario privato che colleghi tu a Google Calendar o ad altre app. Non vendiamo i dati e non li usiamo per pubblicità.'],
      ['Dove sono conservati e per quanto', 'Sul server [DOVE]. Le email vengono inviate tramite [FORNITORE EMAIL]. Se colleghi il calendario, Google (o l\'app che scegli) scarica titolo, data, luogo e note dei tuoi impegni dall\'indirizzo segreto. Se attivi le notifiche su un dispositivo, passano dal servizio di notifica del suo browser o sistema (Google, Apple o Mozilla) cifrate in modo che quel servizio non possa leggerle. Se colleghi un\'app tramite sincronizzazione (CalDAV), quell\'app riceve e conserva sul dispositivo le voci sincronizzate. I dati restano finché hai un account; quando lo elimini vengono cancellati, e spariscono dai backup entro [N] giorni.'],
      ['I tuoi diritti', "Puoi in ogni momento correggere i tuoi dati, eliminare l'account e tutti i dati, revocare il consenso e presentare reclamo al Garante per la protezione dei dati personali. Per qualsiasi richiesta: [EMAIL DI CONTATTO]."],
      ['Cookie', 'Usiamo un solo cookie tecnico per mantenerti collegato. Nessun cookie di profilazione o di terze parti.'],
    ],
    updated: 'Ultimo aggiornamento: [DATA]',
  },
  en: {
    draft: 'Draft – to be completed before opening the app to other people.',
    sections: [
      ['Data controller', '[NAME], [ADDRESS], email: [CONTACT EMAIL].'],
      ['What data we process', 'Account data (name, email, hashed password or sign-in provider identifier) and what you enter: to-dos, deadlines, appointments, notes, questions and answers, attached files. These may include <b>health data</b>, also about minors (e.g. medical reports, paediatric visits – GDPR art. 9): we process it only on the basis of your explicit consent, given at sign-up, which you can withdraw by deleting your account.'],
      ['Why we process it', 'Only to provide the service: organising things to do, sharing them with the family members you invite, sending you email reminders if you turn them on, and publishing the private calendar you connect to Google Calendar or other apps. We do not sell data or use it for advertising.'],
      ['Where it is stored and for how long', 'On the server [WHERE]. Emails are sent via [EMAIL PROVIDER]. If you connect the calendar, Google (or the app you choose) downloads the title, date, place and notes of your events from the secret address. If you turn on notifications on a device, they go through the push service of its browser or system (Google, Apple or Mozilla), encrypted so that service cannot read them. If you connect an app through sync (CalDAV), that app receives and keeps the synced items on the device. Data is kept while you have an account; when you delete it, it is erased, and disappears from backups within [N] days.'],
      ['Your rights', 'At any time you can correct your data, delete your account and all data, withdraw consent and lodge a complaint with your data protection authority. For any request: [CONTACT EMAIL].'],
      ['Cookies', 'We use a single technical cookie to keep you signed in. No profiling or third-party cookies.'],
    ],
    updated: 'Last updated: [DATE]',
  },
};
