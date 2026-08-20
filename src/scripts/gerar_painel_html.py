# -*- coding: utf-8 -*-
"""
gerar_painel_html.py

Le a base tratada + indicadores e gera UM UNICO ARQUIVO HTML autocontido
(sem depender de internet, servidor ou nada externo) com:

  - seletor de periodo: Hoje / Mes atual / Ultimos 90 dias
  - ranking geral por separador (clicavel)
  - detalhe por separador:
      * Hoje: lista de tarefas do dia
      * Mes: calendario com card por dia (CX, Hr Prod, % meta, cor)
      * 3 meses: resumo com contagem de dias por classificacao de cor

Uso:
    python gerar_painel_html.py
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, date

import pandas as pd

import indicadores_produtividade as ip

PASTA_SCRIPT = Path(__file__).resolve().parent.parent.parent
SAIDA_HTML = PASTA_SCRIPT / "painel_produtividade.html"

# Quantos dias de historico o HTML embute. Mais que isso incha o arquivo
# sem necessidade -- quem precisar de dado mais antigo usa o
# gerar_arquivo_auditoria.py, que exporta o historico completo pro Excel.
JANELA_DIAS_HTML = 90

CORES = {
    "vermelho": "#C4453A",
    "amarelo": "#D9A441",
    "verde": "#3F8F5C",
    "estrela": "#E07A2E",
}


def montar_dados_tarefas_por_usuario(df_tarefa: pd.DataFrame) -> dict:
    """Lista de tarefas individuais por usuario/dia, pra alimentar o
    detalhe de 'Hoje' (a granularidade mais fina que expomos no painel)."""
    out: dict[str, dict[str, list]] = {}
    for _, row in df_tarefa.iterrows():
        usuario = row[ip.COL_USUARIO]
        dia = str(row["dia"])
        out.setdefault(usuario, {}).setdefault(dia, []).append(
            {
                "tarefa": row[ip.COL_TAREFA],
                "caixas": int(row["caixas"]),
                "inicio": row["inicio"].strftime("%H:%M") if pd.notna(row["inicio"]) else "-",
                "fim": row["fim"].strftime("%H:%M") if pd.notna(row["fim"]) else "-",
                "tempo_horas": round(row["tempo_horas"], 2) if pd.notna(row["tempo_horas"]) else None,
            }
        )
    return out


def montar_dados_por_dia(por_dia: pd.DataFrame) -> dict:
    """Indicadores diarios por usuario, pra alimentar o calendario do mes
    e o resumo de 3 meses (contagem de cores)."""
    out: dict[str, list] = {}
    for _, row in por_dia.iterrows():
        usuario = row["usuario"]
        out.setdefault(usuario, []).append(
            {
                "dia": str(row["dia"]),
                "caixas": int(row["caixas"]),
                "hr_produtiva": round(row["hr_produtiva"], 2),
                "hr_normal": round(row["hr_normal"], 2),
                "hr_extra": round(row["hr_extra"], 2),
                "hr_improdutiva": round(row["hr_improdutiva"], 2),
                "pct_meta": row["pct_meta"],
                "classificacao": row["classificacao"],
                "n_tarefas": int(row["n_tarefas"]),
            }
        )
    return out


def montar_ranking(por_dia: pd.DataFrame, inicio: date, fim: date) -> list:
    resumo = ip.resumo_periodo(por_dia, inicio, fim)
    registros = []
    for _, r in resumo.iterrows():
        registros.append(
            {
                "usuario": r["usuario"],
                "caixas": int(r["caixas"]),
                "hr_produtiva": round(r["hr_produtiva"], 2),
                "hr_normal": round(r["hr_normal"], 2),
                "hr_extra": round(r["hr_extra"], 2),
                "hr_improdutiva": round(r["hr_improdutiva"], 2),
                "media": r["media_cx_por_hora"] if pd.notna(r["media_cx_por_hora"]) else None,
                "pct_meta": r["pct_meta"],
                "meta_periodo": int(r["meta_periodo"]),
                "dias_trabalhados": int(r["dias_trabalhados"]),
                "dias_abaixo_meta": int(r["dias_abaixo_meta"]),
                "total_tarefas": int(r["total_tarefas"]),
            }
        )
    return registros


def montar_total_por_dia(por_dia: pd.DataFrame) -> list:
    """Agrega TODOS os separadores juntos por dia -- usado no box 'Total
    Separado' pra calcular volume geral e dimensionamento de equipe.
    pessoas_necessarias = ceil(caixas_do_dia / meta_diaria): quantas pessoas
    seriam necessarias, no ritmo da meta, pra dar conta do volume que
    realmente apareceu naquele dia."""
    tot = (
        por_dia.groupby("dia", as_index=False)
        .agg(caixas=("caixas", "sum"), pessoas_ativas=("usuario", "nunique"))
        .sort_values("dia")
    )
    tot["pessoas_necessarias"] = (
        (tot["caixas"] + ip.META_DIARIA - 1) // ip.META_DIARIA
    ).astype(int)  # ceil sem depender de math.ceil
    return [
        {
            "dia": str(r["dia"]),
            "caixas": int(r["caixas"]),
            "pessoas_ativas": int(r["pessoas_ativas"]),
            "pessoas_necessarias": int(r["pessoas_necessarias"]),
        }
        for _, r in tot.iterrows()
    ]


def montar_ranking_por_dia(por_dia: pd.DataFrame) -> dict:
    """Ranking de separadores DENTRO de cada dia (usado no detalhe expandido
    do box Total Separado, ao clicar numa linha do grafico de dias)."""
    out: dict[str, list] = {}
    for dia, grupo in por_dia.groupby("dia"):
        ordenado = grupo.sort_values("caixas", ascending=False)
        out[str(dia)] = [
            {
                "usuario": r["usuario"],
                "caixas": int(r["caixas"]),
                "pct_meta": r["pct_meta"],
                "n_tarefas": int(r["n_tarefas"]),
            }
            for _, r in ordenado.iterrows()
        ]
    return out


def gerar_html(dados_json: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Painel de Produtividade — Separação</title>
<style>
  :root {{
    --bg: #14181C;
    --bg-panel: #1C2228;
    --bg-card: #232B32;
    --border: #313B44;
    --text: #E7ECEF;
    --text-dim: #8B98A3;
    --accent: #E07A2E;
    --vermelho: {CORES['vermelho']};
    --amarelo: {CORES['amarelo']};
    --verde: {CORES['verde']};
    --estrela: {CORES['estrela']};
    --mono: 'IBM Plex Mono', 'Consolas', monospace;
    --sans: 'Inter', -apple-system, sans-serif;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px; background: var(--bg); color: var(--text);
    font-family: var(--sans); font-size: 14px; line-height: 1.5;
  }}
  h1 {{ font-size: 20px; font-weight: 600; margin: 0 0 4px; }}
  .subtitulo {{ color: var(--text-dim); font-size: 13px; margin-bottom: 20px; }}
  .container {{ max-width: 900px; margin: 0 auto; }}

  .flag-selector {{ display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }}
  .flag-selector-label {{ font-size: 12px; color: var(--text-dim); margin-right: 4px; }}
  .flag-btn {{
    background: var(--bg-panel); border: 1px solid var(--border); color: var(--text-dim);
    font-family: var(--sans); font-size: 12px; font-weight: 500; padding: 7px 14px;
    border-radius: 6px; cursor: pointer; transition: all .15s;
  }}
  .flag-btn.ativo {{ background: var(--accent); color: #14181C; border-color: var(--accent); }}

  .hub-grid {{ display: grid; grid-template-columns: 1fr; gap: 12px; }}
  .hub-box-lista {{ margin: 8px 0 0; padding-left: 18px; font-size: 12px; color: var(--text-dim); line-height: 1.6; }}
  .hub-box-lista li {{ margin-bottom: 2px; }}
  .hub-box {{
    background: var(--bg-panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 22px; cursor: pointer; transition: border-color .15s, transform .1s;
  }}
  .hub-box:hover {{ border-color: var(--accent); transform: translateY(-1px); }}
  .hub-box-desabilitada {{ opacity: .55; }}
  .hub-box-desabilitada:hover {{ border-color: var(--border); transform: none; }}
  .hub-box-titulo {{ font-size: 15px; font-weight: 700; margin-bottom: 6px; }}
  .hub-box-desc {{ font-size: 12px; color: var(--text-dim); line-height: 1.4; }}

  .top10-secao {{ margin-bottom: 22px; }}
  .top10-titulo {{ font-size: 13px; font-weight: 700; margin-bottom: 8px; color: var(--accent); }}
  .top10-item {{
    display: flex; align-items: center; gap: 10px; padding: 8px 12px;
    background: var(--bg-panel); border: 1px solid var(--border); border-radius: 6px;
    margin-bottom: 6px; font-size: 13px;
  }}
  .top10-pos {{ font-family: var(--mono); color: var(--text-dim); width: 20px; flex-shrink: 0; }}
  .top10-nome {{ flex: 1; font-weight: 600; }}
  .top10-valor {{ font-family: var(--mono); font-weight: 700; color: var(--accent); }}

  .total-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px,1fr)); gap: 10px; margin-bottom: 20px; }}
  .dimensionamento-box {{
    background: var(--bg-panel); border: 1px solid var(--accent); border-radius: 8px;
    padding: 16px; margin-bottom: 20px;
  }}
  .dimensionamento-titulo {{ font-size: 12px; color: var(--text-dim); margin-bottom: 6px; }}
  .dimensionamento-valor {{ font-family: var(--mono); font-size: 22px; font-weight: 700; color: var(--accent); }}
  .total-dia-row {{
    display: flex; justify-content: space-between; align-items: center; padding: 8px 12px;
    background: var(--bg-panel); border: 1px solid var(--border); border-radius: 6px; margin-bottom: 6px;
    font-family: var(--mono); font-size: 12px; transition: border-color .15s;
  }}
  .total-dia-row:hover {{ border-color: var(--accent); }}
  .total-dia-barra {{ flex: 1; height: 6px; background: var(--bg-card); border-radius: 3px; margin: 0 12px; overflow: hidden; }}
  .total-dia-barra-fill {{ height: 100%; background: var(--accent); }}

  .roster-filtros {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
  .roster-busca {{
    flex: 1; min-width: 160px; background: var(--bg-panel); border: 1px solid var(--border);
    color: var(--text); font-family: var(--sans); font-size: 13px; padding: 9px 12px; border-radius: 6px;
  }}
  .roster-select {{
    background: var(--bg-panel); border: 1px solid var(--border); color: var(--text);
    font-family: var(--sans); font-size: 13px; padding: 9px 12px; border-radius: 6px;
  }}
  .roster-item {{
    display: flex; align-items: center; gap: 12px; padding: 12px 14px;
    background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px;
  }}
  .roster-status-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
  .roster-nome {{ font-weight: 600; font-size: 14px; }}
  .roster-sub {{ font-size: 12px; color: var(--text-dim); font-family: var(--mono); }}
  .roster-badge {{
    font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 5px; text-transform: uppercase;
    letter-spacing: .03em; flex-shrink: 0;
  }}
  .roster-manual-tag {{
    font-size: 10px; color: var(--accent); border: 1px solid var(--accent); border-radius: 4px;
    padding: 1px 6px; margin-left: 6px;
  }}

  /* ===== Ajuda (botao flutuante + painel de busca) ===== */
  .ajuda-fab {{
    position: fixed; bottom: 22px; right: 22px; z-index: 500;
    background: var(--accent); color: #14181C; border: none; border-radius: 50%;
    width: 52px; height: 52px; font-size: 22px; font-weight: 700; cursor: pointer;
    box-shadow: 0 4px 14px rgba(0,0,0,.4); transition: transform .15s;
  }}
  .ajuda-fab:hover {{ transform: scale(1.08); }}

  .ajuda-overlay {{
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,.55); z-index: 600;
    align-items: flex-end; justify-content: center;
  }}
  .ajuda-overlay.aberto {{ display: flex; }}
  .ajuda-painel {{
    background: var(--bg); border: 1px solid var(--border); border-radius: 14px 14px 0 0;
    width: 100%; max-width: 900px; max-height: 82vh; padding: 20px 24px; overflow-y: auto;
    box-shadow: 0 -8px 30px rgba(0,0,0,.5);
  }}
  .ajuda-painel-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
  .ajuda-fechar {{ background: none; border: none; color: var(--text-dim); font-size: 22px; cursor: pointer; padding: 4px 8px; }}
  .ajuda-fechar:hover {{ color: var(--text); }}
  .ajuda-busca {{
    width: 100%; background: var(--bg-panel); border: 1px solid var(--accent); color: var(--text);
    font-family: var(--sans); font-size: 14px; padding: 11px 14px; border-radius: 8px; margin-bottom: 14px;
  }}
  .ajuda-item {{
    background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 14px 16px; margin-bottom: 10px;
  }}
  .ajuda-pergunta {{ font-weight: 600; font-size: 14px; margin-bottom: 6px; color: var(--text-accent); }}
  .ajuda-resposta {{ font-size: 13px; color: var(--text-dim); line-height: 1.55; }}
  .ajuda-resposta code {{
    background: var(--bg-card); padding: 1px 6px; border-radius: 4px; font-family: var(--mono);
    font-size: 12px; color: var(--accent);
  }}
  .ajuda-categoria {{
    font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--accent);
    font-weight: 700; margin: 16px 0 8px;
  }}

  .periodo-tabs {{ display: flex; gap: 8px; margin-bottom: 20px; }}
  .periodo-tabs button {{
    flex: 1; padding: 10px; background: var(--bg-panel); border: 1px solid var(--border);
    color: var(--text-dim); font-family: var(--sans); font-size: 13px; font-weight: 500;
    border-radius: 6px; cursor: pointer; transition: all .15s;
  }}
  .periodo-tabs button.ativo {{ background: var(--accent); color: #14181C; border-color: var(--accent); }}

  .data-especifica {{
    background: var(--bg-panel); border: 1px solid var(--accent); color: var(--text);
    font-family: var(--sans); font-size: 13px; padding: 9px 12px; border-radius: 6px;
    margin-bottom: 16px; width: 100%; color-scheme: dark;
  }}

  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px,1fr)); gap: 10px; margin-bottom: 20px; }}
  .kpi {{ background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }}
  .kpi-label {{ color: var(--text-dim); font-size: 12px; margin-bottom: 4px; }}
  .kpi-valor {{ font-family: var(--mono); font-size: 20px; font-weight: 600; }}

  .ranking-item {{
    display: flex; align-items: center; gap: 12px; padding: 12px 14px;
    background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px;
    margin-bottom: 8px; cursor: pointer; transition: border-color .15s;
  }}
  .ranking-item:hover {{ border-color: var(--accent); }}
  .avatar {{
    width: 34px; height: 34px; border-radius: 50%; background: var(--bg-card);
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 600; flex-shrink: 0; font-family: var(--mono);
  }}
  .ranking-info {{ flex: 1; min-width: 0; }}
  .ranking-nome {{ font-weight: 600; font-size: 14px; }}
  .ranking-sub {{ color: var(--text-dim); font-size: 12px; font-family: var(--mono); }}
  .badge {{
    font-family: var(--mono); font-size: 12px; font-weight: 600; padding: 4px 10px;
    border-radius: 5px; flex-shrink: 0; white-space: nowrap;
  }}
  .chevron {{ color: var(--text-dim); flex-shrink: 0; }}

  .voltar {{
    background: none; border: none; color: var(--text-dim); font-family: var(--sans);
    font-size: 13px; cursor: pointer; display: flex; align-items: center; gap: 6px;
    margin-bottom: 16px; padding: 0;
  }}
  .voltar:hover {{ color: var(--text); }}

  .detalhe-header {{ display: flex; align-items: center; gap: 14px; margin-bottom: 20px; }}
  .avatar-lg {{ width: 48px; height: 48px; font-size: 16px; }}
  .detalhe-nome {{ font-size: 17px; font-weight: 600; }}
  .detalhe-sub {{ color: var(--text-dim); font-size: 13px; }}

  .tarefa-item {{
    display: flex; justify-content: space-between; padding: 10px 0;
    border-top: 1px solid var(--border); font-size: 13px;
  }}
  .tarefa-item:first-child {{ border-top: none; }}
  .tarefa-nome {{ font-family: var(--mono); font-weight: 600; }}
  .tarefa-horario {{ color: var(--text-dim); font-size: 12px; }}

  .calendario {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px,1fr)); gap: 10px; }}
  .dia-card {{
    border-radius: 8px; padding: 14px; text-align: center; font-family: var(--mono);
    border: 1px solid transparent;
  }}
  .dia-data {{ font-size: 12px; opacity: .85; margin-bottom: 8px; font-weight: 600; }}
  .dia-caixas-label {{ font-size: 10px; opacity: .75; letter-spacing: .04em; }}
  .dia-caixas {{ font-size: 22px; font-weight: 700; margin: 2px 0; }}
  .dia-pct {{ font-size: 11px; opacity: .9; margin-bottom: 8px; }}
  .dia-tarefas {{ font-size: 11px; opacity: .8; border-top: 1px solid currentColor; padding-top: 6px; margin-top: 6px; }}

  .resumo3m-grid {{ display: grid; grid-template-columns: repeat(4,1fr); gap: 10px; margin-bottom: 20px; }}
  .resumo3m-item {{ border-radius: 8px; padding: 14px; text-align: center; }}
  .resumo3m-num {{ font-family: var(--mono); font-size: 24px; font-weight: 700; }}
  .resumo3m-label {{ font-size: 11px; opacity: .85; margin-top: 2px; }}

  .mes-toggle {{
    display: flex; justify-content: space-between; align-items: center;
    background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 16px; margin-bottom: 6px; cursor: pointer; font-weight: 600;
    transition: border-color .15s;
  }}
  .mes-toggle:hover {{ border-color: var(--accent); }}

  .vazio {{ color: var(--text-dim); text-align: center; padding: 30px; font-size: 13px; }}

  .aviso-info {{
    background: var(--bg-panel); border: 1px solid var(--border); border-left: 3px solid var(--accent);
    border-radius: 6px; padding: 12px 14px; font-size: 12px; color: var(--text-dim); line-height: 1.5;
    margin-bottom: 18px;
  }}
  .aviso-info strong {{ color: var(--text); }}

  ::-webkit-scrollbar {{ width: 8px; }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 4px; }}
</style>
</head>
<body>
<div class="container">
  <h1>Painel de Produtividade</h1>
  <div class="subtitulo" id="subtitulo-topo">Central de indicadores operacionais</div>

  <!-- ============ HUB INICIAL ============ -->
  <div id="hub">
    <div class="flag-selector">
      <div class="flag-selector-label">Operação:</div>
      <button class="flag-btn ativo" data-flag="ambos">Ambos</button>
      <button class="flag-btn" data-flag="nacional">Nacional</button>
      <button class="flag-btn" data-flag="exportacao">Exportação</button>
    </div>
    <div class="hub-grid">
      <div class="hub-box" onclick="abrirApp('app-separadores')">
        <div class="hub-box-titulo">📦 Separadores</div>
        <div class="hub-box-desc">Ranking dos separadores comparado com a meta de 1.500cx/dia.</div>
        <ul class="hub-box-lista">
          <li>Filtra por Hoje, Mês atual, Últimos 90 dias ou uma Data específica</li>
          <li>Cor de cada um: vermelho (&lt;500cx), amarelo (500-1499cx), verde (bateu a meta), laranja (passou da meta)</li>
          <li>Clique num nome pra ver o detalhe: tarefas do dia com horário, calendário do mês com hora extra, ou resumo de 3 meses</li>
        </ul>
      </div>
      <div class="hub-box" onclick="abrirApp('app-operadores')">
        <div class="hub-box-titulo">🚜 Operadores</div>
        <div class="hub-box-desc">Quem opera empilhadeira, identificado 100% pelo endereço (altura ≥ 01).</div>
        <ul class="hub-box-lista">
          <li>Mostra volume movimentado, tarefas e horas — ainda sem meta definida</li>
          <li>Mesma navegação por período do Separadores (Hoje/Mês/3 meses/Data específica)</li>
          <li>Não depende de cadastro manual — é automático pelo endereço da tarefa</li>
        </ul>
      </div>
      <div class="hub-box" onclick="abrirApp('app-funcionarios')">
        <div class="hub-box-titulo">🏆 Funcionários</div>
        <div class="hub-box-desc">4 rankings Top 10 num só lugar, pra reconhecer e identificar quem precisa de atenção.</div>
        <ul class="hub-box-lista">
          <li>Top 10 mais próximos/acima da meta</li>
          <li>Top 10 que mais separaram caixas</li>
          <li>Top 10 que mais fizeram tarefas</li>
          <li>Top 10 mais abaixo da meta</li>
        </ul>
      </div>
      <div class="hub-box" onclick="abrirApp('app-totalseparado')">
        <div class="hub-box-titulo">📊 Total Separado</div>
        <div class="hub-box-desc">Visão consolidada de TODOS os separadores juntos — o volume geral do galpão.</div>
        <ul class="hub-box-lista">
          <li>Total de caixas por dia, com gráfico de barra visual</li>
          <li>"Dimensionamento sugerido": quantas pessoas seriam necessárias pra dar conta da demanda média/pico</li>
          <li>Clique num dia da lista pra ver o ranking de quem separou naquele dia específico</li>
        </ul>
      </div>
      <div class="hub-box" onclick="abrirApp('app-lista-funcionarios')">
        <div class="hub-box-titulo">📋 Lista de Funcionários</div>
        <div class="hub-box-desc">Cadastro visual: papel, turno, status e última atividade de cada um.</div>
        <ul class="hub-box-lista">
          <li>Busca por nome + filtro por status (Ativo/Atenção/Inativo) e por papel</li>
          <li>Quem está 45+ dias sem separar nada aparece em "Atenção" (amarelo), mesmo sem ninguém ter marcado nada ainda</li>
          <li>Tag "manual" identifica quem teve o papel definido à mão (não é o automático por endereço)</li>
        </ul>
      </div>
    </div>
  </div>

  <!-- ============ APP: SEPARADORES (painel existente) ============ -->
  <div id="app-separadores" style="display:none;">
    <button class="voltar" onclick="voltarHub()">‹ voltar ao painel</button>
    <div class="subtitulo" id="subtitulo-periodo">Meta diária: 1.500 cx · Jornada: 7h20</div>

    <div id="view-geral">
      <div class="periodo-tabs">
        <button class="ativo" data-p="hoje">Hoje</button>
        <button data-p="mes">Mês atual</button>
        <button data-p="3m">Últimos 90 dias</button>
        <button data-p="dia">Dia específico</button>
      </div>
      <input type="date" id="data-especifica-sep" class="data-especifica" style="display:none;">
      <div class="kpis" id="kpis"></div>
      <input type="text" id="busca-separador" class="roster-busca" placeholder="🔍 Buscar separador pelo nome..." style="margin-bottom:12px; width:100%;">
      <div id="ranking-list"></div>
    </div>

    <div id="view-detalhe" style="display:none;"></div>
  </div>

  <!-- ============ APP: OPERADORES ============ -->
  <div id="app-operadores" style="display:none;">
    <button class="voltar" onclick="voltarHub()">‹ voltar ao painel</button>
    <div class="subtitulo" id="subtitulo-periodo-op">Volume e atividade por endereço — sem meta definida ainda</div>
    <div class="aviso-info">
      ℹ️ Esse ranking é 100% pelo <strong>endereço</strong> (altura ≥ 01 = empilhadeira). Não confunda com o
      papel <strong>"Operador"</strong> da Lista de Funcionários — aquele é o <strong>cargo real</strong> da pessoa,
      definido manualmente, e serve pra tirar alguém do ranking de Separador quando ela bipa em altura 00
      fazendo hora extra mas não é separador de verdade.
    </div>

    <div id="view-geral-op">
      <div class="periodo-tabs" id="periodo-tabs-op">
        <button class="ativo" data-p="hoje">Hoje</button>
        <button data-p="mes">Mês atual</button>
        <button data-p="3m">Últimos 90 dias</button>
        <button data-p="dia">Dia específico</button>
      </div>
      <input type="date" id="data-especifica-op" class="data-especifica" style="display:none;">
      <div class="kpis" id="kpis-op"></div>
      <div id="ranking-list-op"></div>
    </div>

    <div id="view-detalhe-op" style="display:none;"></div>
  </div>

  <!-- ============ APP: FUNCIONARIOS (top 10) ============ -->
  <div id="app-funcionarios" style="display:none;">
    <button class="voltar" onclick="voltarHub()">‹ voltar ao painel</button>
    <div class="subtitulo">Rankings Top 10 — Separadores</div>
    <div class="periodo-tabs" id="periodo-tabs-func">
      <button class="ativo" data-p="hoje">Hoje</button>
      <button data-p="mes">Mês atual</button>
      <button data-p="3m">Últimos 90 dias</button>
      <button data-p="dia">Dia específico</button>
    </div>
    <input type="date" id="data-especifica-func" class="data-especifica" style="display:none;">
    <div id="funcionarios-conteudo"></div>
  </div>

  <!-- ============ APP: TOTAL SEPARADO ============ -->
  <div id="app-totalseparado" style="display:none;">
    <button class="voltar" onclick="voltarHub()">‹ voltar ao painel</button>
    <div class="subtitulo">Volume geral e dimensionamento de equipe</div>
    <div class="periodo-tabs" id="periodo-tabs-total">
      <button class="ativo" data-p="hoje">Hoje</button>
      <button data-p="mes">Mês atual</button>
      <button data-p="3m">Últimos 90 dias</button>
      <button data-p="dia">Dia específico</button>
    </div>
    <input type="date" id="data-especifica-total" class="data-especifica" style="display:none;">
    <div id="totalseparado-conteudo"></div>
  </div>

  <!-- ============ APP: LISTA DE FUNCIONARIOS ============ -->
  <div id="app-lista-funcionarios" style="display:none;">
    <button class="voltar" onclick="voltarHub()">‹ voltar ao painel</button>
    <div class="subtitulo">Papel, status e última atividade de cada separador</div>
    <div class="aviso-info">
      ℹ️ O papel <strong>"Operador"</strong> aqui é o <strong>cargo real</strong> da pessoa (definido manualmente
      no editor), usado quando alguém bipa em altura 00 fazendo hora extra mas não é separador de verdade —
      ela sai do ranking de Separador. É diferente do box <strong>"Operadores"</strong> do painel principal,
      que é 100% baseado no endereço (altura ≥ 01), sem depender de cadastro manual.
    </div>
    <div class="roster-filtros">
      <input type="text" id="roster-busca" placeholder="Buscar por nome..." class="roster-busca">
      <select id="roster-filtro-status" class="roster-select">
        <option value="todos">Todos os status</option>
        <option value="ativo">Ativo</option>
        <option value="atencao">Atenção (45+ dias parado)</option>
        <option value="inativo_manual">Inativo (marcado)</option>
      </select>
      <select id="roster-filtro-papel" class="roster-select">
        <option value="todos">Todos os papéis</option>
        <option value="separador">Separador</option>
        <option value="conferente">Conferente</option>
        <option value="analista">Analista</option>
        <option value="operador">Operador</option>
        <option value="inativo">Inativo</option>
      </select>
    </div>
    <div id="roster-conteudo"></div>
  </div>

</div>

<!-- ===== Ajuda: botao flutuante + painel de busca ===== -->
<button class="ajuda-fab" onclick="abrirAjuda()" title="Ajuda">?</button>
<div class="ajuda-overlay" id="ajuda-overlay">
  <div class="ajuda-painel">
    <div class="ajuda-painel-header">
      <strong style="font-size:15px;">Central de Ajuda</strong>
      <button class="ajuda-fechar" onclick="fecharAjuda()">✕</button>
    </div>
    <input type="text" id="ajuda-busca" class="ajuda-busca" placeholder="Digite sua dúvida... ex: 'quanto o zekinha separou no mês'">
    <div id="ajuda-resultados"></div>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/fuse.js/7.0.0/fuse.min.js"></script>
<script>
const DADOS = {dados_json};
const CORES = {json.dumps(CORES)};
let periodoAtual = 'hoje';
let currentFlag = 'ambos';
function D() {{ return DADOS.flags[currentFlag]; }}
function D2() {{ return DADOS.flags_operador[currentFlag]; }}

function iniciaisNome(nome) {{
  return nome.split('.').map(p => p[0]).join('').toUpperCase().slice(0,2);
}}
function nomeExibicao(usuario) {{
  return usuario.split('.').map(p => p.charAt(0).toUpperCase()+p.slice(1)).join(' ');
}}
function corClassificacao(c) {{ return CORES[c] || '#555'; }}

function contarDiasUteis(inicio, fim) {{
  let d = new Date(inicio + 'T00:00:00');
  const end = new Date(fim + 'T00:00:00');
  let n = 0;
  while (d <= end) {{ if (d.getDay() !== 0) n++; d.setDate(d.getDate() + 1); }}
  return n || 1;
}}

/** Agrega o ranking por separador num intervalo qualquer de datas
 * (usado pela aba 'Dia específico', que nao vem pre-calculada do Python). */
function agregarPeriodo(inicio, fim) {{
  const registros = [];
  Object.keys(D().por_dia).forEach(usuario => {{
    const dias = D().por_dia[usuario].filter(d => d.dia >= inicio && d.dia <= fim);
    if (!dias.length) return;
    const caixas = dias.reduce((a,d)=>a+d.caixas, 0);
    const hrProd = dias.reduce((a,d)=>a+d.hr_produtiva, 0);
    const hrExtra = dias.reduce((a,d)=>a+(d.hr_extra||0), 0);
    const hrImprod = dias.reduce((a,d)=>a+d.hr_improdutiva, 0);
    const tarefas = dias.reduce((a,d)=>a+d.n_tarefas, 0);
    const metaPeriodo = DADOS.meta_diaria * contarDiasUteis(inicio, fim);
    registros.push({{
      usuario, caixas,
      hr_produtiva: +hrProd.toFixed(2),
      hr_extra: +hrExtra.toFixed(2),
      hr_improdutiva: +hrImprod.toFixed(2),
      media: hrProd > 0 ? +(caixas/hrProd).toFixed(1) : null,
      pct_meta: +(caixas/metaPeriodo*100).toFixed(1),
      meta_periodo: metaPeriodo,
      dias_trabalhados: dias.length,
      dias_abaixo_meta: dias.filter(d => ['vermelho','amarelo'].includes(d.classificacao)).length,
      total_tarefas: tarefas,
    }});
  }});
  return registros;
}}

/** Retorna {{ranking, label}} pro periodo selecionado numa view, cobrindo
 * tanto os periodos pre-calculados (hoje/mes/3m) quanto 'dia especifico'. */
function obterRankingPeriodo(periodo, dataEspecifica) {{
  if (periodo === 'dia') {{
    if (!dataEspecifica) return {{ ranking: [], label: 'Selecione uma data' }};
    return {{
      ranking: agregarPeriodo(dataEspecifica, dataEspecifica),
      label: 'Exibindo: ' + dataEspecifica.split('-').reverse().join('/'),
    }};
  }}
  return {{ ranking: D().ranking[periodo] || [], label: DADOS.periodo_labels[periodo] || '' }};
}}

function renderKpis(ranking) {{
  const totalCx = ranking.reduce((a,r)=>a+r.caixas,0);
  const naMeta = ranking.filter(r=>r.pct_meta>=100).length;
  const mediaGeral = ranking.length
    ? (ranking.reduce((a,r)=>a+(r.media||0),0)/ranking.filter(r=>r.media).length).toFixed(1)
    : 0;
  document.getElementById('kpis').innerHTML = `
    <div class="kpi"><div class="kpi-label">separadores</div><div class="kpi-valor">${{ranking.length}}</div></div>
    <div class="kpi"><div class="kpi-label">total separado</div><div class="kpi-valor">${{totalCx.toLocaleString('pt-BR')}}</div></div>
    <div class="kpi"><div class="kpi-label">média cx/h</div><div class="kpi-valor">${{mediaGeral}}</div></div>
    <div class="kpi"><div class="kpi-label">na meta</div><div class="kpi-valor">${{naMeta}}/${{ranking.length}}</div></div>
  `;
}}

function corPct(pct) {{
  if (pct >= 100) return CORES.verde;
  if (pct >= 80) return CORES.amarelo;
  return CORES.vermelho;
}}

function renderRanking() {{
  const {{ranking, label}} = obterRankingPeriodo(periodoAtual, window.dataEspecificaSep);
  document.getElementById('subtitulo-periodo').textContent =
    label + ' · Meta diária: 1.500 cx · Jornada: 7h20';
  renderKpis(ranking);

  const buscaTexto = (document.getElementById('busca-separador').value || '').toLowerCase();
  const filtrado = buscaTexto
    ? ranking.filter(r => r.usuario.toLowerCase().includes(buscaTexto))
    : ranking;

  if (!filtrado.length) {{
    document.getElementById('ranking-list').innerHTML = buscaTexto
      ? '<div class="vazio">Nenhum separador encontrado com esse nome nesse período.</div>'
      : '<div class="vazio">Sem dados de separador nesse período.</div>';
    return;
  }}

  const ordenado = [...filtrado].sort((a,b)=>b.caixas-a.caixas);
  document.getElementById('ranking-list').innerHTML = ordenado.map(r => {{
    const cor = corPct(r.pct_meta);
    return `<div class="ranking-item" data-usuario="${{r.usuario}}">
      <div class="avatar">${{iniciaisNome(r.usuario)}}</div>
      <div class="ranking-info">
        <div class="ranking-nome">${{nomeExibicao(r.usuario)}}</div>
        <div class="ranking-sub">${{r.caixas.toLocaleString('pt-BR')}} cx · ${{r.media ?? '-'}} cx/h · ${{r.dias_trabalhados}} dia(s)</div>
      </div>
      <div class="badge" style="background:${{cor}}22; color:${{cor}};">${{r.pct_meta}}%</div>
      <div class="chevron">›</div>
    </div>`;
  }}).join('');

  document.querySelectorAll('.ranking-item').forEach(el => {{
    el.addEventListener('click', () => abrirDetalhe(el.dataset.usuario));
  }});
}}

function abrirDetalhe(usuario) {{
  const {{ranking}} = obterRankingPeriodo(periodoAtual, window.dataEspecificaSep);
  const info = ranking.find(r => r.usuario === usuario);
  if (!info) return;

  let corpo = '';
  if (periodoAtual === 'hoje') {{
    corpo = renderDetalheDia(usuario);
  }} else if (periodoAtual === 'dia') {{
    corpo = renderDetalheDia(usuario, window.dataEspecificaSep);
  }} else if (periodoAtual === 'mes') {{
    corpo = renderDetalheCalendario(usuario);
  }} else {{
    corpo = renderDetalheResumo3m(usuario, info);
  }}

  document.getElementById('view-detalhe').innerHTML = `
    <button class="voltar" onclick="fecharDetalhe()">‹ voltar ao geral</button>
    <div class="detalhe-header">
      <div class="avatar avatar-lg">${{iniciaisNome(usuario)}}</div>
      <div>
        <div class="detalhe-nome">${{nomeExibicao(usuario)}}</div>
        <div class="detalhe-sub">${{info.caixas.toLocaleString('pt-BR')}} cx · ${{info.pct_meta}}% da meta · ${{info.dias_abaixo_meta}} dia(s) abaixo da meta</div>
      </div>
    </div>
    ${{corpo}}
  `;
  document.getElementById('view-geral').style.display = 'none';
  document.getElementById('view-detalhe').style.display = 'block';
}}

function renderDetalheDia(usuario, diaRef) {{
  diaRef = diaRef || DADOS.dia_referencia;
  let tarefas = (D().tarefas[usuario] && D().tarefas[usuario][diaRef]) || [];
  tarefas = [...tarefas].sort((a,b) => a.inicio.localeCompare(b.inicio));
  if (!tarefas.length) return '<div class="vazio">Nenhuma tarefa registrada nesse dia.</div>';
  return '<div>' + tarefas.map(t => `
    <div class="tarefa-item">
      <div><div class="tarefa-nome">${{t.tarefa}}</div><div class="tarefa-horario">${{t.inicio}} – ${{t.fim}}</div></div>
      <div>${{t.caixas.toLocaleString('pt-BR')}} cx</div>
    </div>`).join('') + '</div>';
}}

function renderDetalheCalendario(usuario, mesPrefixo) {{
  mesPrefixo = mesPrefixo || DADOS.mes_atual_prefixo;
  const dias = (D().por_dia[usuario] || []).filter(d => d.dia.startsWith(mesPrefixo));
  if (!dias.length) return '<div class="vazio">Sem registros neste mês.</div>';
  return '<div class="calendario">' + [...dias].sort((a,b)=>a.dia.localeCompare(b.dia)).map(d => {{
    const cor = corClassificacao(d.classificacao);
    const dataFmt = d.dia.slice(8,10) + '/' + d.dia.slice(5,7);
    return `<div class="dia-card" style="background:${{cor}}22; border-color:${{cor}}55; color:${{cor}};">
      <div class="dia-data" style="color:var(--text);">${{dataFmt}}</div>
      <div class="dia-caixas-label">CX</div>
      <div class="dia-caixas">${{d.caixas.toLocaleString('pt-BR')}}</div>
      <div class="dia-pct">${{d.pct_meta}}% da meta dia</div>
      <div class="dia-tarefas">${{d.n_tarefas}} tarefa(s) realizada(s)</div>
      <div class="dia-tarefas" style="border-top:none; margin-top:2px; padding-top:0;">Hr Prod: ${{d.hr_produtiva.toFixed(1)}}h · Hr Improd: ${{d.hr_improdutiva.toFixed(1)}}h</div>
      ${{d.hr_extra > 0.01 ? `<div class="dia-tarefas" style="border-top:none; margin-top:2px; padding-top:0; color:var(--accent);">HE Produtiva: ${{d.hr_extra.toFixed(1)}}h</div>` : ''}}
    </div>`;
  }}).join('') + '</div>';
}}

function renderDetalheResumo3m(usuario, info) {{
  const dias = (D().por_dia[usuario] || []).filter(d => d.dia >= DADOS.inicio_3m);
  const labels = {{ vermelho: 'abaixo de 500', amarelo: '500–1499', verde: 'na meta', estrela: 'acima da meta' }};

  function blocoResumo(diasFiltrados) {{
    const cont = {{ vermelho: 0, amarelo: 0, verde: 0, estrela: 0 }};
    let hrProd = 0, hrImprod = 0, hrExtra = 0, caixas = 0;
    diasFiltrados.forEach(d => {{
      cont[d.classificacao] = (cont[d.classificacao]||0) + 1;
      hrProd += d.hr_produtiva; hrImprod += d.hr_improdutiva; hrExtra += (d.hr_extra||0); caixas += d.caixas;
    }});
    const media = hrProd > 0 ? (caixas/hrProd).toFixed(1) : '-';
    return `<div class="resumo3m-grid">` + Object.keys(cont).map(k => `
      <div class="resumo3m-item" style="background:${{CORES[k]}}22;">
        <div class="resumo3m-num" style="color:${{CORES[k]}};">${{cont[k]}}</div>
        <div class="resumo3m-label">${{labels[k]}}</div>
      </div>`).join('') + '</div>' +
      `<div class="vazio" style="text-align:left; padding:6px 0 16px;">Hr Produtiva total: ${{hrProd.toFixed(2)}}h · Hr Improdutiva total: ${{hrImprod.toFixed(2)}}h` +
      (hrExtra > 0.01 ? ` · <span style="color:var(--accent);">HE Produtiva total: ${{hrExtra.toFixed(2)}}h</span>` : '') +
      ` · Média: ${{media}} cx/h</div>`;
  }}

  // meses distintos presentes no periodo de 3 meses, do mais recente pro mais antigo
  const mesesSet = new Set(dias.map(d => d.dia.slice(0,7)));
  const meses = [...mesesSet].sort().reverse();
  const nomesMes = {{'01':'Janeiro','02':'Fevereiro','03':'Março','04':'Abril','05':'Maio','06':'Junho','07':'Julho','08':'Agosto','09':'Setembro','10':'Outubro','11':'Novembro','12':'Dezembro'}};

  let html = '<h3 style="margin:4px 0 10px; font-size:14px;">Resumo geral (90 dias)</h3>' + blocoResumo(dias);

  meses.forEach(mesPrefixo => {{
    const diasDoMes = dias.filter(d => d.dia.startsWith(mesPrefixo));
    const [ano, mm] = mesPrefixo.split('-');
    const nomeMes = (nomesMes[mm] || mm) + '/' + ano;
    const idCal = 'cal-' + mesPrefixo;
    html += `
      <h3 style="margin:18px 0 10px; font-size:14px;">${{nomeMes}}</h3>
      ${{blocoResumo(diasDoMes)}}
      <div class="mes-toggle" onclick="toggleMesCalendario('${{idCal}}','${{usuario}}','${{mesPrefixo}}')">
        <span>Detalhamento calendário</span>
        <span class="chevron" id="chev-${{idCal}}">›</span>
      </div>
      <div id="${{idCal}}" style="display:none; margin-top:10px; margin-bottom:14px;"></div>
    `;
  }});

  return html;
}}

function toggleMesCalendario(idCal, usuario, mesPrefixo) {{
  const el = document.getElementById(idCal);
  const chev = document.getElementById('chev-' + idCal);
  const abrindo = el.style.display === 'none';
  el.style.display = abrindo ? 'block' : 'none';
  chev.textContent = abrindo ? '⌄' : '›';
  if (abrindo && !el.dataset.carregado) {{
    el.innerHTML = renderDetalheCalendario(usuario, mesPrefixo);
    el.dataset.carregado = '1';
  }}
}}

function fecharDetalhe() {{
  document.getElementById('view-detalhe').style.display = 'none';
  document.getElementById('view-geral').style.display = 'block';
}}

document.querySelectorAll('#app-separadores .periodo-tabs button').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('#app-separadores .periodo-tabs button').forEach(b => b.classList.remove('ativo'));
    btn.classList.add('ativo');
    periodoAtual = btn.dataset.p;
    document.getElementById('data-especifica-sep').style.display = periodoAtual === 'dia' ? 'block' : 'none';
    renderRanking();
  }});
}});
document.getElementById('data-especifica-sep').addEventListener('change', (e) => {{
  window.dataEspecificaSep = e.target.value;
  renderRanking();
}});
document.getElementById('busca-separador').addEventListener('input', renderRanking);

// ===== navegacao do hub =====
function abrirApp(id) {{
  document.getElementById('hub').style.display = 'none';
  document.getElementById(id).style.display = 'block';
  if (id === 'app-separadores') {{
    document.getElementById('view-detalhe').style.display = 'none';
    document.getElementById('view-geral').style.display = 'block';
    renderRanking();
  }}
  if (id === 'app-operadores') {{
    document.getElementById('view-detalhe-op').style.display = 'none';
    document.getElementById('view-geral-op').style.display = 'block';
    renderRankingOp();
  }}
  if (id === 'app-funcionarios') renderFuncionarios();
  if (id === 'app-totalseparado') renderTotalSeparado();
  if (id === 'app-lista-funcionarios') renderListaFuncionarios();
}}
document.querySelectorAll('.flag-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.flag-btn').forEach(b => b.classList.remove('ativo'));
    btn.classList.add('ativo');
    currentFlag = btn.dataset.flag;
    const nomes = {{ ambos: 'Nacional + Exportação', nacional: 'Nacional', exportacao: 'Exportação' }};
    document.getElementById('subtitulo-topo').textContent = 'Central de indicadores operacionais · ' + nomes[currentFlag];
  }});
}});
function voltarHub() {{
  ['app-separadores','app-operadores','app-funcionarios','app-totalseparado','app-lista-funcionarios'].forEach(id => {{
    document.getElementById(id).style.display = 'none';
  }});
  document.getElementById('hub').style.display = 'block';
}}

// ===== APP: FUNCIONARIOS (top 10) =====
let periodoFunc = 'hoje';
function renderFuncionarios() {{
  const {{ranking, label}} = obterRankingPeriodo(periodoFunc, window.dataEspecificaFunc);
  const container = document.getElementById('funcionarios-conteudo');
  if (!ranking.length) {{
    container.innerHTML = '<div class="vazio">Sem dados nesse período.</div>';
    return;
  }}
  const secoes = [
    {{ titulo: 'Top 10 · Mais próximos ou acima da meta', chave: 'pct_meta', sufixo: '%' }},
    {{ titulo: 'Top 10 · Mais caixas separadas', chave: 'caixas', sufixo: ' cx' }},
    {{ titulo: 'Top 10 · Mais tarefas realizadas', chave: 'total_tarefas', sufixo: ' tarefa(s)' }},
    {{ titulo: 'Top 10 · Mais abaixo da meta', chave: 'pct_meta', sufixo: '%', inverso: true }},
  ];
  container.innerHTML = secoes.map(s => {{
    const ordenado = [...ranking].sort((a,b) => s.inverso ? a[s.chave]-b[s.chave] : b[s.chave]-a[s.chave]).slice(0,10);
    const itens = ordenado.map((r,i) => `
      <div class="top10-item">
        <div class="top10-pos">${{i+1}}</div>
        <div class="top10-nome">${{nomeExibicao(r.usuario)}}</div>
        <div class="top10-valor">${{typeof r[s.chave]==='number' ? r[s.chave].toLocaleString('pt-BR') : r[s.chave]}}${{s.sufixo}}</div>
      </div>`).join('');
    return `<div class="top10-secao"><div class="top10-titulo">${{s.titulo}} <span style="color:var(--text-dim); font-weight:400;">(${{label.replace('Exibindo: ','')}})</span></div>${{itens}}</div>`;
  }}).join('');
}}
document.querySelectorAll('#periodo-tabs-func button').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('#periodo-tabs-func button').forEach(b => b.classList.remove('ativo'));
    btn.classList.add('ativo');
    periodoFunc = btn.dataset.p;
    document.getElementById('data-especifica-func').style.display = periodoFunc === 'dia' ? 'block' : 'none';
    renderFuncionarios();
  }});
}});

document.getElementById('data-especifica-func').addEventListener('change', (e) => {{
  window.dataEspecificaFunc = e.target.value;
  renderFuncionarios();
}});

// ===== APP: TOTAL SEPARADO (volume geral + dimensionamento) =====
let periodoTotal = 'hoje';
function filtrarTotalPorDia(inicio, fim) {{
  return D().total_por_dia.filter(d => d.dia >= inicio && d.dia <= fim);
}}
function renderTotalSeparado() {{
  const container = document.getElementById('totalseparado-conteudo');
  const hoje = DADOS.dia_referencia;
  let inicio, fim = hoje, tituloPeriodo;

  if (periodoTotal === 'hoje') {{ inicio = hoje; tituloPeriodo = 'Hoje'; }}
  else if (periodoTotal === 'mes') {{ inicio = DADOS.mes_atual_prefixo + '-01'; tituloPeriodo = 'Mês atual'; }}
  else if (periodoTotal === 'dia') {{
    if (!window.dataEspecificaTotal) {{ container.innerHTML = '<div class="vazio">Selecione uma data.</div>'; return; }}
    inicio = window.dataEspecificaTotal; fim = window.dataEspecificaTotal;
    tituloPeriodo = 'Dia específico (' + inicio.split('-').reverse().join('/') + ')';
  }}
  else {{ inicio = DADOS.inicio_3m; tituloPeriodo = 'Últimos 90 dias'; }}

  const dias = filtrarTotalPorDia(inicio, fim);
  if (!dias.length) {{ container.innerHTML = '<div class="vazio">Sem dados nesse período.</div>'; return; }}

  const totalCx = dias.reduce((a,d)=>a+d.caixas,0);
  const mediaDia = totalCx / dias.length;
  const pessoasMedia = Math.ceil(mediaDia / DADOS.meta_diaria);
  const pessoasAtivasMedia = (dias.reduce((a,d)=>a+d.pessoas_ativas,0) / dias.length).toFixed(1);
  const maiorPico = dias.reduce((m,d)=>d.pessoas_necessarias>m?d.pessoas_necessarias:m, 0);

  let html = `<div class="total-kpis">
    <div class="kpi"><div class="kpi-label">total separado</div><div class="kpi-valor">${{totalCx.toLocaleString('pt-BR')}}</div></div>
    <div class="kpi"><div class="kpi-label">média cx/dia</div><div class="kpi-valor">${{Math.round(mediaDia).toLocaleString('pt-BR')}}</div></div>
    <div class="kpi"><div class="kpi-label">dias no período</div><div class="kpi-valor">${{dias.length}}</div></div>
    <div class="kpi"><div class="kpi-label">separadores ativos (média)</div><div class="kpi-valor">${{pessoasAtivasMedia}}</div></div>
  </div>
  <div class="dimensionamento-box">
    <div class="dimensionamento-titulo">Dimensionamento sugerido — ${{tituloPeriodo}}</div>
    <div class="dimensionamento-valor">${{pessoasMedia}} separador(es)</div>
    <div class="vazio" style="text-align:left; padding:6px 0 0;">
      pra dar conta da média diária (${{Math.round(mediaDia).toLocaleString('pt-BR')}} cx/dia) no ritmo da meta de ${{DADOS.meta_diaria}} cx/pessoa.
      No pico do período, chegou a precisar de <strong style="color:var(--accent);">${{maiorPico}} separador(es)</strong> num único dia.
    </div>
  </div>`;

  if (periodoTotal !== 'hoje') {{
    const maxCx = Math.max(...dias.map(d=>d.caixas));
    html += '<div>' + [...dias].sort((a,b)=>b.dia.localeCompare(a.dia)).map(d => {{
      const dataFmt = d.dia.slice(8,10) + '/' + d.dia.slice(5,7);
      const pct = maxCx ? (d.caixas/maxCx*100) : 0;
      const idRank = 'rankdia-' + d.dia;
      return `<div class="total-dia-row" onclick="toggleRankingDia('${{idRank}}','${{d.dia}}')" style="cursor:pointer;">
        <span style="width:50px;">${{dataFmt}}</span>
        <div class="total-dia-barra"><div class="total-dia-barra-fill" style="width:${{pct}}%;"></div></div>
        <span style="width:70px; text-align:right;">${{d.caixas.toLocaleString('pt-BR')}} cx</span>
        <span style="width:70px; text-align:right; color:var(--text-dim);">${{d.pessoas_necessarias}} pessoa(s)</span>
        <span class="chevron" id="chev-${{idRank}}" style="margin-left:8px;">›</span>
      </div>
      <div id="${{idRank}}" style="display:none; margin:-2px 0 8px;"></div>`;
    }}).join('') + '</div>';
  }}

  container.innerHTML = html;
}}

function toggleRankingDia(idRank, dia) {{
  const el = document.getElementById(idRank);
  const chev = document.getElementById('chev-' + idRank);
  const abrindo = el.style.display === 'none';
  el.style.display = abrindo ? 'block' : 'none';
  chev.textContent = abrindo ? '⌄' : '›';
  if (abrindo && !el.dataset.carregado) {{
    const ranking = D().ranking_por_dia[dia] || [];
    el.innerHTML = ranking.map((r,i) => `
      <div class="top10-item" style="margin-left:20px;">
        <div class="top10-pos">${{i+1}}</div>
        <div class="top10-nome">${{nomeExibicao(r.usuario)}}</div>
        <div style="font-family:var(--mono); font-size:12px; color:var(--text-dim); margin-right:10px;">${{r.n_tarefas}} tarefa(s)</div>
        <div style="font-family:var(--mono); font-size:12px; color:var(--text-dim); margin-right:10px;">${{r.pct_meta}}%</div>
        <div class="top10-valor">${{r.caixas.toLocaleString('pt-BR')}} cx</div>
      </div>`).join('') || '<div class="vazio" style="padding:10px;">Sem separador nesse dia.</div>';
    el.dataset.carregado = '1';
  }}
}}
document.querySelectorAll('#periodo-tabs-total button').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('#periodo-tabs-total button').forEach(b => b.classList.remove('ativo'));
    btn.classList.add('ativo');
    periodoTotal = btn.dataset.p;
    document.getElementById('data-especifica-total').style.display = periodoTotal === 'dia' ? 'block' : 'none';
    renderTotalSeparado();
  }});
}});
document.getElementById('data-especifica-total').addEventListener('change', (e) => {{
  window.dataEspecificaTotal = e.target.value;
  renderTotalSeparado();
}});

// ===== APP: OPERADORES (sem meta/cor ainda -- so volume e atividade) =====
let periodoOp = 'hoje';

function obterRankingPeriodoOp(periodo, dataEspecifica) {{
  if (periodo === 'dia') {{
    if (!dataEspecifica) return {{ ranking: [], label: 'Selecione uma data' }};
    const dias = {{}}; // reaproveita por_dia do operador pra agregar 1 dia
    const registros = [];
    Object.keys(D2().por_dia).forEach(usuario => {{
      const diaDados = D2().por_dia[usuario].find(d => d.dia === dataEspecifica);
      if (!diaDados) return;
      registros.push({{
        usuario, caixas: diaDados.caixas, hr_produtiva: diaDados.hr_produtiva,
        media: diaDados.hr_produtiva > 0 ? +(diaDados.caixas/diaDados.hr_produtiva).toFixed(1) : null,
        dias_trabalhados: 1, total_tarefas: diaDados.n_tarefas,
      }});
    }});
    registros.sort((a,b) => b.caixas - a.caixas);
    return {{ ranking: registros, label: 'Exibindo: ' + dataEspecifica.split('-').reverse().join('/') }};
  }}
  return {{ ranking: D2().ranking[periodo] || [], label: DADOS.periodo_labels[periodo] || '' }};
}}

function renderKpisOp(ranking) {{
  const totalCx = ranking.reduce((a,r)=>a+r.caixas,0);
  const mediaGeral = ranking.length
    ? (ranking.reduce((a,r)=>a+(r.media||0),0)/ranking.filter(r=>r.media).length || 0).toFixed(1)
    : 0;
  document.getElementById('kpis-op').innerHTML = `
    <div class="kpi"><div class="kpi-label">operadores</div><div class="kpi-valor">${{ranking.length}}</div></div>
    <div class="kpi"><div class="kpi-label">total movimentado</div><div class="kpi-valor">${{totalCx.toLocaleString('pt-BR')}}</div></div>
    <div class="kpi"><div class="kpi-label">média cx/h</div><div class="kpi-valor">${{mediaGeral}}</div></div>
    <div class="kpi"><div class="kpi-label">tarefas totais</div><div class="kpi-valor">${{ranking.reduce((a,r)=>a+r.total_tarefas,0)}}</div></div>
  `;
}}

function renderRankingOp() {{
  const {{ranking, label}} = obterRankingPeriodoOp(periodoOp, window.dataEspecificaOp);
  document.getElementById('subtitulo-periodo-op').textContent =
    label + ' · Volume e atividade por endereço — sem meta definida ainda';
  renderKpisOp(ranking);

  if (!ranking.length) {{
    document.getElementById('ranking-list-op').innerHTML = '<div class="vazio">Sem dados de operador nesse período.</div>';
    return;
  }}

  document.getElementById('ranking-list-op').innerHTML = ranking.map(r => `
    <div class="ranking-item" data-usuario="${{r.usuario}}">
      <div class="avatar">${{iniciaisNome(r.usuario)}}</div>
      <div class="ranking-info">
        <div class="ranking-nome">${{nomeExibicao(r.usuario)}}</div>
        <div class="ranking-sub">${{r.caixas.toLocaleString('pt-BR')}} cx · ${{r.media ?? '-'}} cx/h · ${{r.total_tarefas}} tarefa(s) · ${{r.dias_trabalhados}} dia(s)</div>
      </div>
      <div class="chevron">›</div>
    </div>`).join('');

  document.querySelectorAll('#ranking-list-op .ranking-item').forEach(el => {{
    el.addEventListener('click', () => abrirDetalheOp(el.dataset.usuario));
  }});
}}

function abrirDetalheOp(usuario) {{
  let corpo = '';
  if (periodoOp === 'hoje') {{
    corpo = renderDetalheDiaOp(usuario, DADOS.dia_referencia);
  }} else if (periodoOp === 'dia') {{
    corpo = renderDetalheDiaOp(usuario, window.dataEspecificaOp);
  }} else if (periodoOp === 'mes') {{
    corpo = renderDetalheCalendarioOp(usuario);
  }} else {{
    corpo = renderDetalheResumoOp(usuario);
  }}

  document.getElementById('view-detalhe-op').innerHTML = `
    <button class="voltar" onclick="fecharDetalheOp()">‹ voltar ao geral</button>
    <div class="detalhe-header">
      <div class="avatar avatar-lg">${{iniciaisNome(usuario)}}</div>
      <div><div class="detalhe-nome">${{nomeExibicao(usuario)}}</div></div>
    </div>
    ${{corpo}}
  `;
  document.getElementById('view-geral-op').style.display = 'none';
  document.getElementById('view-detalhe-op').style.display = 'block';
}}

function fecharDetalheOp() {{
  document.getElementById('view-detalhe-op').style.display = 'none';
  document.getElementById('view-geral-op').style.display = 'block';
}}

function renderDetalheDiaOp(usuario, diaRef) {{
  let tarefas = (D2().tarefas[usuario] && D2().tarefas[usuario][diaRef]) || [];
  tarefas = [...tarefas].sort((a,b) => a.inicio.localeCompare(b.inicio));
  if (!tarefas.length) return '<div class="vazio">Nenhuma tarefa registrada nesse dia.</div>';
  return '<div>' + tarefas.map(t => `
    <div class="tarefa-item">
      <div><div class="tarefa-nome">${{t.tarefa}}</div><div class="tarefa-horario">${{t.inicio}} – ${{t.fim}}</div></div>
      <div>${{t.caixas.toLocaleString('pt-BR')}} cx</div>
    </div>`).join('') + '</div>';
}}

function renderDetalheCalendarioOp(usuario) {{
  const dias = (D2().por_dia[usuario] || []).filter(d => d.dia.startsWith(DADOS.mes_atual_prefixo));
  if (!dias.length) return '<div class="vazio">Sem registros neste mês.</div>';
  return '<div class="calendario">' + [...dias].sort((a,b)=>a.dia.localeCompare(b.dia)).map(d => {{
    const dataFmt = d.dia.slice(8,10) + '/' + d.dia.slice(5,7);
    return `<div class="dia-card" style="background:var(--bg-card); border-color:var(--border); color:var(--text);">
      <div class="dia-data" style="color:var(--text);">${{dataFmt}}</div>
      <div class="dia-caixas-label">CX</div>
      <div class="dia-caixas">${{d.caixas.toLocaleString('pt-BR')}}</div>
      <div class="dia-tarefas">${{d.n_tarefas}} tarefa(s) · Hr Prod: ${{d.hr_produtiva.toFixed(1)}}h</div>
    </div>`;
  }}).join('') + '</div>';
}}

function renderDetalheResumoOp(usuario) {{
  const dias = (D2().por_dia[usuario] || []).filter(d => d.dia >= DADOS.inicio_3m);
  if (!dias.length) return '<div class="vazio">Sem registros nesse período.</div>';
  const caixas = dias.reduce((a,d)=>a+d.caixas,0);
  const hrProd = dias.reduce((a,d)=>a+d.hr_produtiva,0);
  const tarefas = dias.reduce((a,d)=>a+d.n_tarefas,0);
  const media = hrProd > 0 ? (caixas/hrProd).toFixed(1) : '-';
  return `<div class="total-kpis">
    <div class="kpi"><div class="kpi-label">total movimentado</div><div class="kpi-valor">${{caixas.toLocaleString('pt-BR')}}</div></div>
    <div class="kpi"><div class="kpi-label">dias trabalhados</div><div class="kpi-valor">${{dias.length}}</div></div>
    <div class="kpi"><div class="kpi-label">tarefas totais</div><div class="kpi-valor">${{tarefas}}</div></div>
    <div class="kpi"><div class="kpi-label">média cx/h</div><div class="kpi-valor">${{media}}</div></div>
  </div>`;
}}

document.querySelectorAll('#periodo-tabs-op button').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('#periodo-tabs-op button').forEach(b => b.classList.remove('ativo'));
    btn.classList.add('ativo');
    periodoOp = btn.dataset.p;
    document.getElementById('data-especifica-op').style.display = periodoOp === 'dia' ? 'block' : 'none';
    renderRankingOp();
  }});
}});
document.getElementById('data-especifica-op').addEventListener('change', (e) => {{
  window.dataEspecificaOp = e.target.value;
  renderRankingOp();
}});

// ===== APP: LISTA DE FUNCIONARIOS (visualizacao do roster + excecoes) =====
const STATUS_INFO = {{
  ativo: {{ cor: CORES.verde, label: 'Ativo' }},
  atencao: {{ cor: CORES.amarelo, label: 'Atenção' }},
  inativo_manual: {{ cor: CORES.vermelho, label: 'Inativo' }},
}};
const PAPEL_LABEL = {{ separador: 'Separador', conferente: 'Conferente', inativo: 'Inativo', analista: 'Analista', operador: 'Operador' }};

function renderListaFuncionarios() {{
  const busca = (document.getElementById('roster-busca').value || '').toLowerCase();
  const filtroStatus = document.getElementById('roster-filtro-status').value;
  const filtroPapel = document.getElementById('roster-filtro-papel').value;

  let lista = D().roster || [];
  lista = lista.filter(f => {{
    if (busca && !f.usuario.toLowerCase().includes(busca)) return false;
    if (filtroStatus !== 'todos' && f.status !== filtroStatus) return false;
    if (filtroPapel !== 'todos' && f.papel_efetivo !== filtroPapel) return false;
    return true;
  }});

  const container = document.getElementById('roster-conteudo');
  if (!lista.length) {{
    container.innerHTML = '<div class="vazio">Nenhum funcionário encontrado com esses filtros.</div>';
    return;
  }}

  container.innerHTML = lista.map(f => {{
    const st = STATUS_INFO[f.status] || STATUS_INFO.ativo;
    const dataFmt = f.ultima_atividade.split('-').reverse().join('/');
    return `<div class="roster-item">
      <div class="roster-status-dot" style="background:${{st.cor}};" title="${{st.label}}"></div>
      <div class="avatar">${{iniciaisNome(f.usuario)}}</div>
      <div class="ranking-info">
        <div class="roster-nome">${{nomeExibicao(f.usuario)}}${{f.excecao_manual ? '<span class="roster-manual-tag">manual</span>' : ''}}</div>
        <div class="roster-sub">${{f.total_caixas.toLocaleString('pt-BR')}} cx histórico · última atividade: ${{dataFmt}} (${{f.dias_parado}}d atrás)</div>
      </div>
      <div class="roster-badge" style="background:${{st.cor}}22; color:${{st.cor}};">${{PAPEL_LABEL[f.papel_efetivo] || f.papel_efetivo}}</div>
    </div>`;
  }}).join('');
}}
document.getElementById('roster-busca').addEventListener('input', renderListaFuncionarios);
document.getElementById('roster-filtro-status').addEventListener('change', renderListaFuncionarios);
document.getElementById('roster-filtro-papel').addEventListener('change', renderListaFuncionarios);

// ===== CENTRAL DE AJUDA (busca com Fuse.js) =====
const BASE_AJUDA = [
  {{
    categoria: "Como usar",
    pergunta: "Como ver quanto um separador específico fez no mês (ou em outro período)?",
    resposta: "Vá na box <code>Separadores</code>, escolha o período desejado (Hoje / Mês atual / Últimos 90 dias / Dia específico) nas abas do topo, e use o campo <code>🔍 Buscar separador pelo nome...</code> pra encontrar a pessoa rapidinho. Clique no nome dela pra ver o detalhe."
  }},
  {{
    categoria: "Como usar",
    pergunta: "Como ver as tarefas de um separador num dia específico do passado?",
    resposta: "Na box <code>Separadores</code>, clique na aba <code>Dia específico</code>, escolha a data no calendário que aparece, busque o nome da pessoa, e clique nela — vai mostrar a lista de tarefas daquele dia com horário de início e fim."
  }},
  {{
    categoria: "Como usar",
    pergunta: "Como ver o calendário do mês inteiro de um separador (dia a dia)?",
    resposta: "Vá em <code>Separadores</code> → aba <code>Mês atual</code> → clique no nome da pessoa. Vai abrir um calendário com um card colorido por dia, mostrando caixas, % da meta, tarefas e hora produtiva/extra."
  }},
  {{
    categoria: "Como usar",
    pergunta: "Como ver o ranking dos que mais separaram ou dos que estão abaixo da meta?",
    resposta: "Vá na box <code>Funcionários</code>. Ela já mostra 4 rankings Top 10 de uma vez: mais próximos/acima da meta, mais caixas separadas, mais tarefas feitas, e mais abaixo da meta. Também dá pra filtrar por período."
  }},
  {{
    categoria: "Como usar",
    pergunta: "Como saber quantas pessoas precisaria pra dar conta da demanda?",
    resposta: "Vá na box <code>Total Separado</code>. Ela mostra o \\"Dimensionamento sugerido\\": quantos separadores seriam necessários pra dar conta da média (ou do pico) do período, no ritmo da meta de 1.500cx/pessoa."
  }},
  {{
    categoria: "Como usar",
    pergunta: "Como saber quem é conferente, analista, inativo ou operador (mesmo separando às vezes)?",
    resposta: "Vá na box <code>Lista de Funcionários</code>. Ela mostra o papel de cada um (separador/operador/conferente/analista/inativo), com busca por nome e filtros. A tag \\"manual\\" indica que alguém definiu esse papel à mão (não foi automático)."
  }},
  {{
    categoria: "Como usar",
    pergunta: "Como ver só o pessoal de exportação, ou só nacional?",
    resposta: "No hub inicial (tela de entrada), tem o seletor <code>Operação: Ambos / Nacional / Exportação</code> no topo. Escolha antes de entrar em qualquer box — o filtro vale pra todas as telas."
  }},
  {{
    categoria: "Como usar",
    pergunta: "Como ver quem opera empilhadeira?",
    resposta: "Vá na box <code>Operadores</code>. É baseado 100% no endereço (altura ≥ 01), sem depender de cadastro manual. Ainda não tem meta definida pra esse grupo, só volume e atividade."
  }},
  {{
    categoria: "Significado das cores",
    pergunta: "O que significam as cores vermelho, amarelo, verde e laranja?",
    resposta: "Vermelho: menos de 500cx no dia. Amarelo: entre 500 e 1.499cx. Verde: bateu exatamente 1.500cx (a meta). Laranja/estrela: passou de 1.500cx."
  }},
  {{
    categoria: "Significado das cores",
    pergunta: "O que é HE Produtiva no card do calendário?",
    resposta: "É a Hora Extra Produtiva -- tempo trabalhado depois do horário normal do turno da pessoa (depois das 15:20 pro Turno 1, depois das 23:20 ou de madrugada pro Turno 2)."
  }},
  {{
    categoria: "Dúvidas comuns",
    pergunta: "Por que uma pessoa some do ranking de repente?",
    resposta: "Provavelmente ela foi marcada manualmente como Conferente, Analista, Inativo ou Operador (isso tira do ranking de Separador, mas o volume dela continua contando no Total Separado). Confira na box Lista de Funcionários -- vai ter uma tag \\"manual\\" explicando."
  }},
  {{
    categoria: "Dúvidas comuns",
    pergunta: "Por que alguém aparece como Operador mesmo separando no chão às vezes?",
    resposta: "Existe uma regra: quem já operou empilhadeira uma vez (endereço altura 01+) vira Operador PRA SEMPRE, mesmo nas tarefas que ela fizer depois em altura 00 (chão). É a \\"trava de operador\\"."
  }},
  {{
    categoria: "Dúvidas comuns",
    pergunta: "Por que o painel só mostra os últimos 90 dias?",
    resposta: "É de propósito, pra o arquivo não ficar pesado. O histórico completo (desde o início) fica disponível no arquivo Excel de auditoria (auditoria_producao_completa.xlsx), gerado à parte."
  }},
  {{
    categoria: "Dúvidas comuns",
    pergunta: "O que significa 'Atenção' (amarelo) na Lista de Funcionários?",
    resposta: "Significa que a pessoa está 45 dias ou mais sem nenhuma tarefa registrada, e ninguém ainda marcou o motivo (desligamento, mudança de função, férias longas etc). É só um alerta visual, não uma decisão automática."
  }},
  {{
    categoria: "Dúvidas comuns",
    pergunta: "Qual a jornada e o horário dos turnos considerados?",
    resposta: "Jornada: 7h20 fixo pra todo mundo. Turno 1: 07:00 às 15:20 (normal). Turno 2: 15:00 às 23:20 (normal). Depois desses horários, o tempo trabalhado conta como hora extra."
  }},
];

let fuseAjuda = null;
function abrirAjuda() {{
  document.getElementById('ajuda-overlay').classList.add('aberto');
  if (!fuseAjuda && window.Fuse) {{
    fuseAjuda = new Fuse(BASE_AJUDA, {{
      keys: ['pergunta', 'resposta', 'categoria'],
      threshold: 0.4,
      ignoreLocation: true,
    }});
  }}
  renderAjuda('');
  document.getElementById('ajuda-busca').focus();
}}
function fecharAjuda() {{
  document.getElementById('ajuda-overlay').classList.remove('aberto');
}}
document.getElementById('ajuda-overlay').addEventListener('click', (e) => {{
  if (e.target.id === 'ajuda-overlay') fecharAjuda();
}});

function renderAjuda(termo) {{
  const container = document.getElementById('ajuda-resultados');
  let itens;

  if (!termo) {{
    itens = BASE_AJUDA;
  }} else if (fuseAjuda) {{
    itens = fuseAjuda.search(termo).map(r => r.item);
  }} else {{
    // fallback sem Fuse.js (ex: sem internet pro CDN carregar): busca por
    // PALAVRAS individuais, nao a frase inteira -- bate mais palavra-chave
    const palavras = termo.toLowerCase().split(/[^a-z0-9à-ú]+/).filter(p => p.length > 2);
    itens = BASE_AJUDA.filter(i => {{
      const textoItem = (i.pergunta + ' ' + i.resposta).toLowerCase();
      return palavras.some(p => textoItem.includes(p));
    }});
  }}

  if (!itens.length) {{
    container.innerHTML = '<div class="vazio">Nenhum resultado. Tenta outras palavras, ou chama quem cuida do painel.</div>';
    return;
  }}

  let categoriaAtual = null;
  let html = '';
  itens.forEach(item => {{
    if (!termo && item.categoria !== categoriaAtual) {{
      categoriaAtual = item.categoria;
      html += `<div class="ajuda-categoria">${{categoriaAtual}}</div>`;
    }}
    html += `<div class="ajuda-item">
      <div class="ajuda-pergunta">${{item.pergunta}}</div>
      <div class="ajuda-resposta">${{item.resposta}}</div>
    </div>`;
  }});
  container.innerHTML = html;
}}
document.getElementById('ajuda-busca').addEventListener('input', (e) => renderAjuda(e.target.value));
document.addEventListener('keydown', (e) => {{
  if (e.key === 'Escape') fecharAjuda();
}});

renderRanking();
</script>
</body>
</html>"""


def montar_roster(por_dia_separador: pd.DataFrame, por_dia_operador: pd.DataFrame, excecoes: dict, hoje: date) -> list:
    """Lista de TODOS -- separadores E operadores (mesmo os com excecao),
    com papel efetivo, ultima atividade e status -- pra alimentar a box
    'Lista de Funcionarios', que e so visualizacao (nao edita nada).

    O papel automatico vem de qual fonte a pessoa aparece (separador ou
    operador, ja resolvido pela trava por pessoa em carregar_base). A
    excecao manual, se existir, sempre tem prioridade sobre o automatico."""

    def _resumo(df_pd: pd.DataFrame) -> pd.DataFrame:
        if df_pd.empty:
            return df_pd
        return df_pd.groupby("usuario", as_index=False).agg(
            total_caixas=("caixas", "sum"),
            ultima_atividade=("dia", "max"),
            primeira_atividade=("dia", "min"),
            dias_com_registro=("dia", "nunique"),
        )

    fontes = [("separador", _resumo(por_dia_separador)), ("operador", _resumo(por_dia_operador))]

    registros = []
    usuarios_vistos = set()
    for papel_automatico, resumo in fontes:
        if resumo is None or resumo.empty:
            continue
        for _, r in resumo.iterrows():
            usuario = r["usuario"]
            if usuario.lower() in usuarios_vistos:
                continue  # nao deveria acontecer (trava evita a pessoa estar nas duas), mas por seguranca
            usuarios_vistos.add(usuario.lower())

            excecao = excecoes.get(usuario.lower())
            papel_efetivo = excecao["papel"] if excecao and excecao.get("papel") else papel_automatico
            dias_parado = (hoje - r["ultima_atividade"]).days

            if excecao and excecao.get("papel") == "inativo":
                status = "inativo_manual"
            elif dias_parado >= 45:
                status = "atencao"  # parado ha tempo mas ninguem marcou ainda
            else:
                status = "ativo"

            registros.append({
                "usuario": usuario,
                "papel_efetivo": papel_efetivo,
                "papel_automatico": papel_automatico,
                "excecao_manual": bool(excecao),
                "total_caixas": int(r["total_caixas"]),
                "dias_com_registro": int(r["dias_com_registro"]),
                "ultima_atividade": str(r["ultima_atividade"]),
                "primeira_atividade": str(r["primeira_atividade"]),
                "dias_parado": dias_parado,
                "status": status,
            })

    registros.sort(key=lambda x: x["dias_parado"])
    return registros


def montar_ranking_operador(por_dia: pd.DataFrame, inicio: date, fim: date) -> list:
    """Ranking simplificado de operador: sem meta/cor, so volume e atividade."""
    filtro = (por_dia["dia"] >= inicio) & (por_dia["dia"] <= fim)
    recorte = por_dia.loc[filtro]
    resumo = recorte.groupby("usuario", as_index=False).agg(
        caixas=("caixas", "sum"),
        hr_produtiva=("hr_produtiva", "sum"),
        dias_trabalhados=("dia", "nunique"),
        total_tarefas=("n_tarefas", "sum"),
    )
    resumo["media_cx_por_hora"] = (
        resumo["caixas"] / resumo["hr_produtiva"]
    ).replace([float("inf"), -float("inf")], None).round(1)

    registros = []
    for _, r in resumo.sort_values("caixas", ascending=False).iterrows():
        registros.append({
            "usuario": r["usuario"],
            "caixas": int(r["caixas"]),
            "hr_produtiva": round(r["hr_produtiva"], 2),
            "media": r["media_cx_por_hora"] if pd.notna(r["media_cx_por_hora"]) else None,
            "dias_trabalhados": int(r["dias_trabalhados"]),
            "total_tarefas": int(r["total_tarefas"]),
        })
    return registros


def montar_dados_por_dia_operador(por_dia: pd.DataFrame) -> dict:
    """Igual montar_dados_por_dia, mas sem pct_meta/classificacao (nao existe
    meta pra operador ainda)."""
    out: dict[str, list] = {}
    for _, row in por_dia.iterrows():
        usuario = row["usuario"]
        out.setdefault(usuario, []).append({
            "dia": str(row["dia"]),
            "caixas": int(row["caixas"]),
            "hr_produtiva": round(row["hr_produtiva"], 2),
            "n_tarefas": int(row["n_tarefas"]),
        })
    return out


def montar_flag_operador(df_tarefa_filtrado: pd.DataFrame, hoje: date, inicio_mes: date, inicio_3meses: date) -> dict:
    """Bloco de dados do Operador (sem meta/cor/dimensionamento -- so
    volume, tarefas e horas produtivas, que e o que da pra medir por
    enquanto so com a leitura de endereco)."""
    por_dia = ip.indicadores_por_dia(df_tarefa_filtrado)
    if por_dia.empty:
        return {
            "ranking": {"hoje": [], "mes": [], "3m": []},
            "tarefas": {}, "por_dia": {},
        }
    return {
        "ranking": {
            "hoje": montar_ranking_operador(por_dia, hoje, hoje),
            "mes": montar_ranking_operador(por_dia, inicio_mes, hoje),
            "3m": montar_ranking_operador(por_dia, inicio_3meses, hoje),
        },
        "tarefas": montar_dados_tarefas_por_usuario(df_tarefa_filtrado),
        "por_dia": montar_dados_por_dia_operador(por_dia),
    }


def montar_flag(df_tarefa_filtrado: pd.DataFrame, hoje: date, inicio_mes: date, inicio_3meses: date, excecoes: dict, df_tarefa_operador: pd.DataFrame | None = None) -> dict:
    """Monta o bloco de dados filtravel (ranking/tarefas/por_dia/total) pra
    um recorte de operacao (nacional, exportacao ou ambos combinados).

    Pessoas marcadas em 'excecoes' como conferente/inativo saem do
    RANKING (ninguem quer ver quem foi desligado ou nao e separador
    disputando posicao), mas continuam entrando no Total Separado -- o
    volume que elas separaram e real e ajuda a explicar o total do galpao.

    'df_tarefa_operador' (mesmo recorte de operacao, so que do universo
    operador) e usado so pra alimentar o roster da Lista de Funcionarios,
    que agora mostra separador E operador juntos."""
    por_dia_completo = ip.indicadores_por_dia(df_tarefa_filtrado)
    por_dia_operador = (
        ip.indicadores_por_dia(df_tarefa_operador)
        if df_tarefa_operador is not None and not df_tarefa_operador.empty
        else pd.DataFrame()
    )

    if por_dia_completo.empty:
        return {
            "ranking": {"hoje": [], "mes": [], "3m": []},
            "tarefas": {}, "por_dia": {}, "total_por_dia": [], "ranking_por_dia": {},
            "roster": montar_roster(por_dia_completo, por_dia_operador, excecoes, hoje),
        }

    usuarios_excluidos_ranking = {
        u for u, e in excecoes.items() if e.get("papel") in ("conferente", "inativo", "analista", "operador")
    }
    df_tarefa_ranking = df_tarefa_filtrado[
        ~df_tarefa_filtrado[ip.COL_USUARIO].str.lower().isin(usuarios_excluidos_ranking)
    ]
    por_dia_ranking = ip.indicadores_por_dia(df_tarefa_ranking)

    return {
        "ranking": {
            "hoje": montar_ranking(por_dia_ranking, hoje, hoje),
            "mes": montar_ranking(por_dia_ranking, inicio_mes, hoje),
            "3m": montar_ranking(por_dia_ranking, inicio_3meses, hoje),
        },
        "tarefas": montar_dados_tarefas_por_usuario(df_tarefa_ranking),
        "por_dia": montar_dados_por_dia(por_dia_ranking),
        # total_por_dia e ranking_por_dia usam o COMPLETO (com excecoes) --
        # o Total Separado quer refletir tudo que realmente saiu do chao
        "total_por_dia": montar_total_por_dia(por_dia_completo),
        "ranking_por_dia": montar_ranking_por_dia(por_dia_completo),
        "roster": montar_roster(por_dia_completo, por_dia_operador, excecoes, hoje),
    }


def carregar_excecoes() -> dict:
    """Le o cadastro de excecoes pontuais (conferente/inativo), definido
    pelo editor_funcionario.py. Se nao existir ainda, ninguem tem excecao
    e tudo segue 100% na classificacao automatica."""
    caminho = PASTA_SCRIPT / "base" / "excecoes_funcionarios.json"
    if not caminho.exists():
        return {}
    return json.loads(caminho.read_text(encoding="utf-8"))


def main():
    df = ip.carregar_base()
    df_tarefa = ip.agrupar_por_tarefa(df)

    if df_tarefa.empty:
        print("[erro] nenhum dado de separador encontrado. Rode o tratamento_produtividade.py primeiro.")
        return

    excecoes = carregar_excecoes()
    if excecoes:
        print(f"[excecoes] {len(excecoes)} funcionario(s) com excecao definida: "
              f"{[(u, e.get('papel')) for u, e in excecoes.items()]}")

    hoje_real = datetime.now().date()
    ultima_data = df_tarefa["dia"].max()
    hoje = min(hoje_real, ultima_data)
    inicio_mes = hoje.replace(day=1)

    # JANELA_DIAS_HTML: o HTML embute so os ultimos 90 dias (rolling, nao
    # mes calendario) pra nao inchar o arquivo com o historico inteiro.
    # Tudo mais antigo fica disponivel no .xlsx de auditoria
    # (gerar_arquivo_auditoria.py), nao no painel.
    inicio_3meses = hoje - pd.Timedelta(days=JANELA_DIAS_HTML - 1)

    # filtra a fonte ANTES de montar qualquer coisa -- assim ranking,
    # roster, total_por_dia etc ja nascem limitados aos 90 dias, sem
    # precisar repetir o filtro em cada funcao
    df_tarefa = df_tarefa[df_tarefa["dia"] >= inicio_3meses].copy()

    tem_operacao = "operacao" in df_tarefa.columns
    if tem_operacao:
        print(f"[operacao] tarefas por operacao: {df_tarefa['operacao'].value_counts().to_dict()}")
        df_nacional = df_tarefa[df_tarefa["operacao"] == "nacional"]
        df_exportacao = df_tarefa[df_tarefa["operacao"] == "exportacao"]
        # 'Ambos' = Nacional + Exportacao combinados, NAO 'sem filtro'.
        # Qualquer outro galpao nao classificado (nem 01 nem 04) fica de
        # fora dos 3 modos -- ele nao pertence a nenhuma das duas operacoes.
        df_ambos = df_tarefa[df_tarefa["operacao"].isin(["nacional", "exportacao"])]
        n_outros = len(df_tarefa) - len(df_ambos)
        if n_outros:
            print(f"[aviso] {n_outros} tarefa(s) com galpao fora de 01/04 (nao entram em nenhum dos 3 modos).")
    else:
        print("[aviso] coluna 'operacao' nao encontrada -- rode o tratamento_produtividade.py atualizado. Tratando tudo como 'ambos'.")
        df_nacional = df_tarefa.iloc[0:0]
        df_exportacao = df_tarefa.iloc[0:0]
        df_ambos = df_tarefa.iloc[0:0]

    # ---- OPERADOR (mesmo raciocinio de endereco, sem meta ainda) -----------
    df_op = ip.carregar_base(papel="operador")
    df_tarefa_op = ip.agrupar_por_tarefa(df_op)
    if not df_tarefa_op.empty:
        df_tarefa_op = df_tarefa_op[df_tarefa_op["dia"] >= inicio_3meses].copy()
    if not df_tarefa_op.empty and "operacao" in df_tarefa_op.columns:
        df_op_nacional = df_tarefa_op[df_tarefa_op["operacao"] == "nacional"]
        df_op_exportacao = df_tarefa_op[df_tarefa_op["operacao"] == "exportacao"]
        df_op_ambos = df_tarefa_op[df_tarefa_op["operacao"].isin(["nacional", "exportacao"])]
    else:
        df_op_nacional = df_tarefa_op.iloc[0:0] if not df_tarefa_op.empty else df_tarefa_op
        df_op_exportacao = df_op_nacional
        df_op_ambos = df_op_nacional
    print(f"[operador] {len(df_tarefa_op)} tarefa(s) de operador encontradas.")

    dados = {
        "periodo_labels": {
            "hoje": f"Exibindo: {hoje.strftime('%d/%m/%Y')}",
            "mes": f"Exibindo: {inicio_mes.strftime('%d/%m')} a {hoje.strftime('%d/%m/%Y')}",
            "3m": f"Exibindo: {inicio_3meses.strftime('%d/%m')} a {hoje.strftime('%d/%m/%Y')}",
        },
        "dia_referencia": str(hoje),
        "mes_atual_prefixo": hoje.strftime("%Y-%m"),
        "inicio_3m": str(inicio_3meses),
        "meta_diaria": ip.META_DIARIA,
        "flags": {
            "ambos": montar_flag(df_ambos, hoje, inicio_mes, inicio_3meses, excecoes, df_op_ambos),
            "nacional": montar_flag(df_nacional, hoje, inicio_mes, inicio_3meses, excecoes, df_op_nacional),
            "exportacao": montar_flag(df_exportacao, hoje, inicio_mes, inicio_3meses, excecoes, df_op_exportacao),
        },
        "flags_operador": {
            "ambos": montar_flag_operador(df_op_ambos, hoje, inicio_mes, inicio_3meses),
            "nacional": montar_flag_operador(df_op_nacional, hoje, inicio_mes, inicio_3meses),
            "exportacao": montar_flag_operador(df_op_exportacao, hoje, inicio_mes, inicio_3meses),
        },
    }

    html = gerar_html(json.dumps(dados, ensure_ascii=False, default=str))
    SAIDA_HTML.write_text(html, encoding="utf-8")
    print(f"[ok] painel gerado em {SAIDA_HTML}")


if __name__ == "__main__":
    main()