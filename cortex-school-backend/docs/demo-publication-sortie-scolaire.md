# Démonstration PFE : une sortie pédagogique et ses documents de référence

Ce scénario et ce règlement sont fictifs. Ils servent à démontrer l’application ;
ils ne décrivent pas les règles réelles d’un établissement. Si vous disposez déjà
d’un règlement, utilisez ses dispositions et ses références.

## Publication proposée

**Titre :** Sortie pédagogique du 25 novembre — autorisation parentale

**Publication d’origine :** 18 novembre 2026 à 09 h, heure de Tunis.

**Destinataires :** responsables familiaux et enseignants de la classe choisie.

> Chères familles, chers enseignants,
>
> Une sortie pédagogique est prévue le 25 novembre 2026.
>
> Merci aux responsables familiaux de remettre l’autorisation parentale signée au
> plus tard le 18 novembre 2026 à 18 h.
>
> Les modalités de participation sont précisées dans le document « Règlement des
> sorties scolaires », à consulter dans les consignes de l’établissement.
>
> La lecture de cette publication dans Cortex School ne remplace pas l’autorisation
> parentale signée. Pour toute question concernant le document ou son retour,
> contactez l’administration.
>
> L’administration

Le script `app/scripts/import_historical_publication.py` reprend ce contenu. Par
défaut, il importe une publication générale et ses destinataires. Avec l’option
`--require-acknowledgement`, il importe la version en **suivi élève**, avec demande
explicite d’accusé de réception, une échéance passée et les états familiaux
nécessaires aux relances. Il ne génère ni n’envoie de relance automatiquement.

## Document d’exemple à ajouter aux consignes de l’établissement

Dans **Paramètres de l’école → Consignes de l’établissement**, utiliser l’ajout de
texte, avec le titre exact **Règlement des sorties scolaires**. Copier le contenu
ci-dessous. Un PDF contenant ce même texte peut également être importé pour
montrer l’ouverture du document depuis une citation.

```text
RÈGLEMENT DES SORTIES SCOLAIRES
Document fictif pour une démonstration PFE

Article 1 — Autorisation parentale
Pour une sortie pédagogique, une autorisation écrite signée par un responsable
familial doit être remise à l’établissement.

Article 2 — Date de remise
La date limite de remise de l’autorisation est indiquée dans le message annonçant
la sortie. Les familles sont invitées à respecter cette échéance. En cas de
difficulté pour remettre le document, elles doivent contacter l’administration.

Article 3 — Lecture du message et autorisation signée
La lecture d’un message ou son accusé de réception dans Cortex School confirme
uniquement la prise de connaissance de l’information. Elle ne remplace pas
l’autorisation parentale écrite et signée.

Article 4 — Rappels aux familles
L’établissement peut adresser un rappel aux responsables familiaux qui n’ont pas
encore accusé réception du message. Ce rappel doit conserver la date et les
informations de l’annonce d’origine, sans ajouter de nouvelle condition.
```

## Pourquoi ce sujet montre l’intérêt des documents

Le titre et les observations indiquent la sortie et son échéance. Le document
explique les conditions de participation et la différence entre lire le message
et remettre une autorisation. Une relance peut donc s’appuyer sur un passage
précis plutôt que déduire une règle depuis le titre de l’annonce.

Exemple de relance attendue, à titre indicatif :

> Merci de prendre connaissance du message concernant la sortie pédagogique du
> 25 novembre et d’en accuser réception dans Cortex School. Le règlement prévoit
> une autorisation parentale écrite et signée ; l’accusé de réception ne la
> remplace pas. Si vous rencontrez une difficulté pour remettre le document,
> contactez l’administration.

Les citations doivent provenir des passages réellement retrouvés dans le document
de l’établissement. Le texte exact généré peut varier ; ne pas ajouter une page ou
un numéro de passage qui ne figure pas dans les sources retournées.

## Parcours fonctionnel actuel pour la vidéo

1. Ajouter le règlement dans la bibliothèque des consignes.
2. Importer un **suivi élève** avec accusé de réception obligatoire et échéance
   passée, depuis le backend Railway après déploiement du script :

   ```bash
   python -m scripts.import_historical_publication --organization-id org_... --classroom-name "1A · Jasmin" --require-acknowledgement --due-at "2026-11-18T18:00:00+01:00" --apply
   ```

   Utiliser l’identifiant réel de l’établissement et le nom exact de sa classe.
   Sans `--apply`, la commande fournit uniquement un aperçu. Un enseignant actif
   doit être affecté à la classe. Pour un test créé dans le formulaire enseignant,
   choisir une échéance proche encore future, puis la laisser passer.
3. Ne pas accuser réception avec l’un des comptes familiaux destinataires.
4. Depuis l’administration, ouvrir l’élément en retard et préparer une **relance
   IA**. L’agent lit le suivi et recherche les passages pertinents du règlement.
5. Montrer le brouillon, le titre du document et les extraits cités. Si le document
   a été importé en PDF, montrer également son ouverture.
6. Valider la relance. Celery effectue l’envoi dans l’application aux responsables
   familiaux encore concernés ; les citations conservées sont consultables côté
   famille.

Les dates historiques de la publication proposée permettent d’illustrer une
échéance dépassée au 19 novembre 2026. Le formulaire de création d’un suivi refuse
une échéance déjà passée : il ne faut pas les recopier comme échéance d’un nouveau
suivi créé après cette date.

Le nouvel onglet **Publications** reste un circuit distinct. Le mode avec accusé
écrit dans **Suivis élèves**, puis **À traiter**, afin de réutiliser le parcours de
relance documentaire existant. Une publication générale déjà importée n’est ni
convertie ni supprimée par ce mode.
