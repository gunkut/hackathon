---
inclusion: always
---

# Proje Yapısı

Proje: `/workshop/SktRiskAgent` (`agentcore create --template agent-python-strands` ile iskeletlendi; klasör adı tarihsel, ürün adı TazeRota).

```
SktRiskAgent/
├── agentcore/                    # agentcore.json (runtime `agent`, envVars, additionalPolicies), cdk/
├── data/input/dataa.xlsx         # Tek veri kaynağı
├── src/data/
│   ├── excel_source.py           # Excel okuyucu + ExcelRepository (testler)
│   ├── create_tables.py          # tazerota-* tabloları (tekrar çalıştırılabilir)
│   └── seed_dynamodb.py          # Ham sayfaları DynamoDB'ye yükler
├── app/agent/                    # AgentCore runtime kodu (CodeZip)
│   ├── main.py, parse.py, memory/  # Şablon (lazy init); parse/memory değiştirilmez
│   ├── model/load.py             # Bedrock modeli (MODEL_ID)
│   ├── engine/
│   │   ├── config.py             # AS_OF_DATE, tablo adları, eşikler
│   │   ├── loader.py             # DynamoDB Repository (tablo başına tek scan, önbellek)
│   │   ├── planner.py            # İş kuralları: build_plan, plan_rows, find_lot
│   │   └── approvals.py          # Onay kaydı
│   ├── tools/skt_tools.py        # Strands @tool sarmalayıcıları
│   ├── prompts/system_prompt.py  # TazeRota Ajanı (Türkçe)
│   ├── policies/dynamodb-read.json
│   ├── tests/test_planner.py     # Excel'e karşı golden testler (AWS'siz)
│   └── pyproject.toml            # Runtime bağımlılıkları; pytest/openpyxl/fastapi/uvicorn yalnızca dev
└── ui/
    ├── server.py                 # FastAPI: panel API + sohbet köprüsü (port 8090)
    └── static/                   # index.html, styles.css, app.js (göreli yollar; /proxy/8090/ altında çalışır)
```

## Kurallar
- İş mantığı yalnızca `engine/` içinde. `tools/` ve `ui/server.py` engine'i çağırır.
- Panel çalıştırma: `cd app/agent && uv run python ../../ui/server.py`. Yedek mod (runtime erişilemezse): `CHAT_MODE=local`.
- Testler: `cd app/agent && uv run pytest`.
- Ports: 8080 (IDE) ve 8081 (`agentcore dev`) kullanılmaz; panel 8090.
- İç alan adları İngilizce, kullanıcıya dönük metin Türkçe. `data/output/` git'e eklenmez.
