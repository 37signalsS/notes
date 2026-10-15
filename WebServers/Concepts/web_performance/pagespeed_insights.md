# PageSpeed Insights (PSI)

**Актуально для:** PageSpeed Insights API v5 / Chrome UX Report (CrUX) API / Lighthouse 13.x

## Определения

**PageSpeed Insights (PSI)** — веб-инструмент и REST API от Google для комплексного анализа производительности веб-страниц. PSI объединяет синтетические лабораторные замеры (Lab Data) на движке Lighthouse и телеметрию реального пользовательского опыта (Field Data) из базы Chrome User Experience Report (CrUX).

**CrUX (Chrome User Experience Report)** — публичный агрегированный набор данных о реальном пользовательском опыте миллионов пользователей браузера Chrome. Сбор телеметрии ведется при условиях: включена синхронизация истории, не установлен Sync Passphrase и разрешена отправка статистики использования. Данные собираются по скользящему 28-дневному окну.

**CrUX API (`records:queryRecord`)** — REST API для получения агрегированных полевых метрик Core Web Vitals за последние 28 дней для конкретного URL или всего Origin.

**CrUX History API (`records:queryHistoryRecord`)** — специализированный эндпоинт CrUX для извлечения исторических трендов метрик с шагом в одну неделю за предшествующие 6 месяцев (до 25 точек среза).

**Lighthouse** — открытый автоматизированный инструмент аудита веб-приложений. PSI запускает Lighthouse в песочнице Google с фиксированными параметрами эмуляции оборудования и сети для генерации воспроизводимых лабораторных метрик, диагностических рекомендаций (Opportunities) и аудитов доступности, SEO и Best Practices.

**Lab Data (Лабораторные данные)** — детерминированные синтетические замеры, выполненные в изолированной среде Googlebot/Lighthouse (по умолчанию эмуляция Moto G Power, 4-кратное замедление CPU, троттлинг сети 1.6 Мбит/с down / 750 Кбит/с up, задержка 150 мс RTT). Служат для отладки конкретных технических проблем до выхода в продакшн.

**Field Data (Полевые данные / RUM)** — анонимные агрегированные показатели реальных сессий пользователей Chrome. Являются ключевым источником оценки Core Web Vitals и учитываются алгоритмами ранжирования Google Search.

**Core Web Vitals Assessment (Оценка Core Web Vitals)** — официальный вердикт Google о качестве пользовательского интерфейса. Страница получает статус `Passed` только при соблюдении 75-го перцентиля (p75) по всем трем ключевым метрикам одновременно: LCP ≤ 2.5 с, INP ≤ 200 мс, CLS ≤ 0.1.

**URL vs Origin Aggregation** — двухуровневая модель представления данных CrUX: при наличии достаточного трафика отображаются метрики конкретного запрошенного URL; при нехватке выборки происходит fallback на уровень всего домена (Origin).

## Основные концепции и архитектура

### Полевые данные против лабораторных (Field vs Lab)

Разделение полевых и лабораторных замеров определяет границы их применимости в SRE и системном администрировании:

| Характеристика | Полевые данные (Field / CrUX) | Лабораторные данные (Lab / Lighthouse) |
| :--- | :--- | :--- |
| **Источник данных** | Реальные сессии пользователей браузера Chrome | Одиночный запуск headless-браузера на серверах Google |
| **Временной охват** | Скользящее окно за предшествующие 28 дней | Момент выполнения сетевого запроса |
| **Сетевые условия** | Реальное распределение (2G/3G/4G/5G/Wi-Fi/Ethernet) | Фиксированная эмуляция: 1.6 Мбит/с down, 750 Кбит/с up, 150 мс RTT |
| **Вычислительная среда** | Реальный парк клиентских устройств | Фиксированное замедление CPU (4x slowdown Moto G Power) |
| **Кэширование** | Смесь «холодных» (первый визит) и «горячих» загрузок | Изолированный «холодный» профиль браузера без кэша |
| **Влияние на SEO** | Прямой фактор ранжирования Google Search (Page Experience) | Не влияет напрямую на ранжирование |
| **Интерактивность** | Метрика INP (Interaction to Next Paint) по реальным кликам | Метрика TBT (Total Blocking Time) как лабораторный прокси |
| **Основное назначение** | Контроль выполнения SLO, оценка бизнес-эффекта и SEO | Отладка регрессий, профилирование скриптов, верификация в CI |

### Оценка Core Web Vitals (Core Web Vitals Assessment)

Начиная с марта 2024 года, метрика **INP (Interaction to Next Paint)** полностью заменила устаревшую FID (First Input Delay). Оценка страницы в PSI строится по жестким правилам:

1. **Правило 75-го перцентиля:** Значение каждой метрики рассчитывается так, чтобы как минимум 75% всех зарегистрированных просмотров страниц находились в диапазоне «Хорошо» (Good):
   - **LCP (Largest Contentful Paint):** $\le 2500$ мс (Poor $> 4000$ мс).
   - **INP (Interaction to Next Paint):** $\le 200$ мс (Poor $> 500$ мс).
   - **CLS (Cumulative Layout Shift):** $\le 0.1$ (Poor $> 0.25$).
2. **Бинарный вердикт:** Статус `Passed` присваивается только тогда, когда все три метрики находятся в диапазоне «Хорошо». Если хотя бы одна метрика переходит в «Требует улучшения» (Needs Improvement) или «Плохо» (Poor), общий вердикт становится `Failed`.
3. **Разделение устройств:** Оценка рассчитывается строго раздельно для мобильных пользователей (`PHONE`) и пользователей ПК (`DESKTOP`). При mobile-first индексации приоритетным для ранжирования является мобильный вердикт.

### Уровни агрегации данных и механизм Origin Fallback

CrUX накладывает строгие критерии анонимности и статистической достоверности (K-anonymity):

```text
Запрос URL в PSI API / Web UI
             │
             ▼
 Достаточно ли выборки у URL за 28 дней?
             ├──────────── Да ───────────► Вывод точных метрик URL
             │
            Нет
             ▼
 Достаточно ли выборки у всего Origin?
             ├──────────── Да ───────────► Origin Fallback (метрики всего домена)
             │                             loadingExperience.origin_fallback = true
            Нет
             ▼
 Полевые данные отсутствуют (отображаются только лабораторные тесты Lighthouse)
```

Для появления URL-метрик требуется регулярный поток из сотен уникальных посещений в месяц с включенной отправкой статистики. Новые страницы и редкие внутренние маршруты используют `origin_fallback`, что может маскировать проблемы конкретного URL либо, наоборот, транслировать чужие ошибки на новую оптимизированную страницу.

### Жизненный цикл данных и инерция 28 дней

```text
[ День 0 ] ── Релиз оптимизации Nginx / Frontend на сервере
    │
    ├─► Lab Data (Lighthouse): реагирует мгновенно при следующем запуске теста
    │
    └─► Field Data (CrUX): накапливается ежедневно, но с задержкой:
         • Задержка пайплайна агрегации Google: 24–48 часов
         • Инерция скользящего окна: 28 дней
         • Чтобы вытеснить медленные замеры из выборки p75, требуется 2–4 недели
```

При устранении инфраструктурной проблемы (например, настройке сжатия Brotli или оптимизации TTFB) инженер должен ориентироваться на Lab Data и собственные RUM-логи в первые дни, ожидая выравнивания CrUX только на горизонте 28-дневного цикла.

## Практические сценарии и конфигурация

### Сценарий 1: Комплексный аудит и локализация узких мест

При деградации вердикта Core Web Vitals системный администратор и SRE действуют по нисходящей цепочке от общего статуса к уровню веб-сервера:

1. **Проверка общего статуса:** В блоке `Core Web Vitals Assessment` определяется проблемная метрика (LCP, INP или CLS).
2. **Анализ фаз LCP:** Если просел LCP, проверяется распределение четырех фаз:
   - *Time to First Byte (TTFB)* — время генерации ответа сервером и сеть.
   - *Resource Load Delay* — задержка между TTFB и началом загрузки LCP-ресурса.
   - *Resource Load Duration* — физическое время передачи ассета (размер файла, пропускная способность, сжатие).
   - *Element Render Delay* — время от завершения загрузки до отрисовки в браузере (блокировка рендеринга CSS/JS).
3. **Анализ фаз INP:** Если просел INP, проверяется задержка ввода (Input Delay), длительность выполнения обработчиков в главном потоке (Processing Duration) и задержка кадра отрисовки (Presentation Delay).
4. **Изучение раздела Diagnostics:** Выявление критических путей запросов (Critical Request Chains), веса DOM-дерева и объема передаваемых байтов без сжатия.

### Сценарий 2: Настройка Nginx для прохождения аудитов PSI

Лабораторный бот PSI эмулирует браузер с User-Agent, содержащим строки `Google-Lighthouse` или `Googlebot`. При агрессивных настройках защиты от DDoS, модулях WAF или строгих директивах `limit_req` бот может получать ошибки `403 Forbidden` или `429 Too Many Requests`, что приводит к аварийному завершению теста с кодом `ERRORED_DOCUMENT_REQUEST`.

Конфигурация Nginx с разделением лимитов для краулеров, оптимизацией TTFB, сжатием Brotli/Gzip и корректными заголовками кэширования:

```nginx
# /etc/nginx/conf.d/psi_optimization.conf

# Определение доверенных проверочных ботов по User-Agent
map $http_user_agent $is_audit_bot {
    default 0;
    "~*(Google-Lighthouse|Googlebot|Chrome-Lighthouse)" 1;
}

# Отдельная зона rate limit: для обычных пользователей 10r/s, для ботов аудита — пропуск без жестких ограничений
map $is_audit_bot $limit_key {
    0 $binary_remote_addr;
    1 "";
}

limit_req_zone $limit_key zone=web_req_limit:10m rate=10r/s;

server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # Сжатие данных: минимизирует Resource Load Duration для LCP
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml application/json application/javascript application/xml+rss application/atom+xml image/svg+xml font/woff2;

    # Поддержка Brotli при установленном модуле ngx_brotli
    # brotli on;
    # brotli_comp_level 5;
    # brotli_types text/plain text/css application/javascript application/json image/svg+xml font/woff2;

    # Применение лимитов запросов
    limit_req zone=web_req_limit burst=20 nodelay;

    # Оптимизация кэширования статических ассетов (проверка audit: uses-long-cache-ttl)
    location ~* \.(?:css|js|woff2|png|jpg|jpeg|webp|avif|ico|svg)$ {
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
        access_log off;
        try_files $uri =404;
    }

    # Динамический бэкенд: оптимизация TTFB
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Буферизация для предотвращения задержек передачи клиенту
        proxy_buffering on;
        proxy_buffers 16 16k;
        proxy_buffer_size 16k;

        # Заголовки безопасности (влияют на Best Practices в PSI)
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "SAMEORIGIN" always;
    }
}
```

Проверка конфигурации и применение:

```bash
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

systemctl reload nginx
# → result: конфигурация Nginx успешно обновлена без обрыва активных соединений
```

### Сценарий 3: Валидация деплоя в On-Premise CI/CD пайплайне через PSI API

Для автоматической проверки production-окружения после релиза используется скрипт, опрашивающий PSI API и проверяющий соблюдение бюджетов производительности.

Скрипт проверки (`/usr/local/bin/ci-psi-check.sh`):

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET_URL="${1:-https://example.com/}"
API_KEY="${PSI_API_KEY:-}"
MIN_SCORE="${MIN_SCORE:-85}"

if [[ -z "$API_KEY" ]]; then
  echo "ОШИБКА: Переменная окружения PSI_API_KEY не задана." >&2
  exit 1
fi

echo "Запуск аудита PSI для: ${TARGET_URL} (Strategy: mobile)..."
RESPONSE=$(curl -sS "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=${TARGET_URL}&strategy=mobile&key=${API_KEY}&category=performance")

# Проверка на ошибки API
if echo "$RESPONSE" | grep -q '"error":'; then
  echo "ОШИБКА API:" >&2
  echo "$RESPONSE" | jq -r '.error.message' >&2
  exit 2
fi

SCORE=$(echo "$RESPONSE" | jq -r '(.lighthouseResult.categories.performance.score * 100) | floor')
LCP=$(echo "$RESPONSE" | jq -r '.lighthouseResult.audits["largest-contentful-paint"].numericValue | floor')
TBT=$(echo "$RESPONSE" | jq -r '.lighthouseResult.audits["total-blocking-time"].numericValue | floor')
CLS=$(echo "$RESPONSE" | jq -r '.lighthouseResult.audits["cumulative-layout-shift"].numericValue')

echo "----------------------------------------"
echo "Результаты аудита PageSpeed Insights:"
echo "Performance Score: ${SCORE} (Требуется: >= ${MIN_SCORE})"
echo "LCP (Lab):         ${LCP} ms (Порог: <= 2500 ms)"
echo "TBT (Lab Proxy):   ${TBT} ms (Порог: <= 200 ms)"
echo "CLS (Lab):         ${CLS} (Порог: <= 0.1)"
echo "----------------------------------------"

if (( SCORE < MIN_SCORE )); then
  echo "ПРОВЕРКА НЕ ПРОЙДЕНА: Performance Score ${SCORE} ниже минимального ${MIN_SCORE}" >&2
  exit 3
fi

echo "ПРОВЕРКА УСПЕШНА: Метрики укладываются в установленный Performance Budget."
exit 0
```

Пример интеграции в этап `.gitlab-ci.yml` (On-Premises GitLab Runner):

```yaml
performance_audit:
  stage: post_deploy
  image: alpine:3.20
  before_script:
    - apk add --no-cache bash curl jq
  script:
    - chmod +x /usr/local/bin/ci-psi-check.sh
    - /usr/local/bin/ci-psi-check.sh "https://example.com/"
  variables:
    MIN_SCORE: "80"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

### Сценарий 4: Анализ расхождений между Lab и Field (Discrepancy Analysis)

| Симптом | Причина расхождения | Диагностические действия SRE | Метод устранения |
| :--- | :--- | :--- | :--- |
| **Lab Good, но Field Poor** | Лабораторный тест запускается в дата-центре Google с низким TTFB, а реальные пользователи распределены по регионам с высоким latency | Снять географический TTFB через логи Nginx: `$upstream_response_time`, `$request_time` | Развертывание локальных reverse proxy / CDN-точек, включение HTTP/3, кэширование на edge |
| **Lab Good, но Field Poor (INP)** | Бот Lighthouse не кликает по интерфейсу в глубине сессии; в лабе TBT низкий, но реальные пользователи вызывают тяжелые обработчики | Запустить профилирование в DevTools Performance Panel на медленном мобильном CPU | Декомпозиция длительных задач (Long Tasks), вынос логики в Web Workers, `scheduler.yield()` |
| **Lab Poor, но Field Good** | Реальные посетители заходят с «прогретым» браузерным кэшем и Service Worker, а Lighthouse тестирует строгий «холодный» профиль | Проверить процент возвращающихся пользователей и статус заголовков `Cache-Control` | Оптимизировать холодный запуск: минимизировать размер критического CSS и блокирующего JS |
| **Lab Poor (LCP), Field Good** | Страница использует пререндеринг (`Speculation Rules API`), который Lighthouse не активирует при единичном синтетическом визите | Проверить наличие тега `<script type="speculationrules">` в исходном коде | Убедиться, что для пользователей без поддержки API отдаются корректные `link rel="preload"` |

## Операции и команды

### Запросы к PageSpeed Insights API (v5)

Запуск лабораторного аудита мобильной версии с получением всех категорий:

```bash
curl -sS "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=https://example.com/&strategy=mobile&category=performance&category=best-practices&category=seo&key=YOUR_API_KEY" \
  | jq '{
      score: .lighthouseResult.categories.performance.score,
      lcp: .lighthouseResult.audits["largest-contentful-paint"].displayValue,
      tbt: .lighthouseResult.audits["total-blocking-time"].displayValue,
      cls: .lighthouseResult.audits["cumulative-layout-shift"].displayValue
    }'
# → {
# →   "score": 0.94,
# →   "lcp": "1.8 s",
# →   "tbt": "90 ms",
# →   "cls": "0.02"
# → }
```

Извлечение вердикта и полевых данных Core Web Vitals (CrUX) из ответа PSI:

```bash
curl -sS "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=https://example.com/&key=YOUR_API_KEY" \
  | jq '{
      overall_status: .loadingExperience.overall_category,
      origin_fallback: .loadingExperience.origin_fallback,
      lcp_p75_ms: .loadingExperience.metrics.LARGEST_CONTENTFUL_PAINT_MS.percentile,
      inp_p75_ms: .loadingExperience.metrics.INTERACTION_TO_NEXT_PAINT.percentile,
      cls_p75: (.loadingExperience.metrics.CUMULATIVE_LAYOUT_SHIFT_SCORE.percentile / 100)
    }'
# → {
# →   "overall_status": "FAST",
# →   "origin_fallback": false,
# →   "lcp_p75_ms": 1950,
# →   "inp_p75_ms": 120,
# →   "cls_p75": 0.04
# → }
```

### Запросы к CrUX API (`queryRecord`)

Получение 28-дневных полевых метрик для конкретного URL с фильтрацией по мобильным устройствам:

```bash
curl -sS -X POST "https://chromeuxreport.googleapis.com/v1/records:queryRecord?key=YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/",
    "formFactor": "PHONE",
    "metrics": [
      "largest_contentful_paint",
      "interaction_to_next_paint",
      "cumulative_layout_shift",
      "experimental_time_to_first_byte"
    ]
  }' | jq '.record.metrics | {
      lcp_p75: .largest_contentful_paint.percentiles.p75,
      inp_p75: .interaction_to_next_paint.percentiles.p75,
      cls_p75: .cumulative_layout_shift.percentiles.p75,
      ttfb_p75: .experimental_time_to_first_byte.percentiles.p75
    }'
# → {
# →   "lcp_p75": 2100,
# →   "inp_p75": 140,
# →   "cls_p75": "0.03",
# →   "ttfb_p75": 420
# → }
```

### Запросы к CrUX History API (`queryHistoryRecord`)

Извлечение 25-недельного исторического тренда p75 LCP и INP для оценки регрессий после релизов:

```bash
curl -sS -X POST "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord?key=YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "origin": "https://example.com",
    "metrics": ["largest_contentful_paint", "interaction_to_next_paint"]
  }' | jq '{
      collectionPeriods: .record.collectionPeriods,
      lcp_history_p75: .record.metrics.largest_contentful_paint.percentilesTimeseries.p75s,
      inp_history_p75: .record.metrics.interaction_to_next_paint.percentilesTimeseries.p75s
    }'
# → {
# →   "collectionPeriods": [
# →     {"firstDate": {"year": 2025, "month": 10, "day": 1}, "lastDate": {"year": 2025, "month": 10, "day": 28}},
# →     ...
# →   ],
# →   "lcp_history_p75": [2400, 2350, 2100, ...],
# →   "inp_history_p75": [180, 175, 140, ...]
# → }
```

### Скрипт периодического мониторинга и экспорт в Prometheus

Для интеграции метрик PSI и CrUX в стек мониторинга (Prometheus + Grafana) создается автономный сервис на Python (`/usr/local/bin/psi_exporter.py`). Скрипт собирает метрики раз в 2 часа (для предотвращения исчерпания API-квот) и экспортирует их через встроенный HTTP-сервер.

Код экспортера (`/usr/local/bin/psi_exporter.py`):

```python
#!/usr/bin/env python3
"""
Prometheus-экспортер для Google PageSpeed Insights и CrUX API.
Экспортирует как синтетические (Lab), так и полевые (Field) метрики.
"""

import os
import sys
import time
import logging
import requests
from prometheus_client import start_http_server, Gauge

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

API_KEY = os.getenv("PSI_API_KEY", "")
TARGET_URLS = [u.strip() for u in os.getenv("PSI_TARGET_URLS", "https://example.com/").split(",") if u.strip()]
SCRAPE_INTERVAL_SEC = int(os.getenv("PSI_SCRAPE_INTERVAL", "7200"))
EXPORTER_PORT = int(os.getenv("PSI_EXPORTER_PORT", "9198"))

if not API_KEY:
    logging.error("Переменная окружения PSI_API_KEY не установлена.")
    sys.exit(1)

# Лабораторные метрики (Lighthouse)
LAB_SCORE = Gauge("psi_lab_performance_score", "Lighthouse Performance Score (0-100)", ["url", "strategy"])
LAB_LCP_MS = Gauge("psi_lab_lcp_milliseconds", "Lighthouse Largest Contentful Paint in ms", ["url", "strategy"])
LAB_TBT_MS = Gauge("psi_lab_tbt_milliseconds", "Lighthouse Total Blocking Time in ms", ["url", "strategy"])
LAB_CLS = Gauge("psi_lab_cls_ratio", "Lighthouse Cumulative Layout Shift", ["url", "strategy"])
LAB_TTFB_MS = Gauge("psi_lab_ttfb_milliseconds", "Lighthouse Server Response Time (TTFB) in ms", ["url", "strategy"])

# Полевые метрики (CrUX 28-day p75)
FIELD_LCP_P75_MS = Gauge("psi_field_lcp_p75_milliseconds", "CrUX LCP p75 in ms", ["url", "strategy"])
FIELD_INP_P75_MS = Gauge("psi_field_inp_p75_milliseconds", "CrUX INP p75 in ms", ["url", "strategy"])
FIELD_CLS_P75 = Gauge("psi_field_cls_p75_ratio", "CrUX CLS p75 ratio", ["url", "strategy"])
FIELD_PASSED = Gauge("psi_field_cwv_passed", "Core Web Vitals Assessment verdict (1=Passed, 0=Failed)", ["url", "strategy"])

def collect_metrics_for_url(url: str, strategy: str = "mobile"):
    endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {
        "url": url,
        "strategy": strategy,
        "category": "performance",
        "key": API_KEY
    }

    try:
        resp = requests.get(endpoint, params=params, timeout=60)
        if resp.status_code == 429:
            logging.warning(f"Превышен лимит запросов (HTTP 429) для {url}. Пропуск цикла.")
            return
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Сбой выполнения запроса к PSI API для {url} ({strategy}): {e}")
        return

    # 1. Извлечение Lab Data
    lh = data.get("lighthouseResult", {})
    categories = lh.get("categories", {})
    audits = lh.get("audits", {})

    perf_score = categories.get("performance", {}).get("score")
    if perf_score is not None:
        LAB_SCORE.labels(url=url, strategy=strategy).set(perf_score * 100)

    lcp_val = audits.get("largest-contentful-paint", {}).get("numericValue")
    if lcp_val is not None:
        LAB_LCP_MS.labels(url=url, strategy=strategy).set(lcp_val)

    tbt_val = audits.get("total-blocking-time", {}).get("numericValue")
    if tbt_val is not None:
        LAB_TBT_MS.labels(url=url, strategy=strategy).set(tbt_val)

    cls_val = audits.get("cumulative-layout-shift", {}).get("numericValue")
    if cls_val is not None:
        LAB_CLS.labels(url=url, strategy=strategy).set(cls_val)

    ttfb_val = audits.get("server-response-time", {}).get("numericValue")
    if ttfb_val is not None:
        LAB_TTFB_MS.labels(url=url, strategy=strategy).set(ttfb_val)

    # 2. Извлечение Field Data (CrUX)
    experience = data.get("loadingExperience", {})
    field_metrics = experience.get("metrics", {})

    field_lcp = field_metrics.get("LARGEST_CONTENTFUL_PAINT_MS", {}).get("percentile")
    if field_lcp is not None:
        FIELD_LCP_P75_MS.labels(url=url, strategy=strategy).set(field_lcp)

    field_inp = field_metrics.get("INTERACTION_TO_NEXT_PAINT", {}).get("percentile")
    if field_inp is not None:
        FIELD_INP_P75_MS.labels(url=url, strategy=strategy).set(field_inp)

    field_cls = field_metrics.get("CUMULATIVE_LAYOUT_SHIFT_SCORE", {}).get("percentile")
    if field_cls is not None:
        FIELD_CLS_P75.labels(url=url, strategy=strategy).set(field_cls / 100.0)

    # Вердикт Core Web Vitals
    overall_cat = experience.get("overall_category")
    if overall_cat == "FAST":
        FIELD_PASSED.labels(url=url, strategy=strategy).set(1)
    else:
        FIELD_PASSED.labels(url=url, strategy=strategy).set(0)

    logging.info(f"Успешно собраны метрики для {url} [{strategy}]: Score={perf_score}")

def run_loop():
    logging.info(f"Запуск PSI Exporter на порту {EXPORTER_PORT}...")
    start_http_server(EXPORTER_PORT)

    while True:
        for url in TARGET_URLS:
            collect_metrics_for_url(url, strategy="mobile")
            time.sleep(5)  # Защитная пауза между запросами к API
        time.sleep(SCRAPE_INTERVAL_SEC)

if __name__ == "__main__":
    run_loop()
```

Конфигурационный файл окружения (`/etc/default/psi-exporter`):

```bash
# /etc/default/psi-exporter
PSI_API_KEY="AIzaSyYourSecretTokenHere"
PSI_TARGET_URLS="https://example.com/,https://example.com/catalog"
PSI_SCRAPE_INTERVAL=7200
PSI_EXPORTER_PORT=9198
```

Юнит systemd (`/etc/systemd/system/psi-exporter.service`):

```ini
[Unit]
Description=PageSpeed Insights and CrUX Prometheus Exporter
After=network.target

[Service]
Type=simple
User=prometheus
Group=prometheus
EnvironmentFile=/etc/default/psi-exporter
ExecStart=/usr/bin/python3 /usr/local/bin/psi_exporter.py
Restart=always
RestartSec=30s
ProtectSystem=strict
ProtectHome=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Активация и запуск службы:

```bash
chmod +x /usr/local/bin/psi_exporter.py
systemctl daemon-reload
systemctl enable --now psi-exporter.service
systemctl status psi-exporter.service
# → Active: active (running) since Wed 2026-10-14 12:00:00 UTC; 5s ago
# → Main PID: 12450 (python3)
```

Конфигурация сбора метрик в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'pagespeed_insights'
    scrape_interval: 5m
    scrape_timeout: 30s
    static_configs:
      - targets: ['127.0.0.1:9198']
```

### Правила алертинга в Prometheus Alertmanager

Файл правил (`/etc/prometheus/rules/psi_alerts.yml`):

```yaml
groups:
  - name: pagespeed_insights_alerts
    rules:
      - alert: CoreWebVitalsFailed
        expr: psi_field_cwv_passed{strategy="mobile"} == 0
        for: 1h
        labels:
          severity: warning
          domain: web_performance
        annotations:
          summary: "Core Web Vitals Assessment не пройден для {{ $labels.url }}"
          description: "Страница {{ $labels.url }} не прошла 75-й перцентиль по Core Web Vitals в CrUX. Риск деградации ранжирования."

      - alert: HighFieldLCPDegradation
        expr: psi_field_lcp_p75_milliseconds{strategy="mobile"} > 2500
        for: 2h
        labels:
          severity: warning
        annotations:
          summary: "Превышение порога LCP (p75 > 2500 мс) на {{ $labels.url }}"
          description: "Текущий p75 LCP составляет {{ $value }} мс. Требуется оптимизация TTFB и сжатия ассетов."

      - alert: HighFieldINPDegradation
        expr: psi_field_inp_p75_milliseconds{strategy="mobile"} > 200
        for: 2h
        labels:
          severity: warning
        annotations:
          summary: "Превышение порога INP (p75 > 200 мс) на {{ $labels.url }}"
          description: "Текущий p75 INP составляет {{ $value }} мс. Зафиксированы блокировки главного потока JS при кликах."

      - alert: LabPerformanceScoreDropped
        expr: psi_lab_performance_score{strategy="mobile"} < 80
        for: 30m
        labels:
          severity: critical
        annotations:
          summary: "Резкое падение синтетического балла Lighthouse (< 80) на {{ $labels.url }}"
          description: "Лабораторная производительность упала до {{ $value }}. Возможен сбой кэширования или деплой неоптимизированных скриптов."
```

## Диагностика и устранение неполадок

| Проблема | Симптом / Код ошибки | Первичная диагностика | Решение системного администратора |
| :--- | :--- | :--- | :--- |
| **Превышение квоты API (Rate Limit)** | HTTP 429, `"status": "RESOURCE_EXHAUSTED"` | Проверить заголовки ответа и частоту вызовов через cron/exporter | 1. Использовать API Key.<br>2. Соблюдать лимит: не более 25 000 запросов/сутки и 25 req/s.<br>3. Увеличить интервал опроса экспортера (раз в 2–4 часа).<br>4. Внедрить экспоненциальный backoff при повторах. |
| **Бот заблокирован WAF / Nginx** | `ERRORED_DOCUMENT_REQUEST`, `FAILED_DOCUMENT_REQUEST` | Проверить `/var/log/nginx/access.log` и `error.log` по User-Agent `Google-Lighthouse` | 1. Добавить User-Agent `*Google-Lighthouse*` и `*Chrome-Lighthouse*` в белый список модулей WAF (ModSecurity, Fail2ban).<br>2. Исключить краулеров из жестких зон `limit_req_zone`. |
| **Сбой первой отрисовки в Lab** | `NO_FCP` (Lighthouse did not record any first contentful paint) | Проверить время ответа страницы: `curl -o /dev/null -s -w "%{time_starttransfer}\n" https://example.com/` | 1. Устранить таймаут бэкенда (TTFB > 10 с приводит к ошибке).<br>2. Устранить циклические JS-ошибки, блокирующие рендеринг страницы при пустом кэше. |
| **Недостаточно данных в CrUX** | `loadingExperience.metrics` пустой или `origin_fallback: true` | Проверить объем посещений страницы в аналитике | Страница имеет менее нескольких сотен визитов в месяц. Опираться на Origin-метрики до накопления выборки либо использовать собственный RUM. |
| **Инерция данных при исправлении** | Код исправлен, Lab 100/100, но CrUX показывает `Failed` | Проверить `collectionPeriod` в ответе CrUX API | Полевые данные агрегируются за 28 дней. Зафиксировать дату релиза, отслеживать динамику через CrUX History API неделя к неделе. |
| **Недействительный SSL/TLS сертификат** | `INSECURE_DOCUMENT_REQUEST` | Выполнить валидацию цепочки сертификатов: `openssl s_client -connect example.com:443 -servername example.com` | Обновить просроченный сертификат или настроить корректную отдачу промежуточных сертификатов (Intermediate CA bundle). |
| **Высокий TTFB в Lab Data** | Аудит `server-response-time` > 800 мс | `curl -s -w "@curl-format.txt" -o /dev/null https://example.com/` | 1. Включить кэширование FastCGI/Proxy в Nginx (`proxy_cache`).<br>2. Проверить пулинг соединений `keepalive` до апстримов.<br>3. Оптимизировать медленные SQL-запросы в приложении. |
| **Блокировка отрисовки шрифтами** | Аудит `render-blocking-resources` ругается на шрифты | Проверить заголовок ответа CSS/шрифтов | Настроить отдачу шрифтов локально с Nginx с директивой `font-display: swap;` и кэшированием на 1 год. |

### Методология пошаговой диагностики для SRE

```text
[ Обнаружение деградации в PSI ]
              │
              ▼
 Шаг 1: Разделение контуров
 ├── Если деградировал только Lab Data:
 │     Проверить свежий деплой, bundle size фронтенда, новые сторонние скрипты (Third-Party).
 └── Если деградировал Field Data (CrUX):
       Проверить географию пользователей, всплески сетевых задержек, метрики балансировщика.
              │
              ▼
 Шаг 2: Проверка сетевого стека и доступности Origin
 ├── curl -o /dev/null -s -w "DNS: %{time_namelookup}s | Connect: %{time_connect}s | TLS: %{time_appconnect}s | TTFB: %{time_starttransfer}s | Total: %{time_total}s\n" https://example.com/
 └── openssl s_client -connect example.com:443 -servername example.com -tls1_3
              │
              ▼
 Шаг 3: Проверка блокировок на уровне веб-сервера / WAF
 ├── grep -E "(Google-Lighthouse|Googlebot)" /var/log/nginx/access.log | grep -E " (403|429|500|502|503|504) "
 └── fail2ban-client status nginx-limit-req
              │
              ▼
 Шаг 4: Применение исправлений и контрольная валидация
 ├── nginx -t && systemctl reload nginx
 └── Запуск тестового запроса в PSI API v5 для проверки устранения замечаний в Lab Data
```

## Рекомендации и лучшие практики

### Чеклист SRE и системного администратора

- [ ] **Белый список краулеров:** Проверено, что боты Googlebot и Lighthouse не блокируются Fail2ban, WAF или директивами `limit_req`.
- [ ] **Базовый TTFB $\le 800$ мс:** Настроен reverse proxy кэш в Nginx (`proxy_cache`), включены постоянные соединения к апстримам (`keepalive 32;`).
- [ ] **Современный транспорт:** Включены HTTP/2 и HTTP/3 (QUIC), включен TLS 1.3 с возобновлением сессий (Session Tickets/Cache).
- [ ] **Сжатие текстовых ассетов:** Включено сжатие Brotli (уровень 4–5) и Gzip (уровень 6) для типов `text/*`, `application/javascript`, `application/json`, `image/svg+xml`.
- [ ] **Неизменяемый кэш статики:** Для всех версионированных файлов (`bundle.a1b2c3.js`, шрифты, картинки) отдается `Cache-Control: public, max-age=31536000, immutable`.
- [ ] **Квоты и частота API:** Автоматизированные системы сбора данных (Prometheus Exporter) настроены на опрос не чаще одного раза в 1–2 часа для исключения HTTP 429.
- [ ] **Алертинг на тренды:** Настроены алерты на падение `psi_field_cwv_passed` и скачки `psi_lab_lcp_milliseconds` до того, как они затронут бизнес-показатели.

### Регламент отката при деградации метрик

Если ночной релиз вызвал резкое падение синтетического балла Lighthouse ниже 80 или рост TBT выше 300 мс:

1. **Немедленная фиксация аномалии:** Сохранить JSON-отчет аудита PSI:
   ```bash
   curl -sS "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=https://example.com/&key=$PSI_API_KEY" > /var/log/psi_incident_$(date +%F_%H%M).json
   ```
2. **Откат конфигурации или бандла:**
   ```bash
   # Откат конфигурации Nginx при наличии регрессии в правилах кэширования
   git -C /etc/nginx checkout HEAD~1 conf.d/
   nginx -t && systemctl reload nginx

   # Либо переключение symlink релиза приложения
   ln -sfn /var/www/app/releases/previous /var/www/app/current
   systemctl restart app-backend
   ```
3. **Контрольный прогон PSI:**
   ```bash
   /usr/local/bin/ci-psi-check.sh "https://example.com/"
   ```

### Нагрузка диагностических инструментов и лимиты API

| Операция / Инструмент | Влияние на Production-сервер | Лимиты и квоты | Рекомендация по применению |
| :--- | :--- | :--- | :--- |
| **PageSpeed Insights Web UI** | 1–3 сессии headless Chrome со стороны Google | 25 req/s по IP | Ручной ad-hoc аудит при расследовании инцидентов |
| **PSI API v5 (`runPagespeed`)** | Внешний HTTP-запрос от серверов Google | 25 000 запросов в сутки, 25 req/s | Автоматические проверки в CI/CD и периодический сбор раз в 2 ч |
| **CrUX API (`queryRecord`)** | Нулевая нагрузка на сервер (запрос в базу Google) | 150 запросов в минуту | Сбор агрегированных полевых метрик и SLO-отчетов |
| **CrUX History API** | Нулевая нагрузка на сервер | 150 запросов в минуту | Еженедельное построение ретроспективных графиков в Grafana |
| **Локальный Lighthouse CLI** | Локальная нагрузка на CPU и RAM тестового раннера | Ограничено ресурсами сервера | Регрессионное тестирование на Staging до выкатки на Production |

## Дополнительная информация

### См. также

- **[Ключевые метрики Web Vitals](./web_vitals.md)** — глубокий разбор LCP, INP, CLS, математика перцентилей и браузерная библиотека `web-vitals`.
- **[Методология и принципы тестирования](./testing_principles.md)** — разница между RUM и синтетикой, сетевой троттлинг, статистическая достоверность.
- **[Обзор веб-производительности](./overview.md)** — архитектура и место PSI в общей стратегии SRE/DevOps.
- **[Лучшие практики оптимизации](./best_practices.md)** — расчет Performance Budget, интеграция в CI/CD, серверные оптимизации.
- **[Профессиональный анализ в WebPageTest](./webpagetest.md)** — глубокая диагностика Waterfall, трассировка кадров, когда возможностей PSI недостаточно.
- **[Zero-Downtime Deployment](./zero_downtime_deployment.md)** — деплой веб-сервисов без деградации p75 TTFB и ошибок 5xx.
- **[Image Optimization Pipeline](./image_optimization_pipeline.md)** — автоматизация генерации WebP/AVIF для минимизации фазы Resource Load Duration LCP.
- **[Structured Logging для Performance](./structured_logging_for_performance.md)** — структурированное логирование таймингов Nginx для корреляции с метриками CrUX.
