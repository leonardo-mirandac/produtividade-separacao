"""
exportar_wms_produtividade.py
Abre o ERP/WMS Web no Edge, faz login, navega para
"WMS - Produtividade", preenche o filtro de data (primeiro dia
do mes ate agora) e exporta o relatorio de Movimentacao Geral
de Produtos como base_separacao_AAAAMMDD.xls na pasta extracoes/.

Adaptado do exportar_sistema_b.py (mesmo login, mesma logica
de download) -- so muda a tela e o preenchimento do filtro.

Dependencias: pip install selenium cryptography
Edge + EdgeDriver gerenciado automaticamente pelo Selenium Manager.
"""

import os, sys, time, glob, shutil
from datetime import datetime, date
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Configuracao — lida do credenciais.enc (AES-256-GCM) ────────────────
import importlib.util as _ilu, os as _os, sys as _sys
_env_senha = None
_argv_clean = []
_skip_next = False
for _a in sys.argv[1:]:
    if _skip_next:
        _env_senha = _a
        _skip_next = False
        continue
    if _a == "--env-senha":
        _skip_next = True
        continue
    _argv_clean.append(_a)
sys.argv = [sys.argv[0]] + _argv_clean

_env_ler_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "env_ler.py")
_spec = _ilu.spec_from_file_location("env_ler", _env_ler_path)
_env_ler_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_env_ler_mod)
_env = _env_ler_mod.ler_env(_env_senha)

ERP_URL = _env.get("ERP_URL", "https://exemplo-erp.com/login")
USUARIO     = _env.get("ERP_USUARIO", "")
SENHA       = _env.get("ERP_SENHA", "")

TELA_BUSCA    = "WMS - Produtividade"
HORA_INICIO_FILTRO = "00:00:00"  # hora que entra no campo de horario junto da data inicial

PASTA_SCRIPT  = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDA   = os.path.join(PASTA_SCRIPT, "extracoes")
os.makedirs(PASTA_SAIDA, exist_ok=True)
ARQUIVO_SAIDA = os.path.join(PASTA_SAIDA, f"base_separacao_{datetime.now().strftime('%Y%m%d')}.xls")
TIMEOUT       = 60

if not USUARIO or not SENHA:
    print("[ERRO] ERP_USUARIO e ERP_SENHA nao encontrados.")
    print("       Rode primeiro: python criptografar_credenciais.py")
    sys.exit(1)

# ── Selenium ──────────────────────────────────────────────────
try:
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.edge.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
except ImportError:
    print("[ERRO] selenium nao instalado. Execute: pip install selenium")
    sys.exit(1)


from selenium.webdriver.common.action_chains import ActionChains


def clicar_robusto(driver, elemento):
    """Tenta clicar de 3 formas, na ordem: clique nativo do Selenium (mais
    'correto', mas exige que o elemento passe nas checagens de
    visibilidade/interatividade dele) -> clique via JavaScript (ignora
    essas checagens, funciona bem em popovers/elementos dentro de
    containers com posicionamento CSS estranho) -> disparo manual de
    MouseEvent 'click' via JS (ultimo recurso, cobre handlers que só
    escutam eventos de mouse "de verdade", nao o .click() do DOM)."""
    try:
        elemento.click()
        return True
    except Exception:
        pass

    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento)
    except Exception:
        pass

    try:
        driver.execute_script("arguments[0].click();", elemento)
        return True
    except Exception:
        pass

    try:
        driver.execute_script("""
            const el = arguments[0];
            const ev = new MouseEvent('click', { bubbles: true, cancelable: true, view: window });
            el.dispatchEvent(ev);
        """, elemento)
        return True
    except Exception:
        return False


def abrir_painel_por_hover(driver, elemento):
    """Alguns paineis do ERP/WMS (framework legado) expandem so com o MOUSE PASSANDO
    por cima (hover), nao com clique -- o elemento fica com aria-hidden
    alternando entre true/false. Tenta 3 abordagens em sequencia:
    1) hover de verdade via ActionChains (move_to_element)
    2) hover no elemento PAI (a area sensivel costuma ser maior que o
       botao em si)
    3) forcar via JS, disparando mouseover/mouseenter/mousemove
    Sempre tenta um clique tambem no final, caso o painel use os dois
    (clique OU hover) dependendo da versao."""
    try:
        ActionChains(driver).move_to_element(elemento).pause(0.8).perform()
    except Exception:
        pass

    try:
        pai = elemento.find_element(By.XPATH, "..")
        ActionChains(driver).move_to_element(pai).pause(0.8).perform()
    except Exception:
        pass

    try:
        driver.execute_script("""
            const el = arguments[0];
            ['mouseover', 'mouseenter', 'mousemove'].forEach(tipo => {
                el.dispatchEvent(new MouseEvent(tipo, { bubbles: true, cancelable: true, view: window }));
            });
            let pai = el.parentElement;
            for (let i = 0; i < 3 && pai; i++) {
                ['mouseover', 'mouseenter'].forEach(tipo => {
                    pai.dispatchEvent(new MouseEvent(tipo, { bubbles: true, cancelable: true, view: window }));
                });
                pai = pai.parentElement;
            }
        """, elemento)
    except Exception:
        pass

    try:
        elemento.click()
    except Exception:
        pass  # ok se falhar -- o hover pode ja ter sido suficiente


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def primeiro_dia_do_mes_str() -> str:
    """Data no formato dd/mm/aaaa, igual o ERP/WMS espera no DateBox."""
    hoje = date.today()
    return hoje.replace(day=1).strftime("%d/%m/%Y")


def aguardar_download(pasta, timeout=90):
    log("Aguardando download do arquivo XLS...")
    inicio = time.time()
    while time.time() - inicio < timeout:
        arquivos = glob.glob(os.path.join(pasta, "*.xls"))
        arquivos = [a for a in arquivos if not a.endswith(".crdownload")]
        if arquivos:
            return max(arquivos, key=os.path.getmtime)
        time.sleep(2)
    return None


def renomear_export(arquivo_origem, destino):
    if os.path.abspath(arquivo_origem) == os.path.abspath(destino):
        log(f"Arquivo ja tem o nome correto: {os.path.basename(destino)}")
        return destino
    if os.path.exists(destino):
        os.remove(destino)
    shutil.move(arquivo_origem, destino)
    log(f"Arquivo renomeado para: {os.path.basename(destino)}")
    return destino


def set_valor_gwt(driver, element, value):
    """Preenche um input do framework legado do painel via JavaScript.
    Diferente do React (Sistema B), esse framework legado costuma escutar 'change' e 'blur',
    entao disparamos varios eventos pra garantir que o valor 'pegue'."""
    driver.execute_script("""
        var el = arguments[0], val = arguments[1];
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
        nativeInputValueSetter.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('keyup', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
    """, element, value)


def clicar_por_texto(driver, texto, tag="*"):
    """Clica no primeiro elemento visivel cujo texto EXATO bate. Usado pra
    botoes/labels desse framework legado que nao tem id estavel (as classes tipo
    'GLVY3WBAWC' sao geradas no compile e mudam a cada deploy)."""
    xpath = f'//{tag}[normalize-space(text())="{texto}"]'
    el = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, xpath)))
    el.click()
    return el


def em_qualquer_frame(driver, achar_fn, timeout_por_frame=4, profundidade_max=2):
    """Procura um elemento passando pelo documento principal e por TODOS
    os iframes (inclusive aninhados, ate 'profundidade_max' niveis). Ao
    achar, deixa o driver posicionado DENTRO do frame certo (pra poder
    clicar/preencher em seguida) e retorna o elemento. Se nao achar em
    lugar nenhum, volta pro documento principal e retorna None.

    'achar_fn(driver)' deve retornar um elemento ou None -- nao deve
    lancar excecao que nao seja tratada."""

    def _tentar_no_contexto_atual():
        try:
            return WebDriverWait(driver, timeout_por_frame).until(lambda d: achar_fn(d) or False) or None
        except Exception:
            return None

    def _buscar_recursivo(profundidade):
        el = _tentar_no_contexto_atual()
        if el is not None:
            return el
        if profundidade >= profundidade_max:
            return None
        frames_aqui = driver.find_elements(By.TAG_NAME, "iframe")
        for fr in frames_aqui:
            try:
                driver.switch_to.frame(fr)
            except Exception:
                continue
            el = _buscar_recursivo(profundidade + 1)
            if el is not None:
                return el
            driver.switch_to.parent_frame()
        return None

    driver.switch_to.default_content()
    resultado = _buscar_recursivo(0)
    if resultado is None:
        driver.switch_to.default_content()
    return resultado


def main():
    log("=" * 55)
    log("  EXPORTACAO ERP/WMS — WMS Produtividade")
    log("=" * 55)

    opts = Options()
    opts.add_experimental_option("prefs", {
        "download.default_directory":        PASTA_SAIDA,
        "download.prompt_for_download":      False,
        "download.directory_upgrade":        True,
        "safebrowsing.enabled":              False,
        "safebrowsing.disable_download_protection": True,
    })
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    log("[1/8] Abrindo ERP/WMS Web no Edge...")
    driver = webdriver.Edge(service=Service(), options=opts)
    driver.maximize_window()
    driver.get(ERP_URL)

    try:
        wait = WebDriverWait(driver, TIMEOUT)

        # ── Login (identico ao Sistema B) ─────────────────────────
        log("[2/8] Login...")
        time.sleep(3)

        campo_user = driver.execute_script("""
            const host = document.querySelector('erp-login');
            if (!host || !host.shadowRoot) return null;
            return host.shadowRoot.querySelector('input[name="usuario"], input[placeholder*="suario"], input[type="text"]');
        """)
        if campo_user is None:
            campo_user = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'input[name="usuario"], input[placeholder*="suario"]')))
        set_valor_gwt(driver, campo_user, USUARIO)

        btn1 = driver.execute_script("""
            const host = document.querySelector('erp-login');
            const root = host ? host.shadowRoot : document;
            return root.querySelector('button[type="submit"], button.btn-primary, button[class*="prosseguir"]');
        """)
        if btn1:
            btn1.click()
        else:
            driver.execute_script("""
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    if (b.innerText.toLowerCase().includes('prosseguir') ||
                        b.innerText.toLowerCase().includes('continuar')) { b.click(); break; }
                }
            """)
        time.sleep(2)

        campo_senha = driver.execute_script("""
            const host = document.querySelector('erp-login');
            const root = host ? host.shadowRoot : document;
            return root.querySelector('input[type="password"]');
        """)
        if campo_senha is None:
            campo_senha = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'input[type="password"]')))
        set_valor_gwt(driver, campo_senha, SENHA)

        btn2 = driver.execute_script("""
            const host = document.querySelector('erp-login');
            const root = host ? host.shadowRoot : document;
            return root.querySelector('button[type="submit"], button.btn-primary');
        """)
        if btn2:
            btn2.click()
        else:
            driver.execute_script("""
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    if (b.innerText.toLowerCase().includes('entrar') ||
                        b.innerText.toLowerCase().includes('acessar')) { b.click(); break; }
                }
            """)
        log("   Login OK, aguardando sistema carregar...")
        time.sleep(8)

        # ── Buscar e abrir "WMS - Produtividade" ────────────────
        log(f"[3/8] Buscando tela '{TELA_BUSCA}'...")
        driver.switch_to.default_content()

        seletores_busca = [
            'input[placeholder*="esquisar"]', 'input[placeholder*="Pesquisar"]',
            'input[class*="search"]', 'input[class*="busca"]', 'input[type="search"]',
        ]
        aberto = False
        for sel in seletores_busca:
            try:
                campo = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                campo.click()
                time.sleep(0.5)
                campo.clear()
                campo.send_keys(TELA_BUSCA)
                time.sleep(2.5)
                try:
                    # sugestao exata "WMS - Produtividade" (ver print: aparece destacada em "Mais utilizada")
                    sugestao = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                        (By.XPATH, f'//*[contains(text(),"{TELA_BUSCA}")]')))
                    sugestao.click()
                    aberto = True
                except Exception:
                    campo.send_keys(Keys.RETURN)
                    aberto = True
                break
            except Exception:
                continue

        if not aberto:
            log("   [AV] Nao foi possivel buscar automaticamente.")
            input(f"   Abra manualmente '{TELA_BUSCA}' e pressione Enter aqui: ")

        log("   Aguardando tela carregar...")
        time.sleep(5)

        # ── Abrir o painel de filtro (barra lateral escondida) ──
        log("[4/8] Abrindo painel de filtro...")
        # A barra fica encolhida (~20px) do lado esquerdo do gadget, e o
        # gadget inteiro costuma estar DENTRO de um iframe (as vezes
        # aninhado). em_qualquer_frame procura em todos os niveis e ja
        # deixa o driver posicionado no frame certo pra gente continuar.
        def _achar_toggle_painel(d):
            els = d.find_elements(By.XPATH, '//button[normalize-space(text())="«"]')
            if els:
                return els[0]
            els = d.find_elements(By.CSS_SELECTOR, '[class*="VCompactBar"]')
            return els[0] if els else None

        toggle = em_qualquer_frame(driver, _achar_toggle_painel)
        if toggle is not None:
            abrir_painel_por_hover(driver, toggle)
            log("   Painel aberto automaticamente (hover)")
        else:
            log("   [AV] Nao encontrei o painel de filtro automaticamente.")
            input("   Abra o painel de filtro na mao (clique na barrinha a esquerda) e pressione Enter: ")

        time.sleep(1.5)

        # confirma que o painel realmente abriu -- se os campos de data
        # ainda nao existirem no DOM depois do hover, tenta de novo com
        # um hover mais demorado antes de desistir e cair no manual
        if toggle is not None:
            def _tem_campo_data(d):
                return d.find_elements(By.CSS_SELECTOR, "input.gwt-DateBox")

            if not _tem_campo_data(driver):
                log("   Painel ainda nao expandiu, tentando hover mais demorado...")
                abrir_painel_por_hover(driver, toggle)
                time.sleep(2)

        # ── Preencher Data\Hora Inicial (so a primeira data + hora) ─
        log("[5/8] Preenchendo data inicial (primeiro dia do mes)...")
        data_str = primeiro_dia_do_mes_str()

        def _achar_campo_data(d):
            els = d.find_elements(By.CSS_SELECTOR, "input.gwt-DateBox")
            return els[0] if els else None

        campo_data = em_qualquer_frame(driver, _achar_campo_data)
        if campo_data is None:
            log("   [AV] Nenhum campo de data encontrado automaticamente.")
            input("   Preencha a Data\\Hora Inicial na mao e pressione Enter: ")
        else:
            set_valor_gwt(driver, campo_data, data_str)
            log(f"   Data inicial: {data_str}")

            # o campo de hora fica no MESMO frame que o campo de data --
            # como em_qualquer_frame ja nos deixou nesse frame, so procurar
            # direto (sem precisar varrer tudo de novo)
            campos_hora = driver.find_elements(By.CSS_SELECTOR, "input.gwt-TextBox[style*='65px']")
            if campos_hora:
                set_valor_gwt(driver, campos_hora[0], HORA_INICIO_FILTRO)
                log(f"   Hora inicial: {HORA_INICIO_FILTRO}")
            else:
                log("   [AV] Campo de hora inicial nao encontrado (seguindo sem preencher).")

        time.sleep(1)

        # ── Clicar em Atualizar ──────────────────────────────────
        log("[6/8] Clicando em Atualizar...")

        def _achar_btn_atualizar(d):
            els = d.find_elements(By.XPATH, '//button[normalize-space(text())="Atualizar"]')
            return els[0] if els else None

        btn_atualizar = em_qualquer_frame(driver, _achar_btn_atualizar)
        if btn_atualizar is not None:
            clicar_robusto(driver, btn_atualizar)
            log("   Atualizar clicado automaticamente")
        else:
            log("   [AV] Nao encontrei o botao Atualizar automaticamente.")
            input("   Clique em Atualizar na mao e pressione Enter: ")

        log("   Aguardando grid carregar...")
        time.sleep(6)

        # ── Abrir "Movimentação Geral de Produtos" ──────────────
        log("[7/8] Abrindo Movimentação Geral de Produtos...")

        def _achar_link_movimentacao(d):
            els = d.find_elements(By.XPATH, '//*[normalize-space(text())="Movimentação Geral de Produtos"]')
            if els:
                return els[0]
            # fallback: busca parcial (acentuacao pode variar)
            els = d.find_elements(By.XPATH, '//*[contains(text(),"Movimenta") and contains(text(),"Geral")]')
            return els[0] if els else None

        link_mov = em_qualquer_frame(driver, _achar_link_movimentacao, timeout_por_frame=6)
        if link_mov is not None:
            clicar_robusto(driver, link_mov)
            log("   Movimentação Geral de Produtos aberto automaticamente")
        else:
            log("   [AV] Nao encontrei automaticamente.")
            input("   Clique em 'Movimentação Geral de Produtos' na mao e pressione Enter: ")

        time.sleep(4)

        # ── Exportar XLS (dropdown dentro do iframe, igual Sistema B) ──
        log("[8/8] Exportando para XLS...")

        def _achar_dropdown_export(d):
            els = d.find_elements(
                By.CSS_SELECTOR,
                'button.dropdown-toggle, span.caret, button[sk-popover]'
            )
            return els[0] if els else None

        dropdown = em_qualquer_frame(driver, _achar_dropdown_export, timeout_por_frame=6)
        if dropdown is not None:
            clicar_robusto(driver, dropdown)
            log("   Dropdown de exportacao clicado automaticamente")
            time.sleep(1)
        else:
            log("   [AV] Dropdown de exportacao nao encontrado automaticamente.")
            input("   Abra o dropdown de exportar na mao e pressione Enter: ")

        # ── Clicar em "Exportar para planilha (xls)" -- CUIDADO:
        # existe tambem "(xlsx)" que contem "xls" como substring, entao o
        # match tem que ser pelo texto EXATO, nao "contains". Continua no
        # MESMO frame de onde o dropdown foi aberto (nao precisa buscar
        # em todos de novo).
        try:
            opcao_xls = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((
                By.XPATH,
                '//*[@tooltip="Exportar para planilha (xls)" or '
                'normalize-space(text())="Exportar para planilha (xls)"]'
            )))
            clicar_robusto(driver, opcao_xls)
            log("   'Exportar para planilha (xls)' clicado")
        except Exception:
            # fallback: procura em todos os frames de novo, caso o dropdown
            # tenha aberto um popover fora do frame atual
            def _achar_opcao_xls(d):
                els = d.find_elements(
                    By.XPATH,
                    '//*[@tooltip="Exportar para planilha (xls)" or '
                    'normalize-space(text())="Exportar para planilha (xls)"]'
                )
                return els[0] if els else None

            opcao_xls = em_qualquer_frame(driver, _achar_opcao_xls, timeout_por_frame=5)
            if opcao_xls is not None:
                clicar_robusto(driver, opcao_xls)
                log("   'Exportar para planilha (xls)' clicado (via busca em frames)")
            else:
                log("   [AV] Opcao xls nao encontrada automaticamente.")
                input("   Clique em 'Exportar para planilha (xls)' (NAO o xlsx) na mao e pressione Enter: ")

        driver.switch_to.default_content()
        time.sleep(3)

        try:
            if len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
        except Exception:
            pass

        arquivo = aguardar_download(PASTA_SAIDA)
        if arquivo:
            renomear_export(arquivo, ARQUIVO_SAIDA)
            log("")
            log(f"[OK] Exportacao concluida: {ARQUIVO_SAIDA}")
        else:
            log("[AV] Timeout: arquivo nao encontrado em 90s.")
            sys.exit(1)

    except Exception as e:
        log(f"[ERRO] {e}")
        try:
            driver.save_screenshot(os.path.join(PASTA_SCRIPT, "erro_wms_produtividade.png"))
            log("Screenshot salvo: erro_wms_produtividade.png")
        except Exception:
            pass
        sys.exit(1)
    finally:
        time.sleep(2)
        try: driver.quit()
        except: pass


if __name__ == "__main__":
    main()