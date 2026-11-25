# TazeRota · SKT Kurtarma Paneli

Takım Wakanda · Tedarik Zincirinde Agentic AI Hackathonu (25.11.2026)

Merkez depodaki son kullanma tarihi (SKT) yaklaşan lotları, sakıncalı sevk tarihi geçmeden bayilere yönlendiren
insan onaylı bir yapay zekâ ajanı. Ajan analiz eder ve önerir, sevk emri ancak planlamacı panelden **Onayla**
dediğinde oluşur.

**Sonuç (örnek veri, 60/180 gün eşikleri):** 6 riskli lot, 967 adet. Bayilere 885 adet (%91,5), bağışa 82 adet (%8,5),
imha %0. Müdahalesiz senaryoda imha %15,6 (151 adet). Erken uyarı: 3 lotta ~275 adet fazla.

## Mimari

```
Tarayıcı ─► Lambda Function URL (FastAPI panel, Lambda Web Adapter, response streaming)
               ├─ Panel verisi ─► deterministik motor (app/agent/engine) ─► DynamoDB
               └─ Sohbet ──────► Amazon Bedrock AgentCore Runtime (Strands ajanı) ─► Bedrock Claude
                                                         └─ araçlar ─► aynı motor ─► DynamoDB
```

- **Ajan:** [Strands Agents SDK](https://strandsagents.com), Amazon Bedrock AgentCore Runtime üzerinde, model Claude Sonnet 5.
- **Tasarım ilkesi:** LLM sayı hesaplamaz. Tahmin, kapasite, dağıtım ve KPI hesabı `engine/planner.py` içinde yapılır.
  Panel ve ajan aynı motoru kullanır.
- **İnsan onayı:** Onay lot bazındadır. Ajanın `create_dispatch_orders` aracı, lotun onay kaydı yoksa emir oluşturmayı reddeder.
- **Veri:** Amazon DynamoDB (`tazerota-lots`, `-dealers`, `-sales`, `-approvals`, `-orders`), kaynak `data/input/dataa.xlsx`.

## İş kuralları

- Günlük talep = 0,6 × son 7 gün ortalaması + 0,4 × 15 gün ortalaması
- Bayi kapasitesi = ⌊talep × (SKT'ye kalan gün − teslim süresi) − bayi stoğu⌋
- Riskli lot: sakıncalı sevk tarihine ≤ 60 gün. Erken uyarı: 61–180 gün. Eşikler panelden değiştirilebilir.
- Sırayla: en yüksek kapasiteli bayiye sevk → kalan bağışa → bağışa uygun değilse imha
- Ayrıntı: [.kiro/steering/data-contracts.md](.kiro/steering/data-contracts.md)

## Klasörler

| Yol | İçerik |
|---|---|
| `app/agent/` | AgentCore runtime kodu: `main.py`, `engine/` (iş kuralları), `tools/` (Strands araçları), `prompts/` |
| `ui/` | Panel: `server.py` (FastAPI) ve `static/` (HTML/CSS/JS) |
| `src/data/` | Excel okuyucu, DynamoDB tablo kurulumu ve veri yükleme |
| `infra/` | Panelin Lambda'ya deploy script'i |
| `agentcore/` | AgentCore CLI yapılandırması ve CDK |
| `docs/diagrams/` | draw.io diyagramları |
| `.kiro/` | Kiro steering ve skill dosyaları |

## Kurulum

Gereksinimler: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 20+, AWS CDK, AgentCore CLI
(`npm install -g @aws/agentcore@1.0.3`), Bedrock ve AgentCore erişimi olan AWS kimlik bilgileri (us-east-1).

> **Veri dosyası depoda yok.** `data/input/dataa.xlsx` paylaşılamadığı için depoya eklenmedi. Veri yükleme ve
> testler için dosyayı `data/input/dataa.xlsx` yoluna koyun. Beklenen sayfalar ve kolonlar:
> [.kiro/steering/data-contracts.md](.kiro/steering/data-contracts.md).

```bash
cd app/agent
uv sync

# 1. DynamoDB tabloları ve veri
uv run python ../../src/data/create_tables.py
PYTHONPATH=../../src/data uv run python ../../src/data/seed_dynamodb.py

# 2. Testler (AWS gerekmez): motoru Excel'in hesapladığı sayfalarla karşılaştırır
uv run pytest

# 3. Ajanı deploy et (proje kökünden)
cd ../.. && agentcore deploy

# 4a. Paneli yerelde çalıştır (http://localhost:8090)
cd app/agent && uv run python ../../ui/server.py

# 4b. Paneli AWS Lambda'ya deploy et (proje kökünden; public URL ve şifre üretir)
bash infra/deploy_frontend.sh
```

Model ID'si `app/agent/model/load.py` içinde (`MODEL_ID` ortam değişkeniyle değiştirilebilir).

## Notlar

- Hesap tarihi veri setine göre sabittir: 25.11.2026.
- Bildirimler panelde kayıt olarak tutulur; e-posta veya SMS gönderilmez.
- Kaldırma: `bash infra/deploy_frontend.sh --delete` (panel), `agentcore remove all --yes && agentcore deploy --yes` (ajan).
  DynamoDB tabloları ayrıca silinmelidir.
