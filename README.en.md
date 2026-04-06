# aura_core/diagnostics.py

> This module is part of **AURA**, a fully local AI vocal and visual assistant designed and driven by **Ludovic JAUGEY**.

---

## What it does

- **Startup diagnostic report**: collects hardware metrics in parallel (CPU, GPU, VRAM, temperatures, disk, network, power supply) and displays them in a color-coded table with YAML-configurable thresholds.
- **Cryptographic integrity check**: computes BLAKE3 256-bit fingerprints (SHA-256 fallback) of all critical project files and detects any inter-session modification.
- **HMAC-protected journal**: signs each integrity report with an HMAC-SHA256 derived from the machine identifier — any tampering with the journal is detected at the next startup and triggers a vocal alert.

---

## Why it matters for local AI systems

Local AI assistants execute code, models, and configurations without cloud supervision. `diagnostics.py` addresses three critical needs in this context:

- **Network-free auditability**: the trust chain (file hash → journal → HMAC) runs entirely offline, with no dependency on an external integrity verification service.
- **Silent corruption detection**: a partial update, a disk crash, or an unintended configuration file change can silently alter the system's cognitive behavior with no explicit error message — this module acts as the safety net.
- **Hardware observability at boot**: local AI systems are often hosted on constrained hardware (consumer GPU, battery power, variable NVMe throughput); the startup report provides an instant diagnostic before launching compute-heavy pipelines.

---

## Installation

### Requirements

- Python 3.10 or higher
- The following packages must be available in the project environment:

```bash
pip install psutil requests pyyaml pynvml blake3
```

> **Note:** `blake3` and `pynvml` are optional. If absent, the module falls back to SHA-256 and `nvidia-smi` subprocess respectively, with no service interruption.

### Integration into the AURA project

This module is not standalone. It integrates into the `aura_core` package and requires:

- `aura_core/config.py` — provides `_AURA_HOME`, `_IS_WINDOWS`, `ORCHESTRATOR_CONFIG_PATH`
- `config/orchestrator_config.yaml` — GPU thresholds and hash chunk size (optional, built-in fallbacks)
- `modules/interfaces/logger_debug.py` — structured logger (built-in `print` fallback)

### Minimal usage

```python
from aura_core.diagnostics import display_system_report

# Full startup report (parallel probes + integrity check)
display_system_report()

# With STT and vocal_id instances if available
display_system_report(stt_instance=stt, orchestrator=orchestrator, vocal_id=vocal_id)
```

---

*Designer and Programmer: [Ludovic JAUGEY](https://www.linkedin.com/in/ludovic-jaugey-ia) assisted by Claude — 2026*
