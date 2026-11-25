---
inclusion: always
---

# Teknoloji Kararları

Genel Strands ve AgentCore kuralları `strands-agent-coding.md` ve `agentcore-deployment.md` dosyalarındadır. Bu dosya yalnızca bu projeye özel kararları içerir. Çakışma olursa bu dosya geçerlidir.

## Yığın
- Python 3.12+, tip ipuçları, PEP 8
- Strands Agents SDK (`@tool`), Amazon Bedrock Claude, Amazon Bedrock AgentCore Runtime (`agentcore deploy`)
- Veri: Amazon DynamoDB, 4 tablo (`tazerota-*`, bkz. `data-contracts.md`); runtime'da yalnızca boto3
- Panel: FastAPI + statik HTML/CSS/JS (`ui/`), yerelde port 8090
- Test: pytest + openpyxl (yalnızca `[dependency-groups] dev`)

## Model seçimi
- Model ID'yi sabit yazma. `aws bedrock list-foundation-models --by-provider Anthropic` ile aktif modeli bul, `global.` ön ekini ekle.
- Model ID'yi tek yerde tut: `app/agent/model/load.py` (`MODEL_ID` ortam değişkeniyle ezilebilir).
- Bu hesapta bir model izin listesi var (`ws-bedrock-model-allowlist-policy-1`). `claude-sonnet-5-5` ve `claude-haiku-5-5` açıkça engelli. Kullanılan model: `global.anthropic.claude-sonnet-5`. İzin listesini değiştirmeye çalışma.
- Bir dağıtım `Model access is denied ... AWS Marketplace` hatası verirse, IDE terminalinde `enable_anthropic_models` komutunu bir kez çalıştır ve 2-6 dakika bekle. Runtime rolüne IAM izni ekleme.

## Agent tasarımı
- Tek agent, araçlar: `create_dispatch_orders` (yalnızca onaylı planda yazar), `list_dispatch_orders`, `analyze_plan` (geniş sorular için tek çağrıda tam analiz), `get_overview`, `list_risky_lots`, `get_lot_plan`, `list_early_warnings`, `get_product_demand`. Hepsi `engine.planner`'ı çağırır.
- Gecikme: her araç turu bir model çağrısı demektir. Geniş sorularda yalnızca `analyze_plan` çağrılır ve yanıt ~120 kelimeyle sınırlıdır.
- Panel sohbeti NDJSON akışıdır (`{"t":"status"|"text","text":...}`); araç adımları durum satırı olarak, metin geldikçe gösterilir.
- Panel sohbeti, mesajın başına `[Panel eşikleri: riskli ≤X gün, erken uyarı ≤Y gün]` ekler; ajan araçları bu eşiklerle çağırır.
- Sistem prompt'u `prompts/system_prompt.py` ("TazeRota Ajanı", Türkçe). Ajan onay kaydetmez; onay paneldeki butonla yapılır.

## Veri erişimi
- Runtime rolüne izinler `additionalPolicies` ile verilir: `dynamodb-read.json` (salt okuma) ve `dynamodb-dispatch.json` (`tazerota-orders` yazma, `tazerota-approvals` yalnızca UpdateItem). IAM rolünü elle düzenleme.
- Panel sunucusu katılımcı kimliğiyle çalışır; onay yazma (`PutItem`) panelden yapılır.
- Tablolar CDK stack'inin dışındadır; `agentcore remove all` onları silmez.

## Panelin yayını (public)
- Panel tek bir Lambda'da (`tazerota-panel`, Python 3.12 arm64) Lambda Web Adapter ile FastAPI olarak çalışır; Function URL `RESPONSE_STREAM` modunda, sohbet akışı korunur. Arayüz dosyalarını da aynı Lambda verir (S3/CloudFront yok).
- Kurulum/güncelleme: proje kökünde `bash infra/deploy_frontend.sh` (idempotent). Silme: `bash infra/deploy_frontend.sh --delete`.
- Giriş: şifre sayfası + HttpOnly çerez (`PANEL_PASSWORD`). Basic Auth kullanılmaz: Function URL `WWW-Authenticate` başlığını yeniden adlandırdığı için tarayıcı şifre penceresi açmaz.
- Şifre `infra/.panel-credentials` dosyasındadır (gitignored), Lambda'ya ortam değişkeni olarak verilir.
- Lambda rolü (`tazerota-panel-role`): tazerota-* okuma, approvals/orders yazma, yalnızca bizim runtime'ı çağırma.
- Panel kodu değişince (`ui/` veya `engine/`) script'i yeniden çalıştır; ajan değişince ayrıca `agentcore deploy`.

## Dağıtım kontrol listesi
- Panel her sayfa yüklemesinde yeni ajan oturumu açar: AgentCore oturumu başladığı runtime sürümünde kalır, deploy sonrası eski oturum eski kodu çalıştırır.
- `UNIFIED_TRACES_DESTINATION_ENABLED=true` değişkeni `agentcore.json` içinde `envVars` altında kalır.
- Runtime bağımlılıkları ARM64 uyumlu olmalıdır. pandas ve numpy uyumludur.
- Yerel geliştirme portu: `agentcore dev --port 8081`. 8080 portuna dokunma.
- `--session-id` en az 33 karakter olmalıdır.
