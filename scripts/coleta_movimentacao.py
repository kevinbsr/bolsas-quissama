import pandas as pd
import json
import re
from pathlib import Path
import unicodedata
import argparse

# Configuração de caminhos
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MOV_DIR = BASE_DIR / "movimentacao-diaria"

def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower()).strip()

def clean_val(val):
    if not isinstance(val, str): return val
    # Remove =" e "
    val = val.replace('="', '').replace('"', '')
    # Remove R$, pontos de milhar e troca vírgula por ponto
    val = val.replace('R$', '').replace('.', '').replace(',', '.').strip()
    try:
        return round(float(val), 2)
    except:
        return 0.0

def clean_str(val):
    if not isinstance(val, str): return val
    return val.replace('="', '').replace('"', '').strip()

def process(nome_busca):
    csv_files = sorted(MOV_DIR.glob("*.csv"))
    if not csv_files:
        print(f"Nenhum arquivo encontrado em {MOV_DIR}")
        return

    all_registros = []
    termos = _norm(nome_busca).split()
    
    for csv_file in csv_files:
        print(f"Lendo {csv_file.name}...")
        try:
            # Pula as 4 linhas de metadados, o cabeçalho está na 5ª linha
            df = pd.read_csv(csv_file, sep=";", encoding="latin-1", skiprows=4)
            
            # Limpa nomes das colunas (removendo =" e ")
            df.columns = [clean_str(c) for c in df.columns]
            
            if 'Credor' not in df.columns:
                print(f"Aviso: Coluna 'Credor' não encontrada em {csv_file.name}. Colunas: {df.columns.tolist()}")
                continue

            # Filtra pelo nome do credor
            mask = df['Credor'].apply(lambda x: all(t in _norm(clean_str(x)) for t in termos))
            filtered = df[mask]
            
            ano_match = re.search(r"(\d{4})", csv_file.name)
            ano = ano_match.group(1) if ano_match else "Desconhecido"
            
            for _, row in filtered.iterrows():
                reg = {
                    "data_movimento": clean_str(row.get("Data Movimento", "")),
                    "empenho": clean_str(row.get("Número do Empenho", "")),
                    "tipo": clean_str(row.get("Tipo Empenho", "")),
                    "unidade_gestora": clean_str(row.get("Unidade Gestora", "")),
                    "credor": clean_str(row.get("Credor", "")),
                    "empenhado": clean_val(row.get("Valor Empenho", 0)),
                    "em_liquidacao": clean_val(row.get("Valor Em Liquidação", 0)),
                    "liquidado": clean_val(row.get("Valor Liquidado", 0)),
                    "pago": clean_val(row.get("Valor Pago", 0)),
                    "anulado": clean_val(row.get("Valor Anulado", 0)),
                    "ano": ano,
                }
                # Cálculo de a pagar (simplificado: liquidado - pago, se positivo)
                reg["a_pagar"] = round(max(reg["liquidado"] - reg["pago"], 0.0), 2)
                all_registros.append(reg)
                
            print(f"  -> {len(filtered)} registros encontrados para o ano {ano}")
            
        except Exception as e:
            print(f"Erro ao processar {csv_file.name}: {e}")

    # Ordenar por data (opcional, mas bom para visualização)
    try:
        all_registros.sort(key=lambda x: (x['ano'], x['data_movimento']))
    except:
        pass

    resumo = {
        "qtd": len(all_registros),
        "valor_total": round(sum(x["empenhado"] for x in all_registros), 2),
        "valor_liquidado": round(sum(x["liquidado"] for x in all_registros), 2),
        "valor_pago": round(sum(x["pago"] for x in all_registros), 2),
        "a_pagar": round(sum(x["a_pagar"] for x in all_registros), 2),
    }
    
    payload = {
        "fonte": "Portal da Transparência de Quissamã (Cidade360/IPM) — Importação Manual (Movimentação Diária)",
        "url": "https://webapp1-quissama.cidade360.cloud/pronimtb/",
        "credor_busca": nome_busca,
        "registros": all_registros,
        "resumo": resumo,
    }
    
    output_path = DATA_DIR / "empenhos_bolsa.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    
    print(f"\nSucesso! {len(all_registros)} registros totais.")
    print(f"Resumo: Empenhado R$ {resumo['valor_total']:.2f} | Pago R$ {resumo['valor_pago']:.2f}")
    print(f"Arquivo atualizado: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Processa CSVs de Movimentação Diária e atualiza empenhos_bolsa.json")
    parser.add_argument("--nome", default="KEVIN BENEVIDES DA SILVA ROMARIZ", help="Nome do credor para filtrar")
    args = parser.parse_args()
    
    process(args.nome)
