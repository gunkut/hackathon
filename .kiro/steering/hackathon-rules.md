---
inclusion: always
---

# Hackathon Bağlamı

**Etkinlik:** Tedarik Zincirinde Agentic AI Hackathonu (Deloitte, AWS, MEXT)
**Hackathon günü:** 25 Kasım 2026, 09:00-20:00, MEXT Teknoloji Merkezi, Ataşehir
**Takım:** 3 kişi (en az 1 iş birimi, 1 teknik eş temsilcisi)
**Ödüller:** 1. AirPods 5 (kablosuz şarj kutulu), 2. AirPods 5, 3. AirPods 4 (aktif gürültü engelleme)

## Program
| Saat | Aşama |
|---|---|
| 09:00-10:00 | Açılış ve tanıtım |
| 10:00-17:00 | Çözüm geliştirme |
| 17:00-19:00 | Final sunumları |
| 19:15-20:00 | Ödül töreni |

## Değerlendirme
Davet metnine göre sunumlar, AI jüri asistanı JuryMate ile önceden tanımlı kriterlere göre de değerlendirilir. Resmî kriter listesi henüz elimizde değil. Kriterler öğrenildiğinde bu dosyaya eklenir.

## Çalışma ilkeleri
- **Süre sınırı:** Geliştirme penceresi yaklaşık 7 saattir. Kapsamı büyütme, önce uçtan uca çalışan dilimi bitir (veri → riskli lot → öneri → KPI → sohbet).
- **Demo odaklı:** Sunumda gösterilecek tek akış: riskli lotları bul, öner, KPI'ı göster, agent'a soru sor. Her karar bu akışa hizmet etmiyorsa ertelenir.
- **Sayısal etki:** İmha oranı düşüşü (`disposal_rate_reduction_pp`) ve kurtarılan değer (`saved_value_try`, sentetik) sunumun ana mesajıdır. İki baseline ile karşılaştırma zorunludur.
- **Dağıtım erken denenir:** `agentcore deploy` ilk seferde 5-8 dakika sürer. Son saate bırakma, erken bir sürümü dağıtıp çalıştığını doğrula.
- **Yedek plan:** Dağıtım sorun çıkarırsa demo, `agentcore dev --port 8081` ile yerelde çalışabilmelidir.
- **Dürüstlük:** Sentetik veri açıkça belirtilir. Gerçek kurum adı kullanılmaz.
