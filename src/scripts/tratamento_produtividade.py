# -*- coding: utf-8 -*-
"""
tratamento_produtividade.py

Le a extracao diaria de separacao (.xls/.xlsx), trata os dados e concatena
na base historica mestre (Parquet). E o primeiro estagio do pipeline:

    extracao do dia (.xls)
        -> tratamento_produtividade.py   <- este script
        -> historico_separacao.parquet   (base mestre, cresce todo dia)
        -> [depois] gerar_painel_produtividade.py -> XLSX + HTML

Uso:
    python tratamento_produtividade.py caminho/para/extracao_01_08_2026.xls

Ou, sem argumento, ele procura o .xls mais recente na pasta ./extracoes
"""

from __future__ import annotations

import sys
import re
import io
from pathlib import Path
from datetime import datetime, time

import pandas as pd

VERSAO_SCRIPT = "2026-08-18-v10"  # confira essa linha pra saber se esta com a versao mais recente

# ---------------------------------------------------------------------------
# CONFIGURACAO
# ---------------------------------------------------------------------------

# Caminhos relativos a pasta onde o script esta (funciona em qualquer PC/pasta
# sem precisar editar caminho absoluto do Windows). Se preferir apontar pra
# uma pasta fixa, use raw string: r"C:\Users\...\Extracoes" (o "r" na frente
# evita o erro de unicode escape com \U, \A etc do Windows).
PASTA_SCRIPT = Path(__file__).resolve().parent.parent.parent
PASTA_EXTRACOES = PASTA_SCRIPT / "extracoes"
BASE_MESTRE = PASTA_SCRIPT / "base" / "historico_separacao.csv"
CADASTRO_SEPARADORES = PASTA_SCRIPT / "base" / "cadastro_separadores.json"

META_CAIXAS = 1500

# Janelas de turno e refeicao (usadas para inferir turno e para nao confundir
# pausa de almoco/janta com "tempo morto" entre tarefas)
TURNOS = {
    "turno_1": (time(7, 0), time(15, 30)),
    "turno_2": (time(15, 0), time(23, 10)),
}
ALMOCO = (time(11, 30), time(12, 30))
JANTA = (time(20, 0), time(21, 0))

# Colunas esperadas na extracao (nomes exatamente como vem no .xls)
COL_PRODUTO = "Cód. Produto"
COL_QTD = "Qtd. Movimentada"
COL_TAREFA = "Tarefa"
COL_DT_INI = "Data Hora Inicial"
COL_DT_FIM = "Data Hora Final"
COL_ENDERECO_ORIGEM = "Descr. Endereço Origem"
COL_USUARIO = "Usuário"
COL_LOTE = "Lote"


# ---------------------------------------------------------------------------
# LEITURA
# ---------------------------------------------------------------------------

def localizar_extracao_mais_recente(pasta: Path) -> Path:
    """Se nenhum arquivo for passado por parametro, pega o .xls/.xlsx mais
    recente da pasta de extracoes (mesmo padrao que voce ja usa nos outros
    scripts com .bat)."""
    candidatos = sorted(
        [*pasta.glob("*.xls"), *pasta.glob("*.xlsx")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidatos:
        raise FileNotFoundError(f"Nenhuma extracao encontrada em {pasta.resolve()}")
    return candidatos[0]


def _detectar_linha_cabecalho(df_sem_header: pd.DataFrame) -> int:
    """Alguns exports trazem linhas de metadado antes do cabecalho real
    (ex: linha 1 'arquivo', linha 2 'Emissão: ... Total de registros: ...',
    e só na linha 3 vem 'Cód. Produto | Qtd. Movimentada | ...').
    Procura a primeira linha que contenha o nome de uma coluna-chave."""
    for i, row in df_sem_header.iterrows():
        valores = [str(v).strip() for v in row.tolist()]
        if any("Cód. Produto" in v or "Cod. Produto" in v for v in valores):
            return i
    return 0  # fallback: assume que a primeira linha ja e o cabecalho


def _com_header_detectado(df_bruto: pd.DataFrame) -> pd.DataFrame:
    """Se as colunas ja vierem certas (ex: HTML com <th>, pandas ja
    detectou sozinho), nao mexe. Caso contrario, procura a linha real do
    cabecalho (pode ter metadado antes) e promove ela a cabecalho."""
    colunas_atuais = [str(c) for c in df_bruto.columns]
    if COL_PRODUTO in colunas_atuais and COL_USUARIO in colunas_atuais:
        return df_bruto

    linha_header = _detectar_linha_cabecalho(df_bruto)
    novo = df_bruto.iloc[linha_header + 1:].copy()
    novo.columns = df_bruto.iloc[linha_header].tolist()
    return novo.reset_index(drop=True)


def ler_extracao(caminho: Path) -> pd.DataFrame:
    """Le o .xls/.xlsx com fallback de estrategia, no mesmo espirito do
    carregamento multi-estrategia que voce ja usa no faturamento.

    IMPORTANTE 1: varios ERPs (ERP/WMS entre eles) exportam ".xls" que na
    verdade e uma tabela HTML disfarcada de Excel. Nesse caso xlrd/openpyxl
    falham ("not a zip file"), e o jeito certo de ler e com pd.read_html.

    IMPORTANTE 2: o export tambem pode trazer linhas de metadado (nome do
    arquivo, data de emissao, total de registros) ANTES do cabecalho real
    das colunas -- por isso lemos sempre sem header primeiro e detectamos
    em qual linha o cabecalho de verdade comeca."""
    erros = []

    # 1) tenta como Excel binario/OOXML de verdade
    for engine in ("xlrd", "openpyxl", "calamine"):
        try:
            bruto = pd.read_excel(caminho, engine=engine, dtype=str, header=None)
            return _com_header_detectado(bruto)
        except Exception as e:  # noqa: BLE001
            erros.append(f"{engine}: {e}")

    # 2) fallback: .xls que na verdade e HTML (comum em export de ERP)
    # le os bytes brutos e decodifica manualmente antes de passar pro
    # read_html -- evita um bug de encoding do pandas/lxml no Windows quando
    # se passa o parametro "encoding" direto pra read_html com caminho
    # contendo acentos/espacos (ex: 'Área de Trabalho')
    try:
        bytes_arquivo = caminho.read_bytes()
    except Exception as e:  # noqa: BLE001
        erros.append(f"leitura de bytes: {e}")
        bytes_arquivo = None

    if bytes_arquivo is not None:
        for encoding in ("latin-1", "cp1252", "utf-8"):
            try:
                texto = bytes_arquivo.decode(encoding, errors="strict")
            except UnicodeDecodeError as e:
                erros.append(f"decode ({encoding}): {e}")
                continue
            try:
                tabelas = pd.read_html(io.StringIO(texto), header=None)
                maior = max(tabelas, key=len).astype(str)
                maior = _com_header_detectado(maior)
                if COL_PRODUTO in maior.columns and COL_USUARIO in maior.columns:
                    return maior
                erros.append(f"read_html ({encoding}): colunas nao bateram (acentos provavelmente incorretos)")
            except Exception as e:  # noqa: BLE001
                erros.append(f"read_html ({encoding}): {e}")

    raise RuntimeError(
        "Nao consegui ler o arquivo com nenhuma estrategia disponivel.\n"
        + "\n".join(erros)
    )


# ---------------------------------------------------------------------------
# NORMALIZACAO
# ---------------------------------------------------------------------------

def classificar_funcao(altura: str | None) -> str:
    """Os 2 ultimos digitos do endereco (altura) definem a funcao de quem
    mexeu naquela posicao:
      - '00'        -> separador (chao, picking) -> entra na meta/produtividade
      - '01' pra cima -> operador (empilhadeira, nivel alto) -> fora da meta
    """
    if altura is None:
        return "desconhecido"
    try:
        return "separador" if int(altura) == 0 else "operador"
    except ValueError:
        return "desconhecido"


def classificar_operacao(galpao: str | None) -> str:
    """O PRIMEIRO bloco do endereco (galpao) define nacional vs exportacao:
      - '01' -> nacional
      - '04' -> exportacao
      - qualquer outro -> outro (nao classificado ainda)
    """
    if galpao is None:
        return "desconhecido"
    mapa = {"1": "nacional", "4": "exportacao"}
    try:
        return mapa.get(str(int(galpao)), "outro")
    except ValueError:
        return "desconhecido"


def normalizar_endereco(descr: str) -> dict:
    """Quebra '01.13.15.00' em galpao/rua/local/altura.
    Retorna dict com os 4 campos, ou None quando o padrao nao bate
    (extracao pode trazer endereco de doca junto por engano, por exemplo)."""
    if not isinstance(descr, str):
        return {"galpao": None, "rua": None, "local": None, "altura": None}

    partes = re.findall(r"\d+", descr)
    if len(partes) != 4:
        return {"galpao": None, "rua": None, "local": None, "altura": None}

    galpao, rua, local, altura = partes
    return {"galpao": galpao, "rua": rua, "local": local, "altura": altura}


def parse_data_hora_determinístico(serie: pd.Series) -> pd.Series:
    """Extrai dia/mes/ano/hora/min/seg via regex e monta a data manualmente,
    componente por componente.

    Por que nao usar so pd.to_datetime(..., dayfirst=True): em colunas
    grandes (aqui sao ~730 mil linhas), o pandas pode inferir um UNICO
    formato pra coluna inteira a partir de uma amostra, e essa inferencia
    as vezes ignora dayfirst silenciosamente -- fazendo '01/05/2026'
    (1 de maio) virar 5 de janeiro sem gerar erro nenhum. Extraindo os
    componentes manualmente essa ambiguidade nao existe: o grupo do regex
    SEMPRE e tratado como dia (ou ano), nao importa o que o pandas "acha".

    Suporta os dois formatos que podem aparecer dependendo de como o Excel
    guarda a celula:
      - BR:  DD/MM/AAAA HH:MM:SS   (celula texto, ou export via HTML)
      - ISO: AAAA-MM-DD HH:MM:SS   (celula com tipo Data nativo do Excel,
             que ao virar string via python usa formato internacional)
    Cada linha e testada contra os dois padroes; nao ha inferencia nem
    prioridade ambigua -- cada padrao so casa com um formato exato."""
    texto = serie.astype(str).str.strip()

    padrao_br = r"^(\d{1,2})/(\d{1,2})/(\d{4})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$"
    padrao_iso = r"^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$"

    partes_br = texto.str.extract(padrao_br)
    partes_br.columns = ["dia", "mes", "ano", "hora", "minuto", "segundo"]

    partes_iso = texto.str.extract(padrao_iso)
    partes_iso.columns = ["ano", "mes", "dia", "hora", "minuto", "segundo"]

    # usa BR onde bateu; onde nao bateu, tenta ISO; onde nenhum bateu, fica NaN
    combinado = partes_br.combine_first(partes_iso)
    combinado["segundo"] = combinado["segundo"].fillna("0")

    componentes = combinado.apply(pd.to_numeric, errors="coerce")

    return pd.to_datetime(
        {
            "year": componentes["ano"],
            "month": componentes["mes"],
            "day": componentes["dia"],
            "hour": componentes["hora"],
            "minute": componentes["minuto"],
            "second": componentes["segundo"],
        },
        errors="coerce",
    )


def tratar(df: pd.DataFrame, data_extracao: str) -> pd.DataFrame:
    """Aplica toda a normalizacao linha a linha (antes do agrupamento por
    tarefa, que fica em outra funcao)."""
    df = df.copy()

    # --- limpeza do cabecalho -----------------------------------------------
    # alguns exports de ERP trazem os nomes de coluna com espacos duplicados,
    # espaco nao-quebravel (\xa0) ou espaco nas pontas, o que quebra o
    # casamento exato com os nomes esperados (ex: "Qtd. Movimentada").
    df.columns = [
        re.sub(r"\s+", " ", str(c).replace("\xa0", " ")).strip()
        for c in df.columns
    ]

    # --- tipos e limpeza basica -------------------------------------------------
    df[COL_QTD] = pd.to_numeric(df[COL_QTD], errors="coerce")

    # Lote: sempre string, sem espaco, maiusculo -> evita chave quebrada por
    # causa de formatacao (mesmo principio do bug cod_cidade que voce ja resolveu)
    df[COL_LOTE] = df[COL_LOTE].astype(str).str.strip().str.upper()
    df[COL_PRODUTO] = df[COL_PRODUTO].astype(str).str.strip()
    df[COL_TAREFA] = df[COL_TAREFA].astype(str).str.strip()
    df[COL_USUARIO] = df[COL_USUARIO].astype(str).str.strip().str.lower()

    # Datas: extracao deterministica dia/mes/ano/hora/min/seg via regex (ver
    # docstring de parse_data_hora_determinístico) -- SEM fallback flexivel.
    # Um fallback com dayfirst=True reintroduziria o bug de ambiguidade;
    # melhor a linha virar NaT (e ser reportada) do que ter uma data errada
    # silenciosa.
    for col in (COL_DT_INI, COL_DT_FIM):
        bruto = df[col].astype(str).str.strip()
        parseado = parse_data_hora_determinístico(df[col])

        n_invalidas = (parseado.isna() & bruto.ne("nan") & bruto.ne("")).sum()
        if n_invalidas:
            exemplos = bruto[parseado.isna() & bruto.ne("nan") & bruto.ne("")].unique()[:5]
            print(
                f"[aviso] {n_invalidas} valor(es) de '{col}' fora dos formatos "
                f"aceitos (DD/MM/AAAA ou AAAA-MM-DD, HH:MM:SS) viraram vazio. Exemplos: {list(exemplos)}"
            )

        df[col] = parseado

    # Data Hora Final costuma vir de celula mesclada no Excel de origem: so a
    # primeira linha do bloco da tarefa carrega o valor, as demais ficam em
    # branco/NaN. Propaga o valor pra todas as linhas da mesma tarefa
    # (ffill + bfill cobre o valor estar em qualquer posicao do bloco).
    df[COL_DT_FIM] = df.groupby(COL_TAREFA)[COL_DT_FIM].transform(
        lambda s: s.ffill().bfill()
    )

    # --- endereco de origem: separa por altura -----------------------------
    # altura '00' = separador (chao, picking) | altura '01' pra cima = operador
    # (empilhadeira, nivel alto). So separador entra no calculo de meta/produtividade.
    endereco = df[COL_ENDERECO_ORIGEM].apply(normalizar_endereco).apply(pd.Series)
    df = pd.concat([df, endereco], axis=1)
    df["funcao"] = df["altura"].apply(classificar_funcao)
    df["operacao"] = df["galpao"].apply(classificar_operacao)

    # --- chave composta (deduplicacao) ------------------------------------------
    # Tarefa + Produto + Lote + Usuario: cobre o caso de mesmo produto/tarefa
    # com lotes diferentes (ex: 3108 lote R321... e 3108 lote R222... na mesma tarefa).
    #
    # BUG 1 (corrigido): Lote vazio fazia varias linhas legitimas colidirem
    # na mesma chave e serem descartadas como duplicata.
    #
    # BUG 2 (corrigido): checar so por string vazia ("") nao pega a string
    # literal "nan" que o pandas as vezes gera.
    #
    # BUG 3 (o mais grave, corrigido agora): quando o Lote e um NaN de
    # verdade (float, nao string), a CONCATENACAO "Tarefa|Produto|Lote|Usuario"
    # produz uma chave INTEIRAMENTE NaN pra linha inteira -- e uma chave NaN
    # nunca "bate" com nada no .isin() usado pra deduplicar, entao TODA vez
    # que o arquivo for reprocessado essas linhas sao tratadas como novas e
    # duplicam de novo (silenciosamente, sem erro nenhum). Por isso o
    # primeiro teste "deu certo por acaso" mas ia inflar a base com o tempo.
    #
    # Fix definitivo: usa pd.isna() na coluna ORIGINAL (antes de qualquer
    # astype(str), que pode ou nao converter NaN em string dependendo da
    # versao do pandas) + fillna de seguranca no final, garantindo que
    # NENHUM NaN sobrevive ate a concatenacao da chave.
    lote_bruto = df[COL_LOTE]
    lote_vazio = lote_bruto.isna() | (
        lote_bruto.astype(str).str.strip().str.lower().isin(["", "nan", "none", "nat"])
    )
    lote_normalizado = lote_bruto.astype(str).str.strip()
    horario_como_texto = df[COL_DT_INI].astype(str)

    lote_ou_horario = lote_normalizado.where(~lote_vazio, horario_como_texto)
    # rede de seguranca final: se AINDA sobrou NaN (ex: Data Hora Inicial
    # tambem vazia), usa o indice da linha -- garante que a chave NUNCA
    # fica NaN, doa a quem doer (pior caso e desligar a deduplicacao so
    # dessa linha especifica, nao silenciosamente de um lote inteiro)
    fallback_indice = pd.Series(
        ["SEMDADO_" + str(i) for i in df.index], index=df.index
    )
    lote_ou_horario = lote_ou_horario.fillna(fallback_indice)

    df["chave"] = (
        df[COL_TAREFA] + "|" + df[COL_PRODUTO] + "|" + lote_ou_horario + "|" + df[COL_USUARIO]
    )

    df["data_extracao"] = data_extracao

    return df


# ---------------------------------------------------------------------------
# AGREGACAO POR TAREFA
# ---------------------------------------------------------------------------

def inferir_turno(hora_inicio: time) -> str:
    """Classifica pelo horario de inicio da tarefa. Nao decide sozinho o
    cadastro definitivo do usuario -- isso fica a cargo da tela de
    confirmacao -- mas serve de sugestao automatica.

    As janelas de turno 1 (07:00-15:30) e turno 2 (15:00-23:10) se sobrepoem
    entre 15:00 e 15:30 (troca de turno). Nessa faixa, o inicio da tarefa e
    mais provavelmente turno 2 batendo o ponto de entrada; por isso turno 2
    e checado primeiro."""
    ini2, fim2 = TURNOS["turno_2"]
    if ini2 <= hora_inicio <= fim2:
        return "turno_2"
    ini1, fim1 = TURNOS["turno_1"]
    if ini1 <= hora_inicio <= fim1:
        return "turno_1"
    # fora das janelas conhecidas (ex: hora extra) -> mais perto de qual turno
    return "turno_1" if hora_inicio < time(12, 0) else "turno_2"


def agrupar_por_tarefa(df: pd.DataFrame) -> pd.DataFrame:
    """Regra central do projeto:
    - Data Hora Inicial varia por item -> usamos o MIN por tarefa (quando o
      separador comecou a mexer na tarefa)
    - Data Hora Final e igual em todas as linhas da tarefa (fim da tarefa
      inteira, nao do item) -> usamos o primeiro valor (max ou first tanto faz,
      ja vem repetido)
    - Caixas da tarefa = soma de Qtd. Movimentada
    """
    agg = (
        df.groupby([COL_TAREFA, COL_USUARIO, "data_extracao"], as_index=False)
        .agg(
            caixas=(COL_QTD, "sum"),
            inicio=(COL_DT_INI, "min"),
            fim=(COL_DT_FIM, "max"),
            rua=("rua", lambda s: sorted(set(s.dropna()))),
        )
    )

    agg["tempo_horas"] = (
        (agg["fim"] - agg["inicio"]).dt.total_seconds() / 3600
    ).round(2)

    # tarefas com tempo zerado/negativo (erro de exportacao) nao entram no cx/h
    agg["cx_por_hora"] = agg.apply(
        lambda r: round(r["caixas"] / r["tempo_horas"], 1)
        if r["tempo_horas"] and r["tempo_horas"] > 0
        else None,
        axis=1,
    )

    agg["turno_sugerido"] = agg["inicio"].apply(
        lambda dt: inferir_turno(dt.time()) if pd.notna(dt) else None
    )

    return agg.rename(columns={COL_TAREFA: "tarefa", COL_USUARIO: "usuario"})


# ---------------------------------------------------------------------------
# BASE MESTRE (historico) + DEDUPLICACAO
# ---------------------------------------------------------------------------

def concatenar_na_base_mestre(df_tratado: pd.DataFrame, data_extracao: str) -> pd.DataFrame:
    """Le a base mestre existente (se houver), remove o que ja existe
    GLOBALMENTE (por chave, em qualquer data_extracao anterior), e concatena
    so as linhas realmente novas. Protege tanto contra rodar o script 2x no
    mesmo dia quanto contra o export trazer o historico completo toda vez
    (comum em dump de ERP sem filtro incremental)."""
    BASE_MESTRE.parent.mkdir(parents=True, exist_ok=True)

    if BASE_MESTRE.exists():
        base = pd.read_csv(BASE_MESTRE, dtype=str, encoding="utf-8-sig")
        # se a base existente tem estrutura antiga/incompativel (colunas
        # faltando), avisa e comeca uma base nova em vez de quebrar
        colunas_essenciais = {COL_DT_INI, COL_DT_FIM, "chave", "data_extracao"}
        if not colunas_essenciais.issubset(set(base.columns)):
            print(
                f"[aviso] base mestre existente em {BASE_MESTRE} tem estrutura "
                "antiga/incompativel. Fazendo backup e comecando uma base nova."
            )
            backup = BASE_MESTRE.with_suffix(".bak.csv")
            BASE_MESTRE.rename(backup)
            base = pd.DataFrame(columns=df_tratado.columns)
        else:
            for col in (COL_DT_INI, COL_DT_FIM):
                base[col] = pd.to_datetime(base[col], errors="coerce")
    else:
        base = pd.DataFrame(columns=df_tratado.columns)

    # Deduplicacao GLOBAL por chave, nao so dentro do mesmo data_extracao.
    # Isso importa porque seu export costuma trazer o HISTORICO INTEIRO toda
    # vez (nao so o dia atual) -- se comparasse so contra o mesmo dia de
    # execucao, cada rodada duplicaria todo o historico de novo.
    chaves_existentes = set(base["chave"])
    novas = df_tratado[~df_tratado["chave"].isin(chaves_existentes)]

    base_atualizada = pd.concat([base, novas], ignore_index=True)
    base_atualizada.to_csv(BASE_MESTRE, index=False, encoding="utf-8-sig")

    print(
        f"[base mestre] {len(novas)} linha(s) nova(s) adicionada(s) "
        f"({len(df_tratado) - len(novas)} ja existiam e foram ignoradas)."
    )
    return base_atualizada


# ---------------------------------------------------------------------------
# ORQUESTRACAO
# ---------------------------------------------------------------------------

def main():
    print(f"[versao] {VERSAO_SCRIPT}")
    if len(sys.argv) > 1:
        caminho = Path(sys.argv[1])
    else:
        caminho = localizar_extracao_mais_recente(PASTA_EXTRACOES)

    print(f"[leitura] {caminho.name}")
    df_bruto = ler_extracao(caminho)
    print(f"[colunas encontradas] {list(df_bruto.columns)}")

    # data_extracao = data de hoje (ou extraia da 1a linha de Data Hora Inicial,
    # se preferir amarrar ao dia real da separacao em vez do dia que voce rodou o script)
    data_extracao = datetime.now().strftime("%Y-%m-%d")

    df_item = tratar(df_bruto, data_extracao)
    df_tarefa = agrupar_por_tarefa(df_item)

    # a chave de deduplicacao e por linha-item (Tarefa+Produto+Lote+Usuario);
    # guardamos o item tratado na base mestre (granularidade fina), e o
    # agrupamento por tarefa e feito sob demanda na hora de montar o painel
    concatenar_na_base_mestre(df_item, data_extracao)

    print("\nResumo do processamento:")
    print(f"  tarefas processadas: {len(df_tarefa)}")
    print(f"  usuarios distintos:  {df_tarefa['usuario'].nunique()}")
    n_sem_tempo = df_tarefa["tempo_horas"].isna().sum()
    print(f"  tarefas sem tempo calculado (NaN): {n_sem_tempo}")
    print(f"  linhas por funcao: {df_item['funcao'].value_counts().to_dict()}")
    print(f"  linhas por operacao: {df_item['operacao'].value_counts().to_dict()}")

    print("\nAmostra (10 primeiras tarefas):")
    print(
        df_tarefa[
            ["tarefa", "usuario", "caixas", "tempo_horas", "cx_por_hora", "turno_sugerido"]
        ].head(10).to_string(index=False)
    )

    if n_sem_tempo:
        print(
            f"\n[aviso] {n_sem_tempo} tarefa(s) ficaram sem tempo_horas calculado "
            "(Data Hora Inicial ou Final nao bateu no formato esperado)."
        )


if __name__ == "__main__":
    main()