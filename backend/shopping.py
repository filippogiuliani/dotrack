"""Shopping lists: the supermarket aisle of a thing, the list's history (suggestions while typing) and
quantities typed with the name."""
import re

# First words that give the aisle away (Italian and English). The list's own history wins over these.
WORDS = {
    'produce': '''frutta verdura mela mele pera pere banana banane arancia arance mandarini limone limoni kiwi uva fragole fragola
        pesche pesca albicocche ciliegie melone anguria ananas mango avocado frutti lamponi mirtilli prugne fichi
        insalata lattuga rucola spinaci zucchine zucchina pomodori pomodoro pomodorini patate patata carote carota cipolla cipolle
        aglio peperoni peperone melanzane melanzana cetrioli cetriolo sedano finocchio finocchi broccoli cavolfiore cavolo
        verza zucca funghi porri porro basilico prezzemolo rosmarino salvia menta erbe piselli fagiolini asparagi carciofi
        radicchio cicoria bietole legumi ceci lenticchie
        fruit vegetables apple apples pear pears bananas orange oranges lemon lemons grapes strawberries peaches salad lettuce
        spinach courgette zucchini tomatoes tomato potatoes potato carrots carrot onion onions garlic peppers aubergine
        cucumber celery broccoli cauliflower cabbage pumpkin mushrooms parsley basil herbs peas beans avocado''',
    'bakery': '''pane panini pancarrè piadina piadine focaccia grissini crackers fette biscottate cornetti brioche
        bread rolls bagels baguette croissant croissants buns tortillas''',
    'meat_fish': '''carne pollo petto tacchino manzo vitello maiale macinato salsiccia salsicce hamburger bistecca bistecche fettine
        cotolette arrosto agnello coniglio wurstel prosciutto speck bresaola salame mortadella affettati pancetta
        pesce salmone tonno merluzzo orata branzino spigola gamberi gamberetti cozze vongole calamari polpo sogliola platessa
        meat chicken turkey beef pork veal mince sausage sausages ham bacon steak fish salmon tuna cod prawns shrimp''',
    'dairy': '''latte yogurt yogurth formaggio formaggi mozzarella burrata parmigiano grana pecorino ricotta stracchino
        mascarpone gorgonzola scamorza provola emmental burro panna uova uovo kefir
        milk cheese butter cream eggs egg yoghurt''',
    'frozen': '''surgelati surgelato gelato gelati bastoncini findus sofficini piselli-surgelati minestrone-surgelato
        frozen ice-cream icecream''',
    'pantry': '''pasta spaghetti penne fusilli rigatoni tagliatelle lasagne gnocchi riso farina zucchero sale pepe olio aceto
        passata pelati sugo pesto tonno-in-scatola legumi-in-scatola fagioli ceci-in-scatola mais caffè caffe tè te tisane
        orzo cereali muesli fiocchi marmellata miele nutella cioccolata cacao lievito pangrattato brodo dado spezie
        origano curry maionese ketchup senape cous-cous couscous quinoa polenta
        rice flour sugar salt oil vinegar sauce coffee tea cereal honey jam spices stock''',
    'drinks': '''acqua bibite bibita succo succhi aranciata coca cola birra birre vino spumante prosecco gin vodka liquore
        water juice soda beer wine coke''',
    'snacks': '''biscotti merendine patatine snack snacks cioccolato cioccolatini caramelle gomme taralli noccioline
        arachidi mandorle noci pistacchi frutta-secca popcorn
        biscuits cookies crisps chips chocolate sweets candy nuts''',
    'household': '''detersivo detersivi ammorbidente candeggina sgrassatore anticalcare pastiglie lavastoviglie spugne spugna
        sacchetti sacchi carta-igienica scottex tovaglioli rotoli alluminio pellicola stagnola lampadina lampadine pile batterie
        piatti bicchieri insetticida
        detergent bleach sponges bags foil batteries''',
    'personal_care': '''shampoo balsamo bagnoschiuma sapone saponetta dentifricio spazzolino spazzolini deodorante assorbenti
        cotton fioc cotone rasoio rasoi lamette crema creme struccante cerotti
        toothpaste toothbrush soap deodorant razor''',
    'baby': '''pannolini pannolino salviette omogeneizzati omogeneizzato latte-in-polvere biberon ciuccio pappa pappe
        diapers nappies wipes formula''',
    'pets': '''crocchette croccantini lettiera cibo-gatto cibo-cane scatolette
        petfood kibble litter''',
}
_INDEX = {}
for _section, _words in WORDS.items():
    for _w in _words.split():
        _INDEX.setdefault(_w.replace('-', ' '), _section)

QTY_RE = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s*(kg|g|gr|hg|l|lt|ml|cl|pz|conf|x)?\.?\s+(?:di\s+|of\s+)?(.+)$', re.I)
TRAILING_QTY_RE = re.compile(r'^(.+?)\s+(?:x\s*(\d+)|(\d+)\s*x|×\s*(\d+))\s*$', re.I)


def key(name):
    return re.sub(r'\s+', ' ', name.strip().lower())


def guess_section(name):
    """Aisle of a thing from its words, or 'other'."""
    k = key(name)
    if k in _INDEX:
        return _INDEX[k]
    words = re.findall(r"[\w']+", k)
    for n in (2, 1):  # two-word names first ("carta igienica")
        for i in range(len(words) - n + 1):
            hit = _INDEX.get(' '.join(words[i:i + n]))
            if hit:
                return hit
    # Plurals and close forms: "zucchinette" → zucchine
    for w in words:
        for known, section in _INDEX.items():
            if len(known) >= 4 and ' ' not in known and len(w) >= max(4, len(known) - 1) and \
                    w.startswith(known[:-1]) and len(w) - len(known) <= 3:
                return section
    return 'other'


def section_for(conn, list_id, name):
    """The aisle learned for this name in the list, otherwise a guess."""
    row = conn.execute('SELECT section FROM list_history WHERE list_id = ? AND key = ?', (list_id, key(name))).fetchone()
    return (row['section'] if row and row['section'] else None) or guess_section(name)


def remember(conn, list_id, name, section=None):
    """Note that `name` was put in the list (suggestions by frequency) and in which aisle."""
    k = key(name)
    if not k:
        return
    conn.execute('''INSERT INTO list_history (list_id, key, name, section) VALUES (?,?,?,?)
                    ON CONFLICT(list_id, key) DO UPDATE SET uses = uses + 1, last_used = datetime('now'), name = excluded.name,
                    section = COALESCE(excluded.section, list_history.section)''', (list_id, k, name.strip(), section))


def split_quantity(text):
    """'2 kg mele' → ('mele', '2 kg'); 'latte x2' → ('latte', '2'); otherwise (text, '')."""
    m = TRAILING_QTY_RE.match(text)
    if m:
        return m.group(1).strip(), next(g for g in m.groups()[1:] if g)
    m = QTY_RE.match(text)
    if m and m.group(3).strip():
        unit = (m.group(2) or '').lower()
        qty = m.group(1) + ('' if unit in ('', 'x') else ' ' + unit)
        return m.group(3).strip(), qty
    return text.strip(), ''
