"""
IniciarERP.py
=============================================================================
Atualizador automatico + inicializador do SpeedyErp.exe (versao Python)

Logica (igual ao IniciarERP.bat, porem com interface grafica condicional):

    1. Descobre a pasta onde este programa esta rodando (equivalente ao %~dp0).
    2. Le a versao local e a versao do servidor (arquivo versao.txt).
    3. Se as versoes forem IGUAIS -> abre o SpeedyErp.exe IMEDIATAMENTE,
       sem exibir nenhuma janela (zero delay perceptivel).
    4. Se as versoes forem DIFERENTES -> abre uma janela pequena com barra
       de progresso, fecha o ERP se estiver aberto, copia so os arquivos
       novos/alterados do servidor, atualiza a versao local e so depois
       abre o sistema.
    5. Tudo e registrado em log com data/hora.
    6. Erros (servidor fora do ar, sem acesso, arquivo bloqueado, falha de
       copia) sao tratados e, sempre que possivel, o sistema local e aberto
       mesmo assim.

Este arquivo pode ser distribuido como .py (precisa de Python instalado nos
terminais) ou compilado para .exe com PyInstaller (recomendado - veja as
instrucoes no final da explicacao). Como .exe, ele substitui o atalho atual
do ERP, exatamente como o IniciarERP.bat fazia.
=============================================================================
"""

import os
import sys
import time
import shutil
import subprocess
import threading
import queue
import configparser
import tkinter as tk
from tkinter import ttk
from datetime import datetime

# =============================================================================
# BLOCO 1 - CONFIGURACOES
# Os valores reais ficam no arquivo config.ini (na mesma pasta do
# executavel), para que cada cliente/terminal possa ajustar o caminho do
# servidor sem precisar recompilar o .exe. Os valores abaixo em DEFAULTS
# so sao usados se o config.ini nao existir ou estiver incompleto.
# =============================================================================

DEFAULTS = {
    "exe_name": "SpeedyErp.exe",
    "server_dir": r"\\Servidor\10.7",
    "version_file": "versao.txt",
    "kill_wait_seconds": "3",
    "copy_retries": "3",
    "copy_retry_wait": "2",
    # Lista de arquivos que NUNCA devem ser sobrescritos pela atualizacao,
    # separados por virgula. Pode ser so o nome do arquivo (protege em
    # qualquer subpasta) ou um caminho relativo especifico
    # (ex: "Config\Speedy.ini" protege so aquele arquivo naquela subpasta).
    "arquivos_protegidos": "Speedy.ini, config_export_balanca.cfg",
    # MODO LISTA BRANCA (opcional). Se preenchido, o atualizador sincroniza
    # SOMENTE os arquivos/pastas listados aqui, ignorando todo o restante
    # do servidor. Deixe em branco ("") para sincronizar tudo (comportamento
    # padrao, usado pelo IniciarERP). Preencha para sincronizar so alguns
    # itens (ex: usado pelo IniciarNFCe, que so precisa do executavel e da
    # pasta de Relatorios). Aceita nomes de arquivo e/ou nomes de pastas,
    # separados por virgula. Uma pasta listada e sincronizada por completo,
    # com todas as suas subpastas.
    "itens_sincronizados": "",
}

CHUNK_SIZE = 1024 * 1024  # 1 MB por leitura, usado para progresso suave


def get_local_dir() -> str:
    """
    Retorna a pasta onde este programa esta gravado, equivalente ao %~dp0
    do BAT. Funciona tanto executando o .py direto quanto o .exe compilado
    (PyInstaller), e independe do drive/caminho de instalacao do cliente.
    """
    if getattr(sys, "frozen", False):
        # Quando compilado com PyInstaller, sys.executable e o proprio .exe
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def carregar_configuracoes(local_dir: str, log_debug) -> dict:
    """
    Le o config.ini na pasta local. Se o arquivo nao existir ou faltar
    alguma chave, usa os valores de DEFAULTS no lugar (nunca quebra por
    falta de configuracao).

    Recebe log_debug (uma funcao) para registrar, passo a passo, o que
    esta acontecendo - isso e essencial para diagnosticar por que as
    configuracoes do .ini nao estao sendo aplicadas.
    """
    caminho_ini = os.path.join(local_dir, "config.ini")
    log_debug(f"DIAGNOSTICO: procurando config.ini em: {caminho_ini}")

    parser = configparser.ConfigParser()
    parser["Config"] = DEFAULTS.copy()  # garante todas as chaves com default

    if os.path.isfile(caminho_ini):
        log_debug("DIAGNOSTICO: config.ini FOI ENCONTRADO nesse caminho.")
        try:
            arquivos_lidos = parser.read(caminho_ini, encoding="utf-8-sig")
            if not arquivos_lidos:
                log_debug("DIAGNOSTICO: ERRO - parser.read() nao conseguiu "
                          "ler o arquivo (retornou lista vazia). Verifique "
                          "se o arquivo nao esta corrompido ou bloqueado.")
            elif "Config" not in parser or not parser["Config"].get("server_dir"):
                log_debug("DIAGNOSTICO: AVISO - arquivo lido, mas a secao "
                          "[Config] ou a chave server_dir nao foi encontrada. "
                          "Confira se o arquivo tem a linha '[Config]' e "
                          "'server_dir = ...' exatamente como no modelo.")
            else:
                log_debug(f"DIAGNOSTICO: valor lido de server_dir = "
                          f"'{parser['Config'].get('server_dir')}'")
        except Exception as e:
            log_debug(f"DIAGNOSTICO: ERRO ao ler config.ini ({e}). "
                      f"Usando valores padrao internos.")
    else:
        log_debug("DIAGNOSTICO: config.ini NAO FOI ENCONTRADO nesse caminho. "
                  "Usando valores padrao internos do codigo (DEFAULTS).")

    secao = parser["Config"]

    # Transforma a string "Speedy.ini, Config\Outro.ini" em uma lista limpa,
    # sem espacos extras e em minusculas (para comparacao facilitar)
    protegidos_raw = secao.get("arquivos_protegidos", DEFAULTS["arquivos_protegidos"])
    lista_protegidos = [
        item.strip().lower().replace("/", "\\")
        for item in protegidos_raw.split(",")
        if item.strip()
    ]
    log_debug(f"DIAGNOSTICO: arquivos protegidos (nunca sobrescritos) = {lista_protegidos}")

    # Lista branca (opcional): mantem a grafia original de cada item, pois
    # ela e usada para localizar o arquivo/pasta de verdade dentro do
    # servidor (os.path e case-insensitive no Windows, mas preservar a
    # grafia original evita qualquer surpresa).
    sincronizados_raw = secao.get("itens_sincronizados", DEFAULTS["itens_sincronizados"])
    lista_sincronizados = [
        item.strip().replace("/", "\\")
        for item in sincronizados_raw.split(",")
        if item.strip()
    ]
    if lista_sincronizados:
        log_debug(f"DIAGNOSTICO: modo LISTA BRANCA ativo - sincronizando somente: {lista_sincronizados}")
    else:
        log_debug("DIAGNOSTICO: itens_sincronizados vazio - sincronizando TUDO (modo padrao).")

    resultado = {
        "exe_name": secao.get("exe_name", DEFAULTS["exe_name"]).strip(),
        "server_dir": secao.get("server_dir", DEFAULTS["server_dir"]).strip(),
        "version_file": secao.get("version_file", DEFAULTS["version_file"]).strip(),
        "kill_wait_seconds": secao.getint("kill_wait_seconds", fallback=3),
        "copy_retries": secao.getint("copy_retries", fallback=3),
        "copy_retry_wait": secao.getint("copy_retry_wait", fallback=2),
        "arquivos_protegidos": lista_protegidos,
        "itens_sincronizados": lista_sincronizados,
    }
    log_debug(f"DIAGNOSTICO: configuracao final em uso -> "
              f"server_dir='{resultado['server_dir']}' | "
              f"exe_name='{resultado['exe_name']}' | "
              f"version_file='{resultado['version_file']}'")
    return resultado


def _log_diagnostico_inicial(local_dir: str, mensagem: str) -> None:
    """
    Log minimo usado APENAS durante o carregamento das configuracoes,
    antes do LOG_FILE definitivo existir. Grava num arquivo separado
    (config_debug.log) para nao depender de nada configurado ainda.
    """
    try:
        pasta_log = os.path.join(local_dir, "logs")
        os.makedirs(pasta_log, exist_ok=True)
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        with open(os.path.join(pasta_log, "config_debug.log"), "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {mensagem}\n")
    except Exception:
        pass


LOCAL_DIR = get_local_dir()
CFG = carregar_configuracoes(LOCAL_DIR, lambda msg: _log_diagnostico_inicial(LOCAL_DIR, msg))

EXE_NAME = CFG["exe_name"]
SERVER_DIR = CFG["server_dir"]
VERSION_FILE = CFG["version_file"]
KILL_WAIT_SECONDS = CFG["kill_wait_seconds"]
COPY_RETRIES = CFG["copy_retries"]
COPY_RETRY_WAIT = CFG["copy_retry_wait"]
ARQUIVOS_PROTEGIDOS = CFG["arquivos_protegidos"]
ITENS_SINCRONIZADOS = CFG["itens_sincronizados"]

LOCAL_EXE = os.path.join(LOCAL_DIR, EXE_NAME)
LOCAL_VERSION_FILE = os.path.join(LOCAL_DIR, VERSION_FILE)
SERVER_VERSION_FILE = os.path.join(SERVER_DIR, VERSION_FILE)

LOG_DIR = os.path.join(LOCAL_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "atualizacao.log")


# =============================================================================
# BLOCO 2 - LOG
# =============================================================================

def log(mensagem: str) -> None:
    """Grava uma linha no log com data e hora, no mesmo formato do BAT."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {mensagem}\n")
    except Exception:
        # Se nem o log puder ser gravado (ex: pasta sem permissao de escrita),
        # o programa nao deve travar por isso - so ignora silenciosamente.
        pass


# =============================================================================
# BLOCO 3 - LEITURA DE VERSAO E VERIFICACAO DO SERVIDOR
# =============================================================================

def ler_versao(caminho: str) -> str:
    """Le a versao de um arquivo texto, removendo espacos/linhas em branco."""
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def servidor_disponivel() -> bool:
    """Verifica se a pasta compartilhada do servidor esta acessivel."""
    try:
        return os.path.isdir(SERVER_DIR)
    except Exception:
        return False


def precisa_atualizar() -> bool:
    """
    Decide, de forma RAPIDA, se e necessario atualizar.
    Retorna True se: exe local nao existe, servidor inacessivel deve
    ser tratado separadamente (ver main), ou versoes diferentes.
    """
    if not os.path.isfile(LOCAL_EXE):
        return True

    versao_local = ler_versao(LOCAL_VERSION_FILE)
    versao_servidor = ler_versao(SERVER_VERSION_FILE)

    if versao_servidor == "":
        # Nao foi possivel ler a versao do servidor -> nao forca atualizacao,
        # apenas abre o que existe localmente (tratado como "sem atualizacao")
        return False

    return versao_local != versao_servidor


# =============================================================================
# BLOCO 4 - FECHAR O SISTEMA SE ESTIVER ABERTO
# =============================================================================

def fechar_sistema() -> None:
    """Finaliza o SpeedyErp.exe, se estiver em execucao, usando taskkill."""
    try:
        resultado = subprocess.run(
            ["tasklist", "/fi", f"imagename eq {EXE_NAME}"],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        if EXE_NAME.lower() in resultado.stdout.lower():
            log(f"Finalizando processo {EXE_NAME} antes da atualizacao.")
            subprocess.run(
                ["taskkill", "/im", EXE_NAME, "/f"],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
            time.sleep(KILL_WAIT_SECONDS)  # tempo para o Windows liberar os arquivos
        else:
            log(f"Processo {EXE_NAME} nao estava em execucao.")
    except Exception as e:
        log(f"AVISO: falha ao tentar finalizar {EXE_NAME}: {e}")


# =============================================================================
# BLOCO 5 - COPIA DOS ARQUIVOS (equivalente ao robocopy /E /XO)
# =============================================================================

def arquivo_esta_protegido(caminho_relativo: str) -> bool:
    """
    Verifica se um arquivo (dado seu caminho relativo dentro do ERP, ex:
    "Speedy.ini" ou "Config\\Speedy.ini") esta na lista de arquivos
    protegidos definida no config.ini. A comparacao ignora maiusculas/
    minusculas e aceita tanto "so o nome" quanto "caminho completo".
    """
    caminho_normalizado = caminho_relativo.strip().lower().replace("/", "\\")
    nome_arquivo = os.path.basename(caminho_normalizado)

    for protegido in ARQUIVOS_PROTEGIDOS:
        # Casa se o usuario protegeu so pelo nome (ex: "speedy.ini")
        # ou pelo caminho relativo completo (ex: "config\speedy.ini")
        if protegido == nome_arquivo or protegido == caminho_normalizado:
            return True
    return False


def _avaliar_candidato(caminho_relativo: str, lista_destino: list) -> bool:
    """
    Avalia um unico arquivo (dado seu caminho relativo dentro do ERP) e,
    se ele precisar ser copiado, adiciona (origem, destino, tamanho) em
    lista_destino. Retorna True se o arquivo foi ignorado por estar
    protegido (usado so para contagem/log), False caso contrario.
    Funcao compartilhada pelos dois modos de sincronizacao (tudo / lista
    branca), para nao duplicar a logica de comparacao.
    """
    if arquivo_esta_protegido(caminho_relativo):
        return True

    origem = os.path.join(SERVER_DIR, caminho_relativo)
    destino = os.path.join(LOCAL_DIR, caminho_relativo)

    copiar = False
    if not os.path.exists(destino):
        copiar = True
    else:
        try:
            origem_info = os.stat(origem)
            destino_info = os.stat(destino)
            # Copia se o arquivo do servidor for mais novo OU
            # tiver tamanho diferente do arquivo local
            if (origem_info.st_mtime > destino_info.st_mtime + 1 or
                    origem_info.st_size != destino_info.st_size):
                copiar = True
        except Exception:
            copiar = True

    if copiar:
        try:
            tamanho = os.path.getsize(origem)
        except Exception:
            tamanho = 0
        lista_destino.append((origem, destino, tamanho))

    return False


def listar_arquivos_a_copiar() -> list:
    """
    Monta a lista de arquivos que precisam ser copiados do servidor,
    em um de dois modos:

    MODO PADRAO (itens_sincronizados vazio no config.ini): percorre TODO
    o servidor recursivamente, copiando o que nao existir localmente ou
    estiver com tamanho/data diferentes (mesma ideia do robocopy /XO).
    Usado pelo IniciarERP.

    MODO LISTA BRANCA (itens_sincronizados preenchido): sincroniza SOMENTE
    os arquivos e pastas listados em itens_sincronizados, ignorando todo o
    restante do servidor - mesmo que existam diferencas em outros lugares.
    Usado, por exemplo, pelo IniciarNFCe, que so precisa manter atualizados
    o executavel e a pasta de Relatorios, sem tocar em mais nada.

    Em ambos os modos, arquivos protegidos (arquivos_protegidos) sao
    SEMPRE ignorados, mesmo que estejam dentro de um item da lista branca.
    Retorna lista de tuplas: (origem, destino, tamanho_em_bytes)
    """
    arquivos = []
    arquivos_ignorados = 0

    if ITENS_SINCRONIZADOS:
        # ---------------- MODO LISTA BRANCA ----------------
        for item in ITENS_SINCRONIZADOS:
            origem_item = os.path.join(SERVER_DIR, item)

            if os.path.isdir(origem_item):
                # Item e uma pasta -> sincroniza ela por completo (com subpastas)
                for pasta_raiz, _subpastas, nomes_arquivo in os.walk(origem_item):
                    caminho_relativo_pasta = os.path.relpath(pasta_raiz, SERVER_DIR)
                    for nome in nomes_arquivo:
                        caminho_relativo_arquivo = (
                            nome if caminho_relativo_pasta == "."
                            else os.path.join(caminho_relativo_pasta, nome)
                        )
                        if _avaliar_candidato(caminho_relativo_arquivo, arquivos):
                            arquivos_ignorados += 1

            elif os.path.isfile(origem_item):
                # Item e um arquivo unico (ex: SpeedyNfce.exe)
                if _avaliar_candidato(item, arquivos):
                    arquivos_ignorados += 1

            else:
                log(f"AVISO: item '{item}' definido em itens_sincronizados "
                    f"nao foi encontrado no servidor ({origem_item}).")

    else:
        # ---------------- MODO PADRAO: sincroniza tudo ----------------
        for pasta_raiz, _subpastas, nomes_arquivo in os.walk(SERVER_DIR):
            caminho_relativo_pasta = os.path.relpath(pasta_raiz, SERVER_DIR)
            for nome in nomes_arquivo:
                caminho_relativo_arquivo = (
                    nome if caminho_relativo_pasta == "."
                    else os.path.join(caminho_relativo_pasta, nome)
                )
                if _avaliar_candidato(caminho_relativo_arquivo, arquivos):
                    arquivos_ignorados += 1

    if arquivos_ignorados > 0:
        log(f"INFO: {arquivos_ignorados} arquivo(s) protegido(s) ignorado(s) "
            f"na atualizacao (nunca sobrescritos): {ARQUIVOS_PROTEGIDOS}")

    return arquivos


def copiar_arquivo_com_progresso(origem: str, destino: str, callback_bytes) -> bool:
    """
    Copia um unico arquivo em blocos (chunks), chamando callback_bytes(n)
    a cada bloco lido - isso permite atualizar a barra de progresso de
    forma suave mesmo em arquivos grandes. Faz retry em caso de arquivo
    bloqueado (equivalente ao /R do robocopy).
    """
    os.makedirs(os.path.dirname(destino), exist_ok=True)

    for tentativa in range(1, COPY_RETRIES + 1):
        try:
            with open(origem, "rb") as f_in, open(destino, "wb") as f_out:
                while True:
                    bloco = f_in.read(CHUNK_SIZE)
                    if not bloco:
                        break
                    f_out.write(bloco)
                    callback_bytes(len(bloco))
            shutil.copystat(origem, destino)  # preserva data de modificacao
            return True
        except PermissionError:
            # Arquivo em uso/bloqueado - espera e tenta novamente
            log(f"AVISO: arquivo bloqueado, tentativa {tentativa}/{COPY_RETRIES}: {destino}")
            time.sleep(COPY_RETRY_WAIT)
        except Exception as e:
            log(f"ERRO ao copiar '{origem}' -> '{destino}': {e}")
            return False

    log(f"ERRO: nao foi possivel copiar (arquivo bloqueado apos {COPY_RETRIES} tentativas): {destino}")
    return False


# =============================================================================
# BLOCO 6 - JANELA DE PROGRESSO (so aparece quando ha atualizacao)
# =============================================================================

class JanelaProgresso:
    """
    Janela simples e leve, exibida somente durante o processo de
    atualizacao. Comunicacao com a thread de trabalho via Queue, para nao
    travar a interface grafica durante a copia dos arquivos.
    """

    def __init__(self):
        self.fila = queue.Queue()
        self.janela = tk.Tk()
        self.janela.title("SpeedyERP - Atualizando")
        self.janela.geometry("420x130")
        self.janela.resizable(False, False)
        # Centraliza a janela na tela
        self.janela.eval('tk::PlaceWindow . center')
        self.janela.protocol("WM_DELETE_WINDOW", lambda: None)  # impede fechar no X

        tk.Label(self.janela, text="Atualizando o sistema, aguarde...",
                  font=("Segoe UI", 11, "bold")).pack(pady=(15, 5))

        self.label_status = tk.Label(self.janela, text="Preparando...",
                                      font=("Segoe UI", 9))
        self.label_status.pack(pady=(0, 10))

        self.barra = ttk.Progressbar(self.janela, orient="horizontal",
                                      length=380, mode="determinate")
        self.barra.pack(pady=5)

        self.label_percentual = tk.Label(self.janela, text="0%")
        self.label_percentual.pack()

        self.janela.after(100, self._processar_fila)

    def atualizar(self, status: str, percentual: float) -> None:
        """Chamado pela thread de trabalho para atualizar a tela (thread-safe)."""
        self.fila.put((status, percentual))

    def _processar_fila(self) -> None:
        """Le a fila e atualiza os widgets - roda sempre na thread da GUI."""
        try:
            while True:
                status, percentual = self.fila.get_nowait()
                self.label_status.config(text=status)
                self.barra["value"] = percentual
                self.label_percentual.config(text=f"{percentual:.0f}%")
        except queue.Empty:
            pass
        self.janela.after(100, self._processar_fila)

    def fechar(self) -> None:
        self.janela.destroy()

    def iniciar_loop(self) -> None:
        self.janela.mainloop()


# =============================================================================
# BLOCO 7 - PROCESSO DE ATUALIZACAO (roda em thread separada da GUI)
# =============================================================================

def executar_atualizacao(janela: JanelaProgresso) -> None:
    """
    Executa todo o fluxo de atualizacao, atualizando a janela de progresso.
    Ao final, fecha a janela e abre o sistema (sucesso ou nao).
    """
    try:
        janela.atualizar("Verificando servidor...", 0)
        log("Atualizacao necessaria. Iniciando processo.")

        janela.atualizar("Fechando o sistema, se estiver aberto...", 2)
        fechar_sistema()

        janela.atualizar("Verificando arquivos a atualizar...", 5)
        arquivos = listar_arquivos_a_copiar()

        if not arquivos:
            log("Nenhum arquivo pendente de copia (apenas versao sera atualizada).")
            janela.atualizar("Nenhum arquivo novo encontrado...", 90)
        else:
            total_bytes = sum(tam for _o, _d, tam in arquivos) or 1
            bytes_copiados = {"total": 0}
            falhas = 0

            def callback(n_bytes):
                bytes_copiados["total"] += n_bytes
                percentual = min(bytes_copiados["total"] / total_bytes * 85, 85)
                janela.atualizar("Copiando arquivos atualizados...", percentual)

            for origem, destino, _tamanho in arquivos:
                nome_curto = os.path.basename(origem)
                janela.atualizar(f"Copiando: {nome_curto}",
                                  min(bytes_copiados["total"] / total_bytes * 85, 85))
                sucesso = copiar_arquivo_com_progresso(origem, destino, callback)
                if not sucesso:
                    falhas += 1

            if falhas > 0:
                log(f"ERRO: {falhas} arquivo(s) nao puderam ser copiados.")
                janela.atualizar(f"Atencao: {falhas} arquivo(s) com falha na copia", 88)
                time.sleep(2)
            else:
                log(f"Copia concluida com sucesso ({len(arquivos)} arquivo(s)).")

        # Atualiza o arquivo de versao local somente se a leitura do servidor
        # funcionou (evita marcar como atualizado sem ter copiado nada)
        versao_servidor = ler_versao(SERVER_VERSION_FILE)
        if versao_servidor:
            try:
                with open(LOCAL_VERSION_FILE, "w", encoding="utf-8") as f:
                    f.write(versao_servidor)
                log(f"Versao local atualizada para {versao_servidor}.")
            except Exception as e:
                log(f"ERRO: falha ao gravar arquivo de versao local: {e}")

        janela.atualizar("Atualizacao concluida!", 100)
        time.sleep(0.6)

    except Exception as e:
        log(f"ERRO inesperado durante a atualizacao: {e}")
        janela.atualizar("Ocorreu um erro, abrindo o sistema...", 100)
        time.sleep(1)

    finally:
        # IMPORTANTE: abrir o sistema ANTES de fechar a janela.
        # janela.fechar() chama destroy(), o que encerra o mainloop() que
        # esta rodando na thread principal. Quando o mainloop termina, o
        # programa pode finalizar e encerrar esta thread (que e daemon)
        # antes que ela termine de executar as proximas instrucoes.
        # Chamando abrir_sistema() primeiro, garantimos que o processo do
        # SpeedyErp.exe ja foi disparado antes de qualquer risco de a
        # thread ser interrompida.
        #
        # permitir_dialogo_erro=False porque estamos em uma thread de
        # fundo - criar uma segunda janela Tk aqui poderia travar o
        # programa. Em caso de falha, o erro fica registrado no log e
        # exibido na propria janela de progresso, que e thread-safe.
        sucesso = abrir_sistema(permitir_dialogo_erro=False)
        if not sucesso:
            janela.atualizar(
                f"ERRO ao abrir o sistema. Verifique o log ({LOG_FILE}).", 100
            )
            time.sleep(3)
        janela.fechar()


# =============================================================================
# BLOCO 8 - ABRIR O SISTEMA
# =============================================================================

def abrir_sistema(permitir_dialogo_erro: bool = True) -> bool:
    """
    Abre o SpeedyErp.exe local. Retorna True se conseguiu iniciar o
    processo, False caso contrario.

    IMPORTANTE: esta funcao NAO usa sys.exit(). Quando chamada de dentro
    da thread de atualizacao (background), um sys.exit() so encerraria
    aquela thread silenciosamente, sem fechar o programa nem avisar o
    usuario - o erro passaria despercebido. Quem chama esta funcao decide
    o que fazer com o retorno (ex: encerrar o programa, se for chamada
    direto da thread principal).

    permitir_dialogo_erro=False deve ser usado quando a chamada vem de uma
    thread diferente da thread principal (ex: durante a atualizacao),
    pois o Tkinter nao e thread-safe: criar uma segunda janela Tk fora da
    thread principal pode travar ou derrubar o programa.
    """
    if not os.path.isfile(LOCAL_EXE):
        log(f"ERRO CRITICO: {EXE_NAME} nao encontrado em {LOCAL_DIR}.")
        if permitir_dialogo_erro:
            _mostrar_erro_critico()
        return False

    try:
        subprocess.Popen([LOCAL_EXE], cwd=LOCAL_DIR)
        log(f"{EXE_NAME} iniciado com sucesso.")
        return True
    except Exception as e:
        log(f"ERRO CRITICO: falha ao iniciar {EXE_NAME}: {e}")
        if permitir_dialogo_erro:
            _mostrar_erro_critico()
        return False


def _mostrar_erro_critico() -> None:
    """Mostra uma janela de erro simples quando o sistema nao pode ser aberto."""
    try:
        raiz = tk.Tk()
        raiz.withdraw()
        from tkinter import messagebox
        messagebox.showerror(
            "SpeedyERP - Erro",
            f"Nao foi possivel iniciar {EXE_NAME}.\n\n"
            f"Verifique se o arquivo existe em:\n{LOCAL_DIR}\n\n"
            f"Contate o suporte."
        )
        raiz.destroy()
    except Exception:
        pass


# =============================================================================
# BLOCO 9 - PROGRAMA PRINCIPAL
# =============================================================================

def main() -> None:
    log("=" * 50)
    log("Inicio da verificacao de atualizacao")

    if not servidor_disponivel():
        # Servidor fora do ar / sem acesso -> nao bloqueia o usuario,
        # apenas registra e abre a versao local direto, sem delay.
        log(f"AVISO: servidor indisponivel ou sem acesso ({SERVER_DIR}).")
        if not abrir_sistema():
            sys.exit(1)
        return

    if not precisa_atualizar():
        # Caminho "feliz": sem atualizacao -> abre IMEDIATAMENTE,
        # nenhuma janela e desenhada, sem delay perceptivel.
        log("Sistema ja atualizado. Abrindo sem atualizacao.")
        if not abrir_sistema():
            sys.exit(1)
        return

    # A partir daqui, ha atualizacao pendente -> mostra a janela de progresso
    janela = JanelaProgresso()
    thread_trabalho = threading.Thread(target=executar_atualizacao, args=(janela,), daemon=True)
    thread_trabalho.start()
    janela.iniciar_loop()  # bloqueia ate a janela ser fechada (fim da atualizacao)

    log("Fim da execucao do IniciarERP.py")


if __name__ == "__main__":
    main()
