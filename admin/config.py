"""Caminhos e constantes do painel administrativo.

O painel roda NO CONTAINER de coleta (LXC 102), não no Render: ele precisa do
roster, do cache de detalhes, do git e do Playwright — nada disso existe em
produção. Exposição pretendida: rede privada (Tailscale/LAN), sem senha.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

DATASET = BASE / "app" / "dados" / "bolsas_publicas.json"
AJUSTES = BASE / "app" / "dados" / "ajustes.json"
ROSTER = BASE / "relacao-bolsistas_padronizado.csv"
CACHE = BASE / "data" / "cache" / "detalhe"
CSV_DIR = BASE / "movimentacao-diaria"

ADMIN_DATA = BASE / "data" / "admin"
RUNS_DB = ADMIN_DATA / "runs.db"

# Mesmo lock que o cron usa (`flock -n /tmp/scraper.lock`): segurando-o aqui, um
# run manual e o cron nunca se sobrepõem — quem chegar depois desiste.
LOCK = Path(os.getenv("BQ_LOCK", "/tmp/scraper.lock"))

PROD_URL = os.getenv("BQ_PROD_URL", "https://www.bolsasquissama.com.br").rstrip("/")

# Dias sem execução bem-sucedida antes de acender o alerta no dashboard.
ALERTA_DIAS_SEM_RUN = int(os.getenv("BQ_ALERTA_DIAS", "3"))
