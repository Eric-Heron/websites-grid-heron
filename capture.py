"""
Capture 6 sites web et les assemble en une grille 3x2 (image JPEG).

- Ordre des sites aléatoire à chaque exécution.
- Chaque site est affiché au hasard en version ordinateur ou mobile.
- Les bandeaux de cookies sont fermés ou masqués avant la capture.

Résultat : dossier "public/" contenant grille.jpg et index.html.
"""

import asyncio
import random
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright

# ---------------------------------------------------------------- Réglages ---

LARGEUR, HAUTEUR = 3840, 2160          # taille de l'écran (4K)
COLONNES, LIGNES = 3, 2
PROBA_MOBILE = 0.33                    # chance qu'un site soit en version mobile
AFFICHER_NOMS = True                   # petite étiquette avec le nom du site
FUSEAU = "Europe/Zurich"

CASE_L, CASE_H = LARGEUR // COLONNES, HAUTEUR // LIGNES   # 1280 x 1080 en 4K
ECHELLE = LARGEUR / 1920               # 2 en 4K : textes et marges agrandis
MARGE = round(6 * ECHELLE)             # espace entre les cases
FOND = (18, 18, 20)

# Version ordinateur : fenêtre de même proportion que la case.
# En 4K, chaque pixel de la page correspond à un pixel de l'écran (net).
ORDI = dict(viewport={"width": 1280, "height": 1080},
            device_scale_factor=max(1, ECHELLE / 2),
            is_mobile=False, has_touch=False)
# Version mobile : format iPhone, en haute définition.
MOBILE = dict(viewport={"width": 390, "height": 760}, device_scale_factor=max(2, round(1.5 * ECHELLE)),
              is_mobile=True, has_touch=True,
              user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
                          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
                          "Mobile/15E148 Safari/604.1"))
UA_ORDI = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

DOSSIER = Path(__file__).parent
SORTIE = DOSSIER / "public"
CAPTURES = DOSSIER / "captures"

# ------------------------------------------------- Bandeaux de cookies ---

# Boutons des outils de consentement les plus courants (refus en priorité).
SELECTEURS_COOKIES = [
    "#onetrust-reject-all-handler", "#onetrust-accept-btn-handler",
    "#didomi-notice-disagree-button", "#didomi-notice-agree-button",
    "#axeptio_btn_dismiss", "#axeptio_btn_acceptAll",
    "#CybotCookiebotDialogBodyButtonDecline",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#tarteaucitronAllDenied2", "#tarteaucitronPersonalize2",
    ".cmplz-deny", ".cmplz-accept",
    ".cky-btn-reject", ".cky-btn-accept",
    "#cookie_action_close_header_reject", "#cookie_action_close_header",
    ".iubenda-cs-reject-btn", ".iubenda-cs-accept-btn",
    "[data-cookiefirst-action='reject']", "[data-cookiefirst-action='accept']",
    "#usercentrics-root >>> button[data-testid='uc-deny-all-button']",
    "#usercentrics-root >>> button[data-testid='uc-accept-all-button']",
]
# Textes de boutons (français, allemand, anglais), refus en priorité.
TEXTES_COOKIES = [
    "Tout refuser", "Refuser tout", "Refuser", "Continuer sans accepter",
    "Je refuse", "Alle ablehnen", "Ablehnen", "Reject all", "Decline",
    "Tout accepter", "Accepter tout", "Accepter", "J'accepte", "J’accepte",
    "Alle akzeptieren", "Akzeptieren", "Accept all", "Accept", "OK", "Fermer",
]
# Filet de sécurité : masque ce qui reste des bandeaux connus.
CSS_MASQUAGE = """
#onetrust-consent-sdk, #didomi-host, #axeptio_overlay, #CybotCookiebotDialog,
#tarteaucitronRoot, .cmplz-cookiebanner, .cky-consent-container,
#usercentrics-root, .iubenda-cs-container, #cookie-law-info-bar,
[id*="cookie-banner" i], [class*="cookie-banner" i], [id*="cookieconsent" i],
[class*="cookieconsent" i], [class*="cc-window" i], [aria-label*="cookie" i][role="dialog"]
{ display: none !important; }
html, body { overflow: auto !important; }
"""


async def fermer_cookies(page):
    """Essaie de cliquer sur un bouton de consentement, dans la page et ses iframes."""
    for cadre in page.frames:
        for sel in SELECTEURS_COOKIES:
            try:
                bouton = cadre.locator(sel).first
                if await bouton.is_visible(timeout=300):
                    await bouton.click(timeout=2000)
                    return True
            except Exception:
                pass
    for cadre in page.frames:
        for texte in TEXTES_COOKIES:
            try:
                bouton = cadre.get_by_role("button", name=texte, exact=True).first
                if await bouton.is_visible(timeout=200):
                    await bouton.click(timeout=2000)
                    return True
            except Exception:
                pass
    return False


# --------------------------------------------------------------- Capture ---

async def capturer(navigateur, nom, url, mobile, fichier):
    reglages = dict(MOBILE if mobile else ORDI)
    reglages.setdefault("user_agent", UA_ORDI)
    contexte = await navigateur.new_context(
        locale="fr-CH", timezone_id=FUSEAU, ignore_https_errors=True, **reglages)
    page = await contexte.new_page()
    try:
        await page.goto(url, wait_until="load", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass                                # certains sites ne s'arrêtent jamais
        await page.wait_for_timeout(2500)
        if await fermer_cookies(page):
            await page.wait_for_timeout(1500)
        await page.add_style_tag(content=CSS_MASQUAGE)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)       # fin des animations
        await page.screenshot(path=str(fichier))
        print(f"OK      {nom} ({'mobile' if mobile else 'ordinateur'})")
        return True
    except Exception as erreur:
        print(f"ÉCHEC   {nom} : {erreur}")
        return False
    finally:
        await contexte.close()


# ------------------------------------------------------------ Assemblage ---

def police(taille, gras=False):
    for chemin in (f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if gras else ''}.ttf",):
        if Path(chemin).exists():
            return ImageFont.truetype(chemin, taille)
    return ImageFont.load_default()


def contenir(img, larg, haut):
    """Redimensionne l'image pour qu'elle tienne dans larg x haut."""
    ratio = min(larg / img.width, haut / img.height)
    return img.resize((round(img.width * ratio), round(img.height * ratio)), Image.LANCZOS)


def case_site(fichier, mobile, nom):
    l, h = CASE_L - 2 * MARGE, CASE_H - 2 * MARGE
    case = Image.new("RGB", (l, h), (32, 32, 36))
    if fichier is None:                                   # site injoignable
        d = ImageDraw.Draw(case)
        d.text((l / 2, h / 2 - 14 * ECHELLE), nom, font=police(round(30 * ECHELLE), True), fill=(220, 220, 220), anchor="mm")
        d.text((l / 2, h / 2 + 24 * ECHELLE), "Temporairement indisponible",
               font=police(round(20 * ECHELLE)), fill=(150, 150, 150), anchor="mm")
        return case
    img = Image.open(fichier).convert("RGB")
    if mobile:
        # Téléphone centré sur un fond tiré des couleurs du site.
        moyenne = img.resize((1, 1)).getpixel((0, 0))
        case = Image.new("RGB", (l, h), tuple(int(c * 0.35) for c in moyenne))
        ecran = contenir(img, l, h - round(24 * ECHELLE))
        bord = round(6 * ECHELLE)
        cadre = Image.new("RGB", (ecran.width + 2 * bord, ecran.height + 2 * bord), (10, 10, 10))
        cadre.paste(ecran, (bord, bord))
        masque = Image.new("L", cadre.size, 0)
        ImageDraw.Draw(masque).rounded_rectangle((0, 0, *cadre.size), radius=round(22 * ECHELLE), fill=255)
        case.paste(cadre, ((l - cadre.width) // 2, (h - cadre.height) // 2), masque)
    else:
        img = img.resize((l, round(img.height * l / img.width)), Image.LANCZOS)
        case.paste(img.crop((0, 0, l, h)), (0, 0))
    return case


def etiquette(case, nom):
    d = ImageDraw.Draw(case, "RGBA")
    e = ECHELLE
    f = police(round(18 * e), True)
    x0, y0, x1, y1 = d.textbbox((0, 0), nom, font=f)
    larg, haut = x1 - x0 + 24 * e, y1 - y0 + 14 * e
    bas = case.height - 10 * e
    d.rounded_rectangle((10 * e, bas - haut, 10 * e + larg, bas),
                        radius=haut / 2, fill=(0, 0, 0, 170))
    d.text((22 * e, bas - haut / 2), nom, font=f, fill="white", anchor="lm")


def assembler(resultats):
    grille = Image.new("RGB", (LARGEUR, HAUTEUR), FOND)
    for i, (nom, fichier, mobile) in enumerate(resultats):
        case = case_site(fichier, mobile, nom)
        if AFFICHER_NOMS and fichier is not None:
            etiquette(case, nom)
        x = (i % COLONNES) * CASE_L + MARGE
        y = (i // COLONNES) * CASE_H + MARGE
        grille.paste(case, (x, y))
    return grille


# ------------------------------------------------------------- Programme ---

def lire_sites():
    sites = []
    for ligne in (DOSSIER / "sites.txt").read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#"):
            nom, url = (p.strip() for p in ligne.split("|", 1))
            sites.append((nom, url))
    return sites[: COLONNES * LIGNES]


async def main():
    sites = lire_sites()
    random.shuffle(sites)
    CAPTURES.mkdir(exist_ok=True)
    resultats = []
    async with async_playwright() as p:
        navigateur = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        for i, (nom, url) in enumerate(sites):
            mobile = random.random() < PROBA_MOBILE
            fichier = CAPTURES / f"site{i}.png"
            ok = await capturer(navigateur, nom, url, mobile, fichier)
            resultats.append((nom, fichier if ok else None, mobile))
        await navigateur.close()

    SORTIE.mkdir(exist_ok=True)
    assembler(resultats).save(SORTIE / "grille.jpg", quality=85, optimize=True)
    shutil.copy(DOSSIER / "index.html", SORTIE / "index.html")
    heure = datetime.now(ZoneInfo(FUSEAU)).strftime("%d/%m/%Y %H:%M")
    (SORTIE / "derniere-mise-a-jour.txt").write_text(heure + "\n", encoding="utf-8")
    print(f"Grille générée ({heure})")


if __name__ == "__main__":
    asyncio.run(main())
