# -*- coding: utf-8 -*-
"""
env_ler.py

Modulo usado pelos scripts de exportacao (exportar_wms_produtividade.py,
exportar_sistema_b.py, etc) pra carregar as credenciais do ERP/WMS
sem nunca ter elas em texto puro no disco.

Le o credenciais.enc (gerado por criptografar_credenciais.py), pede a
senha mestra (se nao foi passada por parametro) e devolve um dict com
ERP_USUARIO / ERP_SENHA / ERP_URL.
"""

import getpass
from pathlib import Path

from criptografar_credenciais import descriptografar
from senha_gui import pedir_senha_mestra

PASTA_SCRIPT = Path(__file__).resolve().parent.parent.parent
ARQUIVO_CREDENCIAIS = PASTA_SCRIPT / "credenciais.enc"
ARQUIVO_SENHA_AUTOMATICA = PASTA_SCRIPT / "senha_automatica.dat"


def _tentar_senha_automatica():
    """Se configurar_senha_automatica.py ja foi rodado, tenta pegar a
    senha mestra do cofre do Windows (DPAPI) sem pedir nada pro usuario.
    Retorna a senha ou None se nao tiver configurado / nao for Windows /
    der qualquer erro (nesses casos, cai pro fluxo normal da janela)."""
    if not ARQUIVO_SENHA_AUTOMATICA.exists():
        return None
    try:
        import dpapi_util
        dados_protegidos = ARQUIVO_SENHA_AUTOMATICA.read_bytes()
        return dpapi_util.unprotect(dados_protegidos).decode("utf-8")
    except Exception:
        return None


def ler_env(senha_mestra: str = None) -> dict:
    """Retorna as credenciais descriptografadas como dict.

    Ordem de tentativa pra achar a senha mestra:
      1) se foi passada por parametro (--env-senha), usa ela
      2) se configurar_senha_automatica.py ja rodou nesse PC, pega do
         cofre do Windows (DPAPI) -- sem pedir nada, pro exportador rodar
         sozinho via .bat/agendador
      3) senao, abre a janela grafica pra digitar (fluxo manual)
    """
    if not ARQUIVO_CREDENCIAIS.exists():
        print(f"[ERRO] {ARQUIVO_CREDENCIAIS.name} nao encontrado.")
        print("       Rode primeiro: python criptografar_credenciais.py")
        return {}

    if not senha_mestra:
        senha_mestra = _tentar_senha_automatica()

    if not senha_mestra:
        senha_mestra = pedir_senha_mestra("Autenticação")
        if not senha_mestra:
            print("[ERRO] Nenhuma senha informada (janela cancelada).")
            return {}

    conteudo = ARQUIVO_CREDENCIAIS.read_bytes()
    try:
        return descriptografar(conteudo, senha_mestra)
    except Exception:
        print("[ERRO] senha mestra incorreta ou arquivo de credenciais corrompido.")
        return {}