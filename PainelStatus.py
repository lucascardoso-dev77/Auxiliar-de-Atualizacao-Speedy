"""
PainelStatus.py
=============================================================================
Painel de Monitoramento em Tempo Real - IniciarERP / IniciarNFCe
=============================================================================
Este programa roda no SERVIDOR (nao nos terminais). Ele le os arquivos de
status que cada terminal grava (na pasta configurada em status_dir do
config.ini de cada terminal) e mostra tudo em uma pagina web, atualizada
automaticamente a cada poucos segundos.

Como usar:
    1. Ajuste painel_config.ini (pasta de status e porta).
    2. Rode este programa (ou o PainelStatus.exe compilado).
    3. Abra no navegador: http://<ip-ou-nome-do-servidor>:8090
       (ou a porta configurada). Pode ser acessado de qualquer computador
       da rede, nao so do servidor.

Nao usa nenhuma biblioteca externa - so o que ja vem com o Python, para
poder rodar em qualquer servidor Windows sem instalar nada extra (ou ser
compilado em um .exe standalone com o mesmo Empacotar.bat).
=============================================================================
"""

import os
import sys
import json
import configparser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# =============================================================================
# BLOCO 1 - CONFIGURACAO
# =============================================================================

DEFAULTS = {
    "status_dir": r"\\Servidor\10.7\_status",
    "porta": "8090",
    # Depois de quantos minutos sem nenhuma execucao um terminal passa a
    # ser mostrado como "sem contato" (cinza), mesmo que o ultimo status
    # gravado tenha sido "atualizado".
    "minutos_para_sem_contato": "180",
}


def get_local_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def carregar_configuracoes(local_dir: str) -> dict:
    caminho_ini = os.path.join(local_dir, "painel_config.ini")
    parser = configparser.ConfigParser()
    parser["Config"] = DEFAULTS.copy()
    if os.path.isfile(caminho_ini):
        try:
            parser.read(caminho_ini, encoding="utf-8-sig")
        except Exception:
            pass
    secao = parser["Config"]
    return {
        "status_dir": secao.get("status_dir", DEFAULTS["status_dir"]).strip(),
        "porta": secao.getint("porta", fallback=8090),
        "minutos_para_sem_contato": secao.getint("minutos_para_sem_contato", fallback=180),
    }


LOCAL_DIR = get_local_dir()
CFG = carregar_configuracoes(LOCAL_DIR)
STATUS_DIR = CFG["status_dir"]
PORTA = CFG["porta"]
MINUTOS_SEM_CONTATO = CFG["minutos_para_sem_contato"]


# =============================================================================
# BLOCO 2 - LEITURA DOS STATUS DOS TERMINAIS
# =============================================================================

def ler_versao_arquivo(caminho: str) -> str:
    """Le um arquivo de versao (ex: versao.txt) diretamente do servidor."""
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def coletar_status() -> list:
    """
    Le todos os arquivos .json da pasta de status e monta a lista de
    terminais com a situacao atual de cada um. A versao do servidor e
    RELIDA agora (nao usa apenas o que o terminal reportou), para detectar
    quem ficou desatualizado mesmo sem ter reaberto o sistema.
    """
    resultado = []

    if not os.path.isdir(STATUS_DIR):
        return resultado

    agora = datetime.now()

    for nome_arquivo in os.listdir(STATUS_DIR):
        if not nome_arquivo.lower().endswith(".json"):
            continue

        caminho = os.path.join(STATUS_DIR, nome_arquivo)
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except Exception:
            continue  # arquivo sendo escrito nesse instante ou corrompido - ignora neste ciclo

        # Rele a versao atual do servidor (nao a que o terminal viu por
        # ultimo), para refletir publicacoes novas em tempo real
        versao_servidor_atual = ler_versao_arquivo(dados.get("arquivo_versao_servidor", "")) \
            or dados.get("versao_servidor", "")

        versao_local = dados.get("versao_local", "")
        situacao_reportada = dados.get("situacao", "desconhecido")

        # Calcula ha quanto tempo o terminal deu noticia
        minutos_desde_ultimo_contato = None
        try:
            data_hora = datetime.strptime(dados.get("data_hora", ""), "%Y-%m-%d %H:%M:%S")
            minutos_desde_ultimo_contato = (agora - data_hora).total_seconds() / 60
        except Exception:
            pass

        # Decide a situacao final exibida no painel
        if minutos_desde_ultimo_contato is not None and minutos_desde_ultimo_contato > MINUTOS_SEM_CONTATO:
            situacao_final = "sem_contato"
        elif situacao_reportada == "erro":
            situacao_final = "erro"
        elif situacao_reportada == "atualizando":
            situacao_final = "atualizando"
        elif versao_servidor_atual and versao_local != versao_servidor_atual:
            situacao_final = "desatualizado"
        else:
            situacao_final = "atualizado"

        resultado.append({
            "terminal": dados.get("terminal", "?"),
            "ip": dados.get("ip", ""),
            "sistema": dados.get("sistema", dados.get("exe_name", "?")),
            "versao_local": versao_local,
            "versao_servidor": versao_servidor_atual,
            "situacao": situacao_final,
            "mensagem": dados.get("mensagem", ""),
            "data_hora": dados.get("data_hora", ""),
        })

    # Ordena por sistema e depois por nome do terminal, para ficar estavel na tela
    resultado.sort(key=lambda x: (x["sistema"], x["terminal"]))
    return resultado


# =============================================================================
# BLOCO 3 - PAGINA HTML DO PAINEL (auto-atualizavel via JavaScript)
# =============================================================================

PAGINA_HTML = """<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<title>Painel de Monitoramento - SpeedyERP</title>
<style>
  :root {
    --azul: #1f5c99; --verde: #2e7d32; --verde-bg: #e8f5e9;
    --vermelho: #c62828; --vermelho-bg: #fdecea;
    --laranja: #b95c00; --laranja-bg: #fff1e0;
    --cinza: #616161; --cinza-bg: #f0f0f0;
  }
  * { box-sizing: border-box; }
  body {
    font-family: Segoe UI, Arial, sans-serif; background: #f4f6f8; margin: 0;
    color: #222;
  }
  header {
    background: var(--azul); color: white; padding: 18px 28px;
    display: flex; justify-content: space-between; align-items: center;
  }
  header h1 { font-size: 20px; margin: 0; }
  header span { font-size: 13px; opacity: 0.85; }
  .cards {
    display: flex; gap: 14px; padding: 20px 28px 0 28px; flex-wrap: wrap;
  }
  .card {
    flex: 1; min-width: 130px; background: white; border-radius: 8px;
    padding: 14px 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    border-left: 5px solid #ccc;
  }
  .card .num { font-size: 26px; font-weight: 700; }
  .card .lbl { font-size: 12px; color: #666; }
  .card.total { border-color: var(--azul); }
  .card.ok { border-color: var(--verde); }
  .card.desat { border-color: var(--laranja); }
  .card.erro { border-color: var(--vermelho); }
  .card.semcontato { border-color: var(--cinza); }
  table {
    width: calc(100% - 56px); margin: 20px 28px 40px 28px; border-collapse: collapse;
    background: white; border-radius: 8px; overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }
  th, td { padding: 10px 14px; text-align: left; font-size: 13px; }
  th { background: #eef2f6; color: #444; font-weight: 600; }
  tr:not(:last-child) td { border-bottom: 1px solid #eee; }
  .badge {
    display: inline-block; padding: 3px 10px; border-radius: 12px;
    font-size: 12px; font-weight: 600;
  }
  .badge.atualizado { background: var(--verde-bg); color: var(--verde); }
  .badge.desatualizado { background: var(--laranja-bg); color: var(--laranja); }
  .badge.erro { background: var(--vermelho-bg); color: var(--vermelho); }
  .badge.atualizando { background: #e3f2fd; color: #1565c0; }
  .badge.sem_contato { background: var(--cinza-bg); color: var(--cinza); }
  .vazio { padding: 40px; text-align: center; color: #888; }
  footer { text-align: center; padding: 10px; color: #999; font-size: 12px; }
</style>
</head>
<body>

<header>
  <h1>Painel de Monitoramento - Atualizacoes</h1>
  <span id="relogio"></span>
</header>

<div class="cards" id="cards"></div>

<div id="conteudo-tabela"></div>

<footer>Atualiza automaticamente a cada 5 segundos - pode manter esta pagina aberta em um monitor da sala de TI.</footer>

<script>
const TEXTO_SITUACAO = {
  atualizado: "Atualizado",
  desatualizado: "Desatualizado",
  erro: "Erro",
  atualizando: "Atualizando...",
  sem_contato: "Sem contato",
};

function escapeHtml(t) {
  const d = document.createElement("div");
  d.innerText = t == null ? "" : t;
  return d.innerHTML;
}

async function atualizar() {
  document.getElementById("relogio").innerText = new Date().toLocaleString("pt-BR");
  try {
    const resp = await fetch("/api/status", { cache: "no-store" });
    const dados = await resp.json();
    renderizar(dados);
  } catch (e) {
    document.getElementById("conteudo-tabela").innerHTML =
      '<div class="vazio">Nao foi possivel carregar o status agora. Tentando novamente...</div>';
  }
}

function renderizar(dados) {
  const total = dados.length;
  const cont = { atualizado: 0, desatualizado: 0, erro: 0, atualizando: 0, sem_contato: 0 };
  dados.forEach(d => { if (cont[d.situacao] !== undefined) cont[d.situacao]++; });

  document.getElementById("cards").innerHTML = `
    <div class="card total"><div class="num">${total}</div><div class="lbl">Terminais monitorados</div></div>
    <div class="card ok"><div class="num">${cont.atualizado}</div><div class="lbl">Atualizados</div></div>
    <div class="card desat"><div class="num">${cont.desatualizado + cont.atualizando}</div><div class="lbl">Desatualizados / Atualizando</div></div>
    <div class="card erro"><div class="num">${cont.erro}</div><div class="lbl">Com erro</div></div>
    <div class="card semcontato"><div class="num">${cont.sem_contato}</div><div class="lbl">Sem contato</div></div>
  `;

  if (total === 0) {
    document.getElementById("conteudo-tabela").innerHTML =
      '<div class="vazio">Nenhum terminal reportou status ainda. Verifique se status_dir esta configurado nos terminais.</div>';
    return;
  }

  let linhas = "";
  dados.forEach(d => {
    linhas += `<tr>
      <td>${escapeHtml(d.terminal)}</td>
      <td>${escapeHtml(d.ip)}</td>
      <td>${escapeHtml(d.sistema)}</td>
      <td>${escapeHtml(d.versao_local)}</td>
      <td>${escapeHtml(d.versao_servidor)}</td>
      <td><span class="badge ${d.situacao}">${TEXTO_SITUACAO[d.situacao] || d.situacao}</span></td>
      <td>${escapeHtml(d.mensagem)}</td>
      <td>${escapeHtml(d.data_hora)}</td>
    </tr>`;
  });

  document.getElementById("conteudo-tabela").innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Terminal</th><th>IP</th><th>Sistema</th><th>Versao Local</th>
          <th>Versao Servidor</th><th>Situacao</th><th>Mensagem</th><th>Ultimo Contato</th>
        </tr>
      </thead>
      <tbody>${linhas}</tbody>
    </table>
  `;
}

atualizar();
setInterval(atualizar, 5000);
</script>

</body>
</html>
"""


# =============================================================================
# BLOCO 4 - SERVIDOR WEB (http.server puro, sem dependencias externas)
# =============================================================================

class HandlerPainel(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # silencia o log padrao do http.server no console

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._responder_html(PAGINA_HTML)
        elif self.path.startswith("/api/status"):
            self._responder_json(coletar_status())
        else:
            self.send_response(404)
            self.end_headers()

    def _responder_html(self, html: str):
        corpo = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _responder_json(self, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


def main():
    print("=" * 60)
    print(" Painel de Monitoramento - IniciarERP / IniciarNFCe")
    print("=" * 60)
    print(f" Pasta de status monitorada: {STATUS_DIR}")
    print(f" Acesse em: http://localhost:{PORTA}")
    print(f" Ou de outro computador da rede: http://<ip-deste-servidor>:{PORTA}")
    print(" Pressione CTRL+C para encerrar.")
    print("=" * 60)

    servidor = ThreadingHTTPServer(("0.0.0.0", PORTA), HandlerPainel)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando o painel...")
        servidor.shutdown()


if __name__ == "__main__":
    main()
