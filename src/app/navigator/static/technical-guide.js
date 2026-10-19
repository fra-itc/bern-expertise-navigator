window.PlatformTechnicalGuide = {
  "en": {
    "title": "How the platform works",
    "enter": "How does it work?",
    "overview": "Presentation",
    "steps": [
      [
        "A clear architecture, controlled by your team",
        "The browser presents the workspace; Python and FastAPI coordinate processing, matching and publishing. Dedicated modules handle research, knowledge and delivery. These are controlled workflows, not independent agents free to publish. This keeps the product understandable and lets each component evolve without rebuilding the whole experience.",
        [
          "Browser · HTML / CSS / JavaScript",
          "Python · FastAPI",
          "Sources → review → output"
        ]
      ],
      [
        "From documents to usable knowledge",
        "Public company pages are read with HTTPX and text extraction. PDF, Word, presentations and spreadsheets pass through dedicated parsers. The Knowledge Base stores source text alongside company records, while protected storage retains original uploads. The operator can correct the profile and decide what becomes part of the platform’s knowledge.",
        [
          "Web pages + uploaded files",
          "Extraction + source references",
          "Private Knowledge Base"
        ]
      ],
      [
        "Discovery proposes, the operator decides",
        "A lead supplies the context for complementary capabilities. With a configured SearXNG search service, discovery finds public candidate pages; supplied URLs also work directly. Apertus can structure source-supported fields when connected. Uncertain fields stay red. Approval opens a draft: a separate save is required to register the company.",
        [
          "Lead → complementary capabilities",
          "SearXNG / supplied URLs",
          "Candidate → operator review"
        ]
      ],
      [
        "Find complementary capabilities",
        "Private retrieval uses local multilingual E5 embeddings through SentenceTransformers, together with explicit capability expansion. It can connect a sensor objective with materials or validation expertise. The public research index supports semantic and keyword retrieval. Results are suggestions with evidence; similarity is not a promise of collaboration.",
        [
          "Local E5 embeddings",
          "Concepts + source passages",
          "Review possible connections"
        ]
      ],
      [
        "Apertus assists within boundaries",
        "The configured Apertus endpoint can interpret requests, extract structured information and curate existing partner IDs. Publishing does not rely on unrestricted generated claims: selected names, passages and links are resolved from stored sources. When the endpoint is unavailable, the application exposes its deterministic fallback. Local matching does not require an external embedding API.",
        [
          "Apertus · configurable endpoint",
          "Stored evidence + selected IDs",
          "Explicit fallback"
        ]
      ],
      [
        "One reviewed version, several outputs",
        "The representative approves current public passages before generating a pitch. The recipient page shows the ecosystem and supporting links; ReportLab creates its PDF. Email summarizes the approved pitch. Regeneration creates a new link and preserves older versions. Real sending requires configured SMTP and a public HTTPS address; it is not silently simulated.",
        [
          "Reviewed pitch version",
          "Interactive page + PDF",
          "SMTP after configuration"
        ]
      ],
      [
        "Open components, practical ownership",
        "The interface uses standard web technologies. FastAPI, SQLite, SentenceTransformers, local E5 and Piper provide replaceable building blocks; the public index also supports optional PostgreSQL infrastructure. Source code and configuration remain reviewable. Deployment still requires identity provisioning, encrypted storage, backups and service configuration. Custom narration text can be added later; today the same slide text can already be read aloud.",
        [
          "Reviewable code + configuration",
          "Local models + modular services",
          "Two roles · human approval"
        ]
      ]
    ]
  },
  "de": {
    "title": "So funktioniert die Plattform",
    "enter": "Wie funktioniert das?",
    "overview": "Präsentation",
    "steps": [
      [
        "Klare Architektur unter Ihrer Kontrolle",
        "Der Browser zeigt den Arbeitsbereich. Python und FastAPI koordinieren Verarbeitung, Matching und Veröffentlichung. Eigene Module übernehmen Recherche, Wissen und Versand. Es sind kontrollierte Abläufe: Kein autonomer Agent veröffentlicht selbstständig. Komponenten können weiterentwickelt werden, ohne die gesamte Oberfläche neu zu bauen.",
        [
          "Browser · HTML / CSS / JavaScript",
          "Python · FastAPI",
          "Quellen → Prüfung → Ausgabe"
        ]
      ],
      [
        "Von Dateien zu nutzbarem Wissen",
        "Öffentliche Firmenseiten werden mit HTTPX gelesen und als Text aufbereitet. Eigene Parser verarbeiten PDF, Word, Präsentationen und Tabellen. Die Knowledge Base speichert Quelltexte bei den Firmen; geschützter Speicher bewahrt hochgeladene Originale auf. Mitarbeitende korrigieren Profile und entscheiden, was ins Plattformwissen aufgenommen wird.",
        [
          "Webseiten + Dateien",
          "Extraktion + Quellen",
          "Private Knowledge Base"
        ]
      ],
      [
        "Recherche schlägt vor, Menschen entscheiden",
        "Ein Lead liefert den Kontext für ergänzende Kompetenzen. Ein konfigurierter SearXNG-Dienst findet öffentliche Kandidatenseiten; angegebene URLs funktionieren auch direkt. Apertus kann belegte Felder strukturieren, wenn verbunden. Unsichere Felder bleiben rot. Eine Freigabe öffnet einen Entwurf; erst separates Speichern erfasst die Firma.",
        [
          "Lead → ergänzende Kompetenzen",
          "SearXNG / angegebene URLs",
          "Vorschlag → Prüfung"
        ]
      ],
      [
        "Ergänzende Kompetenzen finden",
        "Private Suche kombiniert lokale mehrsprachige E5-Embeddings mit SentenceTransformers und expliziter Begriffserweiterung. Sensorziele können so mit Material- oder Validierungskompetenzen verbunden werden. Der öffentliche Forschungsindex unterstützt semantische und Stichwortsuche. Ergebnisse sind belegte Vorschläge; Ähnlichkeit ist keine Zusage einer Zusammenarbeit.",
        [
          "Lokale E5-Embeddings",
          "Konzepte + Quellpassagen",
          "Verbindungen prüfen"
        ]
      ],
      [
        "Apertus unterstützt innerhalb klarer Grenzen",
        "Der konfigurierte Apertus-Endpunkt kann Anfragen verstehen, Informationen strukturieren und vorhandene Partner-IDs auswählen. Veröffentlichte Namen, Passagen und Links werden aus gespeicherten Quellen aufgelöst. Ist der Endpunkt nicht erreichbar, zeigt die Anwendung den regelbasierten Ersatz an. Lokales Matching benötigt keine externe Embedding-API.",
        [
          "Apertus · konfigurierbarer Endpunkt",
          "Gespeicherte Belege + IDs",
          "Sichtbarer Ersatzablauf"
        ]
      ],
      [
        "Eine geprüfte Version, mehrere Ausgaben",
        "Der Repräsentant genehmigt aktuelle öffentliche Passagen vor der Pitch-Erstellung. Die Empfängerseite zeigt Ökosystem und Quellen; ReportLab erzeugt das PDF. Die E-Mail fasst den geprüften Pitch zusammen. Neugenerierung erstellt einen neuen Link und erhält alte Versionen. Echter Versand benötigt SMTP und eine öffentliche HTTPS-Adresse.",
        [
          "Geprüfte Pitch-Version",
          "Interaktive Seite + PDF",
          "SMTP nach Konfiguration"
        ]
      ],
      [
        "Offene Bausteine, praktische Kontrolle",
        "Die Oberfläche nutzt Webstandards. FastAPI, SQLite, SentenceTransformers, lokales E5 und Piper sind austauschbare Bausteine; der öffentliche Index unterstützt optional PostgreSQL. Code und Konfiguration bleiben prüfbar. Bereitstellung erfordert Konten, verschlüsselten Speicher, Backups und Dienste. Eigene Sprechertexte folgen später; der vorhandene Folientext kann bereits vorgelesen werden.",
        [
          "Prüfbarer Code + Konfiguration",
          "Lokale Modelle + Module",
          "Zwei Rollen · menschliche Freigabe"
        ]
      ]
    ]
  },
  "fr": {
    "title": "Comment fonctionne la plateforme",
    "enter": "Comment cela fonctionne ?",
    "overview": "Présentation",
    "steps": [
      [
        "Une architecture claire, sous votre contrôle",
        "Le navigateur présente l’espace de travail. Python et FastAPI coordonnent traitement, matching et publication. Des modules distincts gèrent recherche, connaissances et envoi. Ce sont des processus contrôlés : aucun agent autonome ne publie librement. Chaque composant peut évoluer sans reconstruire toute l’expérience.",
        [
          "Navigateur · HTML / CSS / JavaScript",
          "Python · FastAPI",
          "Sources → contrôle → résultat"
        ]
      ],
      [
        "Des fichiers aux connaissances utiles",
        "HTTPX lit les pages publiques et le texte est extrait. Des lecteurs dédiés traitent PDF, Word, présentations et tableaux. La Knowledge Base conserve les textes sources auprès des entreprises ; un stockage protégé garde les originaux téléversés. L’opérateur corrige le profil et décide des connaissances à enregistrer.",
        [
          "Pages web + fichiers",
          "Extraction + références",
          "Knowledge Base privée"
        ]
      ],
      [
        "La recherche propose, l’opérateur décide",
        "Le prospect fournit le contexte des compétences complémentaires. Un service SearXNG configuré trouve des pages publiques candidates ; les URL fournies fonctionnent aussi directement. Apertus peut structurer les champs documentés lorsqu’il est connecté. Les champs incertains restent rouges. L’approbation ouvre un brouillon ; un enregistrement distinct recense l’entreprise.",
        [
          "Prospect → compétences complémentaires",
          "SearXNG / URL fournies",
          "Candidat → contrôle humain"
        ]
      ],
      [
        "Trouver des compétences complémentaires",
        "La recherche privée associe les embeddings E5 multilingues locaux via SentenceTransformers à une expansion explicite des concepts. Un objectif lié aux capteurs peut ainsi rencontrer des compétences en matériaux ou validation. L’index scientifique public combine recherche sémantique et mots-clés. Les résultats sont des suggestions documentées, pas une promesse de collaboration.",
        [
          "Embeddings E5 locaux",
          "Concepts + passages sources",
          "Examiner les connexions"
        ]
      ],
      [
        "Apertus intervient dans un cadre défini",
        "Le point d’accès Apertus configuré peut interpréter les demandes, structurer les informations et sélectionner des identifiants existants. Les noms, passages et liens publiés proviennent des sources conservées. Si le service est indisponible, le traitement déterministe est indiqué. Le matching local ne nécessite pas d’API externe d’embeddings.",
        [
          "Apertus · service configurable",
          "Preuves conservées + identifiants",
          "Traitement de secours explicite"
        ]
      ],
      [
        "Une version contrôlée, plusieurs formats",
        "Le représentant approuve les passages publics actuels avant de générer le pitch. La page destinataire montre l’écosystème et les références ; ReportLab crée le PDF. L’e-mail résume le même pitch. Une nouvelle génération crée un lien distinct et conserve les anciennes versions. L’envoi réel exige SMTP et une adresse HTTPS publique.",
        [
          "Version du pitch contrôlée",
          "Page interactive + PDF",
          "SMTP après configuration"
        ]
      ],
      [
        "Des composants ouverts, une maîtrise pratique",
        "L’interface utilise les standards du web. FastAPI, SQLite, SentenceTransformers, E5 local et Piper sont remplaçables ; l’index public accepte aussi PostgreSQL en option. Code et configuration restent vérifiables. Le déploiement exige comptes, stockage chiffré, sauvegardes et services. Un texte de narration personnalisé pourra suivre ; les textes des slides peuvent déjà être lus.",
        [
          "Code + configuration vérifiables",
          "Modèles locaux + modules",
          "Deux rôles · validation humaine"
        ]
      ]
    ]
  }
};
