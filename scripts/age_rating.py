"""Suggested youth-group age range for a blog post.

Two measures, and the higher one wins:

1. Reading level: the Flesch-Kincaid grade of the text, turned into an age
   for a group reading with an adult leader (grade + 3). Reading level alone
   never goes above 14+, and it is not used on posts under 150 words.
2. Mature themes: counts of words about suicide, sexual violence, graphic
   violence, killing and war, child deaths in boarding schools, police
   violence, drugs, and strong language. A passing mention moves the age a
   little; a post where the subject is central moves it more.

The result is guidance for youth-group leaders, not an official rating.

rate(title, text) -> {"ag": 0|12|14|16|18, "th": [theme names], "rg": grade}
"ag" is -1 when the post has too little text to rate (photos or video only).
"""
import re

# theme: (label, [(regex, weight)], base age if mentioned, age if central)
THEMES = [
    ("suicide or self-harm", [
        (r"\bsuicid\w*", 3), (r"\bself[- ]harm\w*", 3), (r"\bkill(?:ed|s|ing)? (?:him|her|them)sel(?:f|ves)\b", 3),
        (r"\btook (?:his|her|their) own li(?:fe|ves)\b", 3)], 14, 16),
    ("sexual violence", [
        (r"\brap(?:e|ed|es|ing|ist)\b", 3), (r"\bsexual(?:ly)? (?:assault|abuse|violence|abused|assaulted)\w*", 3),
        (r"\bmolest\w*", 3), (r"\bsex trafficking\b", 3)], 14, 16),
    ("graphic violence", [
        (r"\bmassacre\w*", 2), (r"\bslaughter\w*", 2), (r"\bbehead\w*", 3), (r"\btortur\w*", 2),
        (r"\bmutilat\w*", 3), (r"\bburn(?:ed|t) alive\b", 3), (r"\bmass graves?\b", 2), (r"\blynch\w*", 2),
        (r"\bcorpses?\b", 2), (r"\bdismember\w*", 3), (r"\bdecapitat\w*", 3), (r"\bstarv(?:e|ed|ing|ation)\b", 1)], 12, 14),
    ("genocide and war", [
        (r"\bgenocid\w*", 1), (r"\bkill(?:ed|ing|ings|s)?\b", 1), (r"\bmurder\w*", 1), (r"\bbomb(?:s|ed|ing|ings)?\b", 1),
        (r"\bairstrikes?\b", 1), (r"\bshot dead\b", 2), (r"\bdeath toll\b", 1), (r"\bslain\b", 1), (r"\bwar crimes?\b", 1),
        (r"\bethnic cleansing\b", 1), (r"\bmissiles?\b", 1), (r"\bblood[- ]soaked\b", 2), (r"\bcasualt(?:y|ies)\b", 1)], 0, 14),
    ("deaths of children", [
        (r"\b(?:children|child|babies|infants|kids) (?:were |was )?(?:killed|died|dead|murdered)\b", 2),
        (r"\bdead (?:children|babies|infants)\b", 2), (r"\bunmarked graves?\b", 2), (r"\bremains of (?:the )?children\b", 2),
        (r"\bchildren'?s? (?:graves|bodies|remains)\b", 2),
        (r"\b(?:children|child|babies|infants|kids)\b(?:\W+\w+){0,5}?\W+(?:killed|starv\w*|died|die|dead|murdered)\b", 2),
        (r"\b(?:killed|starv\w*|murdered|died)\b(?:\W+\w+){0,5}?\W+(?:children|child|babies|infants|kids)\b", 2)], 12, 14),
    ("police violence", [
        (r"\bpolice (?:killing|killed|shooting|brutality|violence)\b", 2), (r"\bchoked?\b", 1),
        (r"\bkilled by (?:the )?police\b", 2), (r"\btear[- ]gas\w*", 1), (r"\brubber bullets?\b", 1),
        (r"\btasers?\b", 1), (r"\bpolice raids?\b", 1), (r"\bforced their way\b", 1)], 0, 12),
    ("drugs", [
        (r"\boverdos\w*", 2), (r"\bheroin\b", 2), (r"\bfentanyl\b", 2), (r"\bmeth(?:amphetamine)?\b", 2), (r"\bopioid\w*", 1)], 12, 14),
    ("strong language", [
        (r"\bfuck\w*", 3), (r"\bshit\w*", 2), (r"\bbitch\w*", 2), (r"\bbastard\w*", 1)], 12, 14),
]
# Figures of speech that are not about people, such as "the rape of the Earth".
# "suicide bombing" and the like are about war, which has its own theme.
NOT_SUICIDE = re.compile(r"\bsuicide\s+(?:bomb\w*|attack\w*|mission\w*|drone\w*)", re.I)

METAPHOR = re.compile(r"\brap(?:e|ed|es|ing)\s+(?:of\s+)?(?:the\s+|our\s+)?(?:earth|land|planet|mother earth|environment|nature|resources)\b"
                      r"|\b(?:earth|land|planet|nature)\s+(?:is\s+|was\s+)?(?:being\s+)?raped\b", re.I)

COMPILED = [(name, [(re.compile(rx, re.I), w) for rx, w in pats], base, central) for name, pats, base, central in THEMES]

# Theme points needed to call a subject central, scaled to post length.
def _central_threshold(words):
    return max(9, words / 200)


def _syllables(word):
    w = word.lower()
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def reading_grade(text):
    sentences = [s for s in re.split(r"[.!?]+[\s\"”’)]*", text) if re.search(r"[A-Za-z]", s)]
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", text)
    if len(words) < 40 or not sentences:
        return None
    syl = sum(_syllables(w) for w in words)
    wps = min(len(words) / len(sentences), 40)       # long lists without full stops
    return round(0.39 * wps + 11.8 * syl / len(words) - 15.59, 1)


def band(age):
    for b in (18, 16, 14, 12):
        if age >= b:
            return b
    return 0


def rate(title, text):
    text = text or ""
    words = len(text.split())
    hay = (title or "") + " . " + (title or "") + " . " + text     # titles count twice
    hay = METAPHOR.sub(" ", hay)
    hay = NOT_SUICIDE.sub(" attack ", hay)
    if words < 40:
        return {"ag": -1, "th": [], "rg": None}         # too little text to rate
    age, themes = 0, []
    for name, pats, base, central in COMPILED:
        pts = sum(w * len(rx.findall(hay)) for rx, w in pats)
        if not pts:
            continue
        if pts >= _central_threshold(words):
            a = central
        elif pts >= 2:
            a = base
        else:
            a = 0
        if a:
            themes.append(name)
            age = max(age, a)
    # Reading level for a group reading with an adult leader: grade + 3,
    # never above 14 on its own, and not used on very short posts.
    grade = reading_grade(text)
    if grade is not None and words >= 150:
        age = max(age, min(band(grade + 3), 14))
    elif words < 150:
        age = max(age, 12)       # too short to score reading level: written for adults
    return {"ag": band(age), "th": themes, "rg": grade}
