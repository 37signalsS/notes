# SLO/SLI и RUM для фронтенда (SRE-практика)

## Определения

- **SLI (Service Level Indicator)** — измеримая метрика качества (например, доля LCP < 2.5s).
- **SLO (Service Level Objective)** — целевое значение SLI за период (например, 99% запросов LCP < 2.5s за 28 дней).
- **Error Budget (Бюджет ошибок)** — допустимая доля нарушений SLO (100% − SLO). Расходуется при деградации; при исчерпании блокируются рискованные релизы.
- **RUM (Real User Monitoring)** — сбор метрик реальных пользователей из браузеров (в отличие от синтетических тестов в CI).
- **Core Web Vitals (CWV)** — LCP, CLS, INP — ключевые метрики пользовательского опыта.
- **Crash-Free Sessions / JS Error Rate** — доля сессий без необработанных ошибок JS.

---

## Основные концепции

### Зачем фронтенду нужны SLO
Бэкенд может быть «здоров», а пользователь — страдать от медленного рендеринга, битых чанков или ошибок JS. Фронтенд-SLO переводят «ощущение медленности» в измеримые цели и дают основание блокировать релиз при регрессии.

### Метрики фронтенда (что измеряем)
- **Производительность:** LCP, CLS, INP, TTFB, время до интерактивности.
- **Надёжность:** JS Error Rate, Crash-Free Sessions, доля 4xx/5xx на загрузке ассетов.
- **Доступность ассетов:** процент успешных загрузок хэшированных чанков (ловит «битый деплой» / неполную инвалидацию CDN).

### Error Budget (Бюджет ошибок)
Стандартный подход (Google SRE): если бюджет исчерпан — заморозка фич, приоритет стабилизации. В пайплайне это реализуется проверкой метрик за период перед релизом.

### RUM vs синтетика
LHCI в CI (см. [Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)) — это синтетика (лабораторная среда). RUM — поле (реальные устройства, сети, гео). Оба нужны: синтетика ловит регрессию до продакшена, RUM — подтверждает её влияние на пользователей.

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
- record: job:frondend_lcp_good_ratio
  expr: sum(rate(lcp_good[28d])) / sum(rate(lcp_total[28d]))
# alert при расходе бюджета
- alert: FrontendErrorBudgetBurn
  expr: job:frondend_lcp_good_ratio < 0.99   # SLO 99%
  for: 1h
```

### Сценарий 3: Блокировка релиза при исчерпании бюджета (шаг CI)
```bash
# Перед деплоем проверяем текущий SLO
SLO_OK=$(curl -s "$PROMETHEUS/api/v1/query?query=job:frondend_lcp_good_ratio" | jq '.data.result[0].value[1] | tonumber > 0.99')
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

### См. также
- **[Наблюдаемость пайплайнов](../Core_Concepts/pipeline_observability.md)** — откуда берутся метрики сборки.
- **[Метрики DORA](../Core_Concepts/dora_metrics.md)** — Change Failure Rate коррелирует с JS Error Rate.
- **[Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)** — LHCI как синтетический SLI.
- **[Инцидент-респонс для фронтенда](./frontend_incident_response.md)** — действия при расходе бюджета.
