**Актуально для:** Grafana k6 v2.3.0

# Нагрузочное тестирование с помощью k6

## Определения

**k6** — современный инструмент нагрузочного тестирования (load testing) с открытым исходным кодом от Grafana Labs, построенный по принципу **Performance-as-Code**. Позволяет писать сложные сценарии тестирования с использованием JavaScript (или TypeScript в версии 2.2.0+), запускать их из командной строки, интегрировать в CI/CD-пайплайны и эмулировать работу виртуальных пользователей (VU — Virtual Users).

**Performance-as-Code** — декларативное описание нагрузочных сценариев в коде, версионируемое в Git и запускаемое автоматически. Позволяет выявлять деградацию производительности на ранних этапах разработки.

**Виртуальный пользователь (VU — Virtual User)** — изолированный исполнитель, который независимо от других VU выполняет экспортированную функцию сценария. Количество одновременно работающих VU определяет конкуренцию за ресурсы целевой системы.

**Coordinated Omission (координированный пропуск)** — методологическая ошибка, возникающая в Closed Loop-моделях: при росте задержки нагрузочный генератор «сбрасывает» планируемые запросы вместо того чтобы отправлять их с фиксированной частотой, что искусственно занижает перцентили. Исключается через Open Loop-исполнители (`constant-arrival-rate`, `ramping-arrival-rate`).

**Open Loop (открытый цикл)** — модель, при которой запросы генерируются с заданной частотой независимо от времени ответа сервера. Отражает поведение реальных пользователей и даёт точные перцентили.

**Closed Loop (закрытый цикл)** — модель, при которой новые запросы появляются только после завершения предыдущих. Не отражает реальность современного веба и склонна к Coordinated Omission.

**Quality Gate (ворота качества)** — автоматическая проверка пороговых значений метрик в CI/CD-пайплайне. В k6 реализуется через объект `thresholds`: если порог нарушен, процесс завершается с ненулевым кодом.

**Execution Context Variables** — встроенные переменные (`__ITER`, `__VU`, `__ENV`, `__EXEC`, `__SCENARIO`), доступные внутри сценария для параметрицизации и идентификации итераций.

**Хаос-тестирование (Chaos Testing)** — метод проверки устойчивости программных систем путем внесения непредвиденных сбоев или сбоев в инфраструктуру. Цель — выявить слабые места и повысить устойчивость приложения. k6 может использоваться не только для нагрузочного тестирования, но и как часть стратегии хаос-инженерии: во время инъекции сбоев k6 генерирует реалистичную нагрузку, что позволяет проверить, как система справляется с сбоями под реальной нагрузкой. Подробнее о хаос-инженерии: [Обзор Chaos Engineering](../Chaos_Engineering/chaos_engineering_overview.md).

## Основные концепции

### Архитектура и способы запуска

k6 — это CLI-инструмент, который:

- **Запускается из командной строки:** `k6 run script.js`.
- **Интегрируется в CI/CD:** GitHub Actions, GitLab CI, Jenkins, а также запускается в Docker-контейнере `grafana/k6`.
- **Эмулирует виртуальных пользователей (VU):** каждый VU исполняет сценарий независимо, что позволяет масштабировать нагрузку до тысяч и десятков тысяч одновременных пользователей.
- **Поддерживает протоколы:** HTTP/1.1, HTTP/2, HTTP/3 (через расширение xk6-http3), gRPC (модуль `k6/net/grpc`), WebSocket (модуль `k6/websockets` — новый API, либо устаревший `k6/ws`).

Внутренне k6 написан на Go, а VU-ы исполняются в изолированных JavaScript-контекстах (runtime Goja). Это обеспечивает предсказуемость и высокую производительность: один экземпляр k6 может генерировать нагрузку от нескольких десятков до сотен тысяч VUs на современном сервере.

### Режимы исполнения (Execution Modes)

k6 поддерживает три режима запуска:

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **Local** | Тест выполняется на одном хосте/контейнере. | Локальная разработка, smoke-тесты, CI/CD. |
| **Distributed** | Тест распределяется по нескольким хостам. Настраивается через `--execution-segment` (ручной) или k6 Operator (Kubernetes). | Высокая нагрузка, географическое распределение. |
| **Cloud** | Тест выполняется на инфраструктуре Grafana Cloud k6. | Не применяется для on-prem / self-hosted. |

Для on-prem распределённого запуска в Kubernetes используйте **k6 Operator** (`github.com/grafana/k6-operator`) — создаёт init/worker Deployment-ы, синхронизирует старт (через `STARTPHASE` init-контейнер), собирает результаты с мастера. Детали: [Методология тестирования производительности](./performance_testing_methodology.md#распределённая-генерация-нагрузки-distributed-load-testing).

### Параметры конфигурации

Конфигурация теста описывается в экспортируемом объекте `options`. Основные параметры:

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `stages` | Поэтапное наращивание нагрузки (ramp-up, steady state, ramp-down). | `{ duration: "10s", target: 1000 }` |
| `thresholds` | Пороговые значения метрик для Quality Gates. | `http_req_duration: ["p(99) < 3000"]` |
| `insecureSkipTLSVerify` | Отключение проверки TLS-сертификата. | `true` |
| `scenarios` | Расширенная конфигурация исполнителей (constant-arrival-rate, etc.). | `executor: 'constant-arrival-rate'` |
| `discardResponseBodies` | Отказ от чтения тела ответа (экономит память и GC). | `true` |
| `tags` | Теги, применяемые ко всем метрикам теста. | `{ test_run_id: 'abc123' }` |

> **Примечание:** в k6 v2.x параметр `vus` и `duration` являются сокращениями для одиночного сценария с исполнителем `constant-vus`. Для production-тестов рекомендуется использовать `scenarios` с `constant-arrival-rate` или `ramping-arrival-rate`.

Подробнее о типах порогов и моделях нагрузки: [Методология тестирования производительности](./performance_testing_methodology.md).

### Исполнители (executors)

Исполнители определяют, как k6 генерирует нагрузку. Выбор исполнителя зависит от модели нагрузки (Open Loop vs Closed Loop) и цели теста. Начиная с v2.0.0 удалены устаревшие исполнители `externally-controlled` и `per-vu-rate`.

| Executor | Тип | Назначение |
| :--- | :--- | :--- |
| `constant-vus` | Closed Loop | Фиксированное количество VUs, каждый выполняет итерации до завершения `duration`. Простой, но методологически не строгий из-за Coordinated Omission. |
| `ramping-vus` | Closed Loop | Плавное изменение количества VUs по этапам (`stages`). Подходит для stress/spike-тестов с нарастанием нагрузки. |
| `shared-iterations` | Closed Loop | Фиксированное количество итераций, распределяемых между VUs. Подходит для functional/smoke-тестов. |
| `constant-arrival-rate` | Open Loop | Фиксированная скорость поступления запросов (RPS). Исключает Coordinated Omission. Используется для точного контроля SLA. |
| `ramping-arrival-rate` | Open Loop | Изменяющаяся скорость поступления запросов (линейно или по этапам). Подходит для тестов с плавным нарастанием/спадом RPS. |
| `per-vu-iterations` | Closed Loop | Каждый VU выполняет заданное количество итераций. Удобно для тестов с фиксированным объемом работы. |

Для большинства production-тестов в 2026 году рекомендуется использовать Open Loop-модель (`constant-arrival-rate` или `ramping-arrival-rate`), так как она исключяет методологическую ошибку Coordinated Omission и точнее отражает реальный пользовательский трафик.

### Этапы нагрузки (stages)

`stages` — массив объектов `{ duration, target }`, который позволяет плавно изменять количество виртуальных пользователей:

- **Ramp-up:** постепенное увеличение VUs с 0 до `target`. Позволяет избежать резкого скачка нагрузки, которая может искусственно исказить результаты.
- **Steady State:** удержание нагрузки на уровне `target` на заданную длительность. Именно на этом этапе система должна стабильно работать в соответствии с SLA.
- **Ramp-down:** постепенное снижение VUs до 0. Позволяет корректно завершить активные запросы и собрать финальные метрики.

Этот подход имитирует реальное поведение пользователей лучше, чем резкое включение/выключение нагрузки.

### Проверки порогов (thresholds и checks)

- **thresholds** — правила, определяющие прохождение теста. Вычисляются на основе метрик k6 (например, `http_req_duration`, `http_req_failed`). Если порог не выполнен, k6 завершает работу с кодом `99` (threshold abort). Примеры типовых порогов:
  - `p(99) < 3000` — 99% запросов завершаются за менее 3000 мс.
  - `rate < 0.01` — доля ошибок менее 1%.
- **checks** — функции, проверяющие условия на каждый запрос (например, статус ответа 200). Используются для верификации бизнес-логики и корректности ответов, но не влияют на статус завершения теста напрямую (это делают thresholds).

### Пользовательские метрики

k6 позволяет регистрировать собственные метрики для более точного контроля бизнес-показателей:

```javascript
import { Rate, Trend, Counter, Gauge } from 'k6/metrics';

const errorRate = new Rate('errors');
const latencyP95 = new Trend('latency_p95');
const successCount = new Counter('success_count');
const activeUsers = new Gauge('active_users');

export default function () {
  const res = http.get('https://api.example.com/health');
  errorRate.add(res.status !== 200);
  latencyP95.add(res.timings.duration);
  if (res.status === 200) successCount.add(1);
  activeUsers.add(1);
}
```

| Тип | Описание | Пример использования |
| :--- | :--- | :--- |
| `Rate` | Доля событий (0..1). | Доля неуспешных запросов. |
| `Trend` | Статистическое распределение (min, max, avg, p95, p99). | Задержка ответа, размер тела. |
| `Counter` | Монотонно возрастающее значение. | Общее количество успешных запросов. |
| `Gauge` | Текущее значение (может расти и падать). | Количество активных сессий в каждый момент. |

### Переменные окружения

k6 предоставляет объект `__ENV` для доступа к переменным окружения, что позволяет параметризовать скрипты и переиспользовать их в разных окружениях:

```javascript
const url = __ENV.TARGET_URL || 'http://localhost:8080';
```

Переменные окружения передаются через `K6_XXX` или `--env XXX=value`. По умолчанию системные переменные окружения **не передаются** в runtime (для предотвращения утечки секретов); используйте `--include-system-env-vars` при необходимости.

### Выходные форматы (outputs)

k6 поддерживает несколько форматов вывода результатов:

- **Текстовый (stdout):** стандартный вывод в терминал. Достаточен для локального запуска.
- **JSON:** `k6 run --out json=results.json script.js`. Удобен для последующего парсинга и хранения в CI-артефактах.
- **CSV:** `k6 run --out csv=results.csv script.js`. Подходит для импорта в Excel/G Sheets.
- **InfluxDB:** `k6 run --out influxdb=http://influxdb:8086/k6 script.js`. Для долгосрочного хранения и корреляции с метриками инфраструктуры.
- **Prometheus Remote Write:** встроенный output `output-prometheus-remote` (в k6 v2.x не требует сборки xk6). Позволяет передавать метрики k6 напрямую в Prometheus:

```bash
k6 run --out output-prometheus-remote script.js \
  --env K6_PROMETHEUS_REMOTE_URL=http://prometheus:9090/api/v1/write \
  --env K6_PROMETHEUS_RW_LABELS=environment=production,server=srv1
```

- **Web Dashboard:** встроенный output `web-dashboard` для локального просмотра в браузере (`http://localhost:6565`): `k6 run --out web-dashboard script.js`.
- **OpenTelemetry:** встроенный output `otlp` для отправки трейсов и метрик в OTLP-совместимый коллектор: `k6 run --out otlp script.js`.
- **handleSummary():** встроенная функция для кастомного экспорта результатов в любые хранилища (S3, GCS, HTTP endpoint) в конце теста:

```javascript
export function handleSummary(data) {
  return {
    './result.json': JSON.stringify(data),
  };
}
```

### Расширения (xk6)

xk6 — фреймворк для сборки кастомных расширений k6. Позволяет добавлять новые модули, протоколы и выходы. Типичный сценарий:

```bash
# Установка xk6
go install go.k6.io/xk6/cmd/xk6@latest

# Сборка k6 с кастомным расширением
xk6 build --with github.com/grafana/xk6-output-prometheus-remote@latest

# В k6 v2.x многие output встроены и не требуют сборки:
# output-prometheus-remote, web-dashboard, otlp
```

Популярные расширения:
- `xk6-http3` — поддержка HTTP/3 (QUIC).
- `xk6-browser` — поддержка браузерного тестирования (Chromium).
- `xk6-redis` — нагрузка на Redis.

### Метрики

k6 автоматически собирает метрики, включая:

| Метрика | Описание |
| :--- | :--- |
| `http_req_duration` | Полное время выполнения HTTP-запроса (от отправки до получения последнего байта). |
| `http_req_failed` | Доля неуспешных запросов (статус >= 400 или сетевая ошибка). |
| `http_reqs` | Общее количество отправленных HTTP-запросов. |
| `http_req_waiting` | Время до первого байта ответа (TTFB / Time To First Byte). |
| `http_req_sending` | Время отправки тела запроса. |
| `http_req_receiving` | Время получения тела ответа. |
| `iterations` | Количество завершенных итераций сценария. |
| `vus` | Количество активных виртуальных пользователей в каждый момент времени. |
| `vus_max` | Максимальное количество VUs за тест. |
| `checks` | Количество успешных и неуспешных проверок. |
| `iteration_duration` | Полное время одной итерации (включая `sleep`). |

Подробнее о метриках и SLI: [Методология тестирования производительности](./performance_testing_methodology.md).

### Работа с данными

Для параметризации запросов (например, тестирование с разными пользователями/товарами) используйте `SharedArray` и внешние файлы:

```javascript
import { SharedArray } from 'k6/data';
import http from 'k6/http';
import { check } from 'k6';

const users = new SharedArray('users', function () {
  return JSON.parse(open('./users.json'));
});

export default function () {
  const user = users[Math.floor(Math.random() * users.length)];
  const res = http.get(`https://api.example.com/users/${user.id}`);
  check(res, { 'status is 200': (r) => r.status === 200 });
}
```

Файл `users.json` загружается один раз на старте теста и доступен всем VU в Read-Only режиме. Для CSV используйте модуль `k6/x/csv` через xk6 или парсинг внутри скрипта.

### TLS и сертификаты

Безопасность тестирования в production-like средах требует корректной работы с TLS:

- **Самоподписанные сертификаты (staging):** `insecureSkipTLSVerify: true`. Только для небоевых окружений.
- **Кастомные CA:** используйте флаг `--ca-cert` при запуске:
  ```bash
  k6 run --ca-cert /path/to/ca.crt script.js
  ```
- **Автоматическая загрузка недостающих сертификатов (k6 v2.3.0+):** опция `tlsAIAFetch: true` позволяет k6 извлекать недостающие промежуточные сертификаты через расширение AIA (Authority Information Access), сохраняя при этом проверку подлинности сервера:
  ```javascript
  export const options = {
    tlsAIAFetch: true,
  };
  ```
- **mTLS (взаимная аутентификация):** k6 поддерживает клиентские сертификаты через опцию `tlsAuth`:
  ```javascript
  export const options = {
    tlsAuth: [{
      domains: ['api.example.com'],
      cert: open('/path/to/client.crt'),
      key: open('/path/to/client.key'),
    }],
  };
  ```

## Установка и настройка

### Установка из пакетов

#### Debian/Ubuntu

```bash
curl -fsSL https://dl.k6.io/key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/k6-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update
sudo apt-get install k6
```

#### Fedora/CentOS/RHEL

```bash
sudo dnf install https://dl.k6.io/rpm/repo.rpm
sudo dnf install k6
```

#### macOS (Homebrew)

```bash
brew install k6
```

#### Windows

```bash
winget install k6
```

### Установка через Docker

```bash
docker pull grafana/k6:v2.3.0
```

Для браузерных тестов используйте образ с Chromium:

```bash
docker pull grafana/k6:v2.3.0-with-browser
```

### Установка из бинарника

Последние релизы доступны на [странице GitHub Releases](https://github.com/grafana/k6/releases). После загрузки и распаковки поместите бинарник `k6` в `PATH`.

### Системная настройка для k6 runners

Для генерации высокой нагрузки (десятки и сотни тысяч VUs) необходимо настроить систему, иначе k6 станет узким местом. Подробные рекомендации по тюнингу ядра Linux: [Системный тюнинг ядра Linux для бенчмаркинга](../WebServers/webserver_benchmarking.md#системный-тюнинг-ядра-linux-для-бенчмаркинга).

Ключевые параметры для k6-хоста:

```bash
# Увеличение лимита файловых дескрипторов
ulimit -n 1048576

# sysctl для высокой нагрузки (см. webserver_benchmarking.md)
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"
sudo sysctl -w net.ipv4.tcp_tw_reuse=1
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w net.ipv4.tcp_congestion_control=bbr
```

### Запуск k6 как системной службы (systemd)

Для постоянного синтетического мониторинга k6 можно запускать как systemd-сервис:

```ini
# /etc/systemd/system/k6-synthetic.target
[Unit]
Description=k6 Synthetic Monitoring Service
After=network-online.target

[Service]
Type=simple
User=k6
Group=k6
ExecStart=/usr/local/bin/k6 run --out json=/var/log/k6/synthetic.json /opt/scripts/synthetic_check.js
Restart=on-failure
RestartSec=10
LimitNOFILE=1048576
Environment=TARGET_URL=https://api.example.com

[Install]
WantedBy=multi-user.target
```

Активация:

```bash
systemctl daemon-reload
systemctl enable --now k6-synthetic
journalctl -u k6-synthetic -f
```

### Исполнительные переменные для распределённого запуска

Для распределённого запуска k6 по нескольким хостам используйте сегменты исполнения:

```bash
# Хост 1: первая четверть теста
k6 run --execution-segment '0:1/4' --execution-segment-sequence '0,1/4,1/2,1' script.js

# Хост 2: вторая четверть
k6 run --execution-segment '1/4:1/2' --execution-segment-sequence '0,1/4,1/2,1' script.js
```

## Практические сценарии

### Сценарий 1: Тестирование балансировщика нагрузки

При тестировании балансировщика, который еще работает не в боевом режиме, необходимо отправлять запросы на IP-адрес балансера с заголовком `Host`, соответствующим целевому хосту, и игнорировать проверку TLS (например, при использовании самоподписанного сертификата).

В этом примере мы в течение 30 секунд плавно повышаем нагрузку до 1000 виртуальных пользователей, держим 30 секунд и затем за 20 секунд уменьшаем нагрузку до 0.

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  thresholds: {
    http_req_duration: ['p(99) < 3000'],
  },
  stages: [
    { duration: '10s', target: 1000 },
    { duration: '30s', target: 1000 },
    { duration: '20s', target: 0 },
  ],
  insecureSkipTLSVerify: true,
};

export default function () {
  const url = 'https://my.loadbalancer.ip.address';
  const headers = { Host: 'example.com' };

  const res = http.get(url, { headers });
  check(res, { 'status was 200': (r) => r.status == 200 });
  sleep(1);
}
```

**Пояснение параметров:**

- `insecureSkipTLSVerify: true` — отключает проверку TLS-сертификата. Используется, когда балансер работает с самоподписанным сертификатом или когда требуется игнорировать HTTPS для тестовых целей.
- `Host: "example.com"` — переопределяет заголовок Host. Необходимо, когда балансировщик маршрутизирует трафик по заголовку Host, а не по IP-адресу.
- `stages` — плавное повышение нагрузки до 1000 VUs за 10 секунд (ramp-up), удержание на 30 секундах (steady state), затем постепенное снижение до 0 за 20 секунд (ramp-down).
- `thresholds: { http_req_duration: ['p(99) < 3000'] }` — 99% запросов должны завершиться за менее 3000 мс. Если порог нарушен, тест завершится с ошибкой.

Запуск теста:

```bash
k6 run --summary-trend-stats="min,avg,p(95),p(99),max" load-balancer-test.js
```

В результате вы получите детальный отчёт по производительности, включая метрики задержек (p50, p95, p99), количество ошибок и их типы, статистику по виртуальным пользователям и количество успешных/неуспешных проверок.

Для получения полной картины проанализируйте также системные метрики на хосте балансировщика: [Диагностика Tail Latency](../Linux/Diagnostics/Performance/diagnosing_tail_latency.md), [Системный тюнинг Linux](../WebServers/webserver_benchmarking.md#системный-тюнинг-ядра-linux-для-бенчмаркинга).

### Сценарий 2: Использование constant-arrival-rate

Для точного контроля скорости запросов (RPS) используйте исполнитель `constant-arrival-rate` из секции `scenarios`. Это особенно важно для избежания методологической ошибки **Coordinated Omission** (когда инструмент пропускает запросы во время высокой задержки, занижая измеренные перцентили).

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    constant_arrival: {
      executor: 'constant-arrival-rate',
      rate: 100,
      timeUnit: '1s',
      duration: '10m',
      preAllocatedVUs: 50,
      maxVUs: 200,
    },
  },
  thresholds: {
    'http_req_duration{status:200}': ['p(95)<200', 'p(99)<500'],
    'http_req_failed': ['rate<0.01'],
  },
};

export default function () {
  const res = http.get('https://api.example.com/v1/resource');

  check(res, {
    'is status 200': (r) => r.status === 200,
    'body has data': (r) => r.json().data !== undefined,
  });

  sleep(0.5);
}
```

Для веб-серверного бенчмаркинга с k6 см. [Бенчмаркинг веб-серверов](../WebServers/webserver_benchmarking.md).

### Сценарий 3: ramping-arrival-rate (изменяющаяся скорость)

Исполнитель `ramping-arrival-rate` позволяет плавно изменять скорость запросов (RPS) во время теста, имитируя неравномерный пользовательский трафик (например, утренний рост днем и спад ночью).

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    ramp_up_load: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 100,
      stages: [
        { duration: '1m', target: 100 },
        { duration: '3m', target: 100 },
        { duration: '1m', target: 10 },
      ],
    },
  },
  thresholds: {
    'http_req_duration': ['p(95)<300'],
    'http_req_failed': ['rate<0.01'],
  },
};

export default function () {
  const res = http.get('https://api.example.com/products');
  check(res, { 'status is 200': (r) => r.status === 200 });
  sleep(1);
}
```

### Сценарий 4: Запуск в Docker

В продакшен-окружениях и CI/CD k6 обычно запускается в Docker-контейнере `grafana/k6`. Это обеспечивает изоляцию окружения и совместимость между запусками. Используйте pinned image tag вместо `:latest` для воспроизводимых запусков:

```bash
docker run --rm \
  -v $(pwd)/scripts:/scripts \
  -v $(pwd)/results:/results \
  grafana/k6:v2.3.0 run \
  --summary-trend-stats="min,avg,p(95),p(99),max" \
  --out json=/results/k6-results.json \
  /scripts/load-test.js
```

Для локального просмотра результатов в браузере через веб-дашборд:

```bash
docker run --rm -i \
  -v $(pwd)/scripts:/scripts \
  -p 6565:6565 \
  grafana/k6:v2.3.0 run \
  --out web-dashboard \
  /scripts/load-test.js
```

Для CI/CD-пайплайнов (GitLab CI, GitHub Actions) используйте образ `grafana/k6:v2.3.0` как базовый image. Подробнее: [Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md), [Интеграция тестов в CI/CD](./testing_cicd_integration.md#нагрузочное-тестирование-в-ci-k6-и-quality-gates).

### Сценарий 5: Тестирование с k6 Operator (Kubernetes, on-prem)

Для распределённого нагрузочного тестирования в on-prem Kubernetes используйте k6 Operator. Оператор создаёт init-worker Deployment-ы, синхронизирует старт и собирает результаты:

```yaml
apiVersion: k6.io/v1beta2
kind: K6
metadata:
  name: k6-load-test
spec:
  parallelism: 4
  script:
    configMap:
      name: k6-test-script
      file: load-test.js
  runnerPodName: k6-runner
  executor: local
```

Запуск:

```bash
# Создание configmap со скриптом
kubectl create configmap k6-test-script --from-file=load-test.js

# Применение k6 CR
kubectl apply -f k6-test.yaml

# Просмотр логов
kubectl logs -f deployment/k6-load-test-runer
```

Для локального distributed режима (без K8s) используйте `--execution-segment`:

```bash
# 4 хоста, каждый выполняет 25% теста
k6 run --execution-segment '0:1/4' --execution-segment-sequence '0,1/4,1/2,1' script.js
```

### Сценарий 6: Smoke-тест и функциональная проверка (--once)

Флаг `--once` (k6 v2.3.0+) позволяет запустить сценарий один раз с одним VU, сохранив конфигурацию сценария (функцию, env, теги):

```bash
# Запуск одного VU на одну итерацию
k6 run --once --scenario my_scenario script.js

# Smoke-тест перед полной нагрузкой
k6 run -e TARGET_URL='http://staging:8080' --once load-test.js
```

Для многосценарных скриптов используйте `--scenario` для выбора конкретного сценария:

```bash
k6 run --scenario smoke_test script.js
```

### Сценарий 7: WebSocket нагрузочное тестирование

k6 поддерживает WebSocket через модуль `k6/websockets` (рекомендуемый API) или устаревший `k6/ws`. Ниже пример с использованием нового API `k6/websockets`:

```javascript
import { WebSocket } from 'k6/websockets';
import { check } from 'k6';

export const options = {
  scenarios: {
    ws_connections: {
      executor: 'constant-vus',
      vus: 100,
      duration: '2m',
    },
  },
  thresholds: {
    'ws_msgs_sent': ['count>0'],
    'ws_connect_time': ['p(95)<500'],
  },
};

export default function () {
  const url = 'wss://api.example.com/ws';
  const params = { tags: { my_tag: 'websocket' } };

  const res = new WebSocket(url, ['websocket'], params);

  res.addEventListener('open', () => {
    res.send(JSON.stringify({ type: 'ping' }));
  });

  res.addEventListener('message', (e) => {
    const msg = JSON.parse(e.data);
    check(msg, { 'is pong': (m) => m.type === 'pong' });
  });

  res.addEventListener('error', (err) => {
    console.error('WebSocket error:', err);
  });

  setTimeout(() => {
    res.close();
  }, 30000);
}
```

Для использования устаревшего API `k6/ws` (не рекомендуется для новых проектов) синтаксис немного отличается — см. [документацию k6/ws](https://grafana.com/docs/k6/latest/javascript-api/k6-ws/).

### Сценарий 8: gRPC нагрузочное тестирование

k6 поддерживает gRPC через модуль `k6/net/grpc`. Пример вызова gRPC-сервиса:

```javascript
import grpc from 'k6/net/grpc';
import { check, sleep } from 'k6';

const client = new grpc.Client();
client.load(['../proto/service.proto'], 'package.Service');

export const options = {
  scenarios: {
    grpc_calls: {
      executor: 'constant-arrival-rate',
      rate: 50,
      timeUnit: '1s',
      duration: '5m',
      preAllocatedVUs: 20,
      maxVUs: 50,
    },
  },
  thresholds: {
    'grpc_call_duration': ['p(95)<200'],
  },
};

export default function () {
  client.connect('grpc://api.example.com:50051', { plaintext: true });
  const response = client.invoke('package.Service/GetUser', { id: 1 });
  check(response, {
    'status is OK': (r) => r.status === grpc.StatusOK,
    'has user': (r) => r.message && r.message.id === 1,
  });
  client.close();
  sleep(1);
}
```

Для глубокого анализа gRPC-метрик и вложений используйте специализированный инструмент **ghz**. Подробнее: [Бенчмаркинг веб-серверов](../WebServers/webserver_benchmarking.md).

### Сценарий 9: Интеграция в CI/CD с Quality Gates

Для запуска k6 в CI/CD и реализации Quality Gates (автоматических пороговых проверок) см. раздел [Нагрузочное тестирование в CI (k6 и Quality Gates)](./testing_cicd_integration.md#нагрузочное-тестирование-в-ci-k6-и-quality-gates) и [Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md).

Пример минимального скрипта для CI с пороговыми проверками:

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    constant_load: {
      executor: 'constant-arrival-rate',
      rate: 50,
      timeUnit: '1s',
      duration: '5m',
      preAllocatedVUs: 20,
      maxVUs: 50,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
  },
};

export default function () {
  const url = __ENV.TARGET_URL || 'http://localhost:8080';
  const res = http.get(`${url}/api/v1/resource`);
  check(res, { 'status is 200': (r) => r.status === 200 });
  sleep(1);
}
```

## Операции и команды

### CLI-справочник k6

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `k6 run` | Запуск тестового сценария | `k6 run script.js` |
| `k6 archive` | Архивация скрипта с зависимостями | `k6 archive script.js` |
| `k6 inspect` | Просмотр метаданных скрипта | `k6 inspect script.js` |
| `--vus`, `-u` | Количество виртуальных пользователей | `k6 run -u 100 script.js` |
| `--duration`, `-d` | Длительность теста | `k6 run -u 100 -d 5m script.js` |
| `--iterations`, `-i` | Количество итераций | `k6 run -i 1000 script.js` |
| `--out`, `-o` | Выходной формат/адрес | `k6 run -o json=results.json script.js` |
| `--summary-export` | Экспорт сводки в JSON | `k6 run --summary-export=summary.json script.js` |
| `--summary-trend-stats` | Статистика для trend-метрик | `--summary-trend-stats="p(95),p(99),avg"` |
| `--summary-mode` | Режим сводки (`full`, `compact`, `disabled`) | `k6 run --summary-mode=full script.js` |
| `--stage` | Этапы нагрузки (shortcut для stages) | `k6 run --stage "0s:10" --stage "30s:50" script.js` |
| `--tag` | Теги для метрик | `k6 run --tag env=staging --tag commit=abc123 script.js` |
| `--env`, `-e` | Переменные окружения | `k6 run -e TARGET_URL=http://staging:8080 script.js` |
| `--insecure-skip-tls-verify` | Отключить проверку TLS | `k6 run --insecure-skip-tls-verify script.js` |
| `--ca-cert` | Путь к CA-сертификату | `k6 run --ca-cert /path/to/ca.crt script.js` |
| `--address` | Адрес REST API сервера (k6 v2.x выключен по умолчанию) | `k6 run --address localhost:6565 script.js` |
| `--scenario` | Выбор сценария для запуска (k6 v2.3.0+) | `k6 run --scenario smoke_test script.js` |
| `--once` | Запуск одной итерации с одним VU (k6 v2.3.0+) | `k6 run --once script.js` |
| `--log-ns-timestamps` | Наносекундные timestamp в логах | `k6 run --log-ns-timestamps script.js` |
| `--features` | Экспериментальные фичи | `k6 run --features async-metric-context script.js` |
| `--quiet`, `-q` | Отключить вывод прогресса | `k6 run --quiet script.js` |

### Выходные форматы (output)

| Output | Описание | Команда |
| :--- | :--- | :--- |
| `json` | JSON-файл с метриками | `--out json=results.json` |
| `csv` | CSV-файл с метриками | `--out csv=results.csv` |
| `influxdb` | InfluxDB (v1) | `--out influxdb=http://host:8086/db` |
| `output-prometheus-remote` | Prometheus Remote Write (встроенный в k6 v2.x) | `--out output-prometheus-remote` |
| `web-dashboard` | Веб-дашборд в браузере | `--out web-dashboard` |
| `otlp` | OpenTelemetry (gRPC/HTTP) | `--out otlp` |

Для отправки метрик в Prometheus используйте встроенный output и переменные окружения:

```bash
k6 run --out output-prometheus-remote script.js \
  --env K6_PROMETHEUS_REMOTE_URL=http://prometheus:9090/api/v1/write \
  --env K6_PROMETHEUS_RW_LABELS=environment=staging,server=srv1
```

### Извлечение метрик из JSON-отчёта

```bash
# k6: извлечение p95/p99 из JSON-отчёта
P95=$(jq '.metrics.http_req_duration.values["p(95)"]' results.json)
P99=$(jq '.metrics.http_req_duration.values["p(99)"]' results.json)
ERROR_RATE=$(jq '.metrics.http_req_failed.values.rate' results.json)

# Сравнение с baseline
CURRENT=$(jq -r '.metrics.http_req_duration.values["p(95)"]' current.json)
BASELINE=$(jq -r '.metrics.http_req_duration.values["p(95)"]' baseline.json)
if (( $(echo "$CURRENT > $BASELINE * 1.1" | bc -l) )); then
  echo "REGRESSION detected"
  exit 1
fi
```

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `connection refused` / `socket hang up` | Сервис не запущен, неверный URL или firewall | Добавить pre-check: `curl -sf $URL/health` перед запуском k6. |
| p95/p99 сильно скачет между запусками | Нестабильная среда (shared runners, noisy neighbors) | Использовать выделенные раннеры, увеличить duration до 3–5 минут, повторять запуск 3+ раз. |
| `context canceled` | Высокий VU-count на малом контейнере / OOM | Уменьшить VUs, увеличить CPU/Memory контейнера. Проверить `dmesg` на OOM-Kill. |
| Coordinated Omission (заниженный p99) | Использование Closed Loop (`constant-vus`) при высокой latency | Перейти на `constant-arrival-rate` или `ramping-arrival-rate`. |
| `tls: handshake failure` | Несовпадение версий TLS, неверный сертификат | Проверить `openssl s_client -connect host:port`. Использовать `--ca-cert` вместо `insecureSkipTLSVerify`. |
| Метрики не отображаются в Prometheus | Неверный URL или формат переменных окружения | Проверить `K6_PROMETHEUS_REMOTE_URL`, сетевую доступность и теги (`--tag`). |
| High `http_req_waiting` (TTFB) | Бэкенд не справляется, нет кэширования, медленная БД | Анализировать USE-метод (CPU, Disk I/O, Network). Смотреть логи приложения. |
| `Too many open files` | Превышен лимит file descriptors на хосте | Увеличить `ulimit -n` (например, до 1048576) перед запуском. |
| `vus_max` превышен `preAllocatedVUs` | Слишком много одновременных запросов при высоких задержках | Увеличить `preAllocatedVUs` и `maxVUs`. |
| Деградация метрик после простоя кэша | Cold start (page cache, TLS session, JIT) | Добавить warm-up фазу 30–60 секунд перед steady state. |

### Системная диагностика для k6 runners

Перед запуском высокой нагрузки проверьте системные параметры:

```bash
# Проверка лимитов file descriptors
ulimit -n
cat /proc/$$/limits | grep "open files"

# Проверка sysctl
sysctl net.ipv4.ip_local_port_range net.core.somaxconn net.ipv4.tcp_tw_reuse

# Проверка нагрузки на хост k6
sar -u 1 10          # CPU utilization
sar -r 1 10          # Memory usage
sar -n TCP 1 10      # TCP statistics
ss -s                # Socket statistics

# Быстрый smoke-тест перед полной нагрузкой
k6 run -u 1 -d 10s --quiet script.js
```

Подробнее о системной диагностике: [Диагностический алгоритм локализации узкого места](../WebServers/webserver_benchmarking.md#диагностический-алгоритм-локализации-узкого-места).

## Тестирование хаоса с k6

k6 может использоваться в связке с хаос-инженерией. Во время инъекции сбоев (через Chaos Mesh, Litmus, Gremlin или другие инструменты) k6 генерирует реалистичную нагрузку, что позволяет проверить, как система справляется с сбоями под реальной нагрузкой. Это особенно ценно для валидации механизмов защиты (Circuit Breaker, Retry policies, Fallback-логика) и калибровки наблюдаемости.

Пример архитектуры эксперимента:

```
k6 (нагрузка) + Chaos Mesh (инъекция сбоев) → Prometheus/Grafana (наблюдение) → анализ SLO
```

**Пример сценария:** запустите k6 с постепенно нарастающей нагрузкой, одновременно с инъекцией сетевой задержки на сервис базы данных через Chaos Mesh. Наблюдайте за тем, как система применяет паттерны устойчивости (Circuit Breaker) и как растут метрики ошибок и задержек.

Подробнее о хаос-инженерии и инструментах: [Обзор Chaos Engineering](../Chaos_Engineering/chaos_engineering_overview.md), [Инструменты Chaos Engineering](../Chaos_Engineering/chaos_engineering_tools.md).

## Лучшие практики

### Проектирование сценариев

- **Open Loop-модель:** используйте `constant-arrival-rate` или `ramping-arrival-rate` вместо `constant-vus`, чтобы исключить Coordinated Omission.
- **Параметризация:** выносите URL, заголовки, токены в переменные окружения (`__ENV` в k6, `--env` в Locust). Никогда не хардкодьте секреты в скриптах.
- **Реалистичные сценарии:** имитируйте реальные паттерны трафика (распределение эндпоинтов, think-time, ratio reads/writes) на основе access logs.
  - **Warm-up:** всегда включайте прогрев кэшей (30–60 секунд) перед steady state. Метрики cold start нерелевантны для SLA.
- **Cool-down:** дожидайтесь завершения всех активных соединений перед остановкой теста, иначе метрики будут искажены.
- **discardResponseBodies:** для тестов, где тело ответа не нужно для логики скрипта, включайте `discardResponseBodies: true` — это экономит память и уменьшает GC-нагрузку.

### Изоляция и производительность стенда

- **Разделение хостов:** нагрузочный генератор и тестируемый сервис должны быть на физически разных хостах. Запуск k6 на `localhost` искажает результаты из-за конкуренции за CPU и кэш. См. [Принципы корректного тестирования веб-серверов](../WebServers/webserver_benchmarking.md#принципы-корректного-тестирования-веб-серверов).
- **Сетевая изоляция:** используйте `--network host` в Docker для бенчмаркинга; стандартный сетевой мост Docker снижает RPS в 2–4 раза из-за NAT.
- **Тюнинг ядра:** настраивайте `ulimit -n`, `net.ipv4.ip_local_port_range`, `net.core.somaxconn`, `net.ipv4.tcp_congestion_control=bbr` на хосте k6 при высокой нагрузке (см. [Системный тюнинг Linux](../WebServers/webserver_benchmarking.md#системный-тюнинг-ядра-linux-для-бенчмаркинга)).
- **CPU Pinning:** используйте `taskset -c 0-3 k6 run ...` для привязки k6 к конкретным ядрам и изоляции от прерываний.

### CI/CD и Quality Gates

- **Quality Gates:** начинайте с «мягких» порогов (`allow_failure: true` в GitLab), переводя их в блокирующие только после стабилизации окружения и baseline.
- **Triggering:** запускайте нагрузочные тесты на Merge Request и nightly schedule, а не на каждый коммит. Используйте path filters для запуска только при изменениях в relevant-сервисах.
- **Baseline:** храните эталонные результаты в артефактах CI или version-controlled файле. Многократный запуск (минимум 3 прогона) для исключения шума. Используйте относительные пороги (`current < baseline * 1.1`).
- **Изоляция:** используйте dedicated раннеры для нагрузочного тестирования. Shared runners ненадёжны из-за noisy neighbors.

### Безопасность

- **Секреты:** никогда не хардкодьте API-ключи, токены в сценариях. Используйте переменные окружения CI (`$TARGET_URL`, `$API_TOKEN`).
- **Sensitive data:** не логируйте тела запросов/ответов с PII в production-окружениях. Используйте `--quiet` или `console` с фильтрацией.
- **mTLS:** для production-like стены используйте клиентские сертификаты через `tlsAuth` вместо `insecureSkipTLSVerify`.
- **TLS вместо insecureSkipTLSVerify:** предпочитайте `--ca-cert` или `tlsAIAFetch: true` (k6 v2.3.0+) для корректной проверки сертификатов.

### Очистка и архивирование

- После каждого тестового цикла: остановите нагрузку, дождитесь cool-down, заархивируйте артефакты (JSON/CSV отчёты, скриншоты Grafana, логи), освободите ресурсы (завершите фоновые процессы, удалите seeding-данные из БД).
- Используйте `handleSummary()` для кастомного экспорта результатов в хранилище (S3, HTTP endpoint).

## Дополнительная информация

### См. также

- **[Методология тестирования производительности](./performance_testing_methodology.md)** — типы тестов (load, stress, endurance, spike), ключевые метрики (SLI: Latency, Throughput, Error Rate, Saturation), модели нагрузки (Open Loop vs Closed Loop), жизненный цикл тестирования (PTLC), SRE-практики, распределённая генерация нагрузки.
- **[Интеграция тестов в CI/CD](./testing_cicd_integration.md)** — Quality Gates, Regression Detection, Test Impact Analysis (TIA), автоматизация нагрузочных тестов в GitLab CI и GitHub Actions.
- **[Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md)** — k6, Locust, Vegeta, wrk2 в CI/CD: Docker-запуск, база сравнения (baseline), типичные ошибки и диагностика.
- **[Бенчмаркинг веб-серверов](../WebServers/webserver_benchmarking.md)** — системный тюнинг Linux, низкоуровневые утилиты (wrk, ab, h2load), k6 для веб-серверов, выбор инструмента по задаче.
- **[Синтетический мониторинг веб-серверов](../WebServers/Concepts/synthetic_monitoring.md)** — k6 для постоянного синтетического мониторинга, Blackbox Exporter, curl/systemd probes.
- **[Обзор экосистемы Grafana](../Grafana/grafana_overview.md)** — k6 в контексте продуктов Grafana Labs (Alloy, Mimir, Loki, Tempo).
- **[Обзор Chaos Engineering](../Chaos_Engineering/chaos_engineering_overview.md)** — хаос-инженерия, инъекции сбоев, валидация паттернов устойчивости.
- **[Yandex.Tank и Taurus](./yandex_tank_taurus.md)** — альтернативные генераторы, миграция на k6.
- **[Gatling](./gatling_load_testing.md)** — JVM-генератор, сравнение с k6.
- **[JMeter](./jmeter_load_testing.md)** — классический Java-генератор для enterprise/legacy.

### Внешние ресурсы

- [k6 Documentation](https://grafana.com/docs/k6/) — официальная документация Grafana k6 (v2.3.0).
- [k6 на GitHub](https://github.com/grafana/k6) — исходный код, примеры сценариев и расширения.
- [k6 в CI/CD](https://grafana.com/docs/k6/results-output/running-k6-in-ci-cd/) — руководство по интеграции в пайплайны.
- [xk6](https://github.com/grafana/xk6) — фреймворк для сборки кастомных расширений k6.
- [k6 Operator](https://github.com/grafana/k6-operator) — Kubernetes Operator для распределённого запуска k6 (on-prem).
- [k6 WebSockets API](https://grafana.com/docs/k6/latest/javascript-api/k6-websockets/) — документация нового WebSocket API (k6 v2.x).
- [k6 gRPC API](https://grafana.com/docs/k6/latest/javascript-api/k6-net-grpc/) — документация gRPC модуля.
- [k6 Release Notes v2.3.0](https://github.com/grafana/k6/releases/tag/v2.3.0) — новые функции v2.3.0.
