# -*- coding: utf-8 -*-
"""
dpapi_util.py

Wrapper fino para o DPAPI do Windows (Data Protection API), via ctypes
(sem depender de pywin32). O DPAPI criptografa dados vinculados a conta
do usuario do Windows + a maquina -- so o MESMO usuario, no MESMO PC,
consegue descriptografar de volta. Nao precisa de senha nenhuma pra usar
(o Windows ja sabe "quem voce e" pelo login).

Usado pra guardar a senha mestra de forma que o exportador rode sozinho
(agendado, sem ninguem digitando nada), sem abrir mao da criptografia
real das credenciais (credenciais.enc continua protegido por AES-256-GCM
com a senha mestra -- o DPAPI so guarda ESSA senha mestra de um jeito que
so essa conta Windows consegue reabrir).

So funciona no Windows. Em outros sistemas, protect()/unprotect() lancam
RuntimeError.
"""

import sys
import ctypes
from ctypes import wintypes


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_para_bytes(blob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _bytes_para_blob(dados: bytes) -> _DATA_BLOB:
    buffer = ctypes.create_string_buffer(dados, len(dados))
    return _DATA_BLOB(len(dados), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def protect(dados: bytes) -> bytes:
    """Criptografa 'dados' com o DPAPI, vinculado ao usuario Windows atual."""
    if sys.platform != "win32":
        raise RuntimeError("DPAPI so funciona no Windows.")

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    entrada = _bytes_para_blob(dados)
    saida = _DATA_BLOB()

    ok = crypt32.CryptProtectData(
        ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(saida)
    )
    if not ok:
        raise RuntimeError(f"CryptProtectData falhou (erro {kernel32.GetLastError()})")

    try:
        return _blob_para_bytes(saida)
    finally:
        kernel32.LocalFree(saida.pbData)


def unprotect(dados_protegidos: bytes) -> bytes:
    """Descriptografa dados gerados por protect(). So funciona pro mesmo
    usuario Windows + mesma maquina que gerou o dado."""
    if sys.platform != "win32":
        raise RuntimeError("DPAPI so funciona no Windows.")

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    entrada = _bytes_para_blob(dados_protegidos)
    saida = _DATA_BLOB()

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(saida)
    )
    if not ok:
        raise RuntimeError(f"CryptUnprotectData falhou (erro {kernel32.GetLastError()})")

    try:
        return _blob_para_bytes(saida)
    finally:
        kernel32.LocalFree(saida.pbData)
