# CDN — Оптимизация стоимости и Cost Management

## Определения

- **Egress (Исходящий трафик)**: Трафик, передаваемый от CDN-сервера клиенту. Основная статья расходов на CDN, тарифицируемая за гигабайт (GB).
- **Ingress (Входящий трафик)**: Трафик, передаваемый от Origin к CDN-серверу для наполнения кэша. Обычно бесплатен или значительно дешевле Egress.
- **Reserved Capacity (Резервируемый объём)**: Предварительная оплата гарантированного объёма трафика со скидкой (обычно 30-50%). Фиксированная стоимость вне зависимости от фактического потребления.
- **Pay-As-You-Go (PAYG)**: Модель оплаты по фактическому потреблению. Гибкая, но дороже при стабильном высоком трафике.
- **Commitment Discount (Скидка за обязательства)**: Скидка за заключение контракта на 1-3 года. Обычно 20-40% от PAYG тарифа.
- **Cost per GB (Стоимость за ГБ)**: Тариф на передачу данных. Варьируется от $0.02/GB (Cloudflare) до $0.12/GB (CloudFront) в зависимости от региона и объёма.
- **Bandwidth (Полоса пропускания)**: Максимальная скорость передачи данных. CDN-провайдеры продают bandwidth как承诺ный ресурс (Committed Bandwidth).
- **Egress Optimization**: Стратегии снижения стоимости исходящего трафика: кэширование, сжатие, HTTP/3, edge computing.
- **Cost Routing**: Маршрутизация трафика через наиболее дешёвый CDN в Multi-CDN архитектуре.
- **Free Tier (Бесплатный план)**: Базовый уровень обслуживания с ограниченным функционалом и трафиком. Cloudflare: без ограничений трафика; Fastly: 500 МБ/мес.

---

## Теория

### Модели тарификации CDN-провайдеров

**Ключевые компоненты стоимости:**
1. **Трафик (Bandwidth/Egress)**: 60-80% стоимости.
2. **Запросы (Requests)**: 10-20% стоимости (особенно API-вызовы и purge).
3. **Фичи (Add-ons)**: WAF, Bot Management, Rate Limiting, Image Optimization.
4. **Поддержка (Support)**: Premium support = $3,000-$50,000/мес.

**Сравнение моделей тарификации (2026):**

| Провайдер | Модель | Egress (первые 10 ТБ/мес) | Egress (10-50 ТБ/мес) | Free Tier |
| :--- | :--- | :--- | :--- | :--- |
| **Cloudflare** | Flat Rate | $0.02/GB (Pro), $0.015/GB (Biz) | $0.01/GB (Enterprise) | Без ограничений |
| **Fastly** | PAYG | $0.12/GB | $0.08/GB | 500 МБ/мес |
| **Akamai** | Commit + PAYG | $0.03-0.08/GB (зависит от региона) | $0.02-0.05/GB | 500 МБ/мес |
| **CloudFront** | PAYG | $0.085/GB (US/EU) | $0.080/GB | 1 ТБ/мес (12 мес) |
| **Gcore** | PAYG | $0.03/GB | $0.02/GB | 1 ТБ/мес |

### Факторы, влияющие на стоимость

**География:**
- US/EU: $0.02-0.12/GB (самый дешёвый регион).
- Asia: $0.05-0.15/GB (на 30-50% дороже US/EU).
- South America/Africa: $0.10-0.25/GB (самый дорогой).
- CN (Китай): отдельная цена-политика, требует ICP-лицензии.

**Тип трафика:**
- **Статика (Images/JS/CSS)**: Кэшируется хорошо → низкий Egress к Origin.
- **Динамика (API)**: Не кэшируется → полный Egress к Origin.
- **Видео (VOD/Live)**: Высокий объём, но низкий Egress к Origin за счёт кэширования.

**Протоколы:**
- HTTP/1.1: Обычный Egress.
- HTTP/2: Multiplexing снижает overhead, но Egress тот же.
- HTTP/3 (QUIC): Снижает overhead на 1-3% (не влияет на стоимость).

### Стратегии оптимизации

**1. Увеличение Cache Hit Ratio:**
- CHR = 99% → только 1% трафика идёт к Origin → экономия 99% на Egress.
- CHR = 80% → 20% трафика идёт к Origin → потребуется больше Egress.

**2. Сжатие:**
- Gzip/Brotli/ZSTD снижают размер ответа на 60-80%.
- Экономия: при Egress $0.08/GB и сжатии 70% → экономия $0.056/GB.

**3. Tiered Caching:**
- Снижает Egress к-Origin до 99% за счёт промежуточного кэширования.

**4. Изображения:**
- Конвертация в WebP/AVIF снижает размер на 30-50%.
- CDN Image Optimization (Cloudflare Polish, Akamai Image Manager): автоматическая конвертация.

**5. Multi-CDN с Cost Routing:**
- Маршрутизация дешёвого трафика через менее дорогой CDN.

---

## Практика

### Расчёт стоимости для типичного проекта

**Входные данные:**
- Сайт: E-commerce (500K уникальных посетителей/день)
- Средняя страница: 2 МБ (статика + изображения)
- Трафик: 500K × 2 МБ = 1 ТБ/день = 30 ТБ/мес
- Cache Hit Ratio: 95%
- Egress к-Origin: 5% × 30 ТБ = 1.5 ТБ/мес

**Сравнение стоимости (30 ТБ/мес):**

| Провайдер | Egress (30 ТБ) | Requests (100M) | WAF | Итого/мес |
| :--- | :--- | :--- | :--- | :--- |
| **Cloudflare Pro** | $600 | $0 | Включён | **$600** |
| **Cloudflare Business** | $450 | $0 | Включён | **$450** |
| **Fastly** | $2,400 | $350 | +$300 | **$3,050** |
| **CloudFront** | $2,550 | $350 | +$600 (WAF) | **$3,500** |
| **Akamai** | $900-1,500 | $500 | +$1,000 | **$2,400-3,000** |

### Cloudflare: Проверка потребления

```bash
# Проверка потребления трафика за текущий месяц
curl -X GET "https://api.cloudflare.com/client/v4/zones/{zone_id}/analytics/dashboard" \
  -H "Authorization: Bearer {api_token}" \
  -G --data-urlencode "since=-1440" \
  --data-urlencode "until=0"
# → {"result":{"totals":{"requests":25000000,"bandwidth":30720000000,...}}}

# Проверка потребления по регионам
curl -X GET "https://api.cloudflare.com/client/v4/zones/{zone_id}/analytics/dashboard" \
  -H "Authorization: Bearer {api_token}" \
  -G --data-urlencode "since=-1440" \
  --data-urlencode "until=0" \
  --data-urlencode "dimensions=clientCountryName"
# → {"result":[{"clientCountryName":"US","requests":10000000,"bandwidth":12288000000},...]}
```

### Fastly: Проверка потребления

```bash
# Проверка потребления за текущий месяц
curl -X GET "https://api.fastly.com/stats" \
  -H "Fastly-Key: {api_token}"
# → {"data":{"bandwidth":{...},"requests":{...}}}

# Проверка по сервисам
curl -X GET "https://api.fastly.com/service/{service_id}/stats/region" \
  -H "Fastly-Key: {api_token}"
# → {"data":[{"region":"US","bandwidth":...,"requests":...}]}
```

### CloudFront: Проверка потребления

```bash
# Проверка потребления через CloudWatch
aws cloudwatch get-metric-statistics \
  --namespace AWS/CloudFront \
  --metric-name BytesDownloaded \
  --dimensions Name=DistributionId,Value=E1234567890ABC Name=Region,Value=Global \
  --start-time $(date -u -v-30M +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 3600 \
  --statistics Sum

# Проверка количества запросов
aws cloudwatch get-metric-statistics \
  --namespace AWS/CloudFront \
  --metric-name Requests \
  --dimensions Name=DistributionId,Value=E1234567890ABC Name=Region,Value=Global \
  --start-time $(date -u -v-30M +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 3600 \
  --statistics Sum
```

### Скрипт расчёта экономии от сжатия

```bash
#!/bin/bash
# cost_savings_compression.sh — расчёт экономии от сжатия

SITE="https://example.com"
TOTAL_SIZE=$(curl -sI "$SITE/static/app.js" | grep -i content-length | awk '{print $2}' | tr -d '\r')
TOTAL_GB=$(echo "scale=4; $TOTAL_SIZE / 1073741824" | bc)

# Стоимость Egress без сжатия (CloudFront: $0.085/GB)
COST_NO_COMPRESS=$(echo "scale=2; $TOTAL_GB * 0.085" | bc)

# Размер с Brotli (70% сжатие)
BROTLI_SIZE=$(echo "scale=0; $TOTAL_SIZE * 0.3" | bc)
BROTLI_GB=$(echo "scale=4; $BROTLI_SIZE / 1073741824" | bc)
COST_BROTLI=$(echo "scale=2; $BROTLI_GB * 0.085" | bc)

# Экономия
SAVINGS=$(echo "scale=2; $COST_NO_COMPRESS - $COST_BROTLI" | bc)

echo "=== Расчёт экономии от сжатия ==="
echo "Исходный размер: $(echo "scale=2; $TOTAL_SIZE / 1048576" | bc) МБ"
echo "Размер с Brotli: $(echo "scale=2; $BROTLI_SIZE / 1048576" | bc) МБ"
echo "Экономия: $(echo "scale=0; ($TOTAL_SIZE - $BROTLI_SIZE) / 1048576" | bc) МБ ($(echo "scale=0; 100 - 30" | bc)%)"
echo "Стоимость без сжатия: \$$COST_NO_COMPRESS/GB"
echo "Стоимость с Brotli: \$$COST_BROTLI/GB"
echo "Экономия за 1 ТБ трафика: \$$SAVINGS"
```

### Метрики Cost Monitoring

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| **Cost per GB** | Средняя стоимость за ГБ трафика | < $0.05/GB |
| **Cost per Request** | Стоимость за 1000 запросов | < $0.005/1K |
| **Cache Hit Ratio** | Процент кэшированных запросов | >95% |
| **Egress Reduction** | Снижение Egress к-Origin | >90% |
| **Compression Ratio** | Степень сжатия контента | >60% |
| **Cost vs Revenue** | Доля стоимости CDN от дохода | <1% |

---

## Дополнительная информация

### Типичные ошибки и их решение

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| **Non-cacheable Content** | Высокий Egress к-Origin | Использовать `stale-while-revalidate`, увеличить TTL |
| **Vary: Cookie** | Каждый пользователь = отдельный кэш | Убрать `Vary: Cookie` или использовать `Vary: Accept-Encoding` |
| **Query String Pollution** | Один URL кэшируется 100 раз | Включить `Ignore Query String` или нормализовать параметры |
| **Video Streaming** | Огромный Egress | Использовать DASH/HLS с CDN-кэшированием сегментов |
| **DDoS-атака** | Резкий рост трафика | Включить DDoS Protection (обычно включена в тариф) |

### Связанные темы

- **[Обзор CDN](cdn_overview.md)** — архитектура и типы CDN.
- **[Multi-CDN](cdn_multi_cdn_implementation.md)** — Cost Routing и оптимизация через несколько CDN.
- **[Политики кэширования](cdn_caching_and_invalidation.md)** — влияние кэширования на Egress.
