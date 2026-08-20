# -*- coding: utf-8 -*-
"""
editor_funcionarios.py

Editor VISUAL dos papeis dos funcionarios (Separador / Conferente /
Inativo / Analista), rodando local no navegador via Streamlit.

Diferente do editor_funcionario.py (CLI, digita nome por nome), aqui você
ve TODOS de uma vez numa tabela, com busca, e edita o papel clicando na
celula (vira um dropdown). Só clica em "Salvar alteracoes" no final.

Uso:
    streamlit run editor_funcionarios.py

Abre automaticamente no navegador (geralmente http://localhost:8501).
"""

import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

import indicadores_produtividade as ip

PASTA_SCRIPT = Path(__file__).resolve().parent.parent.parent
ARQUIVO_EXCECOES = PASTA_SCRIPT / "base" / "excecoes_funcionarios.json"
ARQUIVO_LOG = PASTA_SCRIPT / "base" / "log_alteracoes.jsonl"

PAPEIS = ["separador", "conferente", "inativo", "analista", "operador"]
PAPEL_LABEL = {"separador": "Separador", "conferente": "Conferente", "inativo": "Inativo", "analista": "Analista", "operador": "Operador"}
TURNOS = ["turno_1", "turno_2"]
TURNO_LABEL = {"turno_1": "Turno 1 (07:00–15:20)", "turno_2": "Turno 2 (15:00–23:20)"}


# ---------------------------------------------------------------------------
# Funcoes de dados (testaveis fora do Streamlit tambem)
# ---------------------------------------------------------------------------

def carregar_excecoes() -> dict:
    if ARQUIVO_EXCECOES.exists():
        return json.loads(ARQUIVO_EXCECOES.read_text(encoding="utf-8"))
    return {}


def salvar_excecoes(excecoes: dict):
    ARQUIVO_EXCECOES.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO_EXCECOES.write_text(
        json.dumps(excecoes, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def registrar_log(usuario: str, campo: str, valor_anterior, valor_novo):
    """Acrescenta uma linha no log de alteracoes (arquivo .jsonl -- um
    registro JSON por linha, facil de ler incrementalmente e nunca
    reescreve o que ja foi gravado)."""
    ARQUIVO_LOG.parent.mkdir(parents=True, exist_ok=True)
    registro = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "usuario": usuario,
        "campo": campo,
        "valor_anterior": valor_anterior,
        "valor_novo": valor_novo,
    }
    with open(ARQUIVO_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def carregar_log(limite: int = 100) -> pd.DataFrame:
    """Le o log de alteracoes, mais recente primeiro."""
    if not ARQUIVO_LOG.exists():
        return pd.DataFrame(columns=["timestamp", "usuario", "campo", "valor_anterior", "valor_novo"])
    linhas = []
    with open(ARQUIVO_LOG, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                linhas.append(json.loads(linha))
    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    return df.sort_values("timestamp", ascending=False).head(limite).reset_index(drop=True)


def montar_tabela_funcionarios() -> pd.DataFrame:
    """Monta a tabela base: todo mundo que ja apareceu na extracao, com
    o papel EFETIVO atual (excecao se tiver, senao 'separador' automatico),
    o turno (definido manualmente ou inferido), total historico e ultima
    atividade -- pra dar contexto na hora de editar."""
    df = ip.carregar_base()
    df_tarefa = ip.agrupar_por_tarefa(df)
    excecoes = carregar_excecoes()

    if df_tarefa.empty:
        return pd.DataFrame(columns=["Usuário", "Papel", "Turno", "Caixas (histórico)", "Última atividade", "Dias parado"])

    hoje = datetime.now().date()
    resumo = df_tarefa.groupby(ip.COL_USUARIO, as_index=False).agg(
        total_caixas=("caixas", "sum"),
        ultima_atividade=("dia", "max"),
    )

    linhas = []
    for _, r in resumo.iterrows():
        usuario = r[ip.COL_USUARIO]
        excecao = excecoes.get(usuario.lower())
        papel = excecao["papel"] if excecao and excecao.get("papel") else "separador"

        # turno: usa o que ja foi calculado em agrupar_por_tarefa (turno_pessoa),
        # que ja respeita a excecao manual se existir
        tarefas_pessoa = df_tarefa[df_tarefa[ip.COL_USUARIO] == usuario]
        turno = tarefas_pessoa["turno_pessoa"].mode().iat[0] if not tarefas_pessoa.empty else "turno_1"

        dias_parado = (hoje - r["ultima_atividade"]).days
        linhas.append({
            "Usuário": usuario,
            "Papel": papel,
            "Turno": turno,
            "Caixas (histórico)": int(r["total_caixas"]),
            "Última atividade": str(r["ultima_atividade"]),
            "Dias parado": dias_parado,
        })

    tabela = pd.DataFrame(linhas).sort_values("Usuário").reset_index(drop=True)
    return tabela


def calcular_diferencas(tabela_original: pd.DataFrame, tabela_editada: pd.DataFrame):
    """Compara papel E turno originais com os editados e retorna so as
    MUDANCAS, no formato pronto pra salvar em excecoes_funcionarios.json.
    Quem voltou pra 'separador' + turno automatico tem a excecao removida
    (so fica registrado o que realmente diverge do automatico).

    Tambem retorna 'eventos_log': lista de mudancas campo a campo, pronta
    pra gravar no log de auditoria (registrar_log)."""
    excecoes_novas = carregar_excecoes()
    mudou = {}
    eventos_log = []

    orig_papel = tabela_original.set_index("Usuário")["Papel"].to_dict()
    orig_turno = tabela_original.set_index("Usuário")["Turno"].to_dict()

    for _, row in tabela_editada.iterrows():
        usuario = row["Usuário"]
        papel_novo = row["Papel"]
        turno_novo = row["Turno"]
        papel_antigo = orig_papel.get(usuario)
        turno_antigo = orig_turno.get(usuario)
        papel_mudou = papel_novo != papel_antigo
        turno_mudou = turno_novo != turno_antigo

        if not papel_mudou and not turno_mudou:
            continue

        chave = usuario.lower()
        entrada = excecoes_novas.get(chave, {})

        if papel_novo != "separador":
            entrada["papel"] = papel_novo
        elif "papel" in entrada:
            del entrada["papel"]

        # turno so vira excecao registrada se o usuario mudou explicitamente
        # (senao ficaria sempre gravando o inferido, perdendo a atualizacao automatica)
        if turno_mudou:
            entrada["turno"] = turno_novo

        if papel_mudou:
            eventos_log.append((usuario, "papel", PAPEL_LABEL.get(papel_antigo, papel_antigo), PAPEL_LABEL[papel_novo]))
        if turno_mudou:
            eventos_log.append((usuario, "turno", TURNO_LABEL.get(turno_antigo, turno_antigo), TURNO_LABEL[turno_novo]))

        if entrada:
            entrada["definido_em"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            excecoes_novas[chave] = entrada
        elif chave in excecoes_novas:
            del excecoes_novas[chave]

        partes = []
        if papel_mudou:
            partes.append(f"papel → {PAPEL_LABEL[papel_novo]}")
        if turno_mudou:
            partes.append(f"turno → {TURNO_LABEL[turno_novo]}")
        mudou[usuario] = ", ".join(partes)

    return excecoes_novas, mudou, eventos_log


# ---------------------------------------------------------------------------
# Interface Streamlit
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Editor de Funcionários", layout="wide")
    st.title("Editor de Funcionários")
    st.caption("Clique na célula 'Papel' pra trocar. Depois clique em Salvar.")

    with st.expander("ℹ️ O que significa cada papel?"):
        st.markdown("""
- **Separador** — automático, quem bipa em endereço altura `00` (chão, picking). Entra no ranking e na meta.
- **Conferente** — cargo que confere separação. Sai do ranking, mas continua contando no Total Separado.
- **Analista** — cargo de análise, às vezes faz movimentação sistêmica. Sai do ranking.
- **Operador** — **cargo real** de quem opera empilhadeira (altura ≥ 01), mesmo quando bipa em altura `00`
  fazendo hora extra. Sai do ranking de Separador. **Não confundir** com o box "Operadores" do painel
  principal, que é 100% automático por endereço — esse aqui é o cadastro manual do cargo da pessoa.
- **Inativo** — pessoa desligada ou parada há muito tempo. Sai do ranking, mas o histórico continua contando.
        """)

    if "tabela_original" not in st.session_state:
        st.session_state.tabela_original = montar_tabela_funcionarios()

    tabela_original = st.session_state.tabela_original

    busca = st.text_input("🔍 Buscar por usuário", "")
    tabela_exibida = tabela_original
    if busca:
        tabela_exibida = tabela_original[
            tabela_original["Usuário"].str.contains(busca, case=False, na=False)
        ]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total de funcionários", len(tabela_original))
    col2.metric("Separadores", (tabela_original["Papel"] == "separador").sum())
    col3.metric("Conferentes/Analistas", tabela_original["Papel"].isin(["conferente", "analista"]).sum())
    col4.metric("Inativos", (tabela_original["Papel"] == "inativo").sum())

    st.markdown("---")

    tabela_editada = st.data_editor(
        tabela_exibida,
        column_config={
            "Papel": st.column_config.SelectboxColumn(
                "Papel",
                options=PAPEIS,
                required=True,
                help="'Operador' aqui = CARGO real da pessoa (ela opera empilhadeira, mas às vezes bipa em "
                     "altura 00 fazendo hora extra). Diferente do box 'Operadores' do painel, que é só endereço.",
            ),
            "Turno": st.column_config.SelectboxColumn(
                "Turno",
                options=TURNOS,
                required=True,
                help="Automático por padrão (inferido pelo horário da 1ª tarefa do dia). Só mude se estiver errado.",
            ),
            "Usuário": st.column_config.TextColumn("Usuário", disabled=True),
            "Caixas (histórico)": st.column_config.NumberColumn("Caixas (histórico)", disabled=True),
            "Última atividade": st.column_config.TextColumn("Última atividade", disabled=True),
            "Dias parado": st.column_config.NumberColumn("Dias parado", disabled=True),
        },
        hide_index=True,
        use_container_width=True,
        key="editor_tabela",
    )

    if st.button("💾 Salvar alterações", type="primary"):
        excecoes_novas, mudancas, eventos_log = calcular_diferencas(tabela_original, tabela_editada)
        if not mudancas:
            st.info("Nenhuma alteração detectada.")
        else:
            salvar_excecoes(excecoes_novas)
            for usuario, campo, valor_anterior, valor_novo in eventos_log:
                registrar_log(usuario, campo, valor_anterior, valor_novo)
            st.success(f"{len(mudancas)} alteração(ões) salva(s):")
            for usuario, acao in mudancas.items():
                st.write(f"- **{usuario}**: {acao}")
            st.session_state.tabela_original = montar_tabela_funcionarios()
            st.warning("Agora rode `python gerar_painel_html.py` pra atualizar o painel.")
            st.rerun()

    st.markdown("---")
    with st.expander("📋 Histórico de alterações", expanded=False):
        log = carregar_log(limite=200)
        if log.empty:
            st.caption("Nenhuma alteração registrada ainda.")
        else:
            busca_log = st.text_input("Buscar no histórico por usuário", "", key="busca_log")
            log_exibido = log
            if busca_log:
                log_exibido = log[log["usuario"].str.contains(busca_log, case=False, na=False)]
            st.dataframe(
                log_exibido.rename(columns={
                    "timestamp": "Quando",
                    "usuario": "Usuário",
                    "campo": "Campo",
                    "valor_anterior": "Valor anterior",
                    "valor_novo": "Valor novo",
                }),
                hide_index=True,
                use_container_width=True,
            )


if __name__ == "__main__":
    main()