---
name: build-tazerota
description: TazeRota (SKT Kurtarma Paneli) projesini dataa.xlsx'ten DynamoDB'ye yükle, Excel kurallarıyla planı hesaplayan motoru ve Strands ajanını çalıştır, AgentCore'a deploy et ve paneli başlat.
---

# TazeRota: kur, doğrula, deploy et, paneli çalıştır

Kurallar ve şemalar: `product.md`, `tech.md`, `structure.md`, `data-contracts.md`. Genel dağıtım kuralları: `agentcore-deployment.md`, `strands-agent-coding.md`.
Proje zaten kurulu: `/workshop/SktRiskAgent`. Klasörü elle yeniden oluşturma; yoksa `agentcore create --name SktRiskAgent --template agent-python-strands` ile iskeletle.

## 1. Veri
```bash
cd /workshop/SktRiskAgent/app/agent
uv sync
uv run python ../../src/data/create_tables.py
PYTHONPATH=../../src/data uv run python ../../src/data/seed_dynamodb.py
```
Beklenen: 50 lot, 235 bayi kaydı (5 profil + 230 stok), 3.450 satış.

## 2. Motoru doğrula (AWS'siz)
```bash
uv run pytest
```
7 test geçmeli. Testler motoru Excel'in ham sayfalarıyla çalıştırıp `Riskli_Lot_Kontrol` ve `Erken_Uyari` sayfalarıyla karşılaştırır. Kuralları değiştirirsen bu testleri kır, sonra düzelt.

## 3. Model
Hesapta model izin listesi var (`ws-bedrock-model-allowlist-policy-1`): `claude-sonnet-5-5` ve `claude-haiku-5-5` engelli. Kullanılan: `global.anthropic.claude-sonnet-5` (`model/load.py`, `MODEL_ID` ile ezilebilir). Yeni model denemek için küçük bir `converse` çağrısı yap; izin listesini değiştirmeye çalışma.

## 4. Deploy
```bash
cd /workshop/SktRiskAgent
agentcore deploy --yes
agentcore status --json
```
`agentcore.json` içinde `UNIFIED_TRACES_DESTINATION_ENABLED=true` ve `additionalPolicies: ["policies/dynamodb-read.json"]` kalmalı.
Test (session id ≥ 33 karakter):
```bash
agentcore invoke --runtime agent --session-id tazerota-demo-session-0000000000001 \
  --payload '{"prompt":"Riskli lotları analiz et ve öneri ver","actorId":"tazerota-panel"}'
```

## 5. Panel
```bash
cd /workshop/SktRiskAgent/app/agent
uv run python ../../ui/server.py            # sohbet: deploy edilmiş runtime
CHAT_MODE=local uv run python ../../ui/server.py   # yedek: ajan süreç içinde
```
Kiro IDE tarayıcısında `/proxy/8090/` adresini aç. 8080 ve 8081 portlarına dokunma.
Kontrol: KPI'lar 6 / 885 / 82 / %0 (müdahalesiz %15,6) / 3 lot; Pınar Hindi Uzun Sosis detayında kapasiteler 25/18/9/9/4.

## Sorun giderme
- `AccessDeniedException ... explicit deny ... model-allowlist`: izinli bir model seç (bölüm 3).
- `AccessDeniedException ... AWS Marketplace`: IDE terminalinde bir kez `enable_anthropic_models`, 2–6 dk bekle.
- `AccessDeniedException ... dynamodb` (yalnızca deploy edilmiş ajanda): `additionalPolicies` ve tablo adlarını kontrol et, yeniden deploy et. Rolü elle düzenleme.
- Panel sohbeti "Ajana ulaşılamadı": `AGENT_RUNTIME_ARN` ortam değişkenini ver veya `CHAT_MODE=local` kullan.
