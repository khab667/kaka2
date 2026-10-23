# ⚽ fedit — montages foot automatiques, calés sur la musique

Tu donnes une musique et des vidéos de foot (liens YouTube/TikTok ou fichiers) ; fedit fabrique un
montage vertical 1080x1920 prêt pour TikTok / Reels / Shorts, où **chaque coupe tombe pile sur un beat**.

## Ce que fait l'outil

1. **Analyse la musique** : tempo (BPM), position de chaque beat (précision ≈ 10 ms), premiers temps
   de mesure, énergie, et **détection du drop**. Il choisit l'extrait pour que le drop arrive vers 35 % du montage.
2. **Découpe en plans** : plans longs et ralentis pendant l'intro calme, coupes rapides (chaque beat ou
   tous les 2 beats) après le drop, et une coupe forcée **exactement sur le drop**.
3. **Choisit les meilleurs passages** dans tes vidéos : mesure le mouvement image par image, repère les
   changements de plan de la réalisation TV (pour ne jamais couper au milieu d'un plan), et recadre en
   vertical **sur la zone où se trouve l'action**. Les actions marquées `vedette` vont sur le drop.
4. **Rend le montage avec les effets synchronisés** : zoom « punch », shake, flash blanc, RGB split,
   écran noir juste avant le drop, pulsation sur chaque beat, velocity (accéléré → ralenti) avec flou de
   mouvement, étalonnage, vignette, grain, titre animé qui pulse au rythme.

| Style | Rythme après le drop | Effets |
|---|---|---|
| `hype` | 1 plan par beat | flash, shake, RGB split, noir avant le drop |
| `velocity` | 1 plan / 2 beats | accéléré → ralenti à chaque plan, flou de mouvement |
| `cinematique` | 1 plan / 2 à 4 beats | ralentis, couleurs film, grain, zooms doux |
| `classique` | 1 plan / 2 beats | coupes nettes, zooms légers |
| `art` | 1 plan / 2 à 4 beats | façon « the art of. » : image carrée sur fond noir, petit texte centré, ralentis |

## Installation

Il faut Python 3.10+ et [ffmpeg](https://ffmpeg.org/download.html).

```bash
cd football-edit
pip install -r requirements.txt
```

## Utilisation

```bash
# 1. Copier l'exemple et mettre tes liens
cp exemples/mbappe.yaml mon-edit.yaml

# 2. Aperçu rapide (540x960) pour vérifier
python3 -m fedit render mon-edit.yaml --apercu

# 3. Version finale (1080x1920), ou 3 variantes différentes pour choisir la meilleure
python3 -m fedit render mon-edit.yaml
python3 -m fedit render mon-edit.yaml --variantes 3
```

Les vidéos arrivent dans `rendus/`, avec un fichier `.plan.json` qui détaille chaque plan
(moment de la musique, vidéo source, minute utilisée).

Options utiles : `--style hype|velocity|cinematique|classique|art`, `--duree 25`, `--fps 60`.

Textes : `titre` (et `sous_titre`) s'affichent jusqu'au drop, `legende` après le drop.

### Autres commandes

```bash
# Analyser une musique : BPM, drop, meilleur extrait
python3 -m fedit beats "https://www.youtube.com/watch?v=..."

# Analyser un montage qui t'inspire (TikTok) : nombre de coupes, % sur le beat, style le plus proche
python3 -m fedit reference "https://vm.tiktok.com/..."

# Télécharger une vidéo ou une musique
python3 -m fedit download "https://www.youtube.com/watch?v=..." [--audio]
```

## YouTube et TikTok

- **TikTok** fonctionne partout, y compris depuis un serveur cloud.
- **YouTube** bloque les téléchargements depuis les serveurs cloud (erreur 403), même quand l'accès réseau
  est autorisé. Depuis ton ordinateur ça marche directement (installe [Node.js](https://nodejs.org) ou
  [Deno](https://deno.com), dont yt-dlp a besoin pour YouTube). Si besoin, un fichier de cookies se passe
  avec `FEDIT_COOKIES=chemin/cookies.txt`.

## Conseils pour un montage réussi

- **Donne des `moments` précis** (`"2:14-2:22"`) : l'outil sait trouver l'action, mais pas savoir qu'un
  passage est un but. Marque le plus beau avec `vedette: true`, il tombera sur le drop.
- Prends des sources **en 50/60 i/s** (fedit les choisit en priorité) : les ralentis sont bien plus fluides.
- Musiques qui marchent bien : phonk, drill, trap, edits « slowed + reverb », avec un vrai drop.
- Sur les plans larges où le recadrage vertical coupe trop le terrain, essaie `reglages: {framing: fit}`.

## Droits d'auteur

Les images de match et les musiques sont protégées. Pour publier sans que TikTok coupe le son, le plus
sûr est de choisir un son présent dans la bibliothèque TikTok (le même morceau, calé au même endroit), ou
une musique libre de droits. Les extraits de match courts dans des edits de fans sont très répandus,
mais restent à tes risques.

## Tests

```bash
python3 tests/test_sync.py
```

Génère une musique (128 BPM, drop connu à 15 s) et des vidéos synthétiques, puis vérifie le tempo, le
drop, que chaque coupe est sur un beat à moins d'une demi-image près, et le format du rendu.
