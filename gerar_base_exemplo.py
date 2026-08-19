# -*- coding: utf-8 -*-
"""
gerar_base_exemplo.py

Gera uma base 100% FICTÍCIA (nomes genéricos, números aleatórios) no
mesmo formato esperado pelo pipeline (base/historico_separacao.csv),
só para produzir um dashboard de EXEMPLO a anexar no repositório
público. Nenhum dado real é usado ou representado aqui.

Uso:
    python gerar_base_exemplo.py
"""

import random
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

random.seed(42)

PASTA_SCRIPT = Path(__file__).resolve().parent
SAIDA = PASTA_SCRIPT / "base" / "historico_separacao.csv"

COLABORADORES = [
    "Colaborador A", "Colaborador B", "Colaborador C", "Colaborador D",
    "Colaborador E", "Colaborador F", "Colaborador G", "Colaborador H",
]
# Colaborador H vai ser marcado como operador (altura >= 01 em algumas tarefas)
OPERADORES = {"Colaborador H"}

# perfil fixo por pessoa, pra ter uma distribuição visual variada no ranking
# (alguns batendo/passando a meta, outros abaixo) -- mais realista que tudo
# convergindo pra média
PERFIS = {
    "Colaborador A": 1.15,
    "Colaborador B": 1.02,
    "Colaborador C": 0.70,
    "Colaborador D": 1.30,
    "Colaborador E": 0.85,
    "Colaborador F": 1.55,
    "Colaborador G": 0.95,
    "Colaborador H": 1.10,
}

RUAS = [f"{r:02d}" for r in range(1, 21)]
LOCAIS = [f"{l:02d}" for l in range(1, 31)]

HOJE = datetime.now().date()
DIAS_HISTORICO = 90  # cobre "hoje", "mês atual" e "últimos 90 dias"


def gerar_tarefas_do_dia(dia, tarefa_id_inicial):
    linhas = []
    tarefa_id = tarefa_id_inicial

    for usuario in COLABORADORES:
        # simula ausência ocasional (fim de semana / folga / afastado)
        if random.random() < 0.02:
            continue

        # perfil de produtividade variando por pessoa (uns rendem mais, outros menos)
        perfil = PERFIS[usuario]
        meta_cx_dia = int(1500 * perfil * random.uniform(0.92, 1.12))

        turno_1 = random.random() < 0.5
        hora_base = datetime.combine(dia, datetime.min.time()) + (
            timedelta(hours=7, minutes=random.randint(0, 20)) if turno_1
            else timedelta(hours=15, minutes=random.randint(0, 20))
        )

        cx_restantes = meta_cx_dia
        cursor = hora_base
        max_tarefas = 40  # trava de segurança, nao deveria bater nisso

        for _ in range(max_tarefas):
            if cx_restantes <= 0:
                break
            cx_tarefa = min(cx_restantes, random.randint(120, 260))
            cx_restantes -= cx_tarefa

            duracao_min = max(5, int(cx_tarefa / random.uniform(3.5, 7.0)))
            inicio = cursor
            fim = inicio + timedelta(minutes=duracao_min)

            # altura: operador as vezes bipa em 00, mas tambem em >=01
            if usuario in OPERADORES and random.random() < 0.4:
                altura = f"{random.randint(1, 5):02d}"
            else:
                altura = "00"

            endereco = f"01.{random.choice(RUAS)}.{random.choice(LOCAIS)}.{altura}"

            linhas.append({
                "Tarefa": tarefa_id,
                "Cód. Produto": f"P{random.randint(1000, 9999)}",
                "Qtd. Movimentada": cx_tarefa,
                "Data Hora Inicial": inicio.strftime("%Y-%m-%d %H:%M:%S"),
                "Data Hora Final": fim.strftime("%Y-%m-%d %H:%M:%S"),
                "Descr. Endereço Origem": endereco,
                "Usuário": usuario,
                "funcao": "operador" if usuario in OPERADORES and altura != "00" else "separador",
                "operacao": random.choice(["nacional", "exportacao"]),
            })

            # gap entre tarefas (tempo de deslocamento/espera)
            cursor = fim + timedelta(minutes=random.randint(2, 15))
            tarefa_id += 1

    return linhas, tarefa_id


def main():
    todas_linhas = []
    tarefa_id = 1

    for i in range(DIAS_HISTORICO, -1, -1):
        dia = HOJE - timedelta(days=i)
        if dia.weekday() == 6:  # domingo = folga
            continue
        linhas_dia, tarefa_id = gerar_tarefas_do_dia(dia, tarefa_id)
        todas_linhas.extend(linhas_dia)

    df = pd.DataFrame(todas_linhas)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SAIDA, index=False, encoding="utf-8-sig")
    print(f"[ok] base fictícia gerada: {SAIDA} ({len(df)} linhas, {DIAS_HISTORICO} dias, {len(COLABORADORES)} colaboradores fictícios)")


if __name__ == "__main__":
    main()
