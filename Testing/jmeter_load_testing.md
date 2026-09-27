# Нагрузочное тестирование с помощью Apache JMeter

## Определения

**JMeter** — open-source инструмент нагрузочного тестирования от Apache Software Foundation. Классический «тяжёлый» генератор нагрузки на Java, де-факто стандарт в enterprise и legacy-проектах. Пригоден как для функциональных/API-проверок, так и для load/stress-тестов HTTP и не только (JDBC, JMS, FTP, LDAP). Актуальная стабильная ветка — **5.6.x** (требует Java 8+, рекомендуется Java 17+; следующий мажор 6.0 переходит на Java 17+).

**Test Plan** — корневой XML-документ (`.jmx`), описывающий весь сценарий: потоки, сэмплеры, тайминги, ассерты, слушатели.

**Sampler** — элемент, выполняющий запрос (HTTP Request, JDBC Request, JMS Sampler и т.д.).

**Thread Group** — группа виртуальных пользователей: количество потоков, ramp-up, длительность или число итераций.

**Listener** — сборщик и визуализатор результатов (View Results Tree, Aggregate Report, Summary Report).

**Assertion** — проверка ответа (Response Assertion, Duration Assertion, JSON Assertion, JMESPath).

**Distributed Testing** — запуск одного теста с нескольких агентов (slave) под управлением мастер-узла.

## Основные концепции

### Архитектура и элементная модель

JMeter — Java-приложение, работающее в двух режимах:

- **GUI** — интерактивный конструктор тест-планов. Используется ТОЛЬКО для разработки и отладки. Запускать большие нагрузки через GUI запрещается: GUI потребляет память и искажает результаты.
- **CLI (non-GUI)** — production-режим для CI/CD и больших нагрузок: `jmeter -n -t plan.jmx -l result.jtl`.

Элементы тест-плана группируются так:

| Категория | Примеры | Назначение |
| :--- | :--- | :--- |
| **Config Elements** | HTTP Request Defaults, CSV Data Set Config, JDBC Connection Configuration | Общие параметры для сэмплеров, чтение данных |
| **Pre-Processors** | User Parameters, JDBC PreProcessor, JSR223 PreProcessor | Подготовка данных перед запросом |
| **Timers** | Constant Timer, Gaussian Random Timer, Synchronizing Timer | Think Time и паузы между запросами |
| **Post-Processors** | JSON Extractor, Regular Expression Extractor, JSR223 PostProcessor | Извлечение значений из ответа (correlation) |
| **Assertions** | Response Assertion, JSON Assertion, Duration Assertion | Проверки корректности ответа |
| **Listeners** | Summary Report, Aggregate Report, View Results Tree | Сбор и отображение результатов |

### Модель нагрузки и Coordinated Omission

JMeter по умолчанию работает в **Closed Loop**: каждый поток отправляет следующий запрос после завершения предыдущего (плюс timer). При деградации системы фактический RPS падает, а перцентили занижаются — это та самая ошибка **Coordinated Omission**.

Практические способы борьбы:

- Задавать точную рабочую нагрузку через **Constant Throughput Timer** (в сочетании с режимом `target throughput only for current thread` — неточно) либо использовать плагины с open-loop моделью.
- Для методологически строгих тестов на рынке чаще выбирают k6 (`constant-arrival-rate`) — подробнее в [Методология тестирования производительности](./performance_testing_methodology.md#модели-нагрузки-workload-models).
- В legacy-проектах JMeter остаётся, но выводы по p99 делают с поправкой на Closed Loop.

### Ramp-up и Thread Group

- **Threads (Users)** — количество виртуальных пользователей.
- **Ramp-up (секунды)** — время, за которое все потоки будут запущены (`рамп до 100 потоков = ~1 поток в 0.1с`).
- **Loop Count / Duration** — количество итераций или фиксированное время теста (`Duration` — предпочтительно для load-тестов).
- **Scheduler** — позволяет задать время старта/завершения теста.

### Параметризация

Данные для запросов берутся из:

- **CSV Data Set Config** — чтение строк из CSV, разделение между потоками (`sharing mode`), обработка окончания файла (`Recycle on EOF`, `Stop thread on EOF`).
- **Переменные** `__P(prop)` — доступ к Java-свойствам из `-J`, `__property` и `__env` — переменные окружения.
- **User Defined Variables** — статические константы тест-плана.
- **JSR223 + Groovy** — полноценные скрипты для динамических данных (рекомендуется Groovy, а не Beanshell, для производительности).

Классическая проблема интервью: **целочисленное сложение `__counter`** и извлечение токена аутентификации — делается через Post-Processor (JSON Extractor) + correlation, повторно использовать в последующих сэмплерах через `${переменная}`.

### Командная строка и отчёты

```bash
# Запуск в non-GUI режиме с записью результата и генерацией HTML-отчёта
jmeter -n -t plan.jmx -l results.jtl \
  -e -o reports/ \
  -Jthreads=100 -Jrampup=30 -Jduration=600

# Формирование HTML-отчёта из уже сохранённого JTL
jmeter -g results.jtl -o reports/

# Просмотр сводки в консоли
# Результат появится после завершения теста (Summary + Aggergate в консоль)
```

Полезные флаги: `-Jkey=value` (переопределение свойств), `-H/-P` (HTTP proxy), `-R host1,host2` (распределённый запуск), `-X` (завершение удалённых агентов).

Формат результатов `.jtl` (CSV/XML) — поля: `timeStamp, elapsed, label, responseCode, responseMessage, threadName, success, bytes, latency, connectTime, ...`. Именно эти данные агрегируются в перцентили отчёта.

### Распределённый запуск (Distributed Testing)

Когда одного экземпляра недостаточно (ограничение потоков на Java, один источник нагрузки не даёт нужный RPS):

- **Master** — владеет тест-планом, распределяет задачу, собирает результаты.
- **Slave (Agent)** — запускает `jmeter-server` на выделенных машинах, генерирует нагрузку, шлёт метрики мастеру.
- Порты: межпроцессный обмен по RMI (`1099` + случайный динамический диапазон `4000–5000` для RMI-сервера регистрации по умолчанию).

```bash
# На агенте
jmeter-server -Dserver_port=1099

# На мастере — запуск с использованием удалённых агентов
jmeter -n -t plan.jmx -l results.jtl -R 10.0.0.10,10.0.0.11
```

Аксиома приёма нагрузки: суммарные ресурсы агентов должны быть в разы выше ресурсов цели — иначе агенты сами станут узким местом и «провалят» координацию.

### Плагины

Каталог: **JMeter Plugins Manager** (менеджер внутри GUI). Типичные расширения:

| Плагин | Назначение |
| :--- | :--- |
| **3 Basic Graphs / Custom Thread Groups** | Кастомные модели нагрузки, графики в GUI |
| **PerfMon Metrics Collector** | Сбор системных метрик агентов (CPU, RAM, network) — серверный агент `ServerAgent` |
| **WebSocket Samplers** | Нагрузка на WebSocket (ws, wss) |
| **gRPC Request** | gRPC-тесты (protobuf) |
| **Dummy Sampler** / **BZM Arnold** | Отладка и тонкие сценарии |

## Практические сценарии

### Сценарий 1: Установка и быстрый старт

```bash
# macOS (Homebrew)
brew install jmeter

# Linux — из архива (просто распаковать, нужен только JRE)
wget https://dlcdn.apache.org/jmeter/binaries/apache-jmeter-5.6.3.tgz
tar xzf apache-jmeter-5.6.3.tgz
./apache-jmeter-5.6.3/bin/jmeter -v
# → Apache JMeter 5.6.3
```

### Сценарий 2: Минимальный HTTP-тест-план в JMX

JMX — XML. Компактный пример одного GET-запроса с 50 потоками:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="Plan">
      <elementProp name="TestPlan.user_defined_variables" elementType="Arguments"/>
    </TestPlan>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" testname="Load">
        <intProp name="ThreadGroup.num_threads">50</intProp>
        <intProp name="ThreadGroup.ramp_time">30</intProp>
        <boolProp name="ThreadGroup.scheduler">true</boolProp>
        <stringProp name="ThreadGroup.duration">600</stringProp>
      </ThreadGroup>
      <hashTree>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="GET /api/v1/resource">
          <stringProp name="HTTPSampler.domain">api.example.com</stringProp>
          <stringProp name="HTTPSampler.port">443</stringProp>
          <stringProp name="HTTPSampler.path">/api/v1/resource</stringProp>
        </HTTPSamplerProxy>
        <hashTree>
          <ResponseAssertion guiclass="AssertionGui" testclass="ResponseAssertion" testname="Status 200">
            <stringProp name="Assertion.test_field">Assertion.response_code</stringProp>
            <stringProp name="Assertion.test_string">200</stringProp>
          </ResponseAssertion>
          <hashTree/>
        </hashTree>
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>
```

### Сценарий 3: Параметризация из CSV со сценарием логина

Типичный кейс: поток с логином → извлечение токена → повторное использование в следующих запросах.

1. **CSV Data Set Config** указывает файл `users.csv` с колонками `login,password`.
2. **HTTP Request (POST /login)** использует `${login}`, `${password}`.
3. **JSON Extractor (Post-Processor)** с `JSONPath: $.access_token`, переменная `token`.
4. В последующих запросах заголовок `Authorization: Bearer ${token}` задаётся через **HTTP Header Manager**.

Признак корректности: `View Results Tree` не должен показывать `401` на втором запросе при успешном первом.

### Сценарий 4: JMeter в CI/CD (GitLab CI)

Рекомендуемые подходы: официальный docker-образ `justb4/jmeter` или сборка собственного образа с кэшированием плагинов.

```yaml
load-test:
  stage: perf
  image: justb4/jmeter:5.6.3
  script:
    - jmeter -n -t /tests/plan.jmx -l results.jtl \
        -Jthreads=$THREADS -Jduration=$DURATION
    - jmeter -g results.jtl -o reports/
  artifacts:
    when: always
    paths:
      - results.jtl
      - reports/
```

Регрессионное сравнение строят так же, как в [Интеграция тестов в CI/CD](./testing_cicd_integration.md#нагрузочное-тестирование-в-ci-k6-и-quality-gates): парсинг `.jtl` (jq/awk) и порог по p95/p99 относительно baseline.

### Сценарий 5: Выбор JMeter или k6

| Критерий | JMeter | k6 |
| :--- | :--- | :--- |
| Сценарии | GUI-конструктор, JMX, Groovy (JSR223) | Код (JS/TS), Performance-as-Code |
| Модель нагрузки | Closed Loop по умолчанию | Открытая модель `constant-arrival-rate` встроена |
| Протоколы | HTTP, JDBC, JMS, FTP, LDAP, SOAP (+ плагины gRPC/WS) | HTTP/1.1-3, gRPC, WebSocket |
| Экосистема | Множество плагинов, enterprise/legacy стандарт | Grafana-стек, идеален для CI/CD |
| Распределённость | Master/agent из коробки | Через Kubernetes-оператор или cluster mode |
| Кого выбирать | Legacy, enterprise, тесты не-веб-протоколов (JMS/JDBC), команды без разработки скриптов | Новые сервисы, CI/CD, developer-driven |

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| OOM / медленный генератор | Запуск в GUI или слишком много потоков/Listeners | Только non-GUI режим; минимизировать Listener-ы в тесте |
| Заниженные перцентили | Closed Loop (Coordinated Omission) | Открытая модель нагрузки или фиксированный RPS через timer |
| `Remote host closed connection during handshake` | RMI-таймаут между master/slave | Увеличить `server.rmi.ssl.disable` для тестовых стендов, настроить порты firewall |
| `Non HTTP response code: java.net.SocketException` | Соединение закрыто: timeout на стороне сервера/балансировщика | Увеличить timeout в HTTP Request Defaults, проверить keep-alive |
| Разброс результатов между прогонами | Noisy neighbors, общие раннеры | Выделенные агенты, фиксировать `ramp-up` и duration |
| CSV закончился — потоки молчат | `Recycle on EOF=false` без обработчиков | Установить `Stop thread on EOF=true` или recycle |
| Ошибки Groovy (JSR223) | Старый Groovy-компилятор, кэш скриптов | Включить `Cache compiled script if available`; использовать Groovy вместо Beanshell |
| Высокий TTFB (connectTime растёт) | Бэкенд/сеть не справляются | Анализ USE-методом, смотреть очередь в БД |

## Дополнительная информация

### См. также

- **[Методология тестирования производительности](./performance_testing_methodology.md)** — SLI, Open/Closed Loop, Coordinated Omission, PTLC (базовая теория для любых генераторов).
- **[Нагрузочное тестирование с помощью k6](./k6_load_testing.md)** — современная Performance-as-Code альтернатива.
- **[Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md)** — k6/Locust/wrk2 в пайплайнах, baseline и Quality Gates.

### Внешние ресурсы

- [Apache JMeter](https://jmeter.apache.org/) — официальный сайт, загрузки, изменения версий.
- [JMeter Plugins Manager](https://jmeter-plugins.org/) — менеджер и каталог плагинов.