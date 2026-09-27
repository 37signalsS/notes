# PageSpeed Insights (PSI)

## Определения

**PageSpeed Insights (PSI)** — веб-инструмент Google для анализа производительности и качества страниц. PSI уникален тем, что объединяет в одном отчете синтетические данные (Lab Data) и реальный пользовательский опыт (Field Data). В 2026 году PSI использует **Lighthouse 13+** как движок лабораторных тестов.

**CrUX (Chrome User Experience Report)** — публичный набор данных о реальном опыте пользователей Chrome, выступающий источником полевых данных для PSI. Данные собираются анонимно от пользователей, согласившихся на синхронизацию истории браузера.

**Lighthouse** — движок с открытым исходным кодом, который PSI запускает в облачной среде Google для получения лабораторных данных и списка технических рекомендаций. Версия **Lighthouse 13+** сфокусирована на метрике INP и диагностических «инсайтах».

**Lab Data** — синтетические данные, полученные в контролируемой среде (эмуляция устройства Moto G Power, фиксированный сетевой троттлинг). Используются для отладки и проверки гипотез.

**Field Data** — данные, собранные от реальных пользователей Chrome за скользящее окно 28 дней. Являются прямым фактором ранжирования в Google Search.

**Core Web Vitals Assessment** — итоговый вердикт о качестве страницы. Страница считается «прошедшей проверку» (Passed), если 75-й перцентиль всех посещений за 28 дней соответствует «хорошему» уровню для всех трех метрик: LCP ≤ 2.5 с, INP ≤ 200 мс, CLS ≤ 0.1.

**PSI API (v5)** — REST API для программного запуска лабораторных тестов. Позволяет интегрировать PSI в CI/CD пайплайны и собственные системы мониторинга.

**CrUX History API** — API для извлечения исторических данных Core Web Vitals, позволяющее строить тренды производительности за последние 6 месяцев.

## Основные концепции / Архитектура

### Полевые данные против Лабораторных (Field vs Lab)

Понимание разницы критично для корректной интерпретации отчета:

| Характеристика | Полевые данные (Field / CrUX) | Лабораторные данные (Lab / Lighthouse) |
| :--- | :--- | :--- |
| **Источник** | Анонимные сессии реальных пользователей Chrome | Один проход бота в облаке Google |
| **Период** | Скользящее окно за последние 28 дней | Момент запуска теста |
| **Условия** | Реальные устройства, сети, кэширование | Эмуляция среднего устройства (Moto G Power) |
| **Применение** | Влияет на ранжирование (SEO) | Отладка и проверка гипотез (Opportunities) |

**Важно:** Экономия времени из раздела Opportunities является расчетной (Estimated) и может не совпадать с реальностью на 100%.

### Оценка Core Web Vitals (Core Web Vitals Assessment)

Ключевым показателем интерактивности является **INP (Interaction to Next Paint)**, который в 2024 году полностью заменил FID.

- **Порог 75-го перцентиля:** Оценка строится по 75-му перцентилю реальных посещений за 28 дней. Даже если медианные значения хороши, деградация нижнего квартиля disqualifies страницу.
- **Мобильный приоритет:** Google использует мобильные данные CrUX как первичный фактор для mobile-first индексации.
- **CrUX History:** В 2026 году PSI отображает исторические тренды метрик за последние 6 месяцев (History API), что позволяет отслеживать влияние релизов на реальных пользователей.

### Уровни агрегации данных (URL vs Origin)

1. **Этот URL:** Точные данные для конкретной страницы. Требует достаточного объема трафика (обычно сотни посещений в месяц).
2. **Origin (Весь домен):** Агрегация по всему источнику. Позволяет оценить «здоровье» домена, если новая или низкотрафиковая страница еще не накопила свои данные.

### Жизненный цикл данных в PSI

```text
Запрос пользователя → Очередь тестов → Запуск Lighthouse (Lab Data)
                                    ↓
                    CrUX Pipeline → Агрегация за 28 дней (Field Data)
                                    ↓
                        Формирование отчета PSI
                                    ↓
                    Ранжирование Core Web Vitals Assessment
```

**Freshness Triggers:**
- Данные CrUX обновляются ежедневно, но с задержкой 1–2 дня.
- Лабораторные данные генерируются на лету при каждом запросе.
- При значительных изменениях на странице CrUX данные могут обновляться до 7 дней.

## Практические сценарии / Установка и настройка / Конфигурация

### Сценарий 1: Технический аудит и поиск «узких мест»

1. Проанализируйте блок **Core Web Vitals Assessment**. Если вердикт `Failed`, определите, какая именно метрика просела.
2. Изучите раздел **Opportunities** (Возможности). PSI ранжирует их по потенциальной экономии времени.
3. **Анализ INP:** Используйте диагностические данные для выявления причин задержки ввода. PSI 2026 года подсвечивает, на каком этапе происходит задержка: Input Delay, Processing Duration или Presentation Delay.
4. Проверьте раздел **Diagnostics**. В нем содержатся критические сведения: размер DOM-дерева, время выполнения сторонних скриптов и цепочки критических запросов.

**Ожидаемый результат:** список проблем, ранжированных по impact, с конкретными рекомендациями.

### Сценарий 2: Интеграция с Google Search Console

PSI является «верхушкой айсберга» мониторинга Google.

- Данные CrUX из PSI идентичны тем, что отображаются в отчете **Core Web Vitals** в Search Console.
- Search Console группирует страницы в кластеры (например, «все карточки товаров»). Если PSI показывает проблему на одной странице, Search Console поможет найти все аналогичные страницы с той же проблемой.

**Применение:** при обнаружении Failed URL в PSI перейдите в Search Console для массового анализа同类 страниц.

### Сценарий 3: Автоматизация через CrUX API и PSI API

Для SRE и DevOps инженеров рекомендуется автоматизировать сбор данных.

- **PSI API (v5):** Позволяет запускать лабораторные тесты программно.
- **CrUX History API:** Позволяет извлекать исторические данные для построения графиков производительности в Grafana или собственных BI-системах.

**Пример запроса тренда LCP за 25 недель:**
```bash
curl -X POST 'https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord?key=YOUR_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{ "origin": "https://example.com", "metrics": ["largest_contentful_paint"] }'
# → {"record": {"metrics": {"largest_contentful_paint": {"histogram": [...], "timeseries": [...]}}}}
```

### Сценарий 4: Интерпретация расхождений (Discrepancies)

| Случай | Причина | Решение |
| :--- | :--- | :--- |
| **Lab > Field** | Страница быстрая в стерильных условиях, но реальные пользователи на слабых устройствах испытывают проблемы | Оптимизация выполнения JS, тестирование на low-end устройствах |
| **Field > Lab** | Реальные пользователи получают преимущество от кэширования (Service Workers) или **Speculative Rules API** (пререндеринг), которые Lighthouse при «холодной» загрузке может учитывать не в полной мере | Убедиться, что Service Worker работает корректно, проверять warm-load метрики |

### Сценарий 5: PSI в мониторинге SRE/DevOps

Настройте PSI как часть общей стратегии мониторинга фронтенда:

1. **Сбор данных:** Настройте cron-задачу для вызова CrUX History API и PSI API с сохранением результатов в TSDB (Prometheus, InfluxDB).
2. **Дашборд:** Создайте Grafana-дашборд с трендами LCP, INP, CLS за 6 месяцев.
3. **Алертинг:** Настройте алерты на Burn Rate (скорость расхода Error Budget) на основе PSI данных.
4. **Runbook:** При каждом алерте проверяйте PSI для определения конкретной проблемной страницы.

## Операции и команды

### PSI API (v5) — лабораторные тесты

```bash
# Запуск теста для URL
curl "https://pagespeed.googleapis.com/pagespeedapi/v5/runPagespeed?url=https://example.com/&key=YOUR_API_KEY"
# → {"lighthouseResult": {"categories": {"performance": {"score": 0.92}}}}
```

**Ключевые параметры:**
- `url` — целевой URL (обязательный)
- `strategy` — `mobile` (по умолчанию) или `desktop`
- `category` — `performance`, `accessibility`, `best-practices`, `seo`
- `locale` — язык отчета (например, `ru`)
- `thresholds` — пороговые значения для метрик

### CrUX History API — исторические данные

```bash
# Запрос истории LCP для origin
curl -X POST 'https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord?key=YOUR_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{
    "origin": "https://example.com",
    "metrics": ["largest_contentful_paint", "interaction_to_next_paint", "cumulative_layout_shift"]
  }'
# → {"record": {"metrics": {...}, "collectionPeriod": {"firstDate": {"year": 2025, "month": 3, "day": 1}}}}
```

### CrUX Real-Time API — актуальные данные

```bash
# Запрос актуальных данных для URL
curl -X POST 'https://chromeuxreport.googleapis.com/v1/records:queryRecord?key=YOUR_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/", "metrics": ["largest_contentful_paint"]}'
# → {"record": {"metrics": {"largest_contentful_paint": {"histogram": [...]}}}}
```

### Автоматизация через cron

```bash
#!/bin/bash
# /etc/cron.d/psi-monitor
# Каждый час собираем PSI данные для критических URL

API_KEY="YOUR_API_KEY"
URLS=("https://example.com/" "https://example.com/products")
OUTPUT_DIR="/var/metrics/psi"

for url in "${URLS[@]}"; do
  filename=$(echo "$url" | md5sum | cut -d' ' -f1)
  curl -s "https://pagespeed.googleapis.com/pagespeedapi/v5/runPagespeed?url=$url&key=$API_KEY" \
    -o "$OUTPUT_DIR/psi-$filename.json"
done

# Парсинг и отправка в Prometheus Pushgateway
python3 /opt/scripts/psi_to_prometheus.py
```

### Проверка заголовков и ответа PSI

```bash
# Проверка доступности PSI API
curl -s "https://pagespeed.googleapis.com/pagespeedapi/v5/runPagespeed?url=https://example.com/&key=YOUR_API_KEY" \
  | jq '.lighthouseResult.categories.performance.score'
# → 0.92

# Проверка CrUX API
curl -s -X POST 'https://chromeuxreport.googleapis.com/v1/records:queryRecord?key=YOUR_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/", "metrics": ["largest_contentful_paint"]}' \
  | jq '.record.metrics.largest_contentful_paint.histogram | length'
# → 3
```

### Интеграция с Prometheus

```yaml
# scrape_configs для psi-exporter
scrape_configs:
  - job_name: 'psi'
    static_configs:
      - targets: ['localhost:9091']
```

```python
# Пример psi-exporter (Python)
from prometheus_client import start_http_server, Gauge
import requests, json, time

LCP = Gauge('psi_lcp_ms', 'LCP from PSI', ['url', 'device'])
INP = Gauge('psi_inp_ms', 'INP from PSI', ['url', 'device'])
CLS = Gauge('psi_cls', 'CLS from PSI', ['url', 'device'])

def collect_psi(url, strategy='mobile'):
    r = requests.get(f'https://pagespeed.googleapis.com/pagespeedapi/v5/runPagespeed',
                     params={'url': url, 'strategy': strategy, 'key': API_KEY})
    data = r.json()['lighthouseResult']['audits']
    LCP.labels(url=url, device=strategy).set(data['largest-contentful-paint']['numericValue'])
    INP.labels(url=url, device=strategy).set(data['interaction-to-next-paint']['numericValue'])
    CLS.labels(url=url, device=strategy).set(data['cumulative-layout-shift']['numericValue'])

if __name__ == '__main__':
    start_http_server(9091)
    while True:
        collect_psi('https://example.com/')
        time.sleep(3600)
```

### Локальный запуск Lighthouse CI

```bash
# Сбор метрик для URL
lhci collect --url=https://example.com/ --numberOfRuns=3
# → Collected 3 runs for https://example.com/
# → Median LCP: 1.8s (Good)
# → Median INP: 145ms (Good)
# → Median CLS: 0.05 (Good)

# Проверка порогов
lhci assert
# → Performance: 0.92 (passed)
# → All thresholds passed
```

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **PSI API rate limit exceeded** | HTTP 429, `"error": {"code": 429}` | Проверить `X-RateLimit-Limit` в заголовках ответа | Соблюдать лимит 25 запросов/секунду, добавить exponential backoff |
| **Нет данных CrUX для URL** | `"record": {"key": {...}, "metrics": {}}` | Проверить трафик URL (нужно >100 посещений/мес) | Использовать Origin-level запрос, ждать накопления данных |
| **Stale CrUX данные** | Данные обновляются реже, чем раз в 28 дней | Проверить `collectionPeriod.firstDate` в ответе | Использовать Lab Data для оперативной диагностики |
| **Расхождение Lab и Field** | Lab Passed, Field Failed | Сравнить условия теста (троттлинг) с реальными пользователями | Тестировать на медленных устройствах (4G, 6x CPU throttle) |
| **PSI показывает Failed, но локальный Lighthouse Passed** | Разные условия эмуляции, версии Lighthouse, кэширование | Запустить `lhci collect` с `--preset=desktop` и `--preset=mobile` | Убедиться, что используете те же preset, что и PSI |
| **Очередь тестов PSI** | Долгое время ожидания результата | PSI использует очередь при высокой нагрузке | Использовать локальный Lighthouse для оперативной отладки |
| **Некорректный verdict для low-traffic URL** | Данные основаны на <20 образцах | Проверить `record.metrics.*.timeseries[].fraction` | Использовать Origin-level агрегацию, не принимать решение по URL |
| **JavaScript-ошибки в Lighthouse** | Audit `errors-in-console` показывает ошибки | Проверить консоль браузера в Lab Data | Исправить JS-ошибки, отключить ненужные расширения в тесте |
| **Сторонний скрипт блокирует INP** | INP > 200 мс, Processing Duration > 100 мс | Diagnostics → `main-thread-tasks` | Заменить скрипт, вынести в Web Worker, использовать Partytown |
| **LCP-элемент не оптимизирован** | LCP > 2.5 с, Resource Load Delay > 500 мс | Diagnostics → `lcp-resource-load-delay` | Добавить `fetchpriority="high"`, `preload`, отключить `loading="lazy"` |

### Методология диагностики PSI-проблем

1. **Определите источник проблемы:** Field Data (CrUX) или Lab Data (Lighthouse)?
2. **Соберите метрики:** Используйте `curl -w` для TTFB, `openssl s_client` для TLS, `curl -sI` для заголовков.
3. **Валидируйте гипотезу:** Сравните с baseline (до изменений) или с эталонной конфигурацией.
4. **Внесите изменения:** примените конфигурацию, проверьте синтаксис, выполните `reload`.
5. **Верифицируйте:** повторите PSI тест, убедитесь, что метрики вернулись к baseline или улучшились.

## Рекомендации

### Чеклист SRE/SysAdmin для работы с PSI

- [ ] **Baseline метрики:** Зафиксируйте текущие значения LCP, INP, CLS для топ-20 критических URL перед любыми изменениями.
- [ ] **Мониторинг:** Настройте автоматический сбор CrUX/PSI данных через API с сохранением в TSDB.
- [ ] **Alerting:** Alert на падение Performance Score ниже 0.9, превышение LCP > 2.5 с, INP > 200 мс, CLS > 0.1.
- [ ] **Изменения в production:** Применяйте изменения в конфигурации сначала на канареечной ноде, затем на всех. Валидируйте через PSI API.
- [ ] **Регрессионное тестирование:** Запускайте Lighthouse CI в пайплайне после каждого деплоя.
- [ ] **Корреляция с инфраструктурой:** Сопоставляйте падения метрик с событиями деплоя, изменениями конфигурации, пиками нагрузки.

### Процедуры операционной поддержки

**Автоматизированный мониторинг через cron:**
```bash
# /etc/cron.d/psi-monitor
0 * * * * ops /opt/scripts/psi_collect.sh >> /var/log/psi-monitor.log 2>&1
```

**Валидация после изменений:**
```bash
# 1. Проверка через PSI API
curl -s "https://pagespeed.googleapis.com/pagespeedapi/v5/runPagespeed?url=https://example.com/&key=$API_KEY" \
  | jq '.lighthouseResult.categories.performance.score'

# 2. Логи веб-сервера
tail -f /var/log/nginx/access.log | grep "$(date +%d/%b/%Y:%H)"

# 3. Метрики TTFB
curl -o /dev/null -s -w "TTFB: %{time_starttransfer}s\n" https://example.com/
```

**Откат изменений:**
```bash
# Если деплой вызвал деградацию PSI
git checkout /etc/nginx/conf.d/example.com.conf
systemctl reload nginx
# Повторить PSI тест для валидации
```

**Бэкап конфигурации:**
```bash
# Бэкап конфигурации
tar czf /backup/nginx-vhosts-$(date +%F).tar.gz /etc/nginx/conf.d/

# Бэкап сертификатов
tar czf /backup/nginx-ssl-$(date +%F).tar.gz /etc/nginx/ssl/
```

### Производительность диагностических инструментов

| Инструмент | Влияние на production | Рекомендация |
| :--- | :--- | :--- |
| `pagespeed.googleapis.com` API | Без влияния (внешний запрос) | Соблюдать rate limit (25 req/s) |
| `curl -s` к собственному URL | Без влияния | Без ограничений |
| `lhci collect` | Умеренная нагрузка на Origin | Использовать staging-окружение |
| `openssl s_client` | Без влияния | Без ограничений |
| `nginx -t` | Без влияния (только чтение конфига) | Обязательно перед reload |

## Дополнительная информация

### См. также

- **[Ключевые метрики Web Vitals](./web_vitals.md)** — глубокий разбор LCP, INP, CLS, пороговых значений и SRE-практик.
- **[Методология и принципы тестирования](./testing_principles.md)** — разница между RUM и синтетикой, троттлинг, статистическая значимость.
- **[Обзор веб-производительности](./overview.md)** — место PSI в общей стратегии SRE/DevOps.
- **[Лучшие практики оптимизации](./best_practices.md)** — Performance Budget, CI/CD интеграция, конкретные оптимизации.
- **[Профессиональный анализ в WebPageTest](./webpagetest.md)** — когда возможностей PSI недостаточно, глубокая диагностика Core Web Vitals.
- [Zero-Downtime Deployment](./zero_downtime_deployment.md) — деплой без прерывания обслуживания.
- [Image Optimization Pipeline](./image_optimization_pipeline.md) — CI/CD и AVIF/WebP.
- [Structured Logging для Performance](./structured_logging_for_performance.md) — анализ логов для performance.
