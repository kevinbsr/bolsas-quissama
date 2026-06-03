"""Camada de IA — explica os números e redige o cruzamento para a população.

Provedor plugável, nesta ordem de preferência:
  1. ANTHROPIC_API_KEY presente  -> SDK Anthropic (claude-opus-4-8) com cache de prompt
  2. binário `claude` no PATH     -> CLI em modo print (sem chave; usa a sessão local)
  3. nenhum                        -> devolve aviso explicando como habilitar

REGRA DE OURO embutida em todo prompt: usar SOMENTE os números fornecidos,
citar a fonte, apresentar dado como dado — nunca afirmar crime, mentira ou
dolo. O texto levanta a pergunta; quem conclui é o cidadão e os órgãos de
controle.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

MODELO = "claude-opus-4-8"

SISTEMA = (
    "Você é o assistente de um portal público de transparência da cidade de "
    "Quissamã/RJ. Sua função é explicar dados fiscais oficiais para qualquer "
    "morador, em português simples. REGRAS INVIOLÁVEIS:\n"
    "1. Use SOMENTE os números e fatos fornecidos no JSON do indicador. Nunca invente valores.\n"
    "2. Refira-se apenas a INSTITUIÇÕES (a Prefeitura, a Câmara, a administração "
    "municipal). NUNCA cite, nomeie ou aluda a qualquer pessoa, gestor, prefeito, "
    "vereador, partido ou cargo individual.\n"
    "3. Apresente dado como dado. NÃO afirme que alguém mentiu, cometeu crime, "
    "desviou ou agiu com dolo. Não emita juízo jurídico nem político.\n"
    "4. Quando houver diferença entre o declarado e o comunicado, descreva-a de "
    "forma factual e faça a PERGUNTA que o dado levanta — reconhecendo explicações "
    "técnicas legítimas quando existirem.\n"
    "5. Sempre cite a fonte oficial de cada número.\n"
    "6. Seja conciso, didático, neutro e apartidário. O dado fala por si."
)


def _prompt_explicar(indicador: dict) -> str:
    return (
        "Explique este indicador para um morador de Quissamã que não entende de "
        "finanças públicas. Diga, em até 2 parágrafos curtos: o que o número "
        "oficial mostra, o que foi comunicado à população, e — se houver "
        "diferença — qual pergunta honesta isso levanta. Termine listando as "
        "fontes. Dados do indicador (JSON):\n\n"
        + json.dumps(indicador, ensure_ascii=False, indent=2)
    )


def _prompt_compartilhar(indicador: dict) -> str:
    return (
        "Escreva um resumo curto e claro (até 4 linhas) que um morador possa "
        "compartilhar para informar outros moradores sobre este indicador. Tom "
        "calmo, factual e apartidário, sem acusar ninguém. Diga o que os dados "
        "oficiais mostram e, se houver, a pergunta honesta que isso levanta. "
        "Termine com a fonte numa linha. Use SOMENTE os números do JSON:\n\n"
        + json.dumps(indicador, ensure_ascii=False, indent=2)
    )


# Sistema específico para extração documental (voto do TCE etc.)
SISTEMA_EXTRACAO = (
    "Você extrai informações de documentos oficiais de controle (votos e "
    "relatórios de Tribunal de Contas). REGRAS INVIOLÁVEIS:\n"
    "1. Reporte SOMENTE o que o documento literalmente afirma. Se algo não "
    "constar, escreva 'não consta no trecho fornecido'. NUNCA preencha lacunas "
    "com suposição.\n"
    "2. Cite valores e números exatamente como aparecem.\n"
    "3. Não nomeie pessoas físicas; refira-se a cargos/órgãos de forma "
    "institucional (o gestor, a Prefeitura, o relator).\n"
    "4. Distinga claramente: (a) fatos apurados, (b) irregularidades apontadas "
    "pelo Tribunal, (c) recomendações/determinações. Não emita opinião própria.\n"
    "5. Quando útil, transcreva trechos curtos entre aspas."
)

# ---------------------------------------------------------------- provedores

def _via_sdk(sistema: str, prompt: str, max_tokens: int) -> str:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODELO,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _via_cli(sistema: str, prompt: str) -> str:
    full = f"{sistema}\n\n---\n\n{prompt}"
    proc = subprocess.run(
        ["claude", "-p", full, "--output-format", "text"],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "claude CLI falhou")
    return proc.stdout.strip()


def _provedor() -> str:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "sdk"
    if shutil.which("claude"):
        return "cli"
    return "nenhum"


def _executar(sistema: str, prompt: str, max_tokens: int = 900) -> dict[str, Any]:
    prov = _provedor()
    try:
        if prov == "sdk":
            texto = _via_sdk(sistema, prompt, max_tokens)
        elif prov == "cli":
            texto = _via_cli(sistema, prompt)
        else:
            return {"provedor": "nenhum", "erro": "IA indisponível: defina ANTHROPIC_API_KEY ou instale o CLI `claude`."}
        return {"provedor": prov, "modelo": MODELO, "texto": texto}
    except Exception as e:  # noqa: BLE001
        return {"provedor": prov, "erro": f"Falha ao gerar: {e}"}


def gerar(tipo: str, indicador: dict) -> dict[str, Any]:
    """tipo: 'explicar' | 'compartilhar'. Retorna {provedor, texto} ou {erro}."""
    prompt = _prompt_compartilhar(indicador) if tipo == "compartilhar" else _prompt_explicar(indicador)
    return _executar(SISTEMA, prompt)


def extrair_documento(texto_documento: str, contexto: str = "") -> dict[str, Any]:
    """Extrai, de um documento de controle (ex.: voto do TCE), o que ele
    literalmente afirma: fatos, irregularidades, valores e recomendações."""
    prompt = (
        "Analise o documento oficial abaixo e produza um resumo estruturado em "
        "markdown com as seções: **Objeto do processo**, **Fatos apurados**, "
        "**Irregularidades apontadas pelo Tribunal**, **Valores citados**, "
        "**Recomendações / determinações**, **Trechos textuais relevantes** "
        "(citações curtas). Use apenas o que consta no texto.\n"
        + (f"\nContexto: {contexto}\n" if contexto else "")
        + "\n=== DOCUMENTO ===\n" + texto_documento
    )
    return _executar(SISTEMA_EXTRACAO, prompt, max_tokens=1600)
