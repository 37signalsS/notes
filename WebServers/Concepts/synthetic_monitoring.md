# Синтетический мониторинг веб-серверов

**Актуально для:** Prometheus Blackbox Exporter 0.28+, Grafana k6 1.x / 0.54+, Playwright 1.50+, Curl 8.x, OpenSSL 3.x, Linux Kernel 6.x

## Определения

- **Синтетический мониторинг (Synthetic Monitoring / Active Probing)** — метод проактивного наблюдения за веб-сервисами, при котором выделенные агенты-проберы (probes) периодически генерируют искусственный трафик к целевым сетевым эндпоинтам для непрерывной оценки доступности (availability), задержек (latency), целостности содержимого (correctness) и соответствия SLA/SLO до того, как деградация затронет реальных пользователей.
- **Blackbox Probing (Черноящичный опрос)** — проверка работоспособности системы исключительно через внешние сетевые интерфейсы (L3/L4/L7: ICMP, TCP, TLS, HTTP, DNS) без доступа к внутреннему состоянию приложения, метрикам рантайма или системным логам сервера.
- **Whitebox Monitoring (Белоящичный мониторинг)** — сбор внутренних телеметрических данных самого веб-сервера и приложения (метрики `nginx_status`, CPU/RAM worker-процессов, системные вызовы ядра, счетчики пула соединений).
- **RUM (Real User Monitoring / Пассивный мониторинг)** — сбор телеметрии непосредственно с устройств и браузеров реальных пользователей (JavaScript-агенты, логи веб-сервера). В отличие от RUM, синтетический мониторинг воспроизводим, детерминирован и функционирует даже при полном отсутствии реального пользовательского трафика (ночные часы, новые регионы).
- **Multi-step Synthetic (Многошаговый транзакционный сценарий)** — цепочка последовательных зависимых HTTP-запросов, имитирующая критический пользовательский путь (user journey): авторизация, сохранение cookie/сессии, получение CSRF-токена, выполнение бизнес-операции и валидация финального состояния.
- **Headless Browser Probe (Пробер на базе безголового браузера)** — автоматизированный экземпляр браузера (Chromium, Firefox) без графического интерфейса (через Playwright, Puppeteer или Selenium), исполняющий клиентский JavaScript, рендерящий DOM-дерево и оценивающий Single Page Applications (SPA) по метрикам Core Web Vitals и Navigation Timing API.
- **TTFB (Time to First Byte)** — время от момента отправки первого байта HTTP-запроса клиентом до получения первого байта заголовков ответа от сервера; ключевой индикатор суммарной сетевой задержки и времени серверной генерации ответа веб-сервером/бэкендом.
- **Synthetic Assertion (Утверждение проверки)** — логическое правило валидации отклика веб-сервера (соответствие HTTP-статуса, валидность SSL-цепочки, наличие подстроки или JSON-поля в теле, лимит времени ответа), нарушение которого переводит проверку в статус сбоя.
- **Probe Hairpinning (NAT Loopback)** — сетевой эффект, возникающий при попытке внутреннего пробера опросить публичный IP-адрес или домен своего же веб-сервера через внешний шлюз/маршрутизатор, что часто приводит к дропу пакетов или ложным аномалиям задержки.

---

## Архитектура и принципы работы

### Анатомия HTTP(S) синтетической транзакции

Синтетический пробер фиксирует задержку не как единое число, а как строгую последовательность сетевых и протокольных фаз. Декомпозиция этапов позволяет локализовать источник проблемы (DNS, сетевой периметр, перегрузка TLS-терминации или зависание upstream-приложения):

```text
+---------------------------------------------------------------------------------------------------+
|                                      Синтетический HTTP(S) запрос                                  |
+---------------------------------------------------------------------------------------------------+
|  DNS Lookup   |  TCP Handshake  |  TLS Handshake  |  Server Processing (TTFB)  | Content Transfer |
| (namelookup)  |    (connect)    |  (appconnect)   |      (starttransfer)       |     (total)      |
+---------------+-----------------+-----------------+----------------------------+------------------+
|<------------->|                                                                                   |
|               |<--------------->|                                                                 |
|                                 |<--------------->|                                               |
|                                                   |<-------------------------->|                  |
|                                                                                |<---------------->|
|<------------------------------------------ Total Time ------------------------------------------->|
```

1. **DNS Lookup (`time_namelookup`):** Разрешение доменного имени через DNS-резолверы. Выявляет деградацию корпоративных DNS-серверов (BIND, PowerDNS, Unbound), задержки авторитативных зон и ошибки кэширования.
2. **TCP Connect (`time_connect`):** Установка 3-стороннего рукопожатия TCP SYN -> SYN-ACK -> ACK с веб-сервером или балансировщиком. Рост времени указывает на переполнение очереди `tcp_max_syn_backlog`, потери пакетов на маршрутизаторах (packet drop) или насыщение сетевого канала.
3. **TLS Handshake (`time_appconnect`):** Согласование шифров, обмен ключами и валидация X.509 сертификатов. Аномалии на этом шаге свидетельствуют о дефиците CPU на TLS-терминаторе (Nginx/HAProxy), неоптимальной цепочке сертификатов (слишком много промежуточных CA) или отсутствии поддержки TLS Session Resumption.
4. **Server Processing / TTFB (`time_starttransfer`):** Ожидание ответа после отправки HTTP-заголовков/тела. Отражает время обработки запроса веб-сервером и проксирования в бэкенд (PHP-FPM, uWSGI, Node.js, Go, базы данных).
5. **Content Transfer (`time_total` - `time_starttransfer`):** Вычитывание тела ответа по сокету. Длительная фаза говорит о шейпинге полосы, больших полезных нагрузках (не включен `gzip`/`brotli`) или проблемах с размером буферов сокета (`tcp_wmem`).

---

### Топология размещения синтетических агентов

В локальной и гибридной инфраструктуре (On-Premises / Private Data Centers) размещение проберов проектируется по многоуровневой схеме для изоляции сетевых сбоев от системных:

```text
                     [ Внешние точки присутствия (External Probes) ]
                     │   ├── Филиал A / Удаленный ЦОД (PoP 1)
                     │   └── Филиал B / Сторонняя площадка (PoP 2)
                     │
                     ▼ (L3/L7 Интернет-трафик)
         ┌───────────────────────────────────────┐
         │       BGP Anycast / Edge Router       │
         └──────────────────┬────────────────────┘
                            │
                            ▼
         ┌───────────────────────────────────────┐
         │     DMZ: Балансировщики (HAProxy)     │ ◄─── [ DMZ Probes ]
         └──────────────────┬────────────────────┘      (Проверка ingress, WAF, SSL)
                            │
           ┌────────────────┴────────────────┐
           ▼                                 ▼
┌─────────────────────┐           ┌─────────────────────┐
│  Nginx / Apache #1  │           │  Nginx / Apache #2  │ ◄─── [ Internal Cluster Probes ]
│  (Static & Reverse) │           │  (Static & Reverse) │      (Blackbox Exporter по LAN)
└──────────┬──────────┘           └──────────┬──────────┘
           │                                 │
           ▼                                 ▼
┌─────────────────────┐           ┌─────────────────────┐
│ Upstream Apps (API) │           │ Upstream Apps (API) │ ◄─── [ k6 / Playwright Workers ]
└─────────────────────┘           └─────────────────────┘      (Транзакционные сценарии)
```

- **Внешние проберы (External Probes):** Развертываются на физически независимых площадках (удаленные офисы, резервные ЦОД, серверы колокации). Проверяют полный сетевой путь клиента: глобальный DNS, BGP-маршрутизацию, граничные файрволы, CDN-ноды и SSL-терминаторы.
- **Внутрисетевые проберы периметра (DMZ Probes):** Находятся в той же сети, что и входные балансировщики. Исключают влияние глобального интернета и служат для выявления деградации самого балансировщика, модулей WAF и SSL-акселераторов.
- **Локальные проберы инфраструктуры (Internal Cluster Probes):** Опрашивают непосредственно worker-ноды и внутренние сокеты веб-серверов по приватным IP-адресам (RFC 1918). Используются для проверки здоровья upstream-кластеров и обнаружения зависших инстансов.

---

### Изоляция синтетического трафика и безопасность

Синтетический мониторинг непрерывно шлет запросы на боевую инфраструктуру, что создает специфические риски:

1. **Загрязнение производственных данных (Data Pollution):** Тестовые заказы, сообщения или записи в БД искажают бизнес-аналитику и забивают хранилища.
   - *Решение:* Использование выделенных синтетических аккаунтов (Canary Tenants) с автоматической очисткой или read-only эндпоинтов, выполняющих все фазы обработки без коммита в основную БД.
2. **Блокировки системами безопасности (WAF / Rate Limiter / Fail2ban):** Высокая частота проверок вызывает срабатывание модулей ограничения частоты (`limit_req` в Nginx, `stick-table` в HAProxy).
   - *Решение:* Добавление статических IP-адресов проберов в белые списки (`geo` модуль) либо передача доверенного криптографического заголовка проверки (например, `X-Synthetic-Secret: <hmac-token>`).
3. **Маркировка трафика для трассировки и логирования:**
   - Передача уникального User-Agent: `User-Agent: Synthetic-Monitor/1.0 (+https://internal.wiki/synthetic)`.
   - Заголовок флага синтетики: `X-Synthetic-Probe: true`.
   - Заголовок корреляции: `X-Correlation-ID: synth-<timestamp>-<random>`.
   - В логах веб-сервера синтетический трафик может отфильтровываться или направляться в отдельный файл через директиву `access_log ... if=$not_synthetic`.

---

## Архитектура инструментов синтетического мониторинга (Self-Hosted)

| Инструмент | Уровень проверок | Модель исполнения | Протоколы | Оптимальное применение |
| :--- | :--- | :--- | :--- | :--- |
| **Prometheus Blackbox Exporter** | L3, L4, L7 (Protocol-level) | Daemon-экспортер (pull по требованию) | HTTP/HTTPS, TCP, ICMP, DNS, gRPC | Базовый uptime, статус-коды, latency фаз, срок SSL |
| **Grafana k6** | L7 (API / Multi-step) | CLI / Worker (cron, daemon, k8s job) | HTTP/1.1, HTTP/2, gRPC, WebSockets | Сложные многошаговые API-цепочки, сценарии авторизации |
| **Playwright / Puppeteer** | L7 (Real Browser DOM/SPA) | Node.js headless workers | Headless Chromium, Firefox, WebKit | Рендеринг SPA, проверка видимости элементов, Core Web Vitals |
| **cURL + Systemd Timers** | L7 (Ad-hoc / Minimalist) | Периодические системные юниты | HTTP/HTTPS, HTTP/2, HTTP/3 | Легковесные проверки на серверах без тяжелого стека |
| **Zabbix Web Scenarios / Browser Items** | L7 (Protocol / WebDriver) | Poller-процессы Zabbix Server/Proxy | HTTP/HTTPS, Selenium WebDriver | Централизованный мониторинг в стеке Zabbix |

---

## Практические сценарии

### Сценарий 1: Проверка L7 и валидация SSL через Prometheus Blackbox Exporter

Blackbox Exporter опрашивает веб-сервер по запросу от Prometheus (`/probe`), имитируя внешний браузер с валидацией SSL, поддержкой HTTP/2 и проверкой содержимого ответа.

#### 1. Конфигурация модуля в `/etc/blackbox_exporter/blackbox.yml`

```yaml
modules:
  webserver_http_status:
    prober: http
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      valid_status_codes: [200, 204]
      method: GET
      headers:
        User-Agent: "Synthetic-Probe/1.0 (Prometheus-Blackbox)"
        Accept: "text/html,application/xhtml+xml,application/json"
        Cache-Control: "no-cache"
        X-Synthetic-Probe: "true"
      no_follow_redirects: false
      fail_if_ssl: false
      fail_if_not_ssl: true
      fail_if_body_not_matches_regexp:
        - "(?i)<html"
        - "(?i)status\":\\s*\"ok"
      tls_config:
        insecure_skip_verify: false
        min_version: "TLS12"
      preferred_ip_protocol: "ip4"
```

#### 2. Ручной опрос экспортера для верификации

```bash
curl -s "http://127.0.0.1:9115/probe?target=https://web.internal.example.com/healthz&module=webserver_http_status" | grep -E "^probe_(success|http_status_code|duration_seconds|ssl_earliest_cert_expiry)"
# → probe_duration_seconds 0.048215321
# → probe_http_status_code 200
# → probe_ssl_earliest_cert_expiry 1.782419e+09
# → probe_success 1
```

#### 3. Конфигурация скрейпинга в `prometheus.yml`

```yaml
scrape_configs:
  - job_name: 'synthetic_webservers'
    metrics_path: /probe
    params:
      module: [webserver_http_status]
    static_configs:
      - targets:
          - https://web.internal.example.com/healthz
          - https://api.internal.example.com/v1/ping
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115  # Адрес Blackbox Exporter
```

#### 4. Правило алертинга при сбое проверки или скором истечении SSL (`web_alerts.yml`)

```yaml
groups:
  - name: synthetic_web_rules
    rules:
      - alert: WebServerSyntheticProbeFailed
        expr: probe_success{job="synthetic_webservers"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Веб-сервер {{ $labels.instance }} недоступен по результатам синтетического опроса"
          description: "Blackbox probe завершился сбоем. Код ответа: {{ $value }}, время: {{ query \"probe_duration_seconds{instance='$labels.instance'}\" }}с."

      - alert: WebServerSSLCertExpiringSoon
        expr: (probe_ssl_earliest_cert_expiry{job="synthetic_webservers"} - time()) / 86400 < 14
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "SSL-сертификат для {{ $labels.instance }} истекает менее чем через 14 дней"
          description: "До окончания срока действия сертификата осталось {{ $value | humanizeDuration }}."
```

---

### Сценарий 2: Многошаговый синтетический сценарий на Grafana k6

Сценарий имитирует сессию пользователя: вход на главную страницу, авторизацию по API с получением session cookie, запрос защищенного профиля и валидацию задержек по квантилям (p95 < 400ms).

#### 1. Файл сценария `/opt/synthetic/k6_user_journey.js`

```javascript
import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const failureRate = new Rate('synthetic_check_failures');
const loginDuration = new Trend('synthetic_login_duration_ms');

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    'synthetic_check_failures': ['rate<0.01'], // Допустимо менее 1% ошибок
    'http_req_duration': ['p(95)<400'],        // 95% запросов должны укладываться в 400ms
  },
};

export default function () {
  const baseUrl = 'https://web.internal.example.com';
  const customHeaders = {
    'User-Agent': 'Synthetic-k6-Worker/1.0',
    'X-Synthetic-Probe': 'true',
  };

  group('01_Homepage_Access', function () {
    const res = http.get(`${baseUrl}/`, { headers: customHeaders, timeout: '5s' });
    const ok = check(res, {
      'home status 200': (r) => r.status === 200,
      'home contains title': (r) => r.body.includes('Enterprise Portal'),
    });
    if (!ok) failureRate.add(1);
  });

  sleep(1);

  let sessionCookie = '';
  group('02_Authentication', function () {
    const loginPayload = JSON.stringify({
      username: 'synthetic_probe_user',
      password: __ENV.SYNTHETIC_USER_PASSWORD || 'SecretProbePass123',
    });

    const loginRes = http.post(`${baseUrl}/api/v1/auth/login`, loginPayload, {
      headers: Object.assign({}, customHeaders, { 'Content-Type': 'application/json' }),
      timeout: '5s',
    });

    loginDuration.add(loginRes.timings.duration);

    const loginOk = check(loginRes, {
      'login status 200': (r) => r.status === 200,
      'token present': (r) => r.json('token') !== undefined,
    });

    if (!loginOk) {
      failureRate.add(1);
      return;
    }

    sessionCookie = loginRes.cookies['session_id'] ? loginRes.cookies['session_id'][0].value : '';
  });

  group('03_Authorized_Dashboard_Fetch', function () {
    const dashRes = http.get(`${baseUrl}/api/v1/user/profile`, {
      headers: Object.assign({}, customHeaders, {
        'Cookie': `session_id=${sessionCookie}`,
      }),
      timeout: '5s',
    });

    const dashOk = check(dashRes, {
      'profile status 200': (r) => r.status === 200,
      'correct user id': (r) => r.json('role') === 'canary_monitor',
    });
    if (!dashOk) failureRate.add(1);
  });
}
```

#### 2. Запуск проверки и валидация результата

```bash
SYNTHETIC_USER_PASSWORD="VaultSecretPassword" k6 run /opt/synthetic/k6_user_journey.js
# → execution: local
# →      ✓ home status 200
# →      ✓ home contains title
# →      ✓ login status 200
# →      ✓ token present
# →      ✓ profile status 200
# →      ✓ correct user id
# →
# →      checks.........................: 100.00% ✓ 6         ✗ 0
# →      http_req_duration..............: avg=64.12ms min=14.2ms med=51.1ms max=127.06ms p(95)=119.8ms
# →      synthetic_check_failures.......: 0.00%   ✓ 0         ✗ 1
```

---

### Сценарий 3: Real Browser мониторинг на базе Playwright (Self-Hosted Linux)

Для современных веб-приложений (React, Vue, Angular) HTTP-запрос возвращает пустой шаблон `<div id="root"></div>`. Синтетический агент на базе Chromium запускается локально на сервере мониторинга без графической подсистемы (Headless).

#### 1. Установка окружения на Ubuntu/Debian

```bash
apt-get update && apt-get install -y nodejs npm
mkdir -p /opt/playwright-synthetic && cd /opt/playwright-synthetic
npm init -y
npm install @playwright/test@1.50.0
npx playwright install --with-deps chromium
```

#### 2. Тестовый скрипт `/opt/playwright-synthetic/tests/spa_monitor.spec.ts`

```typescript
import { test, expect } from '@playwright/test';

test.use({
  userAgent: 'Synthetic-Playwright-Probe/1.0',
  extraHTTPHeaders: { 'X-Synthetic-Probe': 'true' },
  ignoreHTTPSErrors: false,
});

test('SPA Web Application Critical Path', async ({ page }) => {
  const targetUrl = 'https://web.internal.example.com/';
  const t0 = Date.now();

  // Переход на страницу с ожиданием сетевого затишья
  const response = await page.goto(targetUrl, {
    waitUntil: 'networkidle',
    timeout: 10000,
  });

  expect(response?.status()).toBe(200);

  // Валидация отображения клиентских динамических компонентов
  const mainHeader = page.locator('h1.dashboard-title');
  await expect(mainHeader).toBeVisible({ timeout: 5000 });
  await expect(mainHeader).toHaveText(/Система управления/);

  // Проверка отсутствия ошибок в консоли браузера
  const domRenderTimeMs = Date.now() - t0;
  expect(domRenderTimeMs).toBeLessThan(3500); // Порог полной отрисовки 3.5 секунды
});
```

#### 3. Запуск теста в изолированном headless режиме

> [!IMPORTANT]
> При запуске Chromium в контейнере или на сервере без GUI критично выделить достаточный объем разделяемой памяти `/dev/shm` (минимум 1-2 ГБ), иначе worker аварийно завершится с ошибкой `Target closed / Crash`.

```bash
cd /opt/playwright-synthetic
npx playwright test --project=chromium --reporter=line
# → 1 passed (2.3s)
```

---

### Сценарий 4: Легковесный синтетический пробер на cURL и Systemd Timers

Минималистичный агент без сторонних зависимостей, разворачиваемый на любом Linux-сервере для сбора детального тайминга HTTP-фаз веб-сервера.

#### 1. Шаблон форматирования метрик `/etc/synthetic/curl-format.txt`

```text
time_namelookup:    %{time_namelookup}s\n
time_connect:       %{time_connect}s\n
time_appconnect:    %{time_appconnect}s\n
time_pretransfer:   %{time_pretransfer}s\n
time_redirect:      %{time_redirect}s\n
time_starttransfer: %{time_starttransfer}s (TTFB)\n
time_total:         %{time_total}s\n
http_code:          %{http_code}\n
ssl_verify_result:  %{ssl_verify_result}\n
speed_download:     %{speed_download} bytes/s\n
```

#### 2. Скрипт проверки `/usr/local/bin/synthetic_curl_probe.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET_URL="${1:-https://web.internal.example.com/healthz}"
LOG_FACILITY="local0.info"

OUTPUT=$(curl -sS -o /dev/null \
  -w "@/etc/synthetic/curl-format.txt" \
  --header "User-Agent: Synthetic-Bash-Probe/1.0" \
  --header "Cache-Control: no-cache" \
  --max-time 10 \
  "$TARGET_URL")

HTTP_CODE=$(echo "$OUTPUT" | awk '/http_code:/ {print $2}')
TOTAL_TIME=$(echo "$OUTPUT" | awk '/time_total:/ {print $2}' | tr -d 's')

logger -p "$LOG_FACILITY" -t "synthetic_probe" "Target=$TARGET_URL status=$HTTP_CODE total_time=${TOTAL_TIME}s"

if [ "$HTTP_CODE" -ne 200 ]; then
  logger -p "local0.err" -t "synthetic_probe" "CRITICAL: Synthetic check failed for $TARGET_URL with HTTP $HTTP_CODE"
  exit 1
fi

echo "$OUTPUT"
```

Сделать скрипт исполняемым:
```bash
chmod 755 /usr/local/bin/synthetic_curl_probe.sh
```

#### 3. Тестовый запуск

```bash
/usr/local/bin/synthetic_curl_probe.sh https://web.internal.example.com/healthz
# → time_namelookup:    0.001423s
# → time_connect:       0.005118s
# → time_appconnect:    0.021430s
# → time_pretransfer:   0.021512s
# → time_redirect:      0.000000s
# → time_starttransfer: 0.052109s (TTFB)
# → time_total:         0.052840s
# → http_code:          200
# → ssl_verify_result:  0
# → speed_download:     24576 bytes/s
```

#### 4. Юниты Systemd для периодического выполнения

`/etc/systemd/system/synthetic-web-probe.service`:
```ini
[Unit]
Description=Synthetic Web Server Health Probe
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/synthetic_curl_probe.sh https://web.internal.example.com/healthz
User=nobody
Group=nogroup
```

`/etc/systemd/system/synthetic-web-probe.timer`:
```ini
[Unit]
Description=Run Synthetic Web Probe every 60 seconds

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
AccuracySec=1s

[Install]
WantedBy=timers.target
```

Активация таймера:
```bash
systemctl daemon-reload
systemctl enable --now synthetic-web-probe.timer
systemctl list-timers synthetic-web-probe.timer
# → NEXT                        LEFT        LAST PASSED UNIT                      ACTIVATES
# → Thu 2026-10-15 09:30:00 MSK 24s left    n/a  n/a    synthetic-web-probe.timer synthetic-web-probe.service
```

---

### Сценарий 5: Мониторинг срока действия SSL/TLS сертификатов и цепочки доверия

Синтетическая проверка валидности сертификата на уровне OpenSSL без участия HTTP-клиента.

#### 1. Проверка даты истечения и расчет оставшихся дней

```bash
TARGET_HOST="web.internal.example.com"
PORT=443

END_DATE=$(echo | openssl s_client -connect "${TARGET_HOST}:${PORT}" -servername "${TARGET_HOST}" 2>/dev/null | openssl x509 -noout -enddate | cut -d= -f2)
EXPIRE_EPOCH=$(date -d "${END_DATE}" +%s)
NOW_EPOCH=$(date +%s)
DAYS_REMAINING=$(( (EXPIRE_EPOCH - NOW_EPOCH) / 86400 ))

echo "Сертификат для ${TARGET_HOST} истекает через ${DAYS_REMAINING} дн. (Дата: ${END_DATE})"
# → Сертификат для web.internal.example.com истекает через 58 дн. (Дата: Dec 12 12:00:00 2026 GMT)
```

#### 2. Проверка валидности цепочки CA и кода верификации

```bash
echo | openssl s_client -connect web.internal.example.com:443 -servername web.internal.example.com -CApath /etc/ssl/certs 2>/dev/null | grep -E "Verify return code"
# →     Verify return code: 0 (ok)
```

---

## Диагностика и устранение неисправностей (Troubleshooting)

### 1. Флиппинг алертов (Flapping) из-за сетевого джиттера

- **Симптом:** Каждые 10-15 минут приходят кратковременные алерты "Probe Failed", которые автоматически резолвятся через 1 минуту. В логах пробера фиксируются единичные `connection reset by peer` или `i/o timeout`.
- **Причина:** Временные микро-потери пакетов на промежуточных сетевых узлах или кратковременный всплеск нагрузки на веб-сервер.
- **Решение:**
  1. Ввести гистерезис в правила Alertmanager: использовать `for: 3m` или требовать не менее 3 последовательных неудачных проверок (`sum_over_time(probe_success[3m]) == 0`).
  2. Внедрить проверку из нескольких локаций: генерировать Critical алерт только в том случае, если probe упал одновременно минимум с двух независимых проберов:
     ```yaml
     expr: count by (target) (probe_success == 0) >= 2
     ```

---

### 2. Ложные сбои из-за блокировки WAF или Rate Limiter

- **Симптом:** Пробер получает HTTP 403 Forbidden или HTTP 429 Too Many Requests, в то время как пользователи открывают сайт без проблем.
- **Причина:** Модуль защиты веб-сервера (`ngx_http_limit_req_module` или HAProxy `stick-table`) расценивает равномерный непрерывный поток запросов от одного IP как атаку.
- **Решение:**
  - В Nginx: настроить исключение для IP-адресов пробера через директиву `geo` и `map`:
    ```nginx
    geo $synthetic_probe {
        default        0;
        192.0.2.50/32  1; # IP Blackbox Exporter
        198.51.100.12  1; # IP k6 Worker
    }

    map $synthetic_probe $limit_key {
        0 $binary_remote_addr;
        1 ""; # Пустой ключ отключает limit_req
    }

    limit_req_zone $limit_key zone=api_limit:10m rate=10r/s;
    ```

---

### 3. Маскировка сбоев бэкенда кэширующими прокси (Nginx Cache / Varnish)

- **Симптом:** Бэкенд-приложение (PHP/Java/Node) полностью упало, но синтетический мониторинг сообщает `probe_success 1`, так как Nginx отдает закэшированный `200 OK`.
- **Причина:** Пробер запрашивает статический URL или страницу, попадающую под действие директивы `proxy_cache_valid 200 10m`.
- **Решение:**
  1. Добавить заголовок обхода кэша в конфигурацию пробера: `Cache-Control: no-cache`.
  2. В Nginx настроить директиву `proxy_cache_bypass`:
     ```nginx
     proxy_cache_bypass $http_x_synthetic_probe;
     ```
  3. Для проверок использовать специализированный эндпоинт (`/healthz` или `/api/v1/ping`), который обращается к базе данных и кэшу без промежуточного сохранения в Nginx cache.

---

### 4. Аварийное падение Headless-браузеров из-за исчерпания `/dev/shm`

- **Симптом:** Скрипты Playwright/Puppeteer завершаются с ошибкой `Target page, context or browser has been closed` или `Crash: SIGBUS`.
- **Причина:** Chromium интенсивно использует разделяемую память (`/dev/shm`) для рендеринга и композитинга страниц. В Docker по умолчанию размер `/dev/shm` составляет 64 МБ, что приводит к краху при параллельных тестах.
- **Решение:**
  - В Docker / Podman: запускать контейнеры с флагом `--shm-size=2gb` или монтировать `tmpfs`:
    ```bash
    podman run -d --name playwright-probe --shm-size=2g -v /opt/tests:/tests playwright-image
    ```
  - В опциях запуска браузера передавать флаг `--disable-dev-shm-usage`:
    ```typescript
    const browser = await chromium.launch({
      args: ['--disable-dev-shm-usage', '--no-sandbox']
    });
    ```

---

### 5. Сбои из-за Hairpinning NAT при внутренних проверках

- **Симптом:** Пробер, расположенный во внутренней сети компании, не может достучаться до `https://web.company.com/` по публичному IP (ошибка `Connection refused` или таймаут), хотя из внешней сети сайт открывается.
- **Причина:** Маршрутизатор не поддерживает NAT Loopback (Hairpinning) для пакетов, исходящих из локальной сети к внешнему белому адресу той же сети.
- **Решение:**
  - Настроить Split-DNS (внутренний DNS-сервер возвращает локальный IP `192.168.10.15` для имени `web.company.com`).
  - Либо явно переопределить адрес разрешения в пробере (в curl: `--resolve web.company.com:443:192.168.10.15`).

---

## Справочник метрик и параметров синтетики

### Фазы задержки и целевые пороги для веб-серверов

| Фаза транзакции | Название метрики (cURL / Blackbox) | Нормальный диапазон (LAN / WAN) | Причина превышения порога |
| :--- | :--- | :--- | :--- |
| **DNS Resolution** | `time_namelookup` / `probe_dns_lookup_time_seconds` | < 5ms (LAN) / < 30ms (WAN) | Перегрузка DNS-серверов, промахи мимо кэша `nscd`/`systemd-resolved` |
| **TCP Connect** | `time_connect` / `probe_duration_seconds{phase="connect"}` | < 2ms (LAN) / < 40ms (WAN) | Сетевые заторы, SYN flood, переполнение очереди `listen backlog` |
| **TLS Handshake** | `time_appconnect` / `probe_duration_seconds{phase="tls"}` | < 10ms (LAN) / < 80ms (WAN) | Высокая загрузка CPU worker-процессов, отсутствие TLS 1.3 / Session Tickets |
| **TTFB (Latency)** | `time_starttransfer` / `probe_duration_seconds{phase="processing"}`| < 50ms (Static) / < 250ms (Dynamic) | Медленные запросы к СУБД, блокировки в PHP-FPM / upstream серверах |
| **Transfer** | `time_total` - `time_starttransfer` | Зависит от размера страницы | Не включен gzip/brotli сжатие, узкий сетевой интерфейс |

---

## Лучшие практики (Best Practices)

1. **Разделение уровней синтетики (Defense in Depth):**
   - **Уровень 1 (L4/L7 Ping):** Blackbox Exporter каждые 15-30 секунд (проверка живости сокета и HTTP 200).
   - **Уровень 2 (L7 API Flow):** k6 сценарий каждые 2-5 минут (проверка бизнес-логики, авторизации и целостности ответов).
   - **Уровень 3 (Headless Browser):** Playwright каждые 10-15 минут (контроль рендеринга клиентского JS и верстки).
2. **Проверки из нескольких географических зон:** Развертывайте как минимум два независимых инстанса Blackbox Exporter на разных сетевых площадках, чтобы исключить ложные тревоги при локальных сбоях провайдера мониторинга.
3. **Строгая валидация содержимого (Assertions):** Никогда не ограничивайтесь только проверкой статус-кода `200 OK`. Веб-сервер или балансировщик может отдать кастомную страницу ошибки или заглушку "Maintenance" с кодом 200. Обязательно проверяйте наличие ключевых маркеров в теле (`fail_if_body_not_matches_regexp`).
4. **Защита синтетических учетных записей:** Пароли и API-ключи для синтетических проборов передаются исключительно через переменные окружения, HashiCorp Vault или защищенные файлы конфигурации с правами `0600`. Назначьте синтетическим учетным записям минимальные права (Read-Only).
5. **Предотвращение кэширования ответов:** Всегда передавайте заголовки `Cache-Control: no-cache, no-store` и `Pragma: no-cache` либо добавляйте случайный query-параметр (`?_t=${timestamp}`) к URL, если требуется проверить реальную доступность upstream-бэкенда.
6. **Корреляция с трассировкой (OpenTelemetry / Jaeger):** Проставляйте заголовки `traceparent` или `X-Request-ID` в синтетические запросы. Это позволит инженерам моментально открыть трейс неудачной синтетической транзакции в APM/Jaeger и увидеть точный спан сбоя.
7. **Алертинг на деградацию производительности (SLI/SLO):** Настройте предупреждающие алерты не только на полный отказ (`probe_success == 0`), но и на рост задержки: например, `probe_duration_seconds > 0.8` в течение 10 минут, чтобы предотвратить инцидент до наступления полного отказа.

---

## Дополнительная информация

### Внутренние ссылки базы знаний

- **[Blackbox Exporter: установка и настройка](../../Prometheus/Exporters/blackbox/blackbox_exporter_installation_and_setup.md)** — развертывание binary, docker и systemd сервиса.
- **[Blackbox Exporter: конфигурация модулей](../../Prometheus/Exporters/blackbox/blackbox_exporter_modules_configuration.md)** — детальный синтаксис `http`, `tcp`, `dns` и `icmp` модулей.
- **[Blackbox Exporter: метрики и алертинг](../../Prometheus/Exporters/blackbox/blackbox_exporter_metrics_and_alerting.md)** — формулы Prometheus для расчета SLI/SLO доступности.
- **[Мониторинг веб-сайтов в Zabbix](../../Zabbix/zabbix_website_monitoring.md)** — настройка Web Scenarios и Browser Items через Selenium.
- **[Методологии мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** — концепции USE, RED, Four Golden Signals и различие Synthetic vs RUM.
- **[Мета-мониторинг](../../Concepts/Observability_and_Monitoring/meta-monitoring.md)** — обеспечение отказоустойчивости самих систем мониторинга и Dead Man's Switch.
- **[Наблюдаемость HTTP-сервисов](../../Networking/Protocols/HTTP/http_monitoring_observability.md)** — метрики протокола HTTP и организация распределенной трассировки.
- **[HAProxy мониторинг](./haproxy_monitoring.md)** — мониторинг входных балансировщиков и проверка бэкендов по health checks.
- **[Runbooks и реагирование на инциденты](./runbooks_incident_response.md)** — типовые алгоритмы устранения аварий при срабатывании алертов.
