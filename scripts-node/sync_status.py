import os
import time
import requests

# Token vem de variável de ambiente (definida como secret no GitHub Actions).
# Localmente, pode ser exportada no terminal ou colocada num arquivo
# notion_token.txt na mesma pasta (mesmo esquema do hiatus.py original).
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notion_token.txt")


def carregar_token():
    if os.environ.get("NOTION_TOKEN"):
        return os.environ["NOTION_TOKEN"]
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


NOTION_TOKEN = carregar_token()

if not NOTION_TOKEN:
    raise SystemExit(
        "❌ Token do Notion não encontrado.\n"
        f"   Crie o arquivo '{TOKEN_FILE}' com o token dentro,\n"
        "   ou defina a variável de ambiente NOTION_TOKEN."
    )

# IMPORTANTE: desde a API 2025-09-03, consultas (query) são feitas contra a
# DATA SOURCE, não contra a database diretamente.
DATA_SOURCE_ID = "1fdbbc5dc147829382c487d15b0c603c"

HEADERS_NOTION = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2025-09-03"
}

URL_ANILIST = "https://graphql.anilist.co"
REQUEST_TIMEOUT = 30

ANILIST_QUERY = '''
query ($id: Int) {
  Media (id: $id, type: MANGA) {
    id
    status(version: 2)
    title {
      romaji
    }
  }
}
'''

# Mapeamento completo do AniList para os nomes exatos das categorias no Notion.
# Cobre tanto entrada quanto saída de Hiatus, e demais transições.
MAPEAMENTO_STATUS = {
    "RELEASING": "Releasing",
    "HIATUS": "Hiatus",
    "FINISHED": "Finished",
    "CANCELLED": "Cancelled",
    "NOT_YET_RELEASED": "Not Yet Released"
}


def obter_mangas_para_verificar():
    """Busca no Notion todos os mangás em Releasing, Not Yet Released ou Hiatus
    (são os únicos status que ainda podem mudar - Finished/Cancelled são terminais)."""
    url = f"https://api.notion.com/v1/data_sources/{DATA_SOURCE_ID}/query"

    filtro = {
        "filter": {
            "or": [
                {"property": "status", "select": {"equals": "Releasing"}},
                {"property": "status", "select": {"equals": "Not Yet Released"}},
                {"property": "status", "select": {"equals": "Hiatus"}},
            ]
        }
    }

    mangas = []
    has_more = True
    start_cursor = None

    print("🔄 Buscando mangás elegíveis (Releasing / Not Yet Released / Hiatus) na sua database do Notion...")

    while has_more:
        if start_cursor:
            filtro["start_cursor"] = start_cursor

        response = requests.post(url, json=filtro, headers=HEADERS_NOTION, timeout=REQUEST_TIMEOUT)

        if response.status_code != 200:
            print(f"❌ Erro ao acessar o Notion: {response.text}")
            break

        data = response.json()
        mangas.extend(data.get("results", []))

        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor", None)

    print(f"✅ Total de mangás encontrados para verificar: {len(mangas)}")
    return mangas


def consultar_anilist(anilist_id):
    """Consulta o status atual do mangá no AniList respeitando o Rate Limit."""
    variables = {'id': int(anilist_id)}

    while True:
        try:
            response = requests.post(
                URL_ANILIST,
                json={'query': ANILIST_QUERY, 'variables': variables},
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60)) + 2
                print(f"⚠️ Rate limit atingido no AniList. Aguardando {retry_after} segundos...")
                time.sleep(retry_after)
                continue

            if response.status_code != 200:
                return None

            res_json = response.json()
            return res_json.get("data", {}).get("Media", None)
        except Exception as e:
            print(f"❌ Erro na requisição do AniList para o ID {anilist_id}: {e}")
            return None


def atualizar_status_notion(page_id, novo_status, titulo):
    """Atualiza a coluna de Status do item no Notion."""
    url = f"https://api.notion.com/v1/pages/{page_id}"

    payload = {
        "properties": {
            "status": {
                "select": {
                    "name": novo_status
                }
            }
        }
    }

    response = requests.patch(url, json=payload, headers=HEADERS_NOTION, timeout=REQUEST_TIMEOUT)
    if response.status_code == 200:
        print(f"✨ [NOTION ATUALIZADO] '{titulo}' -> Alterado para '{novo_status}'")
        return True
    else:
        print(f"❌ Erro ao atualizar '{titulo}' no Notion: {response.text}")
        return False


def extrair_titulo(props):
    for prop_name in ["Name", "Title", "Nome", "Manga"]:
        prop = props.get(prop_name)
        if prop and prop.get("title"):
            titles = prop["title"]
            if titles and "text" in titles[0]:
                return titles[0]["text"]["content"]
    return "Mangá Sem Título"


def extrair_anilist_id(props):
    anilist_id_prop = props.get("anilistid", {})

    if anilist_id_prop.get("type") == "number":
        return anilist_id_prop.get("number")

    if anilist_id_prop.get("type") == "rich_text":
        text_list = anilist_id_prop.get("rich_text", [])
        if text_list:
            valor = text_list[0].get("text", {}).get("content", "").strip()
            return valor or None

    return None


def main():
    mangas_notion = obter_mangas_para_verificar()

    print("Iniciando varredura e atualização automatizada...")

    atualizados = 0
    total = len(mangas_notion)

    for indice, item in enumerate(mangas_notion, start=1):
        page_id = item["id"]
        props = item["properties"]

        titulo = extrair_titulo(props)
        print(f"🔍 [{indice}/{total}] Verificando: {titulo}")

        status_atual_notion = props.get("status", {}).get("select", {}).get("name")
        anilist_id = extrair_anilist_id(props)

        if not anilist_id:
            print(f"   ⏭️ Sem anilistid preenchido, pulando.")
            continue

        dados_anilist = consultar_anilist(anilist_id)

        # Pausa obrigatória e segura para NUNCA estourar o limite de requisições por minuto do AniList
        time.sleep(2.5)

        if not dados_anilist:
            print(f"❓ Não foi possível obter dados para o mangá: {titulo} (ID: {anilist_id})")
            continue

        status_anilist_cru = dados_anilist.get("status")
        status_traduzido_notion = MAPEAMENTO_STATUS.get(status_anilist_cru)

        if status_traduzido_notion and status_traduzido_notion != status_atual_notion:
            print(f"📢 Mudança detectada em '{titulo}': '{status_atual_notion}' -> '{status_anilist_cru}'")
            sucesso = atualizar_status_notion(page_id, status_traduzido_notion, titulo)
            if sucesso:
                atualizados += 1
        else:
            print(f"   ✅ Sem mudanças (status atual: '{status_atual_notion}')")

    print(f"\n🎯 Varredura concluída! Total de mangás atualizados nesta rodada: {atualizados}")


if __name__ == "__main__":
    main()
