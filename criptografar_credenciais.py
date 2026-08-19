# -*- coding: utf-8 -*-
"""
criptografar_credenciais.py

Roda UMA VEZ (ou toda vez que precisar trocar usuario/senha/url) pra criar
o arquivo credenciais.enc, que guarda ERP_USUARIO / ERP_SENHA /
ERP_URL criptografados com AES-256-GCM. A chave de criptografia nunca
fica salva em lugar nenhum -- ela e derivada na hora, a partir da SENHA
MESTRA que voce digita toda vez que for usar (no exportar_wms_produtividade.py).

Sem a senha mestra certa, o arquivo credenciais.enc e ilegivel.

Uso:
    python criptografar_credenciais.py
"""

import os
import json
import base64
import getpass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from senha_gui import pedir_senha_mestra_nova, _mostrar_erro

PASTA_SCRIPT = Path(__file__).resolve().parent
ARQUIVO_CREDENCIAIS = PASTA_SCRIPT / "credenciais.enc"
ARQUIVO_ENV_TEXTO_PURO = PASTA_SCRIPT / "env.env"  # arquivo de origem, em texto puro

PBKDF2_ITERACOES = 600_000  # padrao recomendado atual (OWASP 2023+) pra PBKDF2-HMAC-SHA256


def ler_env_texto_puro(caminho: Path) -> dict:
    """Le um arquivo .env simples (linhas 'CHAVE=valor', ignora comentarios
    com # e linhas em branco)."""
    dados = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")  # remove aspas se tiver
        dados[chave] = valor
    return dados


def derivar_chave(senha_mestra: str, salt: bytes) -> bytes:
    """Deriva uma chave AES-256 (32 bytes) a partir da senha mestra + salt.
    O salt e unico por arquivo e fica salvo junto (nao e segredo, so
    garante que a mesma senha nunca gera a mesma chave em arquivos diferentes)."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERACOES,
    )
    return kdf.derive(senha_mestra.encode("utf-8"))


def criptografar(dados: dict, senha_mestra: str) -> bytes:
    """Criptografa o dict de credenciais com AES-256-GCM.
    Formato do arquivo final: salt(16) + nonce(12) + ciphertext (com tag)."""
    salt = os.urandom(16)
    nonce = os.urandom(12)
    chave = derivar_chave(senha_mestra, salt)

    aesgcm = AESGCM(chave)
    plaintext = json.dumps(dados, ensure_ascii=False).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)

    return salt + nonce + ciphertext


def descriptografar(conteudo: bytes, senha_mestra: str) -> dict:
    """Operacao inversa -- usada pelo env_ler.py na hora de rodar o export."""
    salt, nonce, ciphertext = conteudo[:16], conteudo[16:28], conteudo[28:]
    chave = derivar_chave(senha_mestra, salt)
    aesgcm = AESGCM(chave)
    plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
    return json.loads(plaintext.decode("utf-8"))


def main():
    print("=" * 55)
    print("Criptografar credenciais ERP/WMS (AES-256-GCM)")
    print("=" * 55)

    if ARQUIVO_CREDENCIAIS.exists():
        resp = input(f"\n[aviso] {ARQUIVO_CREDENCIAIS.name} ja existe. Sobrescrever? (s/n): ").strip().lower()
        if resp != "s":
            print("Cancelado.")
            return

    if ARQUIVO_ENV_TEXTO_PURO.exists():
        print(f"\n[info] encontrei {ARQUIVO_ENV_TEXTO_PURO.name} -- lendo credenciais de la.")
        env_lido = ler_env_texto_puro(ARQUIVO_ENV_TEXTO_PURO)
        usuario = env_lido.get("ERP_USUARIO", "")
        senha = env_lido.get("ERP_SENHA", "")
        url = env_lido.get("ERP_URL", "")

        faltando = [k for k, v in [("ERP_USUARIO", usuario), ("ERP_SENHA", senha), ("ERP_URL", url)] if not v]
        if faltando:
            print(f"[erro] faltando no {ARQUIVO_ENV_TEXTO_PURO.name}: {', '.join(faltando)}")
            return

        print(f"   ERP_USUARIO: {usuario}")
        print(f"   ERP_SENHA: {'*' * len(senha)}")
        print(f"   ERP_URL: {url}")
        confirmar = input("\n   Confirma esses dados? (s/n): ").strip().lower()
        if confirmar != "s":
            print("Cancelado.")
            return
    else:
        print(f"\n[info] {ARQUIVO_ENV_TEXTO_PURO.name} nao encontrado -- digite as credenciais manualmente:")
        usuario = input("  ERP_USUARIO: ").strip()
        senha = getpass.getpass("  ERP_SENHA: ").strip()
        url = input("  ERP_URL (ex: https://exemplo-erp.com/login): ").strip()

        if not usuario or not senha or not url:
            print("\n[erro] todos os campos sao obrigatorios.")
            return

    print("\nAgora defina a SENHA MESTRA (voce vai digitar ela toda vez que rodar o export).")
    senha_mestra = pedir_senha_mestra_nova("Configuração inicial")
    if not senha_mestra:
        print("\n[erro] senha mestra nao confirmada (janela cancelada ou senhas diferentes). Nada foi salvo.")
        return
    if len(senha_mestra) < 8:
        print("\n[aviso] senha mestra bem curta -- considere usar algo mais forte.")

    dados = {
        "ERP_USUARIO": usuario,
        "ERP_SENHA": senha,
        "ERP_URL": url,
    }

    conteudo_criptografado = criptografar(dados, senha_mestra)
    ARQUIVO_CREDENCIAIS.write_bytes(conteudo_criptografado)

    print(f"\n[ok] credenciais salvas (criptografadas) em {ARQUIVO_CREDENCIAIS}")
    print("     Guarde a senha mestra em local seguro -- sem ela, ninguem recupera as credenciais.")

    if ARQUIVO_ENV_TEXTO_PURO.exists():
        apagar = input(f"\n   Apagar o {ARQUIVO_ENV_TEXTO_PURO.name} em texto puro agora? (recomendado) (s/n): ").strip().lower()
        if apagar == "s":
            ARQUIVO_ENV_TEXTO_PURO.unlink()
            print(f"   [ok] {ARQUIVO_ENV_TEXTO_PURO.name} apagado. As credenciais agora só existem criptografadas.")
        else:
            print(f"   [aviso] {ARQUIVO_ENV_TEXTO_PURO.name} continua em texto puro no disco -- apague manualmente quando puder.")


if __name__ == "__main__":
    main()