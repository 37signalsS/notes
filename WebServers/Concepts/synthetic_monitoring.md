# Синтетический мониторинг веб-серверов

## Определения

**Синтетический мониторинг (Synthetic Monitoring)** — метод наблюдения за сервисом, при котором внешние probes отправляют запросы к production-эндпоинтам и измеряют latency, availability, correctness. В отличие от blackbox monitoring, синтетика проверяет не только "жив ли сервис", но и "работает ли он корректно".

**Blackbox Probe** — внешний агент, который периодически опрашивает веб-сервер по HTTP/HTTPS, TCP, ICMP. Измеряет availability и latency извне.

**Multi-step Synthetic** — сложный сценарий, имитирующий путь пользователя: открыть главную страницу, нажать кнопку, отправить форму, проверить редирект.

**Synthetic from multiple locations** — probes из разных geographic locations для проверки CDN, DNS, глобальной доступности.

**Assertion** — проверка корректности ответа: status code, body content, header, latency threshold.

## Основные концепции

### Типы синтетических проверок

| Тип | Механизм | Использование |
| :--- | :--- | :--- |
| **HTTP/HTTPS probe** | GET/POST запрос, проверка status code | Базовый uptime |
| **TCP probe** | Подключение к порту | Проверка слушающего порта |
| **SSL probe** | Проверка сертификата, chain, expiration | TLS мониторинг |
| **DNS probe** | A/AAAA/MX запрос | DNS мониторинг |
| **Multi-step** | Цепочка запросов (login, browse, checkout) | End-to-end сценарии |
| **API probe** | JSON-RPC, GraphQL запрос | API availability |
| **Real Browser** | Headless Chrome/Firefox (Puppeteer, Playwright) | SPA, JS-heavy |

### Метрики синтетики

| Метрика | Описание | Порог |
| :--- | :--- | :--- |
| **Uptime** | % успешных проверок за период | 99.9% |
| **Latency** | Время ответа (p50, p95, p99) | p95 < 500ms |
| **Correctness** | Корректность контента (assertion) | 100% |
| **TTFB** | Time to First Byte | < 200ms |
| **SSL expiry** | Дней до истечения сертификата | > 14 дней |
| **Redirect chain** | Количество редиректов | < 3 |

### Инструменты

| Инструмент | Тип | Особенности |
| :--- | :--- | :--- |
| **UptimeRobot** | SaaS | Простой, 5-min interval |
| **Pingdom** | SaaS | Мониторинг, Real User Monitoring |
| **Datadog Synthetic** | SaaS | Multi-step, Real Browser |
| **New Relic Synthetics** | SaaS | Private locations |
| **Grafana Synthetic** | Open-source | k6-based, self-hosted |
| **Blackbox Exporter** | Open-source | Prometheus, multi-protocol |
| **k6** | Open-source | Load testing + synthetic |
| **Playwright/Puppeteer** | Open-source | Real Browser |

## Практические сценарии

### Сценарий 1: Blackbox Exporter + Prometheus

Полная конфигурация модулей и scrape-правил — в **[Blackbox Exporter: установка и настройка](../../Prometheus/Exporters/blackbox/blackbox_exporter_installation_and_setup.md)**. Краткая проверка:

```bash
curl http://localhost:9115/probe?target=http://example.com&module=http_2xx
# → probe_success 1
```

### Сценарий 2: Multi-step Synthetic с Grafana k6

```javascript
// /etc/k6/synthetic.js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
    scenarios: {
        home_page: {
            executor: 'per-vu-iterations',
            vus: 1,
            iterations: 1,
        },
        login_flow: {
            executor: 'per-vu-iterations',
            vus: 1,
            iterations: 1,
            startTime: '2s',
        },
    },
    thresholds: {
        'http_req_duration': ['p(95)<500'],
        'checks': ['rate>0.99'],
    },
};

export default function () {
    let home = http.get('https://example.com/');
    check(home, {
        'home status is 200': (r) => r.status === 200,
        'home has title': (r) => r.body.includes('Example'),
        'home latency < 500ms': (r) => r.timings.duration < 500,
    });
    sleep(1);

    let login = http.post('https://example.com/login', {
        username: 'test',
        password: 'test',
    });
    check(login, {
        'login status is 200': (r) => r.status === 200,
        'login has cookie': (r) => r.headers['Set-Cookie'] !== undefined,
    });
    sleep(1);

    let dashboard = http.get('https://example.com/dashboard', {
        headers: { Cookie: login.headers['Set-Cookie'] },
    });
    check(dashboard, {
        'dashboard status is 200': (r) => r.status === 200,
        'dashboard has data': (r) => r.body.includes('Dashboard'),
    });
}
```

**Валидация:**
- `k6 run /etc/k6/synthetic.js` — запуск.
- `k6 run --out prometheus-rgw /etc/k6/synthetic.js` — экспорт в Prometheus.

### Сценарий 3: Real Browser с Playwright

```typescript
// /etc/synthetic/homepage.spec.ts
import { test, expect } from '@playwright/test';

test('Homepage loads and has correct title', async ({ page }) => {
    const response = await page.goto('https://example.com/');
    expect(response?.status()).toBe(200);
    await expect(page).toHaveTitle('Example');
    await expect(page.locator('h1')).toContainText('Example');
});
```

**Валидация:**
- `npx playwright test homepage.spec.ts --project=chromium` — запуск.
- `npx playwright test --grep "Homepage" --reporter=list` — краткий вывод.

### Сценарий 4: Проверка SSL-сертификата

```bash
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | \
    openssl x509 -noout -dates

openssl s_client -connect example.com:443 -servername example.com -showcerts 2>/dev/null | \
    grep -E "Verify return code|depth="
```

## Лучшие практики

1. **Несколько locations:** probes из разных geographic locations (EU, US, APAC).
2. **Multi-step для критичных путей:** login, checkout, поиск.
3. **Assertions на каждый шаг:** проверяйте status code, body, headers.
4. **Alert на degradation, не только outage:** latency p95 > threshold = alert.
5. **Private locations для внутренних сервисов:** используйте k6/Playwright из внутренней сети.
6. **Real Browser для SPA:** если сайт на React/Vue, используйте headless Chrome.
7. **Synthetic from CDN edge:** проверяйте, что CDN раздаёт корректный контент.
8. **Correlation ID в synthetic:** добавьте `X-Synthetic-Request-ID` для трассировки.

## Граничные случаи и ограничения

1. **Synthetic не заменяет Real User Monitoring:** synthetic проверяет доступность, RUM — реальный опыт пользователей.
2. **Задержка probes:** интервал опроса влияет на MTTR. 1 min interval — стандарт для production.
3. **CAPTCHA и authentication:** для защищённых endpoints используйте service account или API key.
4. **Rate limiting на synthetic:** probes могут быть заблокированы rate limiter'ом. Whitelist IP probes.
5. **Flapping tests:** если assertion слишком строгий, алерт будет флипать. Используйте `for: 5m`.
6. **CDN кэширование:** synthetic запросы могут кэшироваться CDN. Используйте `Cache-Control: no-cache`.

## Дополнительная информация

- **[Наблюдаемость HTTP-сервисов](../../Networking/Protocols/HTTP/http_monitoring_observability.md)** — RED method, Golden Signals.
- **[Prometheus Blackbox Exporter](https://github.com/prometheus/blackbox_exporter)** — конфигурация.
- **[k6 Synthetic Monitoring](https://k6.io/docs/using-k6/synthetic-monitoring/)** — multi-step synthetic.
- **[Grafana k6](https://grafana.com/docs/k6/latest/)** — cloud-hosted synthetic.
