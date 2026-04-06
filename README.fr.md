# aura_core/diagnostics.py

> Ce module fait partie d'**AURA**, un assistant IA vocal et visuel 100 % local conçu et piloté par **Ludovic JAUGEY**.

---

## Ce que ça fait

- **Rapport de bord au démarrage** : collecte en parallèle les métriques matérielles (CPU, GPU, VRAM, températures, disque, réseau, alimentation) et les affiche dans un tableau coloré avec seuils configurables via YAML.
- **Contrôle d'intégrité cryptographique** : calcule l'empreinte BLAKE3 256 bits (ou SHA-256 en fallback) de l'ensemble des fichiers critiques du projet et détecte toute modification inter-sessions.
- **Journal HMAC-protégé** : signe chaque rapport d'intégrité avec un HMAC-SHA256 dérivé de l'identifiant machine — toute falsification du journal est détectée au démarrage suivant et déclenche une alerte vocale.

---

## Pourquoi c'est utile pour les systèmes IA locaux

Les assistants IA locaux exécutent du code, des modèles et des configurations sans supervision cloud. Un module comme `diagnostics.py` répond à trois besoins critiques dans ce contexte :

- **Auditabilité sans réseau** : la chaîne de confiance (hachage fichier → journal → HMAC) fonctionne entièrement en local, sans dépendance à un service externe de vérification d'intégrité.
- **Détection de corruption silencieuse** : une mise à jour partielle, un crash disque ou une modification involontaire d'un fichier de configuration peuvent altérer le comportement cognitif du système sans message d'erreur explicite — ce module en est le filet de sécurité.
- **Observabilité matérielle au démarrage** : les systèmes IA locaux sont souvent hébergés sur du matériel contraint (GPU consommateur, alimentation batterie, NVMe variable) ; le rapport de bord fournit un diagnostic instantané avant le lancement des pipelines lourds.

---

## Installation

### Prérequis

- Python 3.10 ou supérieur
- Les dépendances suivantes doivent être disponibles dans l'environnement du projet :

```bash
pip install psutil requests pyyaml pynvml blake3
```

> **Note :** `blake3` et `pynvml` sont optionnels. En leur absence, le module bascule automatiquement sur SHA-256 et `nvidia-smi` respectivement, sans interruption de service.

### Intégration dans le projet AURA

Ce module n'est pas autonome. Il s'intègre dans le package `aura_core` et requiert :

- `aura_core/config.py` — fournit `_AURA_HOME`, `_IS_WINDOWS`, `ORCHESTRATOR_CONFIG_PATH`
- `config/orchestrator_config.yaml` — seuils GPU et taille de bloc de hachage (optionnel, fallbacks intégrés)
- `modules/interfaces/logger_debug.py` — logger structuré (fallback `print` intégré)

### Utilisation minimale

```python
from aura_core.diagnostics import display_system_report

# Rapport complet au démarrage (sondes parallèles + vérification intégrité)
display_system_report()

# Avec instances STT et vocal_id si disponibles
display_system_report(stt_instance=stt, orchestrator=orchestrator, vocal_id=vocal_id)
```

---

*Concepteur et Programmeur : [Ludovic JAUGEY](https://www.linkedin.com/in/ludovic-jaugey-ia) assisté par Claude — 2026*
