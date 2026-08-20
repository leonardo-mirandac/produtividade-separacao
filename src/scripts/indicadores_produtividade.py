# -*- coding: utf-8 -*-
"""
indicadores_produtividade.py

Le a base historica ja tratada (base/historico_separacao.csv, gerada pelo
tratamento_produtividade.py) e calcula os indicadores por separador/dia:

    - caixas separadas
    - hr produtiva      (soma do tempo_horas das tarefas do dia)
    - hr improdutiva    (HR_TRABALHADA - hr produtiva, pode ficar negativo)
    - media             (hr produtiva / caixas)
    - % da meta         (caixas / meta do periodo)
    - classificacao     (vermelho / amarelo / verde / estrela)

Depois agrega por Hoje / Mes atual / Ultimos 3 meses, pronto pra alimentar
o painel HTML.

Uso:
    python indicadores_produtividade.py
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, date, time

import pandas as pd

PASTA_SCRIPT = Path(__file__).resolve().parent.parent.parent
BASE_MESTRE = PASTA_SCRIPT / "base" / "historico_separacao.csv"
ARQUIVO_EXCECOES = PASTA_SCRIPT / "base" / "excecoes_funcionarios.json"

META_DIARIA = 1500
HR_TRABALHADA = 7 + 20 / 60  # 7:20, fixo pra todo mundo (turno 1 ou 2)

# Fim do horario NORMAL de cada turno (depois disso, o que for bipado conta
# como hora extra produtiva). Turno 1 normal ate 15:20, turno 2 ate 23:20 --
# ambos podem estourar (18:00 e 04:00 do dia seguinte respectivamente), mas
# pra fins de HE produtiva contamos tudo que passar do fim normal.
TURNO_FIM_NORMAL = {"turno_1": time(15, 20), "turno_2": time(23, 20)}
TURNO_INICIO_JANELA = {"turno_1": time(7, 0), "turno_2": time(15, 0)}


def carregar_excecoes() -> dict:
    """Le o cadastro de excecoes (papel + turno definidos manualmente pelo
    editor_funcionarios.py). Quem nao tem excecao usa 100% o automatico."""
    if ARQUIVO_EXCECOES.exists():
        return json.loads(ARQUIVO_EXCECOES.read_text(encoding="utf-8"))
    return {}


def inferir_turno_tarefa(hora_inicio: time) -> str:
    """Classifica uma tarefa individual pelo horario de inicio. Usado tanto
    pra sugerir automaticamente o turno de alguem (moda das tarefas) quanto
    como fallback quando a pessoa nao tem turno definido no cadastro.

    As janelas se sobrepoem entre 15:00-15:20 (troca de turno); nesse caso
    turno 2 tem prioridade, pois e mais provavel ser alguem batendo entrada."""
    ini2 = TURNO_INICIO_JANELA["turno_2"]
    if hora_inicio >= ini2 or hora_inicio < time(4, 0):
        return "turno_2"
    return "turno_1"


def determinar_turno_pessoa(usuario: str, tarefas_pessoa: pd.DataFrame, excecoes: dict) -> str:
    """Turno 'oficial' da pessoa: usa o que foi definido manualmente no
    cadastro (excecoes) se existir; senao, infere pelo horario da PRIMEIRA
    tarefa de cada dia (nao pela moda de todas as tarefas -- isso evitaria
    que dias com muita hora extra 'puxassem' a pessoa pro turno errado,
    ja que a maioria das tarefas dela naquele dia ficaria depois das 15h)."""
    excecao = excecoes.get(usuario.lower())
    if excecao and excecao.get("turno"):
        return excecao["turno"]

    if tarefas_pessoa.empty or "dia" not in tarefas_pessoa.columns:
        return "turno_1"

    primeiro_horario_por_dia = tarefas_pessoa.dropna(subset=["inicio"]).groupby("dia")["inicio"].min()
    if primeiro_horario_por_dia.empty:
        return "turno_1"

    turnos = primeiro_horario_por_dia.apply(lambda dt: "turno_1" if dt.time() < time(12, 0) else "turno_2")
    return turnos.mode().iat[0]


def classificar_normal_ou_extra(hora_inicio: time, turno_pessoa: str) -> str:
    """Pra uma tarefa de alguem com turno JA DEFINIDO (o turno da pessoa,
    nao o inferido tarefa a tarefa): 'normal' se comecou dentro do horario
    normal do turno dela, 'extra' se comecou depois do fim normal.

    Turno 2 cruza a meia-noite (23:20 -> 04:00 do dia seguinte), entao o
    horario de 00:00 as 03:59 tambem conta como extra do turno 2."""
    fim_normal = TURNO_FIM_NORMAL[turno_pessoa]
    if turno_pessoa == "turno_2":
        # extra = depois das 23:20 OU de madrugada (00:00-03:59)
        if hora_inicio >= fim_normal or hora_inicio < time(4, 0):
            return "extra"
        return "normal"
    else:
        return "extra" if hora_inicio >= fim_normal else "normal"


COL_TAREFA = "Tarefa"
COL_USUARIO = "Usuário"
COL_QTD = "Qtd. Movimentada"
COL_DT_INI = "Data Hora Inicial"
COL_DT_FIM = "Data Hora Final"
COL_FUNCAO = "funcao"
COL_OPERACAO = "operacao"


def classificar(caixas: float) -> str:
    """Vermelho < 500 | Amarelo 500-1499 | Verde = 1500 | Estrela >= 1501.
    Faixa fechada, sem buraco entre os limites."""
    if caixas < 500:
        return "vermelho"
    if caixas < META_DIARIA:
        return "amarelo"
    if caixas == META_DIARIA:
        return "verde"
    return "estrela"


def aplicar_trava_operador(df: pd.DataFrame) -> pd.DataFrame:
    """Trava por PESSOA, nao por linha: quem ja apareceu alguma vez
    movimentando altura '01' pra cima (funcao=='operador') e operador
    SEMPRE -- inclusive nas tarefas dele em altura '00'. Na pratica: o
    operador tambem movimenta chao as vezes, mas continua sendo tarefa
    dele, nao vira separador so porque bipou num endereco baixo naquele
    momento. Sem essa trava, a mesma pessoa apareceria fatiada entre as
    duas listas."""
    if COL_FUNCAO not in df.columns or COL_USUARIO not in df.columns:
        return df

    usuarios_operadores = set(
        df.loc[df[COL_FUNCAO] == "operador", COL_USUARIO].str.lower().unique()
    )
    if not usuarios_operadores:
        return df

    mask = df[COL_USUARIO].str.lower().isin(usuarios_operadores)
    n_promovidas = int((mask & (df[COL_FUNCAO] != "operador")).sum())
    df.loc[mask, COL_FUNCAO] = "operador"

    if n_promovidas:
        print(
            f"[trava operador] {n_promovidas} linha(s) em altura 00 de "
            f"{len(usuarios_operadores)} operador(es) foram reclassificadas "
            "como operador (a pessoa ja opera empilhadeira em outro momento)."
        )
    return df


def carregar_base(papel: str = "separador") -> pd.DataFrame:
    """papel='separador' (padrao, altura=='00' E a pessoa NUNCA operou
    empilhadeira, tem meta de 1500cx) ou papel='operador' (a pessoa opera
    empilhadeira -- toda tarefa dela conta aqui, mesmo em altura '00')."""
    if not BASE_MESTRE.exists():
        raise FileNotFoundError(
            f"Base mestre nao encontrada em {BASE_MESTRE}. "
            "Rode primeiro o tratamento_produtividade.py."
        )
    df = pd.read_csv(BASE_MESTRE, dtype=str, encoding="utf-8-sig")
    df[COL_QTD] = pd.to_numeric(df[COL_QTD], errors="coerce")
    df[COL_DT_INI] = pd.to_datetime(df[COL_DT_INI], errors="coerce")
    df[COL_DT_FIM] = pd.to_datetime(df[COL_DT_FIM], errors="coerce")

    df = aplicar_trava_operador(df)

    if COL_FUNCAO in df.columns:
        n_antes = len(df)
        df = df[df[COL_FUNCAO] == papel].copy()
        print(f"[filtro] {n_antes - len(df)} linha(s) fora de '{papel}' excluidas do calculo.")
    else:
        print("[aviso] coluna 'funcao' nao encontrada na base -- rode o tratamento_produtividade.py atualizado pra gerar essa classificacao.")

    return df


def agrupar_por_tarefa(df: pd.DataFrame) -> pd.DataFrame:
    """Mesma logica do tratamento_produtividade: soma caixas, pega o
    inicio minimo e o fim maximo por tarefa."""
    tem_operacao = COL_OPERACAO in df.columns
    agg_dict = {
        "caixas": (COL_QTD, "sum"),
        "inicio": (COL_DT_INI, "min"),
        "fim": (COL_DT_FIM, "max"),
    }
    if tem_operacao:
        # uma tarefa deveria ter um unico galpao/operacao; se por algum
        # motivo vier misturado, pega o mais frequente pra nao quebrar
        agg_dict["operacao"] = (COL_OPERACAO, lambda s: s.mode().iat[0] if not s.mode().empty else "desconhecido")

    agg = (
        df.groupby([COL_TAREFA, COL_USUARIO], as_index=False)
        .agg(**agg_dict)
    )
    agg["tempo_horas"] = (
        (agg["fim"] - agg["inicio"]).dt.total_seconds() / 3600
    ).clip(lower=0)

    # "dia produtivo" (regra de virada de turno): tarefa que comeca entre
    # 00:00 e 03:59 conta como sendo do DIA ANTERIOR (turno 2 estourando
    # a noite). Truque: subtrai 4h do inicio antes de pegar a data --
    # 23:50 vira 19:50 do mesmo dia (nao muda), 02:20 do dia X vira 22:20
    # do dia X-1 (muda pro dia anterior corretamente).
    agg["dia"] = (agg["inicio"] - pd.Timedelta(hours=4)).dt.date

    # ---- turno da pessoa + hora normal vs extra ----------------------------
    excecoes = carregar_excecoes()
    turno_por_pessoa = {}
    for usuario, tarefas_pessoa in agg.groupby(COL_USUARIO):
        turno_por_pessoa[usuario] = determinar_turno_pessoa(usuario, tarefas_pessoa, excecoes)

    agg["turno_pessoa"] = agg[COL_USUARIO].map(turno_por_pessoa)
    agg["tipo_hora"] = agg.apply(
        lambda r: classificar_normal_ou_extra(r["inicio"].time(), r["turno_pessoa"])
        if pd.notna(r["inicio"]) else "normal",
        axis=1,
    )
    return agg


def indicadores_por_dia(df_tarefa: pd.DataFrame) -> pd.DataFrame:
    """Agrega tarefa -> dia/separador. E a granularidade base de tudo:
    o card de hoje, o calendario do mes e o resumo de 3 meses partem daqui."""
    tem_tipo_hora = "tipo_hora" in df_tarefa.columns
    if tem_tipo_hora:
        df_tarefa = df_tarefa.copy()
        df_tarefa["horas_extra_tmp"] = df_tarefa["tempo_horas"].where(df_tarefa["tipo_hora"] == "extra", 0.0)
        df_tarefa["horas_normal_tmp"] = df_tarefa["tempo_horas"].where(df_tarefa["tipo_hora"] == "normal", 0.0)

    agg_dict = dict(
        caixas=("caixas", "sum"),
        hr_produtiva=("tempo_horas", "sum"),
        n_tarefas=("tarefa" if "tarefa" in df_tarefa.columns else COL_TAREFA, "count"),
    )
    if tem_tipo_hora:
        agg_dict["hr_extra"] = ("horas_extra_tmp", "sum")
        agg_dict["hr_normal"] = ("horas_normal_tmp", "sum")
        agg_dict["turno_pessoa"] = ("turno_pessoa", "first")

    por_dia = df_tarefa.groupby([COL_USUARIO, "dia"], as_index=False).agg(**agg_dict)

    if not tem_tipo_hora:
        por_dia["hr_extra"] = 0.0
        por_dia["hr_normal"] = por_dia["hr_produtiva"]
        por_dia["turno_pessoa"] = None

    por_dia["hr_improdutiva"] = HR_TRABALHADA - por_dia["hr_produtiva"]  # pode ficar negativo, ok
    por_dia["media_cx_por_hora"] = (
        por_dia["caixas"] / por_dia["hr_produtiva"]
    ).replace([float("inf"), -float("inf")], None)
    por_dia["pct_meta"] = (por_dia["caixas"] / META_DIARIA * 100).round(1)
    por_dia["classificacao"] = por_dia["caixas"].apply(classificar)
    return por_dia.rename(columns={COL_USUARIO: "usuario"})


def dias_uteis_no_periodo(inicio: date, fim: date) -> int:
    """Conta dias uteis (segunda a sabado, folga so domingo) no intervalo,
    usado pra calcular a meta acumulada do mes/3 meses."""
    dias = pd.date_range(inicio, fim, freq="D")
    return int((dias.weekday != 6).sum())  # weekday 6 = domingo


def resumo_periodo(por_dia: pd.DataFrame, inicio: date, fim: date) -> pd.DataFrame:
    """Agrega os indicadores diarios num periodo (hoje/mes/3 meses) por
    separador, com a meta acumulada proporcional aos dias uteis do periodo."""
    filtro = (por_dia["dia"] >= inicio) & (por_dia["dia"] <= fim)
    recorte = por_dia.loc[filtro]

    meta_periodo = META_DIARIA * dias_uteis_no_periodo(inicio, fim)

    resumo = (
        recorte.groupby("usuario", as_index=False)
        .agg(
            caixas=("caixas", "sum"),
            hr_produtiva=("hr_produtiva", "sum"),
            hr_normal=("hr_normal", "sum"),
            hr_extra=("hr_extra", "sum"),
            hr_improdutiva=("hr_improdutiva", "sum"),
            dias_trabalhados=("dia", "nunique"),
            total_tarefas=("n_tarefas", "sum"),
        )
    )
    resumo["media_cx_por_hora"] = (
        resumo["caixas"] / resumo["hr_produtiva"]
    ).replace([float("inf"), -float("inf")], None).round(1)
    resumo["pct_meta"] = (resumo["caixas"] / meta_periodo * 100).round(1)
    resumo["meta_periodo"] = meta_periodo

    # dias abaixo da meta no periodo (classificacao vermelho/amarelo do dia)
    dias_ruins = (
        recorte[recorte["classificacao"].isin(["vermelho", "amarelo"])]
        .groupby("usuario")
        .size()
        .rename("dias_abaixo_meta")
    )
    resumo = resumo.merge(dias_ruins, on="usuario", how="left")
    resumo["dias_abaixo_meta"] = resumo["dias_abaixo_meta"].fillna(0).astype(int)

    return resumo.sort_values("caixas", ascending=False)


def main():
    df = carregar_base()
    df_tarefa = agrupar_por_tarefa(df)
    por_dia = indicadores_por_dia(df_tarefa)

    hoje_real = datetime.now().date()

    if por_dia.empty:
        print("[erro] nenhuma linha de separador (altura=00) encontrada na base apos os filtros. Nada a calcular.")
        return

    ultima_data_na_base = por_dia["dia"].max()

    if ultima_data_na_base < hoje_real:
        print(
            f"[aviso] a base nao tem nenhuma tarefa de hoje ({hoje_real}). "
            f"Usando a ultima data disponivel na base ({ultima_data_na_base}) "
            "como referencia 'hoje' so pra fins de conferencia. Quando voce "
            "rodar com a extracao do proprio dia, isso ajusta sozinho."
        )
    hoje = min(hoje_real, ultima_data_na_base) if pd.notna(ultima_data_na_base) else hoje_real

    inicio_mes = hoje.replace(day=1)
    inicio_3meses = (inicio_mes - pd.DateOffset(months=2)).date().replace(day=1)

    print(f"\n=== HOJE ({hoje}) ===")
    print(resumo_periodo(por_dia, hoje, hoje).to_string(index=False))

    print(f"\n=== MES ATUAL ({inicio_mes} a {hoje}) ===")
    print(resumo_periodo(por_dia, inicio_mes, hoje).to_string(index=False))

    print(f"\n=== ULTIMOS 3 MESES ({inicio_3meses} a {hoje}) ===")
    print(resumo_periodo(por_dia, inicio_3meses, hoje).to_string(index=False))

    # salva o detalhado por dia tambem, pra alimentar o calendario do mes
    saida = PASTA_SCRIPT / "base" / "indicadores_por_dia.csv"
    por_dia.to_csv(saida, index=False, encoding="utf-8-sig")
    print(f"\n[ok] indicadores por dia salvos em {saida}")


if __name__ == "__main__":
    main()