# Concepteur et Programmeur : Ludovic JAUGEY assisté par Claude — 2026
# Ce module fait partie d'AURA, un assistant IA vocal et visuel 100 % local conçu et piloté par Ludovic JAUGEY.
# aura.cybernetique@gmail.com
"""
aura_core/diagnostics.py — Diagnostic matériel & rapport d'intégrité
====================================================================
Responsabilité unique : collecte des métriques matérielles et affichage
du rapport de démarrage avec contrôle d'intégrité cryptographique.

v2.7.0 — CFG-DIAG-1 : _HASH_CHUNK_SIZE externalisé vers YAML (2026-03-21) :

    [CFG-DIAG-1] _load_diag_config() : lecture de diagnostics.hash_chunk_size

      PROBLÈME :
        _HASH_CHUNK_SIZE = 65_536 (taille des blocs de lecture pour SHA-256)
        était hardcodé. Impossible d'ajuster pour les SSD NVMe Gen4+
        (128 KiB optimal) ou les HDD/réseau (16 KiB) sans modifier le code.

      CORRECTION :
        Ajout de `global _HASH_CHUNK_SIZE` dans _load_diag_config() et lecture
        de orchestrator_config.yaml section diagnostics.hash_chunk_size.
        Clé YAML déjà présente dans orchestrator_config.yaml v1.16.0 (CFG-16).

      ZÉRO RÉGRESSION :
        • Clé absente / section absente → _HASH_CHUNK_SIZE=65536 conservé.
        • Valeur < 512 → rejetée (chunk trop petit = overhead syscalls excessif).
        • Valeur invalide → warning + fallback.
      TAG : CFG-DIAG-1 v2.7.0

v2.6.0 — FIX-VRAM-SOURCE (2026-03-14) :

  [FIX-VRAM-SOURCE] get_vram_usage() + get_temperatures() — Unification source
  pynvml (watchdog) vs subprocess nvidia-smi (diagnostics) :

  ┌──────────────────────────────────────────────────────────────────────────┐
  │  PROBLÈME                                                                │
  ├───┬──────────────────────────────────────────────┬──────────────────────┤
  │ 1 │ Deux sources pour la même métrique VRAM.     │ ANTI-PATTERN         │
  │   │ get_vram_usage() → nvidia-smi subprocess     │                      │
  │   │ → MB décimaux (base 1000).                   │                      │
  │   │ watchdog + llm_backend → pynvml              │                      │
  │   │ → MiB binaires (base 1024).                  │                      │
  │   │ Écart observé log 2026-03-14 :               │                      │
  │   │   nvidia-smi : 2147 Mo                       │                      │
  │   │   pynvml     : 2322 MiB                      │                      │
  │   │ → TTS post-/clear annonçait 2147, watchdog   │                      │
  │   │   affichait 2322. Même matériel, même instant.│                     │
  ├───┼──────────────────────────────────────────────┼──────────────────────┤
  │ 2 │ subprocess nvidia-smi : fork + exec + decode │ PERF                 │
  │   │ ~80–150 ms par appel (RTX 3070 Ti observé).  │                      │
  │   │ Appelé dans le polling 500ms (commands.py    │                      │
  │   │ step 6b) → latence TTS +150ms minimum.       │                      │
  │   │ pynvml : appel C direct ~0.1 ms.             │                      │
  ├───┼──────────────────────────────────────────────┼──────────────────────┤
  │ 3 │ app.py L2529 : max(pynvml_peak, nvidia_smi)  │ UNITÉ INCORRECTE     │
  │   │ comparait MiB (pynvml) vs MB (nvidia-smi)    │                      │
  │   │ → résultat correct par coïncidence sur GPU   │                      │
  │   │ 8 GiB (valeurs proches), mais incorrect sur  │                      │
  │   │ GPU < 4 GiB ou > 16 GiB.                     │                      │
  └───┴──────────────────────────────────────────────┴──────────────────────┘

  CORRECTION :
    get_vram_usage() : pynvml nvmlDeviceGetMemoryInfo() en priorité.
      → Retourne MiB (base 1024, identique watchdog).
      → Format : "{used} MiB / {total} MiB ({pct}%)"
      → Fallback : subprocess nvidia-smi (comportement v2.5.x) si pynvml absent.
        Format fallback : "{used} Mo / {total} Mo ({pct}%)" (inchangé).
    get_temperatures() : pynvml nvmlDeviceGetTemperature() en priorité.
      → Valeur identique (°C = °C quelle que soit la source).
      → Fallback : subprocess nvidia-smi inchangé.
    _PYNVML_AVAILABLE : flag module-level (pattern _BLAKE3_AVAILABLE).

  CYCLE DE VIE pynvml :
    nvmlInit() appelé dans chaque fonction (idempotent, ref-counted).
    nvmlShutdown() NON appelé — le watchdog gère le cycle de vie applicatif.
    Thread-safety : pynvml est thread-safe après nvmlInit(). Compatible avec
    l'appel depuis ThreadPoolExecutor (display_system_report) et asyncio.to_thread.

  ZÉRO RÉGRESSION :
    • app.py re.findall(r"([0-9.]+)", vram_info) : extrait les nombres par
      position → fonctionne avec "2322 MiB / 8192 MiB (28.4%)" ✓
    • commands.py int(_str.split()[0]) : premier token = nombre ✓
    • app.py max(pynvml_peak, nvidia_smi_post) : désormais MiB vs MiB ✓
    • get_temperatures() retourne {"gpu": int} ou {"gpu": "N/A"} : inchangé ✓
    • display_system_report() : vram_val affiché dans specs dict, aucun parsing ✓
    • Fallback nvidia-smi si pynvml absent : comportement v2.5.x identique ✓

  TAG : FIX-VRAM-SOURCE v2.6.0

v2.5.0 — FIX-CPU-METRICS (2026-03-12) :

  ┌──────────────────────────────────────────────────────────────────────┐
  │  CORRECTION FIX-CPU-METRICS                                          │
  ├───┬────────────────────────────────────────────────┬────────────────┤
  │ 1 │ display_system_report() ne sondait pas la      │ HAUTE          │
  │   │ charge CPU système — absent du rapport de      │                │
  │   │ bord, monitoring trompeur.                     │                │
  │   │ AVANT : aucune sonde cpu_percent dans pool     │                │
  │   │ APRÈS : _measure_cpu_pct_diag() ajoutée.       │                │
  │   │   psutil.cpu_percent(interval=0.1) dans        │                │
  │   │   ThreadPoolExecutor — bloque 100ms dans le    │                │
  │   │   thread, non bloquant pour le rapport.        │                │
  │   │   Évite cpu_percent(interval=None) = 0.0 sur   │                │
  │   │   premier appel. Retourne "N/A" si psutil      │                │
  │   │   absent.                                      │                │
  ├───┼────────────────────────────────────────────────┼────────────────┤
  │ 2 │ _f_cpu = pool.submit(_measure_cpu_pct_diag)    │ HAUTE          │
  │   │ ajouté dans le pool de 8 threads.              │                │
  │   │ Résultat affiché : "Charge CPU (instant)" avec │                │
  │   │ couleur verte/jaune/rouge (seuils 50/80%).     │                │
  └───┴────────────────────────────────────────────────┴────────────────┘

  Unification : même pattern interval=0.1 que watchdog.py _get_cpu_pct()
    et place_description_base.py step-10 — source de vérité unique.


Contenu :
  - Sondes matérielles (CPU, GPU, disque, réseau, température)
  - Cryptographie 2026 : BLAKE3 + HMAC-SHA256 (section dédiée)
  - Vérification d'intégrité fichiers + authenticité du journal
  - display_system_report() avec parallélisation (FIX-STARTUP)

v2.4.0 — Extension périmètre d'intégrité (audit 2026) :

  ┌──────────────────────────────────────────────────────────────────────┐
  │  NOUVEAUX FICHIERS SURVEILLÉS                                        │
  ├───┬────────────────────────────────────────────────┬────────────────┤
  │ + │ config/user.yaml                               │ Profil         │
  │ + │ config/policies.yaml                           │ Configuration  │
  │ + │ config/orchestrator_config.yaml                │ Configuration  │
  │   │   (déjà lu par watchdog — cohérence intégrité) │                │
  │ + │ config/schemas/policies.schema.json            │ Configuration  │
  │ + │ config/schemas/user.schema.json                │ Configuration  │
  │ + │ aura_core/react_agent.py                       │ Noyau Async    │
  │ + │ modules/interfaces/camera_singleton.py         │ Interfaces     │
  ├───┼────────────────────────────────────────────────┼────────────────┤
  │ - │ aura_core/handlers.py  RETIRÉ du périmètre     │ —              │
  └───┴────────────────────────────────────────────────┴────────────────┘

  Chemins dynamiques via _AURA_HOME (config.py) — zéro chemin brut.
  fichiers_inviolables : react_agent.py, policies.yaml,
    orchestrator_config.yaml ajoutés.
  categories_map : 6 entrées ajoutées, handlers.py retiré.

v2.3.0 — Unification seuils YAML (audit 2026) :

  ┌──────────────────────────────────────────────────────────────────┐
  │  CORRECTION CFG-DIAG-THRESHOLD                                   │
  ├───┬──────────────────────────────────────────┬──────────────────┤
  │ 6 │ Seuil GPU hardcodé à 75°C dans           │ MOYEN            │
  │   │ display_system_report() — incohérence    │                  │
  │   │ possible avec watchdog.py si orchestrator│                  │
  │   │ _config.yaml est modifié.                │                  │
  │   │ AVANT : t_col = r if gpu_t >= 75         │                  │
  │   │         (littéraux 75 et 65 dans le code)│                  │
  │   │ APRÈS : DIAG_GPU_WARN_C (module-level)   │                  │
  │   │         DIAG_GPU_HOT_C  = warn - 10      │                  │
  │   │         _load_diag_config() lit le YAML  │                  │
  │   │         hardware_alerts.gpu_warn_celsius  │                  │
  │   │         Fallback sur 75 si YAML absent.  │                  │
  └───┴──────────────────────────────────────────┴──────────────────┘

v2.2.0 (audit sécurité 2026 — chiffrement état de l'art) :

  ┌──────────────────────────────────────────────────────────────────┐
  │  ANALYSE DES FAILLES CORRIGÉES                                   │
  ├───┬──────────────────────────────────────────┬──────────────────┤
  │ 1 │ SHA-256 tronqué [:16] = 64 bits          │ CRITIQUE         │
  │   │ Birthday attack à 2^32 ops (trivial 2026)│                  │
  │   │ → BLAKE3 256 bits full / SHA-256 256 bits│                  │
  ├───┼──────────────────────────────────────────┼──────────────────┤
  │ 2 │ integrity_log.json en clair, non signé   │ CRITIQUE         │
  │   │ Modification log + fichier = bypass total│                  │
  │   │ → HMAC-SHA256 du JSON sur clé machine    │                  │
  ├───┼──────────────────────────────────────────┼──────────────────┤
  │ 3 │ load_previous_integrity() sans vérif HMAC│ CRITIQUE         │
  │   │ Log falsifié accepté comme valide        │                  │
  │   │ → Vérification HMAC avant confiance      │                  │
  ├───┼──────────────────────────────────────────┼──────────────────┤
  │ 4 │ Aucune agility algorithmique             │ MOYEN            │
  │   │ Pas de champ "algo" — migration bloquée  │                  │
  │   │ → Champ "algo" dans chaque entrée log    │                  │
  ├───┼──────────────────────────────────────────┼──────────────────┤
  │ 5 │ Chunk read = 4 KB (syscalls excessifs)   │ MINEUR           │
  │   │ Inefficace sur gros fichiers .py         │                  │
  │   │ → 64 KB (_HASH_CHUNK_SIZE = 65536)       │                  │
  └───┴──────────────────────────────────────────┴──────────────────┘

  [CRYPTO-1] BLAKE3 (SotA 2026) :
    Fastest cryptographic hash — AVX2/AVX-512 parallelism,
    résistant aux attaques par extension de longueur, output 256 bits
    sans troncature. Fallback SHA-256 full (256 bits) si blake3 absent.
    `pip install blake3` — stable depuis 2022.

  [CRYPTO-2] Clé machine dérivée (MachineGuid Windows) :
    Clé 32 octets = SHA-256("AURA-INTEGRITY-v3::{MachineGuid}::{hostname}")
    Aucun secret stocké sur disque. Déterministe par machine.
    Fallback hostname pur si winreg indisponible (Linux/Mac).
    Mise en cache module-level (calcul unique au démarrage).

  [CRYPTO-3] HMAC-SHA256 du journal d'intégrité :
    Chaque sauvegarde integrity_log.json contient un champ "_hmac"
    = HMAC-SHA256(cle_machine, json_canonique_utf8).
    load_previous_integrity() verifie le HMAC avant de retourner
    les données. Si invalide → journal rejeté + critical_violation.

  [CRYPTO-4] Agility algorithmique :
    Chaque entrée de métadonnées stocke {"sig":..., "date":..., "algo":...}.
    Comparaison cross-algo suspendue (pas de fausse alerte sur migration).

  [CRYPTO-5] Chunk size 64 KB :
    _HASH_CHUNK_SIZE = 65536 — 16x plus efficace que 4096 sur SSD NVMe.

  Rétrocompatibilité :
    • Logs sans "_hmac" → migration silencieuse (warning + re-sauvegarde)
    • Logs sans "algo"  → comparaison acceptée, tracé "legacy"
    • API display_system_report() inchangée (même signature)
    • check_list v2.1.0 conservée à l'identique (hors ajouts/retrait v2.4.0)

Auteur  : Ludovic JAUGEY — 2026
Version : 2.6.0 (FIX-VRAM-SOURCE : pynvml unifié pour VRAM + températures)
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import hmac as _hmac_module
import json
import os
import pathlib
import platform
import subprocess
from datetime import datetime
from typing import Optional

import psutil
import requests

from aura_core.config import _AURA_HOME, _IS_WINDOWS, ORCHESTRATOR_CONFIG_PATH

# Import logger avec fallback
try:
    from modules.interfaces.logger_debug import (
        info,
        warning,
        error,
        critical,
    )
except ImportError:  # pragma: no cover
    def info(msg, **kw):    print(f"[INFO]  {msg}")
    def warning(msg, **kw): print(f"[WARN]  {msg}")
    def error(msg, **kw):   print(f"[ERROR] {msg}")
    def critical(msg, **kw):print(f"[CRIT]  {msg}")

# ---------------------------------------------------------------------------
# Cache latence réseau (anti-ping excessif)
# ---------------------------------------------------------------------------
_LAST_NET_CHECK: dict = {"time": 0, "value": "N/A"}


# ===========================================================================
# CFG-DIAG-THRESHOLD : Seuils d'affichage GPU — VALEURS PAR DÉFAUT
# ─────────────────────────────────────────────────────────────────────────────
# Ces constantes servent de FALLBACK si orchestrator_config.yaml est absent
# ou si la section hardware_alerts: est manquante.
# En fonctionnement normal, _load_diag_config() les réassigne depuis YAML.
#
# Cohérence avec watchdog.py : les deux modules lisent la même clé YAML
#   hardware_alerts.gpu_warn_celsius → source unique de vérité.
#
# DIAG_GPU_WARN_C : seuil alerte rouge dans le rapport de démarrage (°C).
#                   Identique à WD_GPU_WARN_C de watchdog.py.
# DIAG_GPU_HOT_C  : seuil "attention" jaune = warn - 10°C (dérivé, non YAML).
#                   Réajusté automatiquement si warn change.
# ===========================================================================

DIAG_GPU_WARN_C: int = 75   # Seuil rouge : alerte thermique (°C)
DIAG_GPU_HOT_C:  int = 65   # Seuil jaune : température élevée = warn - 10

# ===========================================================================
# CFG-DIAG-THRESHOLD : Chargement des seuils depuis orchestrator_config.yaml
# ===========================================================================

def _load_diag_config() -> None:
    """
    [CFG-DIAG-THRESHOLD] Charge les seuils d'affichage GPU depuis YAML.
    [CFG-DIAG-1 v2.7.0]  Charge également diagnostics.hash_chunk_size → _HASH_CHUNK_SIZE.

    Lit hardware_alerts.gpu_warn_celsius dans orchestrator_config.yaml et
    réassigne DIAG_GPU_WARN_C et DIAG_GPU_HOT_C (= warn - 10) au niveau
    module, garantissant la cohérence avec watchdog.py qui lit la même clé.

    Stratégie identique à watchdog._load_watchdog_config() :
      • Import yaml + résolution _AURA_HOME identique aux autres modules.
      • Fallback gracieux si YAML absent, section manquante ou clé absente.
      • Typage int() explicite — YAML peut retourner float selon formattage.
      • Tout échec logué en WARNING, valeurs par défaut conservées.

    Appelée UNE SEULE FOIS au chargement du module (fin de ce fichier).
    Thread-safety : non requise (module-level, avant tout thread).
    """
    global DIAG_GPU_WARN_C, DIAG_GPU_HOT_C
    global _HASH_CHUNK_SIZE   # [CFG-DIAG-1 v2.7.0]

    try:
        import yaml

        cfg_path = ORCHESTRATOR_CONFIG_PATH

        if not cfg_path.exists():
            # Fichier absent : fallback silencieux.
            # Cas légitimes : tests unitaires, première installation.
            info(
                f"orchestrator_config.yaml introuvable ({cfg_path}) "
                "— seuils affichage GPU par défaut conservés (75°C / 65°C)",
                category="DIAGNOSTICS",
            )
            return

        with cfg_path.open(encoding="utf-8") as fh:
            full_cfg = yaml.safe_load(fh)

        if not isinstance(full_cfg, dict):
            warning(
                "orchestrator_config.yaml vide ou invalide "
                "— seuils affichage GPU par défaut conservés",
                category="DIAGNOSTICS",
            )
            return

        ha = full_cfg.get("hardware_alerts")
        if not isinstance(ha, dict):
            # Section absente (ancien fichier) : fallback silencieux.
            info(
                "Section hardware_alerts: absente dans orchestrator_config.yaml "
                "— seuils affichage GPU par défaut conservés (75°C / 65°C)",
                category="DIAGNOSTICS",
            )
            return

        if "gpu_warn_celsius" in ha:
            DIAG_GPU_WARN_C = int(ha["gpu_warn_celsius"])
            # DIAG_GPU_HOT_C = seuil "attention" jaune, dérivé : warn - 10°C.
            # Pas de clé YAML séparée — ratio fixe, cohérent avec l'UX d'AURA.
            # Si warn = 75 → hot = 65 (inchangé).
            # Si warn = 80 → hot = 70 (adapté automatiquement).
            DIAG_GPU_HOT_C = DIAG_GPU_WARN_C - 10

            info(
                f"Seuils affichage GPU chargés depuis YAML — "
                f"rouge ≥ {DIAG_GPU_WARN_C}°C, jaune ≥ {DIAG_GPU_HOT_C}°C",
                category="DIAGNOSTICS",
            )

        # ── [CFG-DIAG-1 v2.7.0] Taille bloc hachage SHA-256 ──────────────────
        diag_cfg = full_cfg.get("diagnostics")
        if isinstance(diag_cfg, dict) and "hash_chunk_size" in diag_cfg:
            try:
                _v = int(diag_cfg["hash_chunk_size"])
                if _v >= 512:
                    _HASH_CHUNK_SIZE = _v
                else:
                    warning(
                        f"[CFG-DIAG-1] diagnostics.hash_chunk_size={_v} < 512"
                        f" invalide (overhead syscalls excessif)"
                        f" — {_HASH_CHUNK_SIZE} conservé",
                        category="DIAGNOSTICS",
                    )
            except (TypeError, ValueError):
                warning(
                    f"[CFG-DIAG-1] diagnostics.hash_chunk_size="
                    f"{diag_cfg['hash_chunk_size']!r} invalide"
                    f" — {_HASH_CHUNK_SIZE} conservé",
                    category="DIAGNOSTICS",
                )

    except ImportError as exc:
        warning(
            f"PyYAML non disponible — seuils affichage GPU par défaut conservés : {exc}",
            category="DIAGNOSTICS",
        )
    except Exception as exc:
        warning(
            f"Erreur chargement seuils GPU depuis YAML : {exc} "
            "— seuils par défaut conservés (75°C / 65°C)",
            category="DIAGNOSTICS",
        )


# ===========================================================================
# SONDES MATÉRIELLES
# (Inchangées v2.0.0 → v2.4.0 — zéro régression)
# ===========================================================================

def get_cpu_topology() -> Optional[dict]:
    """Topologie CPU hybride (Intel 12th Gen+). Heuristique conservative."""
    try:
        total_phys = psutil.cpu_count(logical=False)
        total_log  = psutil.cpu_count(logical=True)
        ht_ratio   = total_log / total_phys if total_phys else 1
        if ht_ratio >= 2:
            p_cores = total_phys
            e_cores = 0
        else:
            p_cores = total_log - total_phys
            e_cores = total_phys - p_cores if total_phys > p_cores else 0
        p_threads = p_cores * 2
        return {
            "p_info": f"{p_cores} P-Cores ({p_threads} Threads)",
            "e_info": f"{e_cores} E-Cores ({e_cores} Threads)",
            "total":  f"{total_phys} Phys / {total_log} Log",
        }
    except Exception:
        return None


def get_gpu_wmi() -> str:
    """Identification GPU via WMI (Windows uniquement)."""
    try:
        cmd    = "wmic path win32_VideoController get name"
        output = subprocess.check_output(cmd, shell=True).decode().split("\n")
        return output[1].strip() if len(output) > 1 else "N/A"
    except Exception:
        return "WMI indisponible"


def get_gpu_nvidia() -> str:
    """Identification GPU via nvidia-smi."""
    try:
        cmd    = "nvidia-smi --query-gpu=name --format=csv,noheader"
        output = subprocess.check_output(cmd, shell=True).decode().strip()
        return output if output else "Aucun GPU NVIDIA"
    except Exception:
        return "Pilote NVIDIA non trouvé"


def get_audio_card() -> str:
    """Identification du contrôleur audio (encodage cp1252 Windows)."""
    try:
        cmd    = "wmic path win32_SoundDevice get name"
        output = subprocess.check_output(cmd, shell=True)\
            .decode("cp1252", errors="ignore").split("\n")
        devices = [l.strip() for l in output[1:] if l.strip() and "Name" not in l]
        if not devices:
            return "Aucune carte détectée"
        phys = [d for d in devices if "Realtek" in d or "NVIDIA High Definition" in d]
        return phys[0] if phys else devices[0]
    except Exception:
        return "Erreur décodage"


def get_disk_info() -> str:
    """Capacité du volume système."""
    try:
        path  = "C:" if _IS_WINDOWS else "/"
        usage = psutil.disk_usage(path)
        return f"{round(usage.total / (1024**3), 2)} Go (Système)"
    except Exception:
        return "N/A"


def _measure_cpu_pct_diag() -> float | None:
    """
    [FIX-CPU-METRICS v2.5.0] Mesure la charge CPU instantanée pour le rapport
    de démarrage.

    Utilise psutil.cpu_percent(interval=0.1) :
      • interval=0.1 : bloque 100ms dans le thread du ThreadPoolExecutor →
        mesure sur une vraie fenêtre d'activité CPU.
      • Évite cpu_percent(interval=None) qui retourne 0.0 au premier appel
        du process (compteur OS non encore initialisé).
      • Exécutée dans pool.submit() → zéro impact sur le thread principal.

    Unification watchdog.py v5.1.0 : même pattern interval=0.1 dans un thread.

    Returns:
        float [0.0–100.0] ou None si psutil absent.
    """
    try:
        return float(psutil.cpu_percent(interval=0.1))
    except Exception:
        return None


def get_vram_usage() -> str:
    """
    Utilisation VRAM en temps réel.

    [FIX-VRAM-SOURCE v2.6.0] Source unifiée pynvml (priorité) :
      AVANT : subprocess nvidia-smi → MB décimaux (base 1000) → ~80-150ms.
      APRÈS : pynvml nvmlDeviceGetMemoryInfo() → MiB binaires (base 1024) → ~0.1ms.
      Même source que watchdog.py et llm_backend.py → cohérence totale.
      Fallback nvidia-smi si pynvml absent (comportement v2.5.x préservé).

    Format retour :
      pynvml   : "{used} MiB / {total} MiB ({pct}%)"
      fallback : "{used} Mo / {total} Mo ({pct}%)"
      erreur   : "N/A"

    Parsing callers (zéro régression) :
      app.py   re.findall(r"([0-9.]+)", …) → extrait nombres par position ✓
      app.py   int(.split()[0])            → premier token = nombre ✓
      commands.py int(.split()[0])         → idem ✓

    Cycle de vie pynvml :
      nvmlInit() appelé ici (idempotent). nvmlShutdown() non appelé
      (cycle de vie géré par le watchdog).
    """
    # ── Priorité 1 : pynvml (~0.1 ms, MiB binaires, même source que watchdog) ─
    if _PYNVML_AVAILABLE and _pynvml is not None:
        try:
            _pynvml.nvmlInit()
            _handle  = _pynvml.nvmlDeviceGetHandleByIndex(0)
            _mem     = _pynvml.nvmlDeviceGetMemoryInfo(_handle)
            used_mib  = _mem.used  // (1024 * 1024)
            total_mib = _mem.total // (1024 * 1024)
            pct       = round((used_mib / total_mib) * 100, 1) if total_mib else 0.0
            return f"{used_mib} MiB / {total_mib} MiB ({pct}%)"
        except Exception:
            pass   # nvmlInit pas encore possible → fallback nvidia-smi

    # ── Fallback : subprocess nvidia-smi (comportement v2.5.x) ─────────────────
    try:
        cmd = "nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits"
        out = subprocess.check_output(cmd, shell=True).decode().strip().split(",")
        used, total = int(out[0].strip()), int(out[1].strip())
        pct = round((used / total) * 100, 1)
        return f"{used} Mo / {total} Mo ({pct}%)"
    except Exception:
        return "N/A"


def get_cloud_latency(
    url: str = "https://generativelanguage.googleapis.com",
    ttl: int = 30,
) -> str:
    """
    Latence HTTPS vers le cloud. Cache TTL=30s (anti-ping excessif).
    FIX-DUPNET : remplace get_network_latency (supprimée v2.0.0).
    """
    global _LAST_NET_CHECK
    now = __import__("time").time()
    if now - _LAST_NET_CHECK["time"] < ttl:
        return _LAST_NET_CHECK["value"]
    try:
        import time as _t
        start   = _t.time()
        requests.get(url, timeout=2.0)
        latency = int((_t.time() - start) * 1000)
        result  = f"{latency} ms"
    except requests.exceptions.RequestException as _net_exc:
        result = "Timeout"
        try:
            from aura_core.self_debugger import record_error as _re_diag  # noqa: PLC0415
            _re_diag("network", _net_exc, context={"url": url, "source": "get_cloud_latency"})
        except Exception:
            pass
    except Exception as _net_exc:
        result = "Erreur Réseau"
        try:
            from aura_core.self_debugger import record_error as _re_diag  # noqa: PLC0415
            _re_diag("network", _net_exc, context={"url": url, "source": "get_cloud_latency"})
        except Exception:
            pass
    _LAST_NET_CHECK["time"]  = now
    _LAST_NET_CHECK["value"] = result
    return result


def get_power_status() -> tuple[str, str]:
    """État d'alimentation (Secteur/Batterie) et mode de performance associé."""
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return "Secteur", "Performance Max"
        source = "Secteur" if battery.power_plugged else "Batterie"
        mode   = "Performance" if battery.power_plugged else "Économie"
        return source, mode
    except Exception:
        return "Inconnue", "N/A"


def get_performance_mode() -> str:
    """Profil d'énergie Windows actif."""
    try:
        cmd = "powercfg /getactivescheme"
        out = subprocess.check_output(cmd, shell=True).decode()
        if "Performances optimales" in out or "High performance" in out:
            return "Haute Performance"
        return "Équilibré"
    except Exception:
        return "Standard"


def get_temperatures() -> dict:
    """
    Température GPU en temps réel.

    [FIX-VRAM-SOURCE v2.6.0] Source unifiée pynvml (priorité) :
      AVANT : subprocess nvidia-smi → ~80-150ms de latence.
      APRÈS : pynvml nvmlDeviceGetTemperature() → ~0.1ms.
      Valeur identique (°C = °C quelle que soit la source).
      Fallback nvidia-smi si pynvml absent.

    Retour : {"gpu": int} en °C, ou {"gpu": "N/A"} si indisponible.
    Format identique à v2.5.x — zéro régression pour display_system_report()
    et app.py (_gpu_temp = _temperatures.get("gpu") or 0.0).
    """
    temps: dict = {"gpu": "N/A"}

    # ── Priorité 1 : pynvml (~0.1 ms) ──────────────────────────────────────────
    if _PYNVML_AVAILABLE and _pynvml is not None:
        try:
            _pynvml.nvmlInit()
            _handle      = _pynvml.nvmlDeviceGetHandleByIndex(0)
            temps["gpu"] = int(_pynvml.nvmlDeviceGetTemperature(
                _handle, _pynvml.NVML_TEMPERATURE_GPU
            ))
            return temps
        except Exception:
            pass   # fallback nvidia-smi

    # ── Fallback : subprocess nvidia-smi (comportement v2.5.x) ─────────────────
    try:
        cmd = "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader"
        temps["gpu"] = int(subprocess.check_output(cmd, shell=True).decode().strip())
    except Exception:
        pass
    return temps


# ===========================================================================
# CRYPTOGRAPHIE — BLAKE3 / SHA-256 / HMAC-SHA256
# ===========================================================================
#
# Fonctions internes (préfixe _) :
#   _compute_hash()        → Hachage fichier 256 bits, BLAKE3 ou SHA-256
#   _derive_machine_key()  → Clé HMAC 32 octets, dérivée du MachineGuid
#   _sign_log()            → HMAC-SHA256 d'un payload JSON canonique
#   _verify_log_hmac()     → Vérification HMAC avec compare_digest()
#
# Fonctions publiques (API inchangée depuis v2.0.0) :
#   get_file_checksum()    → str : hash 256 bits hexadécimal
#   get_file_metadata()    → dict : {"sig", "date", "algo"}
#   load_previous_integrity() → tuple[dict, bool]
#   save_current_integrity()  → None
#   log_vram()             → None (log VRAM debug)
#
# ===========================================================================

# ── [CRYPTO-1] Disponibilité BLAKE3 ────────────────────────────────────────
try:
    import blake3 as _blake3_mod
    _BLAKE3_AVAILABLE = True
    _HASH_ALGO_NAME   = "blake3"
except ImportError:
    _blake3_mod       = None          # type: ignore[assignment]
    _BLAKE3_AVAILABLE = False
    _HASH_ALGO_NAME   = "sha256"

# ── [FIX-VRAM-SOURCE v2.6.0] Disponibilité pynvml ──────────────────────────
# pynvml est la source primaire pour VRAM et températures GPU.
# Même bibliothèque que watchdog.py et llm_backend.py → source unique de vérité.
# nvmlInit() est idempotent (ref-counted) : safe à appeler depuis get_vram_usage()
# même si le watchdog a déjà appelé nvmlInit() en amont.
# nvmlShutdown() N'EST PAS appelé ici : le watchdog gère le cycle de vie applicatif.
try:
    import pynvml as _pynvml
    _PYNVML_AVAILABLE = True
except ImportError:
    _pynvml           = None          # type: ignore[assignment]
    _PYNVML_AVAILABLE = False

# ── [CRYPTO-5] Chunk size optimisé : 64 KB ─────────────────────────────────
# 16× plus efficace que 4 KB pour les fichiers Python et les modèles YAML.
# Les SSD NVMe transfèrent 512 KB+ par burst — ce chunk en capture plusieurs
# sans saturer la mémoire de travail.
_HASH_CHUNK_SIZE: int = 65_536

# ── Cache clé machine (dérivation unique au démarrage) ─────────────────────
_MACHINE_KEY_CACHE: Optional[bytes] = None


def _derive_machine_key() -> bytes:
    """
    [CRYPTO-2] Clé HMAC de 32 octets dérivée de l'identifiant machine.

    Sources d'identité (par priorité décroissante) :
      1. Windows : HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid
      2. Linux   : /etc/machine-id (systemd)
      3. Fallback: platform.node() (hostname)

    Dérivation :
      SHA-256("AURA-INTEGRITY-v3::{guid}::{hostname}".encode("utf-8"))
      → 32 octets déterministes, spécifiques à la machine.

    Propriétés :
      • Aucun secret stocké sur disque (pas de fichier de clé à protéger).
      • Résistant à la copie du log : un log exporté sur une autre machine
        ne passe pas la vérification HMAC (clé différente).
      • Cache module-level : une seule dérivation par session AURA.
    """
    global _MACHINE_KEY_CACHE
    if _MACHINE_KEY_CACHE is not None:
        return _MACHINE_KEY_CACHE

    machine_guid = ""

    if _IS_WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            ) as key:
                machine_guid = winreg.QueryValueEx(key, "MachineGuid")[0]
        except Exception:
            pass

    if not machine_guid:
        try:
            machine_guid = pathlib.Path("/etc/machine-id").read_text().strip()
        except Exception:
            machine_guid = platform.node()

    try:
        hostname = platform.node()
    except Exception:
        hostname = "aura-host"

    raw = f"AURA-INTEGRITY-v3::{machine_guid}::{hostname}".encode("utf-8")
    _MACHINE_KEY_CACHE = hashlib.sha256(raw).digest()  # 32 bytes
    return _MACHINE_KEY_CACHE


def _compute_hash(filepath: str) -> tuple[str, str]:
    """
    [CRYPTO-1] Calcule le hash cryptographique complet d'un fichier.

    BLAKE3 (prioritaire, si disponible) :
      - Parallèle AVX2/AVX-512, 3-5× plus rapide que SHA-256
      - Pas d'attaque par extension de longueur
      - Output 256 bits — aucune troncature

    SHA-256 (fallback) :
      - Output COMPLET 256 bits — aucune troncature
      - Corrige la faille v2.0.0 qui tronquait à 64 bits [:16]
      - Birthday resistance : 2^128 (au lieu de 2^32 en v2.0.0)

    [CRYPTO-5] Chunk 64 KB — 16× moins de syscalls qu'avec 4 KB.

    Returns:
        (hash_hex, algo_name) — hash_hex = 64 chars hex (256 bits)
    """
    try:
        if _BLAKE3_AVAILABLE and _blake3_mod is not None:
            hasher = _blake3_mod.blake3()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
                    hasher.update(chunk)
            return hasher.hexdigest(), "blake3"
        else:
            sha256 = hashlib.sha256()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
                    sha256.update(chunk)
            return sha256.hexdigest(), "sha256"
    except Exception:
        return "Introuvable", _HASH_ALGO_NAME


def _sign_log(payload: str) -> str:
    """
    [CRYPTO-3] Calcule HMAC-SHA256 d'une chaîne JSON canonique.

    Args:
        payload: JSON sérialisé (sort_keys=True, ensure_ascii=True)

    Returns:
        HMAC hexadécimal 64 chars (256 bits).
    """
    key = _derive_machine_key()
    return _hmac_module.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_log_hmac(payload: str, expected_hmac: str) -> bool:
    """
    [CRYPTO-3] Vérifie le HMAC-SHA256 d'un payload JSON.

    Utilise hmac.compare_digest() — comparaison en temps constant,
    résistante aux timing attacks (bonne pratique même hors réseau).

    Returns:
        True si HMAC valide, False si altération détectée.
    """
    computed = _sign_log(payload)
    return _hmac_module.compare_digest(computed, expected_hmac)


# ===========================================================================
# API PUBLIQUE — INTÉGRITÉ FICHIERS
# ===========================================================================

def get_file_checksum(filepath: str) -> str:
    """
    Signature cryptographique d'un fichier — 256 bits complets, sans troncature.

    [CRYPTO-1] BLAKE3 ou SHA-256 selon disponibilité.
    [CRYPTO-5] Chunk 64 KB.

    Signature identique à v2.0.0 — "Introuvable" si fichier inaccessible.

    Returns:
        str: Hash hexadécimal 64 chars (256 bits) ou "Introuvable".
    """
    hash_hex, _ = _compute_hash(filepath)
    return hash_hex


def get_file_metadata(filepath: str) -> dict:
    """
    Métadonnées temporelles et cryptographiques d'un fichier.

    [CRYPTO-4] Ajoute "algo" pour l'agility algorithmique.
      Permet la comparaison même lors d'une migration blake3→autre.

    Returns:
        dict: {"sig": str, "date": str, "algo": str}
    """
    try:
        stats    = os.stat(filepath)
        mtime    = datetime.fromtimestamp(stats.st_mtime).strftime("%Y/%m/%d %H:%M:%S")
        hash_hex, algo = _compute_hash(filepath)
        return {"sig": hash_hex, "date": mtime, "algo": algo}
    except (OSError, ValueError):
        return {"sig": "Introuvable", "date": "N/A", "algo": "Introuvable"}


def log_vram(message: str, vram_before: str = "", vram_after: str = "", **kwargs) -> None:
    """Log VRAM dans le fichier debug uniquement. (Inchangé v2.0.0 → v2.4.0)"""
    try:
        from modules.interfaces.logger_debug import debug_logger
        debug_logger.info(
            f"[VRAM] {message}",
            vram_before=vram_before,
            vram_after=vram_after,
            **kwargs,
        )
    except Exception:
        pass


# ===========================================================================
# INTÉGRITÉ — PERSISTANCE HMAC-PROTÉGÉE
# ===========================================================================

def load_previous_integrity() -> tuple[dict, bool]:
    """
    Charge l'état du dernier démarrage réussi avec vérification HMAC.

    [CRYPTO-3] Processus :
      1. Lire le JSON brut du fichier log
      2. Extraire "_hmac" de la dernière entrée
      3. Reconstruire le payload signable (JSON sans "_hmac")
      4. Vérifier via hmac.compare_digest() — résistant aux timing attacks
      5. HMAC invalide → ({}, tampered=True) → critical_violation en amont
      6. HMAC absent  → log legacy v2.0.0/v2.1.0, migration silencieuse

    Rétrocompatibilité v2.0.0/v2.1.0 :
      Logs sans "_hmac" chargés normalement + INFO migration.
      Re-sauvegardés avec HMAC au prochain cycle (aucune action manuelle).

    Returns:
        tuple[dict, bool]:
          dict — données dernière session (vide si introuvable/altéré)
          bool — True si HMAC invalide (altération détectée)
    """
    log_path = _AURA_HOME / "config" / "integrity_log.json"

    if not log_path.exists():
        return {}, False

    try:
        raw_text = log_path.read_text(encoding="utf-8")
        history  = json.loads(raw_text)

        if not isinstance(history, list) or not history:
            return {}, False

        last_entry = history[-1]

        # ── Vérification HMAC ────────────────────────────────────────────────
        stored_hmac = last_entry.pop("_hmac", None)

        if stored_hmac is not None:
            # Log v2.2.0+ — vérification obligatoire
            payload_to_verify = json.dumps(
                last_entry,
                ensure_ascii=True,
                sort_keys=True,
            )
            if not _verify_log_hmac(payload_to_verify, stored_hmac):
                warning(
                    "HMAC du journal d'intégrité INVALIDE — altération détectée",
                    log_path=str(log_path),
                    category="INTEGRITY",
                )
                return {}, True  # tampered = True
        else:
            # Log legacy — migration transparente
            info(
                "Journal d'intégrité au format legacy (sans HMAC) — migration v2.2.0",
                category="INTEGRITY",
            )

        return last_entry, False

    except (OSError, json.JSONDecodeError, KeyError) as exc:
        warning(
            f"Erreur lecture journal d'intégrité : {exc}",
            category="INTEGRITY",
        )
        return {}, False


def save_current_integrity(current_data: dict) -> None:
    """
    Historise l'état actuel avec signature HMAC-SHA256.

    [CRYPTO-3] Processus de signature :
      1. Sérialiser current_data en JSON canonique (sort_keys, ensure_ascii)
         La canonicalisation garantit un HMAC identique cross-plateforme.
      2. HMAC-SHA256(clé_machine, json_canonique)
      3. Injecter "_hmac" dans une COPIE (current_data non modifié)
      4. Appender à l'historique, tronquer à 50 entrées, écrire

    Note : current_data n'est jamais modifié (copie défensive via JSON round-trip).
    """
    log_path = _AURA_HOME / "config" / "integrity_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Signature ────────────────────────────────────────────────────────────
    canonical_payload = json.dumps(
        current_data,
        ensure_ascii=True,
        sort_keys=True,
    )
    hmac_signature = _sign_log(canonical_payload)

    # Copie signée — deep copy via JSON round-trip (défensif)
    signed_entry = json.loads(canonical_payload)
    signed_entry["_hmac"] = hmac_signature

    # ── Historique (50 cycles max) ───────────────────────────────────────────
    history: list = []
    if log_path.exists():
        try:
            history = json.loads(log_path.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except (OSError, json.JSONDecodeError):
            history = []

    history.append(signed_entry)
    if len(history) > 50:
        history = history[-50:]

    log_path.write_text(
        json.dumps(history, indent=4, ensure_ascii=True),
        encoding="utf-8",
    )


# ===========================================================================
# [WD-FILE-1] API BOOT INTEGRITY SUMMARY — consommée par app.py au démarrage
# ===========================================================================

def get_boot_integrity_summary() -> "str | None":
    """
    [WD-FILE-1] Retourne un résumé des violations détectées AU DÉMARRAGE.

    Lit integrity_log.json (déjà écrit par display_system_report via
    save_current_integrity) et compare la dernière entrée avec l'avant-dernière.
    Opération de LECTURE PURE — aucun effet de bord, aucune écriture.

    Appelée par app.py APRÈS display_system_report() pour alimenter
    state.system.boot_integrity_violations (bullet WM permanent de session).

    Logique de comparaison :
      • Si < 2 entrées dans l'historique → None (première session, pas de baseline).
      • Pour chaque fichier : sig session_courante ≠ sig session_précédente
        ET sig_précédente ≠ "N/A" ET sigs non "Introuvable" × 2
        → fichier modifié inter-sessions.
      • sig == "Introuvable" en session courante → fichier absent au démarrage.
      • Algo changé entre sessions → comparaison suspendue (pas de fausse alerte).
      • HMAC invalide → None + warning (données non fiables, pas d'alerte mensongère).

    Returns:
        str  : description courte des violations, ex :
               "policies.yaml modifié entre sessions | app.py absent au démarrage"
        None : tout nominal, ou < 2 sessions, ou données non fiables.

    ZÉRO RÉGRESSION :
      • display_system_report() : inchangé ligne à ligne.
      • save_current_integrity() : inchangé.
      • load_previous_integrity() : inchangé — appelé indépendamment ici.
      • Appelable même si display_system_report() n'a pas encore tourné
        (log absent → None immédiat).
    TAG : WD-FILE-1 v1.0.0
    """
    log_path = _AURA_HOME / "config" / "integrity_log.json"

    if not log_path.exists():
        return None

    try:
        history = json.loads(log_path.read_text(encoding="utf-8"))
        if not isinstance(history, list) or len(history) < 2:
            return None   # Première session — pas de baseline antérieure

        current_entry  = history[-1]
        previous_entry = history[-2]

        # ── Vérification HMAC entrée courante ────────────────────────────────
        # Si tampered → données non fiables → pas d'alerte mensongère
        _hmac_current = current_entry.get("_hmac")
        if _hmac_current:
            _payload = json.dumps(
                {k: v for k, v in current_entry.items() if k != "_hmac"},
                ensure_ascii=True,
                sort_keys=True,
            )
            if not _verify_log_hmac(_payload, _hmac_current):
                warning(
                    "[WD-FILE-1] get_boot_integrity_summary : HMAC entrée courante"
                    " invalide — résumé non disponible",
                    category="INTEGRITY",
                )
                return None

        violations: list[str] = []

        for name, current in current_entry.items():
            if name == "_hmac":
                continue
            if not isinstance(current, dict):
                continue

            previous = previous_entry.get(name, {})
            if not isinstance(previous, dict):
                continue

            sig_cur  = current.get("sig",  "N/A")
            sig_prev = previous.get("sig", "N/A")
            algo_cur  = current.get("algo",  "N/A")
            algo_prev = previous.get("algo", "N/A")

            # Fichier absent au démarrage courant
            if sig_cur == "Introuvable":
                violations.append(f"{_basename(name)} absent au démarrage")
                continue

            # Pas de baseline antérieure pour ce fichier
            if sig_prev in ("N/A", "Introuvable"):
                continue

            # Migration algo → comparaison suspendue (pas de fausse alerte)
            if algo_cur not in ("N/A", "Introuvable") \
                    and algo_prev not in ("N/A", "legacy", algo_cur):
                continue

            # Signature différente → modification inter-sessions
            if sig_cur != sig_prev:
                violations.append(f"{_basename(name)} modifié entre sessions")

        return " | ".join(violations) if violations else None

    except Exception as exc:
        warning(
            f"[WD-FILE-1] get_boot_integrity_summary erreur : {exc} — None retourné",
            category="INTEGRITY",
        )
        return None


def _basename(label: str) -> str:
    """Extrait le nom court depuis un label check_list ou un chemin."""
    import os as _os
    return _os.path.basename(label) or label


# ===========================================================================
# [WD-FILE-1 v1.1.0] REGISTRE FICHIERS AURA — source unique de vérité
# ===========================================================================
# Extrait de display_system_report() pour être importable par watchdog.py.
# Utilisé par :
#   • display_system_report()         → rapport boot + integrity_log.json
#   • async_file_integrity_watchdog() → surveillance session (via watchdog.py)
#   • get_boot_integrity_summary()    → bullet WM boot_integrity_violations
#
# "COLLECTION_MARKER" : entrée spéciale ChromaDB — exclue du watchdog session
#   (pas un fichier disque, géré séparément via orchestrator.collection_sig).
#
# categories_map et fichiers_inviolables restent LOCAUX à display_system_report()
#   → leur sémantique (TTS groupé, critical_violation) est exclusivement boot.
#   → les élever ici créerait une dépendance inutile pour le watchdog session.
#
# ZÉRO RÉGRESSION display_system_report() :
#   check_list = _AURA_FILE_REGISTRY  ← une ligne, comportement identique.
# TAG : WD-FILE-1 v1.1.0
_AURA_FILE_REGISTRY: dict[str, str] = {
    # ── [1] Point d'entrée ────────────────────────────────────────────────
    "Script Principal Systeme (aura.py)":
        str(_AURA_HOME / "aura.py"),

    # ── [2] Configuration centrale config/ ───────────────────────────────
    "Module de Tracabilite (logger_custom.py)":
        "modules/interfaces/logger_custom.py",
    "Configuration Modele Local (model.yaml)":
        str(_AURA_HOME / "config" / "model.yaml"),
    "Profil Utilisateur Config (config/user.yaml)":
        str(_AURA_HOME / "config" / "user.yaml"),
    "Politiques Systeme (config/policies.yaml)":
        str(_AURA_HOME / "config" / "policies.yaml"),
    "Configuration Orchestrateur (orchestrator_config.yaml)":
        str(_AURA_HOME / "config" / "orchestrator_config.yaml"),

    # ── [2bis] Schémas de validation config/schemas/ ─────────────────────
    "Schema Politiques (policies.schema.json)":
        str(_AURA_HOME / "config" / "schemas" / "policies.schema.json"),
    "Schema Profil Utilisateur (user.schema.json)":
        str(_AURA_HOME / "config" / "schemas" / "user.schema.json"),

    # ── [3] Modules cognitifs ─────────────────────────────────────────────
    "Donnees Medicales (user_profile.py)":
        "modules/cognition/user_profile.py",
    "Base Biochimie (base_knowledge.py)":
        "modules/cognition/base_knowledge.py",
    "Moteur de Personnalite (personality.py)":
        "modules/cognition/personality.py",
    "Logique Ethique (ethics.py)":
        "modules/cognition/ethics.py",

    # ── [4] Moteur (engine) ───────────────────────────────────────────────
    "Orchestrateur Principal (orchestrator.py)":
        "modules/engine/orchestrator.py",
    "Base de donnees RAG (ChromaDB)":
        "COLLECTION_MARKER",
    "Generateur de Prompts (prompt_builder.py)":
        "modules/engine/prompt_builder.py",

    # ── [5] Interfaces v2.0.0 ─────────────────────────────────────────────
    "Interface Vocale STT (stt_backend.py)":
        "modules/interfaces/stt_backend.py",
    "Interface Vocale TTS (tts_backend.py)":
        "modules/interfaces/tts_backend.py",
    "Interface Flux Vocal (tts_voicemode_backend.py)":
        "modules/interfaces/tts_voicemode_backend.py",
    "Interface Visuelle UI (ui_backend.py)":
        "modules/interfaces/ui_backend.py",
    "Interface Intelligence LLM (llm_backend.py)":
        "modules/interfaces/llm_backend.py",
    "Module de Debug (logger_debug.py)":
        "modules/interfaces/logger_debug.py",
    "Verification Locuteur (speaker_verification.py)":
        "modules/interfaces/speaker_verification.py",
    "Gestionnaire d'Etat (state_manager.py)":
        "modules/core/state_manager.py",
    "Bus d'Evenements (event_bus.py)":
        "modules/core/event_bus.py",
    "Gestionnaire Facial Async (face_async_manager_base.py)":
        "modules/interfaces/face_async_manager_base.py",
    "Handler STT Async (stt_async_handler.py)":
        "modules/interfaces/stt_async_handler.py",
    "Description Visuelle (place_description_base.py)":
        "modules/interfaces/place_description_base.py",
    "Gestionnaire Avatar (avatar_display.py)":
        str(_AURA_HOME / "modules" / "interfaces" / "avatar_display.py"),
    "Animation Avatar (avatar_animation.py)":
        str(_AURA_HOME / "modules" / "interfaces" / "avatar_animation.py"),
    "Analyseur Multi-Visages (face_analyzer_multi.py)":
        "modules/interfaces/face_analyzer_multi.py",
    "Gestionnaire Camera (camera_singleton.py)":
        "modules/interfaces/camera_singleton.py",

    # ── [7] Noyau Async aura_core/ (v2.1.0+) ─────────────────────────────
    "Machine d'Etats Async (aura_core/app.py)":
        str(_AURA_HOME / "aura_core" / "app.py"),
    "Configuration Globale Async (aura_core/config.py)":
        str(_AURA_HOME / "aura_core" / "config.py"),
    "Pipeline LLM-TTS Async (aura_core/pipeline.py)":
        str(_AURA_HOME / "aura_core" / "pipeline.py"),
    "Watchdog Thermique Async (aura_core/watchdog.py)":
        str(_AURA_HOME / "aura_core" / "watchdog.py"),
    "Commandes Console (aura_core/commands.py)":
        str(_AURA_HOME / "aura_core" / "commands.py"),
    "Rapport Integrite (aura_core/diagnostics.py)":
        str(_AURA_HOME / "aura_core" / "diagnostics.py"),
    "Package Init Async (aura_core/__init__.py)":
        str(_AURA_HOME / "aura_core" / "__init__.py"),
    "Agent ReAct (aura_core/react_agent.py)":
        str(_AURA_HOME / "aura_core" / "react_agent.py"),

    # ── [8] Interfaces async (v2.1.0+) ────────────────────────────────────
    "Patch STT Async (stt_backend_async_patch.py)":
        "modules/interfaces/stt_backend_async_patch.py",

    # ── [9] STT pipeline complet (WD-FILE-2 v2.8.0) ──────────────────────
    "Moteur STT Principal (stt_core.py)":
        "modules/interfaces/stt_core.py",
    "Configuration STT (stt_config.py)":
        "modules/interfaces/stt_config.py",
    "VAD et Gate TTS (stt_vad.py)":
        "modules/interfaces/stt_vad.py",

    # ── [10] Outils MCP clients (WD-FILE-2 v2.8.0) ───────────────────────
    "Serveur Meteo MCP (weather_server.py)":
        str(_AURA_HOME / "mcp_servers" / "weather_server.py"),
    "Serveur Actualites MCP (news_server.py)":
        str(_AURA_HOME / "mcp_servers" / "news_server.py"),
    "Serveur PubMed MCP (pubmed_server.py)":
        str(_AURA_HOME / "mcp_servers" / "pubmed_server.py"),
    "Registre MCP Client (_core.py)":
        str(_AURA_HOME / "aura_core" / "tools" / "_core.py"),
    "Serveur Chimie MCP (chemistry_server.py)":
        str(_AURA_HOME / "mcp_servers" / "chemistry_server.py"),
    "Serveur Pipeline Document MCP (document_pipeline_server.py)":  # [WD-DOC-1]
        str(_AURA_HOME / "mcp_servers" / "document_pipeline_server.py"),
    "Pipeline Extraction Documentaire (document_pipeline.py)":      # [WD-DOC-1]
        str(_AURA_HOME / "mcp_servers" / "document_pipeline.py"),

    # ── [11] Goals et memoire (v3.0.0 — migration aura_core/) ────────────
    "Gestionnaire Goals (goal_manager.py)":
        str(_AURA_HOME / "aura_core" / "goals" / "goal_manager.py"),
    "Executeur Goals (goal_executor.py)":
        str(_AURA_HOME / "aura_core" / "goals" / "goal_executor.py"),
    "Init Package Goals (aura_core/goals/__init__.py)":          # [WD-FILE-4 v2.11.0]
        str(_AURA_HOME / "aura_core" / "goals" / "__init__.py"),
    "Consolidateur Memoire (memory_consolidator.py)":
        str(_AURA_HOME / "aura_core" / "memory_consolidator.py"),

    # ── [12] Divers (WD-FILE-2 v2.8.0) ───────────────────────────────────
    "Parseur Delta Scene (scene_diff_parser.py)":
        "modules/interfaces/scene_diff_parser.py",
    "Chargeur Configuration (config_loader.py)":
        "modules/cognition/config_loader.py",
    "File d'Emails (email_queue.py)":
        str(_AURA_HOME / "aura_core" / "email_queue" / "email_queue.py"),

    # ── [13] Handlers evenements (WD-FILE-2 v2.9.0) ──────────────────────
    # Retiré délibérément en v2.4.0 — réintégré v2.9.0 :
    # handlers.py gère vision, TTS, goals, events — critique pour l'intégrité.
    "Handlers Evenements (aura_core/handlers.py)":
        str(_AURA_HOME / "aura_core" / "handlers.py"),

    # ── [14] Mémoire & connaissance aura_core/ (WD-FILE-3 v2.10.0) ───────
    # Injectés dans chaque prompt via build_system_prompt() — modification
    # silencieuse = comportement cognitif corrompu sans aucune alerte.
    "Registre Entites (aura_core/entity_store.py)":
        str(_AURA_HOME / "aura_core" / "entity_store.py"),
    "Etat Monde Persistant (aura_core/world_state.py)":
        str(_AURA_HOME / "aura_core" / "world_state.py"),
    "Graphe Connaissances (aura_core/knowledge_graph.py)":
        str(_AURA_HOME / "aura_core" / "knowledge_graph.py"),
    "Modele de Soi (aura_core/self_model.py)":
        str(_AURA_HOME / "aura_core" / "self_model.py"),
    "Memoire Meta-Cognitive (aura_core/meta_memory.py)":        # [WD-FILE-4 v2.11.0]
        str(_AURA_HOME / "aura_core" / "meta_memory.py"),
    "Raisonnement Temporel (aura_core/temporal_reasoner.py)":   # [WD-FILE-4 v2.11.0]
        str(_AURA_HOME / "aura_core" / "temporal_reasoner.py"),

    # ── [15] Sécurité & introspection aura_core/ (WD-FILE-3 v2.10.0) ─────
    # self_audit / self_debugger : modules de surveillance eux-mêmes non surveillés
    # jusqu'ici — angle mort critique (ironie sécurité).
    "Auto-Audit Securite (aura_core/self_audit.py)":
        str(_AURA_HOME / "aura_core" / "self_audit.py"),
    "Auto-Debugger (aura_core/self_debugger.py)":
        str(_AURA_HOME / "aura_core" / "self_debugger.py"),
    "Boucle Recherche Autonome (aura_core/aura_research_loop.py)":
        str(_AURA_HOME / "aura_core" / "aura_research_loop.py"),

    # ── [16] Serveurs MCP exécution (WD-FILE-3 v2.10.0) ──────────────────
    # code_executor_server.py : vecteur d'exécution de code arbitraire —
    # modification = sandbox compromis, niveau sécurité maximal.
    "Serveur Execution Code MCP (code_executor_server.py)":
        str(_AURA_HOME / "mcp_servers" / "code_executor_server.py"),
    "Serveur Fetch MCP (fetch_server.py)":
        str(_AURA_HOME / "mcp_servers" / "fetch_server.py"),

    # ── [17] Outils MCP clients aura_core/tools/ (WD-FILE-3 v2.10.0) ─────
    "Init Package Tools (aura_core/tools/__init__.py)":          # [WD-FILE-4 v2.11.0]
        str(_AURA_HOME / "aura_core" / "tools" / "__init__.py"),
    "Client PubMed MCP (tools/pubmed.py)":
        str(_AURA_HOME / "aura_core" / "tools" / "pubmed.py"),
    "Client Actualites MCP (tools/news.py)":
        str(_AURA_HOME / "aura_core" / "tools" / "news.py"),
    "Client Meteo MCP (tools/weather.py)":
        str(_AURA_HOME / "aura_core" / "tools" / "weather.py"),

    # ── [18] Configuration supplémentaire (WD-FILE-3 v2.10.0) ────────────
    "Registre Serveurs MCP (config/mcp_servers.json)":
        str(_AURA_HOME / "config" / "mcp_servers.json"),
    "Objectifs Autonomes (config/goals.yaml)":
        str(_AURA_HOME / "config" / "goals.yaml"),

    # ── [19] Goals journal (WD-FILE-3 v2.10.0) ───────────────────────────
    "Journal Goals (goals/goals_journal.py)":
        str(_AURA_HOME / "aura_core" / "goals" / "goals_journal.py"),

    # ── [20] Exercices sandbox (WD-FILE-3 v2.10.0) ───────────────────────
    # error_fix.py invoqué automatiquement par self_debugger — modification
    # = correction automatique d'erreurs corrompue (vecteur indirect).
    "Correcteur Auto Erreurs (exercises/error_fix.py)":
        str(_AURA_HOME / "aura_core" / "exercises" / "error_fix.py"),
    "Exemple Sandbox (exercises/primes.py)":
        str(_AURA_HOME / "aura_core" / "exercises" / "primes.py"),
}


# ===========================================================================
# RAPPORT DE DÉMARRAGE (FIX-STARTUP : sondes parallèles via ThreadPoolExecutor)
# ===========================================================================

def display_system_report(stt_instance=None, orchestrator=None, vocal_id=None) -> None:
    """
    Rapport de bord au démarrage avec vérification d'intégrité cryptographique.

    Signature inchangée (zéro régression API).

    Modifications internes v2.4.0 :
      - check_list étendue :
          [2bis] config/ : user.yaml, policies.yaml, orchestrator_config.yaml
          [2ter] config/schemas/ : policies.schema.json, user.schema.json
          [7] aura_core/ : react_agent.py ajouté
          [5] modules/interfaces/ : camera_singleton.py ajouté
          [7] aura_core/handlers.py RETIRÉ du périmètre de surveillance
      - categories_map : react_agent.py → "Noyau Async",
          camera_singleton.py → "Interfaces",
          policies.yaml / orchestrator_config.yaml / *.schema.json → "Configuration"
          handlers.py retiré (cohérence avec check_list)
      - fichiers_inviolables : react_agent.py, policies.yaml,
          orchestrator_config.yaml ajoutés.
      - Tous les chemins sont dynamiques via _AURA_HOME — zéro chemin brut.

    Modifications internes v2.3.0 :
      - Seuil GPU rouge : DIAG_GPU_WARN_C (chargé depuis YAML, défaut 75°C)
        Remplace les 3 occurrences du littéral 75 hardcodé.
      - Seuil GPU jaune : DIAG_GPU_HOT_C = DIAG_GPU_WARN_C - 10 (dérivé)
        Remplace le littéral 65 hardcodé.
      - Comportement visuel identique à v2.2.0 si YAML absent.

    Modifications internes v2.2.0 :
      - load_previous_integrity() → retourne (dict, bool)
        Si bool=True : critical_violation immédiate + alerte vocale dédiée
      - Affichage de l'algorithme actif (BLAKE3 ou SHA-256)
      - Comparaison cross-algo suspendue (pas de fausse alerte sur migration)
      - Affichage hash tronqué à 16 chars pour la lisibilité (hash complet en log)
    """

    # =========================================================================
    # categories_map — Association fichier → catégorie vocale/thématique
    # Étendu v2.1.0 : "Noyau Async" pour aura_core/*
    # Étendu v2.2.0 : "Interfaces" pour stt_backend_async_patch.py
    # Étendu v2.4.0 : "Configuration" pour YAML/JSON config + schemas,
    #                 "Noyau Async" pour react_agent.py,
    #                 "Interfaces" pour camera_singleton.py
    #                 handlers.py RETIRÉ (cohérence avec check_list)
    # =========================================================================
    categories_map = {
        # ── Cœur du Système ───────────────────────────────────────────────────
        "aura.py":                      "Cœur du Système",
        "orchestrator.py":              "Cœur du Système",
        "prompt_builder.py":            "Cœur du Système",
        "logger_custom.py":             "Cœur du Système",
        # ── Maintenance ───────────────────────────────────────────────────────
        "logger_debug.py":              "Maintenance",
        "diagnostics.py":               "Maintenance",
        # ── Personnalité ──────────────────────────────────────────────────────
        "personality.py":               "Personnalité",
        # ── Éthique ───────────────────────────────────────────────────────────
        "ethics.py":                    "Éthique",
        # ── Profil ────────────────────────────────────────────────────────────
        # Note : "user.yaml" couvre les deux instances (config/ et persona_data/)
        # car la correspondance se fait sur os.path.basename(path).
        "user.yaml":                    "Profil",
        "user_profile.py":              "Profil",
        # ── Configuration (v2.4.0) ────────────────────────────────────────────
        "policies.yaml":                "Configuration",
        "orchestrator_config.yaml":     "Configuration",
        "policies.schema.json":         "Configuration",
        "user.schema.json":             "Configuration",
        "model.yaml":                   "Configuration",
        # ── Connaissances ─────────────────────────────────────────────────────
        "base_knowledge.py":            "Connaissances",
        # ── Interfaces ────────────────────────────────────────────────────────
        "stt_backend.py":               "Interfaces",
        "tts_backend.py":               "Interfaces",
        "tts_voicemode_backend.py":     "Interfaces",
        "llm_backend.py":               "Interfaces",
        "speaker_verification.py":      "Interfaces",
        "face_async_manager_base.py":   "Interfaces",
        "stt_async_handler.py":         "Interfaces",
        "stt_backend_async_patch.py":   "Interfaces",
        "place_description_base.py":    "Vision",
        "avatar_display.py":            "Interfaces",
        "avatar_animation.py":          "Interfaces",
        "document_handler.py":          "Interfaces",
        "face_analyzer_multi.py":       "Interfaces",
        "ui_backend.py":                "Interfaces",
        "camera_singleton.py":          "Interfaces",       # [v2.4.0]
        # ── Noyau Async aura_core/ ────────────────────────────────────────────
        "app.py":                       "Noyau Async",
        "config.py":                    "Noyau Async",
        "pipeline.py":                  "Noyau Async",
        "watchdog.py":                  "Noyau Async",
        # "handlers.py" RETIRÉ v2.4.0 — cohérence avec check_list
        "commands.py":                  "Noyau Async",
        "__init__.py":                  "Noyau Async",
        "react_agent.py":               "Noyau Async",      # [v2.4.0]
        # ── Mémoire & connaissance (WD-FILE-3 v2.10.0) ───────────────────────
        "entity_store.py":              "Mémoire",
        "world_state.py":               "Mémoire",
        "knowledge_graph.py":           "Mémoire",
        "meta_memory.py":               "Mémoire",          # [WD-FILE-4 v2.11.0]
        "temporal_reasoner.py":         "Mémoire",          # [WD-FILE-4 v2.11.0]
        "self_model.py":                "Noyau Async",
        # ── Sécurité & introspection (WD-FILE-3 v2.10.0) ─────────────────────
        "self_audit.py":                "Sécurité",
        "self_debugger.py":             "Maintenance",
        "aura_research_loop.py":        "Noyau Async",
        # ── Serveurs MCP exécution (WD-FILE-3 v2.10.0) ───────────────────────
        "code_executor_server.py":      "Sécurité",
        "fetch_server.py":              "Outils MCP",
        "document_pipeline_server.py":  "Outils MCP",       # [WD-DOC-1]
        "document_pipeline.py":         "Outils MCP",       # [WD-DOC-1]
        # ── Outils MCP clients (WD-FILE-3 v2.10.0) ───────────────────────────
        "pubmed.py":                    "Outils MCP",
        "news.py":                      "Outils MCP",
        "weather.py":                   "Outils MCP",
        # ── Configuration supplémentaire (WD-FILE-3 v2.10.0) ─────────────────
        "mcp_servers.json":             "Configuration",
        "goals.yaml":                   "Configuration",
        # ── Goals journal (WD-FILE-3 v2.10.0) ────────────────────────────────
        "goals_journal.py":             "Goals",
        # ── Exercices sandbox (WD-FILE-3 v2.10.0) ────────────────────────────
        "error_fix.py":                 "Maintenance",
        "primes.py":                    "Maintenance",
    }

    # =========================================================================
    # fichiers_inviolables — Toute modification → critical_violation = True
    # Étendu v2.4.0 : react_agent.py, policies.yaml, orchestrator_config.yaml
    # =========================================================================
    fichiers_inviolables = [
        # ── Cœur historique (v2.0.0) ──────────────────────────────────────────
        "orchestrator.py",
        "ethics.py",
        "aura.py",
        "state_manager.py",
        "event_bus.py",
        # ── Noyau Async INVIOLABLE (v2.1.0+) ─────────────────────────────────
        "app.py",           # Machine d'états async principale
        "config.py",        # Pool TTS + chemins infrastructure
        "pipeline.py",      # Pipeline LLM→TTS asyncio.Queue
        "diagnostics.py",   # Auto-protection rapport d'intégrité
        "__init__.py",      # Points d'entrée packages goals+tools+aura_core — re-exports critiques  [WD-FILE-4 v2.11.0]
        # ── Noyau étendu INVIOLABLE (v2.4.0) ─────────────────────────────────
        "react_agent.py",           # Agent ReAct — logique d'outillage critique
        "policies.yaml",            # Politiques système — niveau gouvernance
        "orchestrator_config.yaml", # Configuration centrale — seuils + modèles
        # ── Noyau étendu INVIOLABLE (v2.9.0) ─────────────────────────────────
        "handlers.py",      # Handlers vision/TTS/goals/events — réintégré v2.9.0
        "llm_backend.py",   # Inférence LLM — falsification = réponses corrompues
        "stt_core.py",      # Moteur STT — modification = pipeline vocal mort
        # ── Mémoire INVIOLABLE (WD-FILE-3 v2.10.0) ───────────────────────────
        # Injectés dans chaque prompt — falsification silencieuse = corruption
        # cognitive sans aucune détection amont possible.
        "entity_store.py",          # Registre entités — corruption mémoire directe
        "world_state.py",           # Snapshot externe — contexte erroné cross-session
        "knowledge_graph.py",       # Graphe SPO — relations inter-entités corrompues
        "self_model.py",            # Auto-description — identité/capacités tronquées
        "meta_memory.py",           # 5e couche méta — directives auto-correction corrompues  [WD-FILE-4 v2.11.0]
        "temporal_reasoner.py",     # Contexte temporel prompt — conscience temporelle falsifiée  [WD-FILE-4 v2.11.0]
        # ── Sécurité INVIOLABLE (WD-FILE-3 v2.10.0) ──────────────────────────
        "self_audit.py",            # Module d'audit — modification = surveillance aveugle
        "code_executor_server.py",  # Sandbox exécution — vecteur sécurité maximal
    ]

    modified_categories: set  = set()
    critical_violation:  bool = False
    log_was_tampered:    bool = False

    c, j, v, r, res, b = "\033[96m", "\033[93m", "\033[92m", "\033[91m", "\033[0m", "\033[94m"

    # ── Sondes parallèles (FIX-STARTUP) ──────────────────────────────────────
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=8, thread_name_prefix="StartupDiag"
    ) as pool:
        _f_perf   = pool.submit(get_performance_mode)
        _f_net    = pool.submit(get_cloud_latency)
        _f_audio  = pool.submit(get_audio_card)
        _f_gpu_wm = pool.submit(get_gpu_wmi)
        _f_gpu_nv = pool.submit(get_gpu_nvidia)
        _f_vram   = pool.submit(get_vram_usage)
        _f_temps  = pool.submit(get_temperatures)
        _f_cpu    = pool.submit(_measure_cpu_pct_diag)   # [FIX-CPU-METRICS v2.5.0]

        usage          = psutil.disk_usage("C:" if _IS_WINDOWS else "/")
        topo           = get_cpu_topology()
        raw_pwr_source, pwr_mode = get_power_status()

        win_mode    = _f_perf.result()
        net_latency = _f_net.result()
        audio_card  = _f_audio.result()
        gpu_wmi_val = _f_gpu_wm.result()
        gpu_nv_val  = _f_gpu_nv.result()
        vram_val    = _f_vram.result()
        temps       = _f_temps.result()
        cpu_pct_val = _f_cpu.result()                    # [FIX-CPU-METRICS v2.5.0]

    libre_pct  = round((usage.free / usage.total) * 100, 1)
    pwr_source = (
        f"{r}Batterie (Performances dégradées){res}"
        if raw_pwr_source == "Batterie"
        else f"{v}Secteur{res}"
    )
    display_latency = f"{r}{net_latency}{res}" if "Timeout" in net_latency else net_latency

    # [FIX-CPU-METRICS v2.5.0] — Affichage Charge CPU avec coloration seuils.
    # Seuils : vert < 50% | jaune 50–80% | rouge > 80%.
    # "N/A" si psutil absent (cpu_pct_val=None).
    if cpu_pct_val is None:
        display_cpu = f"{r}N/A{res}"
    elif cpu_pct_val >= 80.0:
        display_cpu = f"{r}{cpu_pct_val:.1f}%{res}"
    elif cpu_pct_val >= 50.0:
        display_cpu = f"{j}{cpu_pct_val:.1f}%{res}"
    else:
        display_cpu = f"{v}{cpu_pct_val:.1f}%{res}"

    specs = {
        "OS":                   f"{platform.system()} {platform.release()}",
        "Processeur":           f"{platform.processor()[:45]}...",
        "Coeurs Totaux":        topo["total"] if topo else "N/A",
        "Architecture P-Cores": topo["p_info"] if topo else "N/A",
        "Architecture E-Cores": topo["e_info"] if topo else "N/A",
        "RAM Totale":           f"{round(psutil.virtual_memory().total / (1024**3), 2)} Go",
        "Charge CPU (instant)": display_cpu,                      # [FIX-CPU-METRICS v2.5.0]
        "Disque Total":         get_disk_info(),
        "Espace Libre":         f"{round(usage.free / (1024**3), 2)} Go ({libre_pct}%)",
        "Carte Son":            audio_card,
        "Microphone Actif":     (
            f"Index {stt_instance.mic_index}" if stt_instance else "Scan en cours..."
        ),
        "Empreintes Vocales":   (
            ", ".join(vocal_id.voiceprints.keys())
            if vocal_id and hasattr(vocal_id, "voiceprints")
            else "Aucune"
        ),
        "Source Energie":       f"{pwr_source} ({win_mode})",
        "GPU (Methode WMI)":    gpu_wmi_val,
        "GPU (Methode NV)":     f"{gpu_nv_val} / {vram_val}",
        "Latence Reseau":       display_latency,
    }

    print(f"\n{b}{'='*65}{res}")
    print(f"{j}[STATION AURA] - DIAGNOSTIC SYSTEME & SECURITE - {datetime.now().strftime('%d/%m/%Y %H:%M')}{res}")
    print(f"{b}{'='*65}{res}")
    for k, val in specs.items():
        print(f"{c}{k:<22}{res} : {val}")
        if k == "Architecture P-Cores":
            print(f"   {j}--- [NOTE] Seuls les P-Cores sont pris en compte pour le 'num_thread'.{res}")

    # ── [CRYPTO-1] Affichage algorithme de hachage actif ─────────────────────
    algo_label = (
        f"{v}BLAKE3  256 bits (SotA 2026){res}"
        if _BLAKE3_AVAILABLE
        else f"{j}SHA-256 256 bits{res} {j}(pip install blake3 pour BLAKE3){res}"
    )
    print(f"{b}{'-'*65}{res}")
    print(f"{c}Algo intégrité{res}        : {algo_label}")
    print(f"{c}Protection journal{res}    : {v}HMAC-SHA256 (clé machine, sans stockage){res}")

    # ── [CFG-DIAG-THRESHOLD] Affichage température GPU avec seuils YAML ──────
    # DIAG_GPU_WARN_C et DIAG_GPU_HOT_C sont chargés depuis orchestrator_config.yaml
    # hardware_alerts.gpu_warn_celsius par _load_diag_config() (appel module-level).
    # Cohérent avec watchdog.py WD_GPU_WARN_C — source unique de vérité.
    print(f"{b}{'-'*65}{res}")
    gpu_t = temps.get("gpu", "N/A")
    if isinstance(gpu_t, int):
        t_col  = r if gpu_t >= DIAG_GPU_WARN_C else (j if gpu_t >= DIAG_GPU_HOT_C else v)
        alerte = f" {r}!! ALERTE THERMIQUE CRITIQUE !!{res}" if gpu_t >= DIAG_GPU_WARN_C else ""
        print(f"{j}TEMPERATURE GPU{res}        : {t_col}{gpu_t}C{res}{alerte}")
        if gpu_t >= DIAG_GPU_WARN_C:
            print(f"\033[41m\033[97m DANGER : Temperature GPU elevee ({gpu_t}C). Risque de throttling. \033[0m")
    else:
        print(f"{j}TEMPERATURE GPU{res}        : {r}N/A{res}")

    print(f"{b}{'-'*65}{res}")
    print(f"{j}AUTO-CHECK GLOBAL (Comparaison avec démarrage précédent){res}")

    # =========================================================================
    # check_list — Inventaire complet des fichiers surveillés
    #
    # Structure v2.4.0 :
    #   [1]    Point d'entrée
    #   [2]    Configuration centrale config/         ← étendu v2.4.0
    #   [2bis] Schémas de validation config/schemas/  ← nouveau v2.4.0
    #   [2ter] Données persona persona_data/
    #   [3]    Modules cognitifs
    #   [4]    Moteur (engine)
    #   [5]    Interfaces v2.0.0                      ← camera_singleton ajouté
    #   [6]    Core
    #   [7]    Noyau Async aura_core/                 ← react_agent ajouté,
    #                                                    handlers.py RETIRÉ
    #   [8]    Interfaces async
    #
    # Tous les chemins sont construits via _AURA_HOME (config.py) — aucun
    # chemin brut Windows/Linux dans ce dictionnaire.
    # =========================================================================
    # [WD-FILE-1 v1.1.0] Source unique de vérité — registre module-level.
    # categories_map et fichiers_inviolables restent locaux (sémantique boot).
    check_list = _AURA_FILE_REGISTRY

    # ── [CRYPTO-3] Chargement log avec vérification HMAC ────────────────────
    previous_data, log_was_tampered = load_previous_integrity()

    if log_was_tampered:
        critical(
            "JOURNAL D'INTEGRITE ALTERE — HMAC invalide",
            log_path=str(_AURA_HOME / "config" / "integrity_log.json"),
            category="INTEGRITY",
        )
        print(f"\n{r}{'!'*65}{res}")
        print(f"\033[41m\033[97m ALERTE : Le journal d'integrite a ete modifie (HMAC invalide). {res}")
        print(f"\033[41m\033[97m          Tous les resultats ci-dessous sont NON FIABLES.        {res}")
        print(f"{r}{'!'*65}{res}\n")
        critical_violation = True

    current_session_data: dict = {}

    for name, path in check_list.items():
        if path == "COLLECTION_MARKER" and orchestrator:
            current = {
                "sig":  orchestrator.collection_sig,
                "date": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                "algo": "collection",
            }
        else:
            current = get_file_metadata(path)

        current_session_data[name] = current
        prev = previous_data.get(name, {"sig": "N/A", "date": "N/A", "algo": "N/A"})

        # ── [CRYPTO-4] Comparaison cross-algo safe ───────────────────────────
        # Si l'algo a changé (ex : migration sha256→blake3), les signatures
        # ne sont pas comparables — suspension de la comparaison, pas de fausse alerte.
        prev_algo    = prev.get("algo", "legacy")
        current_algo = current.get("algo", _HASH_ALGO_NAME)
        algo_changed = (
            prev_algo not in ("N/A", "legacy", current_algo)
            and current_algo != "Introuvable"
        )

        changed = (
            not algo_changed
            and (current["sig"] != prev["sig"])
            and (prev["sig"] != "N/A")
        )

        sig_col = r if changed else v

        if changed:
            file_basename = os.path.basename(path)
            warning(
                f"Violation d'intégrité détectée : {file_basename}",
                path=path,
                old_sig=prev["sig"][:16],
                new_sig=current["sig"][:16],
                algo=current_algo,
                category="INTEGRITY",
            )
            if file_basename in categories_map:
                modified_categories.add(categories_map[file_basename])
            if file_basename in fichiers_inviolables:
                critical_violation = True

        if current["sig"] == "Introuvable":
            sig_col = r

        # Affichage : hash tronqué à 16 chars pour lisibilité (complet en log)
        def _short(h: str) -> str:
            return f"{h[:16]}..." if h not in ("N/A", "Introuvable") else h

        algo_badge = f" [{current_algo}]" if current_algo not in ("N/A", "Introuvable") else ""
        print(f"{c}{name:<48}{res}")
        print(f"  --- Actuel   : {sig_col}{_short(current['sig'])}{res}{j}{algo_badge}{res} ({current['date']})")

        if algo_changed:
            print(f"  --- {j}Migration algo {prev_algo} -> {current_algo} (comparaison suspendue){res}")
        elif changed:
            print(f"  --- Precedent : {j}{_short(prev['sig'])}{res} ({prev['date']}) {r}!! MODIFIE !!{res}")
        else:
            print(f"  --- Precedent : {_short(prev['sig'])} ({prev['date']})")

    save_current_integrity(current_session_data)

    # ── Synthèse vocale des alertes groupées ─────────────────────────────────
    try:
        from modules.interfaces.tts_backend import TTSBackend
        tts_start = TTSBackend()
    except Exception:
        tts_start = None

    alertes_vocales: list[str] = []

    if log_was_tampered:
        # [CRYPTO-3] Alerte prioritaire — journal altéré
        alertes_vocales.append(
            "Alerte critique de sécurité. Le journal d'intégrité a été altéré. "
            "Je ne peux pas garantir l'intégrité de mon système."
        )
    elif critical_violation:
        critical(
            "INTEGRITE COMPROMISE SUR LE NOYAU",
            modified_files=list(modified_categories),
            category="INTEGRITY",
        )
        alertes_vocales.append(
            "Alerte de sécurité. Une violation d'intégrité a été détectée sur mon noyau critique."
        )
    elif modified_categories:
        themes = " et ".join(list(modified_categories))
        alertes_vocales.append(f"Mise à jour détectée dans les modules : {themes}.")

    if "Timeout" in net_latency:
        warning("Connexion Internet indisponible au démarrage", category="NETWORK")
        alertes_vocales.append(
            "La connexion au service cloud est interrompue. Je fonctionnerai en mode local."
        )

    if orchestrator:
        if getattr(orchestrator, "rag_status", None) == "MISSING":
            alertes_vocales.append(
                f"Attention, la collection {orchestrator.RAG_COLLECTION_NAME} est introuvable."
            )
        elif getattr(orchestrator, "rag_status", None) == "EMPTY":
            alertes_vocales.append(
                f"Alerte, la collection {orchestrator.RAG_COLLECTION_NAME} est vide."
            )

    if alertes_vocales and tts_start:
        tts_start.speak(" ".join(alertes_vocales))


# ===========================================================================
# CFG-DIAG-THRESHOLD : Initialisation au chargement du module
# ===========================================================================
# Appelé une seule fois, avant tout usage de DIAG_GPU_WARN_C / DIAG_GPU_HOT_C.
# Réassigne silencieusement les constantes depuis le YAML si disponible.
# En cas d'échec, les valeurs par défaut (75°C / 65°C) sont conservées.
_load_diag_config()
