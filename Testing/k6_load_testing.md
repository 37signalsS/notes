# Нагрузочное тестирование с помощью k6

## Определения

**k6** — современный инструмент нагрузочного тестирования (load testing) с открытым исходным кодом от Grafana Labs, построенный по принципу **Performance-as-Code**. Позволяет писать сложные сценарии тестирования с использованием JavaScript (или TypeScript в версии 2.2.0+), запускать их из командной строки, интегрировать в CI/CD-пайплайны и эмулировать работу виртуальных пользователей (VU — Virtual Users).

**Performance-as-Code** — декларативное описание нагрузочных сценариев в коде, версионируемое в Git и запускаемое автоматически. Позволяет выявлять деградацию производительности на ранних этапах разработки.

**Хаос-тестирование (Chaos Testing)** — метод проверки устойчивости программных систем путем внесения непредвиденных сбоев или сбоев в инфраструктуру. Цель — выявить слабые места и повысить устойчивость приложения. k6 может использоваться не только для нагрузочного тестирования, но и как часть стратегии хаос-тестирования: во время инъекции сбоев k6 генерирует реалистичную нагрузку, что позволяет проверить, как система справляется с сбоями под реальной нагрузкой. Подробнее о хаос-инженерии: [Обзор Chaos Engineering](../Chaos_Engineering/chaos_engineering_overview.md).

## Основные концепции

### Архитектура и способы запуска

k6 — это CLI-инструмент, который:

- **Запускается из командной строки:** `k6 run script.js`.
- **Интегрируется в CI/CD:** GitHub Actions, GitLab CI, Jenkins, а также запускается в Docker-контейнере `grafana/k6`.
- **Эмулирует виртуальных пользователей (VU):** каждый VU исполняет сценарий независимо, что позволяет масштабировать нагрузку до тысяч и десятков тысяч одновременных пользователей.
- **Поддерживает протоколы:** HTTP/1.1, HTTP/2, HTTP/3 (через расширение xk6-http3), gRPC (модуль `k6/net/grpc`), WebSocket (модуль `k6/ws`).

Внутренне k6 написан на Go, а VU-ы исполняются в изолированных JavaScript-контекстах (runtime Goja). Это обеспечивает предсказуемость и высокую производительность: один экземпляр k6 может генерировать нагрузку от нескольких десятков до сотен тысяч VUs на современном сервере.

### Параметры конфигурации

Конфигурация теста описывается в экспортируемом объекте `options`. Основные параметры:

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `stages` | Поэтапное наращивание нагрузки (ramp-up, steady state, ramp-down). | `{ duration: "10s", target: 1000 }` |
| `thresholds` | Пороговые значения метрик для Quality Gates. | `http_req_duration: ["p(99) < 3000"]` |
| `insecureSkipTLSVerify` | Отключение проверки TLS-сертификата. | `true` |
| `scenarios` | Расширенная конфигурация исполнителей (constant-arrival-rate, etc.). | `executor: 'constant-arrival-rate'` |

Подробнее о типах порогов и моделях нагрузки: [Методология тестирования производительности](./performance_testing_methodology.md).

### Исполнители (executors)

Исполнители (executors) определяют, как k6 генерирует нагрузку. Выбор исполнителя зависит от модели нагрузки (Open Loop vs Closed Loop) и цели теста.

| Executor | Тип | Назначение |
| :--- | :--- | :--- |
| `constant-vus` | Closed Loop | Фиксированное количество VUs, каждый выполняет итерации до завершения `duration`. Простой, но методологически не строгий из-за Coordinated Omission. |
| `constant-arrival-rate` | Open Loop | Фиксированная скорость поступления запросов (RPS). Исключает Coordinated Omission. Используется для точного контроля SLA. |
| `ramping-arrival-rate` | Open Loop | Изменяющаяся скорость поступления запросов (линейно или по этапам). Подходит для тестов с плавным нарастанием/спадом RPS. |
| `per-vu-iterations` | Closed Loop | Каждый VU выполняет заданное количество итераций. Удобно для тестов с фиксированным объемом работы. |
| `per-vu-rate` | Open Loop | Каждый VU генерирует заданное количество итераций в секунду. Суммарная нагрузка = VUs × rate. |
| `externally-controlled` | Гибрид | Управление количеством VUs из внешнего процесса через API. Используется для координированных экспериментов (например, вместе с Chaos Engineering). |

Для большинства production-тестов в 2026 году рекомендуется использовать Open Loop-модель (`constant-arrival-rate` или `ramping-arrival-rate`), так как она исключает методологическую ошибку Coordinated Omission и точнее отражает реальный пользовательский трафик.

### Этапы нагрузки (stages)

`stages` — массив объектов `{ duration, target }`, который позволяет плавно изменять количество виртуальных пользователей:

- **Ramp-up:** постепенное увеличение VUs с 0 до `target`. Позволяет избежать резкого скачка нагрузки, которая может искусственно исказить результаты.
- **Steady State:** удержание нагрузки на уровне `target` на заданную длительность. Именно на этом этапе система должна стабильно работать в соответствии с SLA.
- **Ramp-down:** постепенное снижение VUs до 0. Позволяет корректно завершить активные запросы и собрать финальные метрики.

Этот подход имитирует реальное поведение пользователей лучше, чем резкое включение/выключение нагрузки.

### Проверки порогов (thresholds и checks)

- **thresholds** — правила, определяющие прохождение теста. Вычисляются на основе метрик k6 (например, `http_req_duration`, `http_req_failed`). Если порог не выполнен, k6 завершает работу с ошибкой. Примеры типовых порогов:
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

### Выходные форматы (outputs)

k6 поддерживает несколько форматов вывода результатов:

- **Текстовый (stdout):** стандартный вывод в терминал. Достаточен для локального запуска.
- **JSON:** `k6 run --out json=results.json script.js`. Удобен для последующего парсинга и хранения в CI-артефактах.
- **CSV:** `k6 run --out csv=results.csv script.js`. Подходит для импорта в Excel/G Sheets.
- **InfluxDB:** `k6 run --out influxdb=http://influxdb:8086/k6 script.js`. Для долгосрочного хранения и корреляции с метриками инфраструктуры.
- **Prometheus Remote Write:** через расширение `xk6-output-prometheus-remote`. Позволяет передавать метрики k6 напрямую в Prometheus без промежуточных агентов.

### Расширения (xk6)

xk6 — фреймворк для сборки кастомных расширений k6. Позволяет добавлять новые модули, протоколы и выходы. Типичный сценарий:

```bash
# Установка xk6
go install go.k6.io/xk6/cmd/xk6@latest

# Сборка расширения с кастомным модулем
xk6 build --with github.com/grafana/xk6-output-prometheus-remote@latest
```

Популярные расширения:
- `xk6-http3` — поддержка HTTP/3 (QUIC).
- `xk6-output-prometheus-remote` — отправка метрик в Prometheus через Remote Write.
- `xk6-browser` — поддержка браузерного тестирования (Chromium).

### Метрики

k6 автоматически собирает метрики, включая:

- `http_req_duration` — время выполнения HTTP-запроса.
- `http_req_failed` — доля неуспешных запросов.
- `iterations` — количество завершенных итераций сценария.
- `vus` — количество активных виртуальных пользователей в каждый момент времени.
- `checks` — количество успешных и неуспешных проверок.
- `http_reqs` — общее количество отправленных HTTP-запросов.
- `http_req_waiting` (TTFB) — время до первого байта ответа (Time To First Byte).

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
- **mTLS (взаимная аутентификация):** k6 поддерживает клиентские сертификаты через модуль `k6/http` и опции запроса:
  ```javascript
  http.get('https://api.example.com', {
    tlsAuth: [{
      cert: open('/path/to/client.crt'),
      key: open('/path/to/client.key'),
    }],
  });
  ```

## Практические сценарии

### Сценарий 1: Тестирование балансировщика нагрузки

При тестировании балансировщика, который еще работает не в боевом режиме, необходимо отправлять запросы на IP-адрес балансера с заголовком `Host`, соответствующим целевому хосту, и игнорировать проверку TLS (например, при использовании самоподписанного сертификата).

В этом примере мы в течение 30 секунд плавно повышаем нагрузку до 1000 виртуальных пользователей, держим 30 секунд и затем за 20 секунд уменьшаем нагрузку до 0.

```javascript
import http from "k6/http";
import { check, sleep } from "k6";

// Конфигурация теста
export const options = {
  thresholds: {
    // 99% запросов должны завершиться за менее 3000 мс
    http_req_duration: ["p(99) < 3000"],
  },
  stages: [
    { duration: "10s", target: 1000 },  // Плавное повышение до 1000 VUs
    { duration: "30s", target: 1000 },  // Удержание на 30 секунд
    { duration: "20s", target: 0 },     // Постепенное снижение до 0
  ],
  // Отключение проверки TLS (для staging / self-signed сертификатов)
  insecureSkipTLSVerify: true,
};

// Имитация поведения пользователя
export default function () {
  const url = "https://my.loadbalancer.ip.address"; // IP-адрес балансировщика

  // Переопределение заголовка Host для маршрутизации через балансировщик
  const headers = {
    Host: "example.com",
  };

  let res = http.get(url, { headers });

  // Проверка статуса ответа
  check(res, { "status was 200": (r) => r.status == 200 });

  sleep(1);
}
```

**Пояснение параметров:**

- `insecureSkipTLSVerify: true` — отключает проверку TLS-сертификата. Используется, когда балансер работает с самоподписанным сертификатом или когда требуется игнорировать HTTPS для тестовых целей.
- `Host: "example.com"` — переопределяет заголовок Host. Это необходимо, когда балансировщик маршрутизирует трафик по заголовку Host, а не по IP-адресу.
- `stages` — плавное повышение нагрузки до 1000 VUs за 10 секунд (ramp-up), удержание на 30 секунд (steady state), затем постепенное снижение до 0 за 20 секунд (ramp-down).
- `thresholds: { http_req_duration: ["p(99) < 3000"] }` — 99% запросов должны завершиться за менее 3000 мс. Если порог нарушен, тест завершится с ошибкой.

Запуск теста:

```bash
k6 run load-balancer-test.js
```

В результате вы получите детальный отчёт по производительности, включая:

- Метрики задержок (p50, p95, p99).
- Количество ошибок и их типы.
- Статистику по виртуальным пользователям (максимум, среднее).
- Количество успешных и неуспешных проверок.

Это довольно базовый сценарий, но сила k6 заключается в возможности наращивать и усложнять логику — добавлять аутентификацию, работу с API, сценарии с данными и т.д., ограниченную только вашей фантазией и требованиями бизнес-процессов.

### Сценарий 2: Использование constant-arrival-rate

Для точного контроля скорости запросов (RPS) используйте исполнитель `constant-arrival-rate` из секции `scenarios`. Это особенно важно для избежания методологической ошибки **Coordinated Omission** (когда инструмент пропускает запросы во время высокой задержки, занижая измеренные перцентили).

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    constant_arrival: {
      executor: 'constant-arrival-rate',
      rate: 100,              // 100 запросов в секунду
      timeUnit: '1s',
      duration: '10m',
      preAllocatedVUs: 50,    // Заранее выделенные виртуальные пользователи
      maxVUs: 200,            // Максимальный предел VUs
    },
  },
  thresholds: {
    'http_req_duration{status:200}': ['p(95)<200', 'p(99)<500'], // SLA по задержке
    'http_req_failed': ['rate<0.01'],                           // Ошибок менее 1%
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
      startRate: 10,        // Начальная скорость: 10 RPS
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 100,
      stages: [
        { duration: '1m', target: 100 },  // Рост до 100 RPS за 1 минуту
        { duration: '3m', target: 100 },  // Удержание 100 RPS
        { duration: '1m', target: 10 },   // Снижение до 10 RPS
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

В продакшен-окружениях и CI/CD k6 обычно запускается в Docker-контейнере `grafana/k6`. Это обеспечивает изоляцию окружения и совместимость между запусками.

```bash
docker run --rm \
  -v $(pwd)/scripts:/scripts \
  -v $(pwd)/results:/results \
  grafana/k6:latest run \
  --out json=/results/k6-results.json \
  /scripts/load-test.js
```

Для CI/CD-пайплайнов (GitLab CI, GitHub Actions) используйте образ `grafana/k6` как базовый image. Подробнее: [Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md).

### Сценарий 5: WebSocket нагрузочное тестирование

k6 поддерживает WebSocket через модуль `k6/ws`. Пример сценария для проверки устойчивости WebSocket-сервера:

```javascript
import ws from 'k6/ws';
import { check, sleep } from 'k6';

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

  const res = ws.connect(url, params, function (socket) {
    socket.on('open', () => {
      socket.send(JSON.stringify({ type: 'ping' }));
    });

    socket.on('message', (data) => {
      const msg = JSON.parse(data);
      check(msg, { 'is pong': (m) => m.type === 'pong' });
    });

    socket.on('error', (err) => {
      console.error('WebSocket error:', err);
    });

    socket.setTimeout(() => {
      socket.close();
    }, 30000);
  });

  check(res, { 'connection established': (r) => r && r.status === 101 });
  sleep(1);
}
```

### Сценарий 6: gRPC нагрузочное тестирование

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

### Сценарий 7: Интеграция в CI/CD с Quality Gates

Для запуска k6 в CI/CD и реализации Quality Gates (автоматических пороговых проверок) см. раздел [Нагрузочное тестирование в CI (k6 и Quality Gates)](./testing_cicd_integration.md#нагрузочное-тестирование-в-ci-k6-и-quality-gates) и [Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md).

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `connection refused` / `socket hang up` | Сервис не запущен, неверный URL или firewall | Добавить pre-check: `curl -sf $URL/health` перед запуском k6. |
| p95/p99 сильно скачет между запусками | Нестабильная среда (shared runners, noisy neighbors) | Использовать выделенные раннеры, увеличить duration до 3–5 минут, повторять запуск 3+ раз. |
| `context canceled` | Высокий VU-count на малом контейнере / OOM | Уменьшить VUs, увеличить CPU/Memory контейнера. Проверить `dmesg` на OOM-Kill. |
| Coordinated Omission (заниженный p99) | Использование Closed Loop (`constant-vus`) при высокой latency | Перейти на `constant-arrival-rate` или `ramping-arrival-rate`. |
| `tls: handshake failure` | Несовпадение версий TLS, неверный сертификат | Проверить `openssl s_client -connect host:port`. Использовать `--ca-cert` вместо `insecureSkipTLSVerify`. |
| Метрики не отображаются в Prometheus | Не настроен xk6-output-prometheus-remote | Проверить URL Prometheus, сетевую доступность и формат меток (`--tag`). |
| High `http_req_waiting` (TTFB) | Бэкенд не справляется, нет кэширования, медленная БД | Анализировать USE-метод (CPU, Disk I/O, Network). Смотреть логи приложения. |
| `Too many open files` | Превышен лимит file descriptors на хосте | Увеличить `ulimit -n` (например, до 65535) перед запуском. |

## Тестирование хаоса с k6

k6 может использоваться в связке с хаос-инженерией. Во время инъекции сбоев (через Chaos Mesh, Litmus, Gremlin или другие инструменты) k6 генерирует реалистичную нагрузку, что позволяет проверить, как система справляется с сбоями под реальной нагрузкой. Это особенно ценно для валидации механизмов защиты (Circuit Breaker, Retry policies, Fallback-логика) и калибровки наблюдаемости.

Пример архитектуры эксперимента:

```
k6 (нагрузка) + Chaos Mesh (инъекция сбоев) → Prometheus/Grafana (наблюдение) → анализ SLO
```

**Пример сценария:** запустите k6 с постепенно нарастающей нагрузкой, одновременно с инъекцией сетевой задержки на сервис базы данных через Chaos Mesh. Наблюдайте за тем, как система применяет паттерны устойчивости (Circuit Breaker) и как растут метрики ошибок и задержек.

Подробнее о хаос-инженерии и инструментах: [Обзор Chaos Engineering](../Chaos_Engineering/chaos_engineering_overview.md), [Инструменты Chaos Engineering](../Chaos_Engineering/chaos_engineering_tools.md).

## Дополнительная информация

### См. также

- **[Методология тестирования производительности](./performance_testing_methodology.md)** — типы тестов (load, stress, endurance, spike), ключевые метрики (SLI: Latency, Throughput, Error Rate, Saturation), модели нагрузки (Open Loop vs Closed Loop), жизненный цикл тестирования (PTLC).
- **[Интеграция тестов в CI/CD](./testing_cicd_integration.md)** — Quality Gates, Regression Detection, Test Impact Analysis (TIA), автоматизация нагрузочных тестов в GitLab CI и GitHub Actions.
- **[Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md)** — k6, Locust, Vegeta, wrk2 в CI/CD: Docker-запуск, база сравнения (baseline), типичные ошибки и диагностика.
- **[Бенчмаркинг веб-серверов](../WebServers/webserver_benchmarking.md)** — низкоуровневые утилиты (wrk, ab, h2load), k6 для веб-серверов, выбор инструмента по задаче.
- **[Обзор экосистемы Grafana](../Grafana/grafana_overview.md)** — k6 в контексте продуктов Grafana Labs (Alloy, Mimir, Loki, Tempo).

### Внешние ресурсы

- [k6 Documentation](https://grafana.com/docs/k6/) — официальная документация Grafana k6.
- [k6 на GitHub](https://github.com/grafana/k6) — исходный код, примеры сценариев и расширения.
- [k6 в CI/CD](https://grafana.com/docs/k6/results-output/running-k6-in-ci-cd/) — руководство по интеграции в пайплайны.
- [xk6](https://github.com/grafana/xk6) — фреймворк для сборки кастомных расширений k6.
