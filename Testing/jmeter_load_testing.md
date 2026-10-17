# Нагрузочное тестирование с помощью Apache JMeter

**Актуально для:** Apache JMeter 5.6.3 / Java 8+ (рекомендовано Java 17+)

## Определения

**JMeter** — open-source инструмент нагрузочного тестирования от Apache Software Foundation. Классический «тяжёлый» генератор нагрузки на Java, де-факто стандарт в enterprise и legacy-проектах. Пригоден как для функциональных/API-проверок, так и для load/stress-тестов HTTP и не только (JDBC, JMS, FTP, LDAP). Требует Java 8+ (рекомендуется Java 17+ для производительности).

**Test Plan** — корневой XML-документ (`.jmx`), описывающий весь сценарий: потоки, сэмплеры, тайминги, ассерты, слушатели.

**Sampler** — элемент, выполняющий запрос (HTTP Request, JDBC Request, JMS Sampler и т.д.).

**Thread Group** — группа виртуальных пользователей: количество потоков, ramp-up, длительность или число итераций.

**Listener** — сборщик и визуализатор результатов (View Results Tree, Aggregate Report, Summary Report).

**Assertion** — проверка ответа (Response Assertion, Duration Assertion, JSON Assertion, JMESPath).

**Distributed Testing** — запуск одного теста с нескольких агентов (slave) под управлением мастер-узла.

**Performance Test Life Cycle (PTLC)** — методология load-тестирования: требования → подготовка среды → разработка сценариев → выполнение → сбор метрик → анализ → рекомендации. Для JMeter применяется из [Методология тестирования производительности](./performance_testing_methodology.md#3-жизненный-цикл-тестирования-ptlc).

## Архитектура и принцип работы

### Модель выполнения

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

### Модель нагрузки: Open Loop vs Closed Loop, Coordinated Omission

JMeter по умолчанию работает в **Closed Loop**: каждый поток отправляет следующий запрос после завершения предыдущего (плюс timer). При деградации системы фактический RPS падает, а перцентили занижаются — это та самая ошибка **Coordinated Omission**.

Практические способы борьбы:

- Задавать точную рабочую нагрузку через **Constant Throughput Timer** (в сочетании с режимом `target throughput only for current thread` — неточно) либо использовать плагины с open-loop моделью.
- Для методологически строгих тестов на рынке чаще выбирают k6 (`constant-arrival-rate`) — подробнее в [Методология тестирования производительности](./performance_testing_methodology.md#модели-нагрузки-workload-models).
- В legacy-проектах JMeter остаётся, но выводы по p99 делают с поправкой на Closed Loop.

Теория моделей нагрузки и SLI/SLO — см. [Методология тестирования производительности](./performance_testing_methodology.md#2-основные-концепции-2026).

### Ramp-up и Thread Group

- **Threads (Users)** — количество виртуальных пользователей.
- **Ramp-up (секунды)** — время, за которое все потоки будут запущены (`рамп до 100 потоков = ~1 поток в 0.1с`).
- **Loop Count / Duration** — количество итераций или фиксированное время теста (`Duration` — предпочтительно для load-тестов).
- **Scheduler** — позволяет задать время старта/завершения теста.

### Параметризация и correlation

Данные для запросов берутся из:

- **CSV Data Set Config** — чтение строк из CSV, разделение между потоками (`sharing mode`), обработка окончания файла (`Recycle on EOF`, `Stop thread on EOF`).
- **Переменные** `__P(prop)` — доступ к Java-свойствам из `-J`, `__property` и `__env` — переменные окружения.
- **User Defined Variables** — статические константы тест-плана.
- **JSR223 + Groovy** — полноценные скрипты для динамических данных (рекомендуется Groovy, а не Beanshell, для производительности).

Классическая проблема интервью: **целочисленное сложение `__counter`** и извлечение токена аутентификации — делается через Post-Processor (JSON Extractor) + correlation, повторно использовать в последующих сэмплерах через `${переменная}`.

### Распределённый запуск (Distributed Testing)

**Предпосылки:**
- Master и slave-узлы с JMeter 5.6.3
- Сетевая доступность портов RMI (1099 + диапазон 4000-5000)
- Одинаковые версии Java и JMeter на всех узлах

Когда одного экземпляра недостаточно (ограничение потоков на Java, один источник нагрузки не даёт нужный RPS):

- **Master** — владеет тест-планом, распределяет задачу, собирает результаты.
- **Slave (Agent)** — запускает `jmeter-server` на выделенных машинах, генерирует нагрузку, шлёт метрики мастеру.
- **Порты:** межпроцессный обмен по RMI (`1099` + динамический диапазон `4000–5000` для RMI-сервера по умолчанию).

```bash
# На агенте (slave)
jmeter-server -Dserver_port=1099

# На мастере — запуск с использованием удалённых агентов
jmeter -n -t plan.jmx -l results.jtl -R 10.0.0.10,10.0.0.11
```

**Валидация:** master видит статус slave-ов через `netstat -an | grep 1099`; тест завершается с exit code 0.

Аксиома приёма нагрузки: суммарные ресурсы агентов должны быть в разы выше ресурсов цели — иначе агенты сами становятся узким местом и искажают координацию.

## Практические сценарии

### Сценарий 1: Установка и быстрый старт

**Предпосылки:**
- Java 8+ (рекомендуется Java 17+)
- Доступ к `https://downloads.apache.org/jmeter/`
- Порт 80/443 открыты (для скачивания архива)

```bash
# Linux — из архива (просто распаковать, нужен только JRE)
wget https://dlcdn.apache.org/jmeter/binaries/apache-jmeter-5.6.3.tgz
tar xzf apache-jmeter-5.6.3.tgz
./apache-jmeter-5.6.3/bin/jmeter -v
# → Apache JMeter 5.6.3

# macOS (Homebrew)
brew install jmeter
```

**Валидация:** `jmeter -v` выводит версию 5.6.3.

### Сценарий 2: Минимальный HTTP-тест-план в JMX

**Предпосылки:** тестовый HTTP-сервис с эндпоинтом `/api/v1/resource`.

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

**Валидация:** `jmeter -n -t plan.jmx -l result.jtl` завершается с exit code 0; в логе нет ошибок подключения.

### Сценарий 3: Параметризация из CSV со сценарием логина

**Предпосылки:** CSV-файл `users.csv` с колонками `login,password`, тестовый сервис с `/login` и `/api/v1/resource`.

Типичный кейс: поток с логином → извлечение токена → повторное использование в следующих запросах.

1. **CSV Data Set Config** указывает файл `users.csv` с колонками `login,password`.
2. **HTTP Request (POST /login)** использует `${login}`, `${password}`.
3. **JSON Extractor (Post-Processor)** с `JSONPath: $.access_token`, переменная `token`.
4. В последующих запросах заголовок `Authorization: Bearer ${token}` задаётся через **HTTP Header Manager**.

Признак корректности: `View Results Tree` не должен показывать `401` на втором запросе при успешном первом.

### Сценарий 4: JMeter в CI/CD (GitLab CI)

**Предпосылки:**
- CI-runner с Docker-in-Docker
- JMX-файл в репозитории
- переменные CI/CD: `THREADS`, `DURATION`

Рекомендуемый подход: Docker-образ `justb4/jmeter:5.5` (последний совместимый с JMeter 5.6.x) или сборка собственного образа с кэшированием плагинов.

```yaml
load-test:
  stage: perf
  image: justb4/jmeter:5.5
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

**Валидция:** pipeline падает на non-zero exit code при тестовом failure; артефакты `results.jtl` и `reports/` доступны в UI.

Регрессионное сравнение строят так же, как в [Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md) и [Интеграция тестов в CI/CD](./testing_cicd_integration.md#нагрузочное-тестирование-в-ci-k6-и-quality-gates): парсинг `.jtl` (jq/awk) и порог по p95/p99 относительно baseline.

### Сценарий 5: Выбор JMeter или k6

| Критерий | JMeter | k6 |
| :--- | :--- | :--- |
| Сценарии | GUI-конструктор, JMX, Groovy (JSR223) | Код (JS/TS), Performance-as-Code |
| Модель нагрузки | Closed Loop по умолчанию | Открытая модель `constant-arrival-rate` встроена |
| Протоколы | HTTP, JDBC, JMS, FTP, LDAP, SOAP (+ плагины gRPC/WS) | HTTP/1.1-3, gRPC, WebSocket |
| Экосистема | Множество плагинов, enterprise/legacy стандарт | Grafana-стек, идеален для CI/CD |
| Распределённость | Master/agent из коробки | Через Kubernetes-оператор или cluster mode |
| Кому выбирать | Legacy, enterprise, тесты не-веб-протоколов (JMS/JDBC), команды без разработки скриптов | Новые сервисы, CI/CD, developer-driven |

## Операции и команды

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `jmeter -v` | Проверка версии | `jmeter -v` |
| `jmeter -n -t plan.jmx` | Запуск теста в non-GUI режиме | `jmeter -n -t plan.jmx -l results.jtl` |
| `jmeter -g results.jtl -o reports/` | Генерация HTML-отчёта | `jmeter -g results.jtl -o reports/` |
| `jmeter -R host1,host2 -X` | Распределённый запуск + stop slaves | `jmeter -n -t plan.jmx -R 10.0.0.10,10.0.0.11 -X` |
| `jmeter-server -Dserver_port=1099` | Запуск slave-агента | `jmeter-server` |
| `jmeter -n -t plan.jmx -Jthreads=100` | Переопределение свойств | `-Jduration=600 -Jrampup=30` |
| `jmeter -n -t plan.jmx -H proxy -P 8080` | Через HTTP proxy | `-H 10.0.0.1 -P 8080` |
| `jq -r '.[] \| select(.success=="true")' results.jtl` | Парсинг JTL (JSON) | Извлечение успешных запросов |
| `awk -F, '{print $2}' results.jtl` | Парсинг CSV (latency) | Извлечение latency |

### Полезные флаги

| Флаг | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `-n` | non-GUI режим | — |
| `-t` | путь к JMX | — |
| `-l` | файл результатов (.jtl) | — |
| `-Jkey=value` | переопределение свойств | — |
| `-R` | список slave-хостов | — |
| `-X` | stop remote slaves after test | — |
| `-H`, `-P` | HTTP proxy host/port | — |
| `-e -o` | генерация HTML-отчёта | — |

### Переменные окружения для CI/CD

| Переменная | Применение |
| :--- | :--- |
| `JVM_ARGS` | Параметры JVM (heap, GC): `-Xmx4g -XX:+UseG1GC` |
| `JMETER_HOME` | Путь к установке JMeter |
| `JMETER_OPTS` | Доп. опции для запуска |

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| OOM / медленный генератор | Запуск в GUI или слишком много потоков/Listeners | `top -p $(pgrep jmeter)` — проверить heap | Только non-GUI режим; минимизировать Listener-ы в тесте |
| Заниженные перцентили | Closed Loop (Coordinated Omission) | Сравнить с k6 `constant-arrival-rate` | Открытая модель нагрузки или фиксированный RPS через timer |
| `Remote host closed connection during handshake` | RMI-таймаут между master/slave | `netstat -an \| grep 1099` на slave | Увеличить `server.rmi.ssl.disable` для тестовых стендов, настроить firewall |
| `Non HTTP response code: java.net.SocketException` | Соединение закрыто: timeout на стороне сервера/балансировщика | `telnet host port` снаружи | Увеличить timeout в HTTP Request Defaults, проверить keep-alive |
| Разброс результатов между прогонами | Noisy neighbors, общие раннеры | Запустить 3 раза, сравнить baseline | Выделенные агенты, фиксировать `ramp-up` и duration |
| CSV закончился — потоки молчат | `Recycle on EOF=false` без обработчиков | Проверить `Recycle on EOF` и `Stop thread on EOF` в CSV Data Set Config | Установить `Stop thread on EOF=true` или `Recycle=true` |
| Ошибки Groovy (JSR223) | Старый Groovy-компилятор, кэш скриптов | Логи в `jmeter.log` | Включить `Cache compiled script if available`; использовать Groovy вместо Beanshell |
| Высокий TTFB (connectTime растёт) | Бэкенд/сеть не справляются | USE-метод: `iostat -x`, `ss -s` | Анализировать bottleneck на уровне CPU/сети/БД |
| `java.lang.OutOfMemoryError: Java heap space` | Недостаточно heap дляListeners | `jstat -gc $(pgrep java)` | `JVM_ARGS="-Xmx4g"` и убрать View Results Tree на production |
| `Connection timed out` в распределённом режиме | Firewall между master и slave | `ping slave_host` с master | Открыть порты 1099 + диапазон RMI (4000-5000) |

## Лучшие практики

### Общие принципы

1. **Non-GUI только в CI/CD**: никогда не запускайте большие нагрузки через GUI — потребление памяти и искажение метрик (GUI-Listeners добавляют overhead).
2. **Минимизируйте Listeners**: убирайте `View Results Tree`, `Debug Sampler`, `Simple Data Writer` в production-тестах. Используйте только `Backend Listener` (InfluxDB/Grafana) или `.jtl`-файл.
3. **Open Loop для SLM**: если нужна точная модель rps (service level objectives), используйте `Constant Throughput Timer` или переходите на k6 `constant-arrival-rate` (см. [Методология тестирования производительности](./performance_testing_methodology.md#модели-нагрузки-workload-models)).
4. **Distributed за необходимостью**: RMI master/agent — легко перенастроить firewall забыть. Используйте только когда одиночный экземпляр не даёт нужный RPS.
5. **Correlation, а не хардкод**: извлекайте токены через JSON Extractor / Regular Expression Extractor, не хардкодьте в CSV.

### CI/CD интеграция

6. **Docker образ с pinned версией**: используйте `justb4/jmeter:5.5` (не `latest`) для воспроизводимых прогонов. Собирайте кастомный образ с плагинами и кэшируйте зависимости.
7. **Baseline comparison**: сохраняйте `.jtl` как baseline, сравнивайте p95/p99 между прогонами через jq/awk. Автоматический fail при регрессии — Quality Gate (см. [Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md)).
8. **SRE Error Budget**: связывайте результаты JMeter с SLO (latency p99 < 500ms). Используйте burn rate alerts на основе JTL — см. [SRE-практики: Error Budget, Burn Rate, Alerting](./performance_testing_methodology.md#7-sre-практики-error-budget-burn-rate-и-alerting-для-производительности).

### Архитектурные решения

9. **JMeter как legacy, k6 как modern**: если команда пишет код, используйте k6 для новых сервисов. JMeter остаётся для JMS/JDBC/FTP/LDAP — протоколов, где k6 не подходит.
10. **Отказ от GUI для отчётов**: генерируйте HTML-отчёт (`-e -o`) из `.jtl` в CI, а не открывайте GUI локально — масштабируемо и воспроизводимо.

## Ограничения и крайние случая

- **Memory footprint**: JMeter с GUI потребляет ~500MB + heap. В non-GUI режиме — ~200MB, но с большим количеством Threads растёт. Используйте `JVM_ARGS="-Xmx4g"` и убирайте GUI-Listeners.
- **Coordinated Omission**: Closed Loop нмодель занижает p99 при деградации. Требует фиксировки в анализе или перехода на k6.
- **Java 8 vs 17**: JMeter 6.0 требует Java 17+. В текущей версии 5.6.3 Java 8 допустим, но Java 17 даёт лучшую производительность GC.
- **RMI в distributed mode**: требует firewall-правил на slave-узлах (порт 1099 + диапазон 4000-5000). В облаке это частая проблема — используйте выделенные VM без NAT.
- **CSV Data Set Config**: по умолчанию `Recycle on EOF = true`, `Stop thread on EOF = false` — если CSV мал, потоки повторно используют данные, что может исказить нагрузку.
- **JSR223 Beanshell deprecated**: Beanshell медленнее в 10-50x. Используйте Groovy для скриптов.
- **Assertions overhead**: Response Assertion на каждый запрос добавляет ~5-10% overhead. Отключайте в high-throughput тестах (10k+ rps).
- **JTL размер**: файл `.jtl` растёт пропорционально количеству запросов. На 1M запросов — ~50MB. Используйте `jmeter -Jtarget.results.file=results.jtl` с `jmeter.save` config для ограничения полей.

## Очистка

1. **JTL-артефакты** — удаляйте `.jtl` и `reports/` после анализа в CI:
   ```bash
   rm -f results.jtl && rm -rf reports/
   ```
2. **Docker-образы JMeter** — удаляйте кэш после теста:
   ```bash
   docker rmi justb4/jmeter:5.5 || true
   ```
3. **slave-агенты** — после распределённого теста:
   ```bash
   jmeter -m -R 10.0.0.10,10.0.0.11 -X  # stop remote
   ```
4. **JVM heap dumps** — при OOM удаляйте `jmap`-файлы:
   ```bash
   rm -f jmeter*.*.hprof
   ```
5. **Log rotation** — настраивайте `log4j2.xml` в JMeter для ограничения `jmeter.log`:
   ```xml
   <RollingFile fileName="${sys:jmeter.home}/logs/jmeter.log">
     <Policies><SizeBasedTriggeringPolicy size="10MB"/></Policies>
   </RollingFile>
   ```
6. **Test Plan resources** — если использовалась `HTTP Cookie Manager`, `JDBC Connection Configuration` — они автоматически закрываются при завершении теста, но в non-GUI рекомендуется `teardownScript` для cleanup.

## Дополнительная информация

### См. также

- **[Методология тестирования производительности](./performance_testing_methodology.md)** — модели нагрузки, SLI/SLO, PTLC, SRE Error Budget (базовая теория для любых генераторов).
- **[Нагрузочное тестирование с помощью k6](./k6_load_testing.md)** — современная Performance-as-Code альтернатива с open-loop моделью.
- **[Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md)** — baseline comparison, Quality Gates, артефакты в CI.
- **[Интеграция тестов в CI/CD](./testing_cicd_integration.md#нагрузочное-тестирование-в-ci-k6-и-quality-gates)** — паттерны CI/CD для тестов производительности.
- **[Нагрузочное тестирование с помощью Yandex.Tank и Taurus](./yandex_tank_taurus.md)** — Taurus executor `jmeter` для совместимости с JMX.

### Внешние ресурсы

- [Apache JMeter](https://jmeter.apache.org/) — официальный сайт, загрузки, изменения версий.
- [JMeter Plugins Manager](https://jmeter-plugins.org/) — менеджер и каталог плагинов.
- [justb4/jmeter на Docker Hub](https://hub.docker.com/r/justb4/jmeter) — официальный community Docker-образ.
- [JMeter User Manual](https://jmeter.apache.org/usermanual/) — справка по использованию.

## Overlap Declaration (§0.10)

**Файлы, проверенные на семантическое пересечение:**

1. `./performance_testing_methodology.md` — SSoT по методологии (модели нагрузки, SLI/SLO, PTLC, Error Budget). Пересечение с JMX-specific деталями — связь через cross-reference, не дублирование.
2. `./k6_load_testing.md` — аналогичный формат, но для k6 (Performance-as-Code). Пересечение только в «Сценарии 5: Выбор JMeter или k6» — намеренное сравнение, не дублирование.
3. `./yandex_tank_taurus.md` — упоминает JMeter как executor в Taurus. Ссылка через cross-reference, не дублирует JMX-детали.
4. `CI-CD/Testing/load_testing_ci_cd.md` — SSoT по baseline comparison и Quality Gates в CI. Пересечение только в паттернах CI/CD — связь через cross-reference.
5. `./testing_cicd_integration.md` — общие паттерны CI/CD для тестов. Ссылка на конкретный anchor `#нагрузочное-тестирование-в-ci-k6-и-quality-gates`.

**Решение:** Никакого дублирования нет — каждая тема покрывается в соответствующем файле, а общая теория находится в `performance_testing_methodology.md`.
