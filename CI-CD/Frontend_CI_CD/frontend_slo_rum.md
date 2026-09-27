# SLO/SLI и RUM для фронтенда (SRE-практика)

## Определения

- **SLI (Service Level Indicator)** — измеримая метрика качества сервиса, по которой оценивается здоровье фронтенда (например, доля успешных загрузок LCP < 2.5 с).
- **SLO (Service Level Objective)** — целевое значение SLI за период (например, 99% посещений с LCP < 2.5 с за 28 дней).
- **Error Budget (Бюджет ошибок)** — допустимая доля нарушений SLO (100% − SLO). Расходуется при деградации; при исчерпании блокируются рискованные релизы.
- **RUM (Real User Monitoring)** — сбор метрик реальных пользователей из браузеров на производственных устройствах и сетях (в отличие от синтетических тестов в CI).
- **Core Web Vitals (CWV)** — LCP, CLS, INP — ключевые метрики пользовательского опыта. Детали порогов, фаз LCP и диагностики: [Web Vitals — ключевые метрики](../../WebServers/Concepts/web_performance/web_vitals.md).
- **Crash-Free Sessions / JS Error Rate** — доля сессий без необработанных ошибок JS.
- **Burn Rate (Скорость сжигания)** — отношение фактической частоты ошибок к запланированной. Формула и multi-window алертинг: [Концепции SRE](../../Concepts/sre_concepts_main.md), [Web Vitals](../../WebServers/Concepts/web_performance/web_vitals.md).

---

## Основные концепции

### Зачем фронтенду нужны SLO

Бэкенд может быть «здоров», а пользователь — страдать от медленного рендеринга, битых чанков или ошибок JS. Фронтенд-SLO переводят «ощущение медленности» в измеримые цели и дают основание блокировать релиз при регрессии.

### Архитектура сбора RUM

Данные от браузера до алерта проходят несколько этапов:
1. **Инъекция агента:** библиотека `web-vitals` или кастомный агент отправляет метрики через `navigator.sendBeacon` (с фолбэком на `fetch` с `keepalive: true`).
2. **Коллектор:** self-hosted endpoint (Nginx/Angie, Prometheus Pushgateway или Grafana Faro). Желательно размещать на отдельном origin/subdomain, чтобы оставаться доступным при сбое основного сайта.
3. **Агрегация:** Prometheus собирает метрики, вычисляет `good_ratio` за скользящее окно (28 дней).
4. **Алертинг:** Alertmanager группирует и эскалирует алерты по severity.
5. **Реакция:** on-call инженер выполняет runbook (откат, kill switch, анализ).

### Метрики фронтенда (что измеряем)
- **Производительность:** LCP, CLS, INP, TTFB, время до интерактивности.
- **Надёжность:** JS Error Rate, Crash-Free Sessions, доля 4xx/5xx на загрузке ассетов.
- **Доступность ассетов:** процент успешных загрузок хэшированных чанков (ловит «битый деплой» / неполную инвалидацию CDN).

### Error Budget (Бюджет ошибок)
Стандартный подход (Google SRE): если бюджет исчерпан — заморозка фич, приоритет стабилизации. В пайплайне это реализуется проверкой метрик за период перед релизом.

Политика реагирования:
- **>50% осталось:** обычная работа, агрессивные эксперименты.
- **10–50% осталось:** повышенное внимание к тестам, замедление релизов.
- **0–10% осталось:** только критические исправления.
- **≤0% (бюджет исчерпан):** Feature Freeze, работа только над стабильностью.

### Требования к окружению

Для реализации фронтенд-SLO в продакшене необходимы:
- **Библиотека сбора метрик:** `web-vitals` или кастомный агент, внедрённый в сборку/шаблон.
- **Коллектор:** self-hosted endpoint (Nginx/Angie, Prometheus Pushgateway или Grafana Faro). Желательно на отдельном origin/subdomain, чтобы оставаться доступным при сбое основного сайта.
- **Prometheus + Alertmanager:** для хранения временных рядов, вычисления `good_ratio` и эскалации алертов.
- **CI/CD:** возможность запуска скриптов перед деплоем (GitLab CI, GitHub Actions, Jenkins).
- **Feature flag платформа:** для kill switch (Unleash, Flipt, LaunchDarkly) или собственная реализация.
- **Дашборд:** Grafana-панель с трендами LCP/INP/CLS и error budget.

### RUM vs синтетика
LHCI в CI (см. [Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)) — это синтетика (лабораторная среда). RUM — поле (реальные устройства, сети, гео). Оба нужны: синтетика ловит регрессию до продакшена, RUM — подтверждает её влияние на пользователей.

### Связь с Progressive Delivery
RUM-метрики используются как сигнал для канареечных деплоев и автоматического отката. После переключения части трафика на новую версию мониторится Burn Rate по RUM; при превышении порога — автоматический rollback или ручной kill switch через feature flag (см. [Feature flags в доставке фронтенда](./feature_flags_frontend.md)).

---

## Практические сценарии

### Сценарий 1: Сбор RUM в браузере
```javascript
// web-vitals + отправка в self-hosted коллектор/Prometheus Pushgateway
import { onLCP, onCLS, onINP } from 'web-vitals'
function send(metric) {
  navigator.sendBeacon('/collect', JSON.stringify({
    name: metric.name, value: metric.value, path: location.pathname,
  }))
}
onLCP(send); onCLS(send); onINP(send)
// JS-ошибки
window.addEventListener('error', e => navigator.sendBeacon('/collect', JSON.stringify({name:'js_error', msg:e.message})))
```

### Сценарий 2: Определение SLI/SLO и алерт (Prometheus)
```yaml
# recording rule: доля LCP < 2.5s
- record: job:frontend_lcp_good_ratio
  expr: sum(rate(lcp_good[28d])) / sum(rate(lcp_total[28d]))
# alert при расходе бюджета
- alert: FrontendErrorBudgetBurn
  expr: job:frontend_lcp_good_ratio < 0.99   # SLO 99%
  for: 1h
```

### Сценарий 3: Блокировка релиза при исчерпании бюджета (шаг CI)
```bash
# Перед деплоем проверяем текущий SLO
SLO_OK=$(curl -s "$PROMETHEUS/api/v1/query?query=job:frontend_lcp_good_ratio" | jq '.data.result[0].value[1] | tonumber > 0.99')
if [ "$SLO_OK" != "true" ]; then echo "Error budget exhausted — deploy blocked"; exit 1; fi
```

### Сценарий 4: Алерт на всплеск JS-ошибок после деплоя
```yaml
- alert: JSErrorSpike
  expr: increase(js_errors_total[5m]) / increase(page_views_total[5m]) > 0.01
  for: 10m
  annotations:
    runbook: "Откатить через feature flag kill switch (см. feature_flags_frontend.md)"
```

---

## Дополнительная информация

### Лучшие практики
1. Начните с 2-3 SLO (LCP, JS Error Rate, Crash-Free), не пытайтесь покрыть всё сразу.
2. RUM-данные агрегируйте по страницам/гео — регрессия часто локальна.
3. Свяжите SLO с пайплайном: блокируйте релиз при сожжённом бюджете.
4. Используйте `sendBeacon` — он не блокирует выгрузку страницы при уходе пользователя.
5. Дублируйте RUM-проверку ассетов: падение загрузки чанков = ранний сигнал битого деплоя.

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| RUM не совпадает с LHCI | Разные устройства/сети | RUM и синтетика — разные источники, сравнивайте тренды, не точки |
| Данные теряются | `sendBeacon` режется блокировщиком | Резервный `fetch` с `keepalive: true` |
| Ложные алерты | Шумные страницы | Фильтрация по percentile, группировка по route |
| Нет корреляции с релизом | Метрики без версии | Добавлять `deploy_version` в RUM-события |
| Бюджет тает без инцидентов | Постоянный низкий фон ошибок | Анализ Burn Rate с длинным окном (6ч, 24ч); проверка таймаутов на стороне бэкендов |
| SLO выполняется, но пользователи недовольны | Выбран неверный SLI | Внедрение RUM (CrUX или кастомный агент), проверка CUJ через E2E тесты |
| Алерт не срабатывает при падении | Отсутствуют данные за окно (низкий трафик) | Увеличить окно или использовать anomaly detection вместо абсолютного порога |
| Откат не помог | Старый SW кэширует битый HTML | Инвалидировать `sw.js` + принудительный reload |

### Диагностика пайплайна RUM

```bash
# Проверка доступности коллектора
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://example.com/collect \
  -H "Content-Type: application/json" \
  -d '{"name":"test","value":1}'
# → 204 (при корректной настройке)

# Проверка CORS для RUM-эндпоинта
curl -sI -X OPTIONS https://example.com/collect \
  -H "Origin: https://example.com" \
  -H "Access-Control-Request-Method: POST" | \
  grep -i "access-control-allow-origin"
# → access-control-allow-origin: https://example.com

# Проверка, что метрики доходят до Prometheus
curl -s "$PROMETHEUS/api/v1/query?query=rate(lcp_total[1m])" | \
  jq '.data.result[0].value[1]'
# → 0.5 (ненулевое значение при наличии трафика)

# Проверка активных алертов фронтенда
curl -s "$PROMETHEUS/api/v1/query?query=ALERTS{alertname=~\"Frontend.*\"}" | \
  jq '.data.result | length'
# → 0 (ожидается при нормальной работе)
```

### Особые случаи

- **Ad blockers и Privacy-режимы:** многие блокировщики рекламы отрезают отправку метрик на сторонние домены. Используйте тот же origin, что и сайт (first-party), или субдомен с разрешённой передачей.
- **Низкий трафик (low-traffic B2B):** при малом объёме сессий статистическая значимость 28-дневного окна низка. Увеличивайте окно или используйте anomaly detection вместо абсолютного порога.
- **SPA и маршрутизация:** `location.pathname` может быть неинформативен, если SSR отдаёт один `index.html`. Используйте client-side route или data-атрибут для идентификации логической страницы.
- **Iframes и кросс-origin:** `web-vitals` в iframe измеряет только фрейм. Для страницы в целом нужна агрегация на уровне верхнего окна или server-side метрики.
- **Боты и Synthetics:** трафик ботов и Lighthouse в CI может искажать RUM. Фильтруйте по User-Agent и исключайте известные CIDR синтетики из расчёта SLO.

### См. также
- **[Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)** — LHCI как синтетический SLI.
- **[Инцидент-респонс для фронтенда](./frontend_incident_response.md)** — действия при расходе бюджета.
- **[Web Vitals — ключевые метрики](../../WebServers/Concepts/web_performance/web_vitals.md)** — пороги CWV, Burn Rate, Prometheus-алертинг.
