#!/usr/bin/env python3
"""Builds /ko/index.html and /es/index.html from /index.html.

The English page is the only one edited by hand. After changing it, run:

    python3 tools/i18n/build.py

Each language has one file here (ko.json, es.json):
  "text"  English words on the page (text and alt/aria-label/placeholder/data-launch/meta content) -> translation
  "raw"   [english html, translated html, times it appears] for the few places where the word order has to change
  "js"    the words the page's script writes (the keys of T in index.html's script)

App screens in a language go in assets/screens/<lang>/ under the same file names as the English ones
(log-demo.webp, positions.webp, week-card.webp); the build points that language's page at them.

The build stops if anything on the page has no translation, so a new English sentence cannot ship untranslated.
The script itself is identical on all three pages, so they share one Content-Security-Policy hash.
"""
import base64, hashlib, json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
SITE = 'https://gyse.app'
LANGS = ('ko', 'es')

# Words that read the same in every language.
KEEP = {'GYSE', '$YOU', '$MINA', '$ALEX', 'M', 'PLUS', 'SMA 10', 'EMA 20', '87.5 kg × 8', '87.5 kg × 9', 'YOU',
        'you@example.com', 'support@gyse.app', 'English', '한국어', 'Español'}
ATTRS = ('alt', 'aria-label', 'placeholder', 'data-launch', 'content')
TOKEN = re.compile(r'<!--.*?-->|<script\b.*?</script>|<style\b.*?</style>|<[^>]+>', re.S)
LETTER = re.compile(r'[A-Za-zÀ-ɏㄱ-힣]')
MARK_IN, MARK_OUT = '<!--i18n-->', '<!--/i18n-->'


def fail(msg):
    sys.exit('i18n build: ' + msg)


def build(lang):
    cfg = json.loads((HERE / f'{lang}.json').read_text())
    text, used, missing = cfg['text'], set(), []
    page = (ROOT / 'index.html').read_text()

    script = re.search(r'<script>(.*?)</script>', page, re.S)
    digest = base64.b64encode(hashlib.sha256(script.group(1).encode()).digest()).decode()
    if f"'sha256-{digest}'" not in page:
        fail('index.html: the Content-Security-Policy hash does not match its script')

    # 1. Places where the word order changes.
    for old, new, times in cfg['raw']:
        if page.count(old) != times:
            fail(f'{lang}: expected {times} of {old[:60]!r}, found {page.count(old)}')
        page = page.replace(old, MARK_IN + new + MARK_OUT)

    def say(en):
        if en in text:
            used.add(en)
            return text[en]
        if en in KEEP or not LETTER.search(en):
            return en
        missing.append(en)
        return en

    def attrs(tag):
        def one(m):
            name, value = m.group(1), m.group(2)
            if not value or (name == 'content' and value not in text):
                return m.group(0)
            return f'{name}="{say(value)}"'
        return re.sub(r'\b(%s)="([^"]*)"' % '|'.join(ATTRS), one, tag)

    # 2. Every piece of text between tags, and the attributes people read or hear.
    out, at, raw = [], 0, False
    for m in TOKEN.finditer(page):
        piece = page[at:m.start()]
        norm = ' '.join(piece.split())
        if raw or not norm:
            out.append(piece)
        else:
            new = say(norm)
            lead = piece[:len(piece) - len(piece.lstrip())]
            tail = piece[len(piece.rstrip()):]
            out.append(('' if new[:1] in '.,:;' else lead) + new + tail)
        tag = m.group(0)
        if tag == MARK_IN:
            raw = True
        elif tag == MARK_OUT:
            raw = False
        elif tag.startswith('<') and not tag.startswith(('<!--', '<script', '<style')):
            tag = attrs(tag)
        out.append(tag)
        at = m.end()
    out.append(page[at:])
    page = ''.join(out).replace(MARK_IN, '').replace(MARK_OUT, '')

    if missing:
        fail(f'{lang}: no translation for:\n  ' + '\n  '.join(dict.fromkeys(missing)))
    unused = [k for k in text if k not in used]
    if unused:
        fail(f'{lang}: these are no longer on the page, remove them from {lang}.json:\n  ' + '\n  '.join(unused))

    # 3. The words the script writes.
    table = re.search(r'const T = Object\.assign\(\{(.*?)\n  \}, ', script.group(1), re.S).group(1)
    keys = re.findall(r'(\w+): (?=[\'"])', table)
    js = cfg['js']
    if set(keys) != set(js):
        fail(f'{lang}: "js" differs from T in index.html: missing {sorted(set(keys) - set(js))}, extra {sorted(set(js) - set(keys))}')
    data = json.dumps(js, ensure_ascii=False).replace('</', '<\\/')

    # 4. Language, addresses and links.
    def swap(old, new, times=1):
        nonlocal page
        if page.count(old) != times:
            fail(f'{lang}: expected {times} of {old!r}, found {page.count(old)}')
        page = page.replace(old, new)

    swap('<html lang="en">', f'<html lang="{lang}">')
    swap(f'<meta property="og:url" content="{SITE}/">', f'<meta property="og:url" content="{SITE}/{lang}/">')
    swap(f'<link rel="canonical" href="{SITE}/">', f'<link rel="canonical" href="{SITE}/{lang}/">')
    swap('<a class="brand" href="/"', f'<a class="brand" href="/{lang}/"')
    page = re.sub(r'href="/(privacy|terms)\b', rf'href="/{lang}/\1', page)
    swap('<a href="/" lang="en" hreflang="en" aria-current="page">', '<a href="/" lang="en" hreflang="en">')
    swap(f'<a href="/{lang}/" lang="{lang}" hreflang="{lang}">', f'<a href="/{lang}/" lang="{lang}" hreflang="{lang}" aria-current="page">')
    swap('\n<script>', f'\n<script type="application/json" id="i18n">{data}</script>\n<script>')
    # App screens captured in this language, where assets/screens/<lang>/ has them.
    for shot in sorted((ROOT / 'assets' / 'screens' / lang).glob('*.webp')):
        swap(f'src="/assets/screens/{shot.name}"', f'src="/assets/screens/{lang}/{shot.name}"', 2)

    after = re.search(r'<script>(.*?)</script>', page, re.S).group(1)
    if after != script.group(1):
        fail(f'{lang}: the script changed during the build')
    (ROOT / lang).mkdir(exist_ok=True)
    (ROOT / lang / 'index.html').write_text(page)
    print(f'{lang}/index.html  {len(text)} phrases, {len(js)} script phrases')


if __name__ == '__main__':
    for code in LANGS:
        build(code)
