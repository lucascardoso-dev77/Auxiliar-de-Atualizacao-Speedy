@echo off
REM ============================================================================
REM  Empacotar.bat
REM  Script auxiliar de DESENVOLVIMENTO - roda apenas na maquina de quem
REM  mantem o sistema, NUNCA nos terminais dos clientes.
REM
REM  Finalidade: compilar o IniciarERP.py em DOIS executaveis diferentes,
REM  sem janela de console, usando PyInstaller:
REM
REM    - IniciarERP.exe   (usa config.ini      -> sincroniza tudo)
REM    - IniciarNFCe.exe  (usa config_nfce.ini -> sincroniza so o
REM                        SpeedyNfce.exe e a pasta Relatorios)
REM
REM  Os dois executaveis vem do MESMO codigo-fonte (IniciarERP.py). O que
REM  muda o comportamento de cada um e o config.ini que acompanha cada
REM  executavel na pasta de instalacao do terminal.
REM
REM  Pre-requisito: Python 3 instalado nesta maquina (nos terminais dos
REM  clientes NAO e necessario ter Python - so o .exe final).
REM ============================================================================

setlocal

echo ============================================================
echo   Empacotando IniciarERP.py em executaveis (.exe)
echo ============================================================
echo.

REM ----------------------------------------------------------------------
REM PASSO 1 - Verifica se o Python esta instalado e acessivel no PATH
REM ----------------------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao foi encontrado no PATH desta maquina.
    echo        Instale o Python 3 ^(python.org^) e marque a opcao
    echo        "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

REM ----------------------------------------------------------------------
REM PASSO 2 - Verifica/instala o PyInstaller
REM ----------------------------------------------------------------------
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [INFO] PyInstaller nao encontrado. Instalando...
    python -m pip install --upgrade pip >nul 2>&1
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar o PyInstaller. Verifique sua conexao
        echo        com a internet ou tente instalar manualmente com:
        echo        python -m pip install pyinstaller
        echo.
        pause
        exit /b 1
    )
) else (
    echo [OK] PyInstaller ja esta instalado.
)
echo.

REM ----------------------------------------------------------------------
REM PASSO 3 - Verifica se o arquivo fonte existe nesta pasta
REM ----------------------------------------------------------------------
if not exist "%~dp0IniciarERP.py" (
    echo [ERRO] Arquivo IniciarERP.py nao encontrado nesta pasta.
    echo        Coloque este Empacotar.bat na mesma pasta do IniciarERP.py.
    echo.
    pause
    exit /b 1
)

REM ----------------------------------------------------------------------
REM PASSO 4 - Limpa builds anteriores (evita confusao com versao antiga)
REM ----------------------------------------------------------------------
echo [INFO] Limpando compilacoes anteriores, se existirem...
if exist "%~dp0build" rd /s /q "%~dp0build"
if exist "%~dp0dist" rd /s /q "%~dp0dist"
if exist "%~dp0IniciarERP.spec" del /q "%~dp0IniciarERP.spec"
if exist "%~dp0IniciarNFCe.spec" del /q "%~dp0IniciarNFCe.spec"
echo.

REM ----------------------------------------------------------------------
REM PASSO 5 - Compila o IniciarERP.exe
REM   --onefile     -> gera um unico arquivo .exe (mais facil de distribuir)
REM   --noconsole   -> nao abre janela preta de console junto com o programa
REM   --name        -> define o nome final do executavel gerado
REM ----------------------------------------------------------------------
echo [INFO] Compilando IniciarERP.exe, aguarde...
echo.
cd /d "%~dp0"
python -m PyInstaller --onefile --noconsole --name IniciarERP IniciarERP.py

if errorlevel 1 (
    echo.
    echo [ERRO] A compilacao do IniciarERP.exe falhou. Verifique as mensagens acima.
    echo.
    pause
    exit /b 1
)

REM ----------------------------------------------------------------------
REM PASSO 6 - Compila o IniciarNFCe.exe (mesmo codigo-fonte, nome diferente)
REM ----------------------------------------------------------------------
echo.
echo [INFO] Compilando IniciarNFCe.exe, aguarde...
echo.
python -m PyInstaller --onefile --noconsole --name IniciarNFCe IniciarERP.py

if errorlevel 1 (
    echo.
    echo [ERRO] A compilacao do IniciarNFCe.exe falhou. Verifique as mensagens acima.
    echo.
    pause
    exit /b 1
)

REM ----------------------------------------------------------------------
REM PASSO 7 - Organiza a saida em duas pastas prontas para distribuicao:
REM           Distribuir\ERP  e  Distribuir\NFCe
REM ----------------------------------------------------------------------
set "SAIDA_ERP=%~dp0Distribuir\ERP"
set "SAIDA_NFCE=%~dp0Distribuir\NFCe"
if not exist "%SAIDA_ERP%" mkdir "%SAIDA_ERP%"
if not exist "%SAIDA_NFCE%" mkdir "%SAIDA_NFCE%"

copy /y "%~dp0dist\IniciarERP.exe" "%SAIDA_ERP%\IniciarERP.exe" >nul
copy /y "%~dp0dist\IniciarNFCe.exe" "%SAIDA_NFCE%\IniciarNFCe.exe" >nul

if exist "%~dp0config.ini" (
    copy /y "%~dp0config.ini" "%SAIDA_ERP%\config.ini" >nul
) else (
    echo [AVISO] config.ini nao encontrado nesta pasta - lembre-se de
    echo         criar um antes de distribuir o IniciarERP para os terminais.
)

if exist "%~dp0config_nfce.ini" (
    copy /y "%~dp0config_nfce.ini" "%SAIDA_NFCE%\config.ini" >nul
) else (
    echo [AVISO] config_nfce.ini nao encontrado nesta pasta - lembre-se de
    echo         criar um antes de distribuir o IniciarNFCe para os terminais.
)

echo.
echo ============================================================
echo   [OK] Compilacao concluida!
echo.
echo   IniciarERP.exe  + config.ini   -^> %SAIDA_ERP%
echo   IniciarNFCe.exe + config.ini   -^> %SAIDA_NFCE%
echo.
echo   Copie cada par de arquivos para a pasta de instalacao
echo   correspondente em cada terminal (ERP e/ou NFCe) e ajuste
echo   o server_dir do config.ini de cada um.
echo ============================================================
echo.
pause

endlocal
exit /b 0
