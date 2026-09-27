# Chaos Engineering: Обзор

## Определения

**Chaos Engineering (Хаос-инженерия)** — это дисциплина, основанная на проведении контролируемых экспериментов в распределенных системах для формирования уверенности в их способности выдерживать турбулентные условия в промышленной эксплуатации.

В отличие от классического тестирования, хаос-инженерия рассматривает систему как живой организм с высокой степенью неопределенности. Цель дисциплины — не подтверждение корректности логики, а опровергнуть гипотезу об устойчивости и выявить скрытые системные дефекты (каскадные сбои, некорректные таймауты, ошибки конфигурации) до того, как они приведут к реальному инциденту.

**Steady State (Устойчивое состояние)** — нормальное поведение системы, зафиксированное до начала эксперимента через измеримые показатели (latency p99, error rate, RPS). Эксперимент считается успешным, если steady state сохраняется во время fault injection.

**Blast Radius (Радиус поражения)** — контролируемый масштаб эксперимента: процент ресурсов, узлов или пользователей, затронутых сбоем. В production начинается с 1–5% трафика или одного пода.

**Steady State Hypothesis** — предположение о том, что система находится в стабильном состоянии (HTTP 200, latency < 200ms, error rate < 1%). Если гипотеза опровергается — эксперимент остановлен, система не выдержала нагрузку.

**Stop-switch (Аварийная остановка)** — автоматический механизм прекращения эксперимента при нарушении SLO. Может быть реализован через алерты Prometheus/Alertmanager или встроенный в платформу (Chaos Mesh, Litmus) emergency stop.

**Game Day** — запланированное мероприятие, в ходе которого команда имитирует реальные инциденты (отказы серверов, сетевые сбои, утечки памяти) и отрабатывает процедуры реагирования в реальном времени.

**Fault Injection (Инъекция сбоев)** — целенаправленное внесение дефекта в систему для проверки ее поведения. Подмножество Chaos Engineering, фокусирующееся на конкретном условии сбоя.

**Resilience (Устойчивость)** — способность системы адаптироваться к изменениям и поглощать сбои без потери функциональности. Хаос-инженерия является инструментом для достижения resilience.

**Mean Time to Recovery (MTTR)** — время от прекращения инъекции до возвращения системы в steady state. Чем ниже MTTR, тем лучше отлажены процессы восстановления.

**Mean Time to Detect (MTTD)** — время от начала инъекции до срабатывания первого алерта. Показывает качество observability. Целевой показатель — MTTD < 60 секунд.

**Probe (Проба)** — активная проверка steady state во время эксперимента. Проверяет доступность сервиса (HTTP 200), время отклика, количество рестартов. Без probes эксперимент — не научный метод.

**Resilience Patterns Testing** — проверка через хаос-инженерию архитектурных паттернов: Circuit Breaker, Bulkhead, Rate Limiter, Retry, Fallback. Если при отказе зависимости circuit breaker не срабатывает — это архитектурный риск.

**Chaos Monkey** — паттерн и инструмент случайного уничтожения ресурсов в рабочей среде для проверки устойчивости системы. Работает в рабочее время, когда инженеры на месте и могут отреагировать на каскадный сбой.

**Confidence Score** — интегральный показатель уверенности в устойчивости системы. Растет с количеством успешных экспериментов. 10+ успешных runs дают high confidence для production.

### Хаос-инженерия vs Fault Injection

| Аспект | Fault Injection | Chaos Engineering |
|:---|:---|:---|
| **Подход** | Тестирование конкретного условия (например, диск полон). | Эксперимент над системой в целом для поиска неизвестных уязвимостей. |
| **Цель** | Проверить конкретный механизм защиты. | Сформировать уверенность в устойчивом состоянии (Steady State). |
| **Масштаб** | Часто ограничивается одним компонентом. | Фокусируется на взаимодействии распределенных узлов. |

## Основные концепции

### Ключевые принципы хаоса

1.  **Формирование гипотезы об устойчивом состоянии (Steady State):** Определение измеримых показателей (SLI), которые описывают нормальное поведение системы. В современных практиках акцент сместился с системных метрик (CPU/RAM) на бизнес-метрики (количество успешных транзакций в секунду) и пользовательский опыт (p99 latency, error rate).
2.  **Варьирование событий реального мира:** Симуляция событий с учетом вероятности их возникновения: отказ хоста, потеря пакетов в ненадежных сетевых соединениях, аномальные скачки трафика, исчерпание ресурсов.
3.  **Эксперименты в продакшене:** Распределенные системы ведут себя непредсказуемо под нагрузкой. Тестирование в Staging полезно для базовой проверки, но только Production дает истинную уверенность. Обязательное условие — ограничение blast radius и автоматический stop-switch.
4.  **Автоматизация:** Интеграция в CI/CD и использование хаос-платформ для регулярного проведения тестов без участия человека. Каждый Pull Request должен проходить минимальный хаос-тест.
5.  **Ограничение радиуса поражения (Blast Radius):** Жесткий контроль области воздействия. Эксперимент должен затрагивать минимально возможное количество пользователей и немедленно прекращаться при нарушении SLO.

### Механизмы повышения устойчивости

*   **Выявление скрытых зависимостей:** Инъекция задержек (Latency Injection) вскрывает синхронные вызовы в цепочках микросервисов, которые должны были быть асинхронными. В SRE-контексте это относится к принципу «устранение синхронных зависимостей».
*   **Валидация механизмов защиты:** Проверка работоспособности паттернов Circuit Breaker, Bulkhead, Retry policies и Fallback-логики. Если при отказе зависимости circuit breaker не срабатывает — архитектурный риск.
*   **Калибровка наблюдаемости (Observability):** Проверка того, что система мониторинга (Prometheus, OpenTelemetry, Jaeger) видит сбой, а алертинг уведомляет команду вовремя. MTTD < 60 секунд — целевой показатель.
*   **Resilience Engineering:** Хаос-инженерия является инструментом для достижения Resilience — способности системы адаптироваться к изменениям и поглощать сбои без потери функциональности. Другие инструменты: DR-планирование, graceful degradation, redundancy.

### Жизненный цикл хаос-эксперимента

Качественный эксперимент проходит через шесть этапов:

1.  **Определение steady state** — как выглядит «норма»? Какие метрики (SLI) характеризуют здоровье системы? На этом этапе фиксируются baseline значения: latency p99, error rate, RPS, saturation.
2.  **Формулировка гипотезы** — «сервис выдержит отказ одного пода базы данных». Гипотеза должна быть измеримой и опровергаемой.
3.  **Выбор сценария и blast radius** — что именно сломаем (pod kill, network delay, disk full) и на каком масштабе (1% трафика, один узел, конкретный namespace).
4.  **Настройка наблюдения** — probes для проверки steady state во время эксперимента. Без probes эксперимент — не научный метод, а «угадайка».
5.  **Выполнение** — инъекция сбоя под контролем stop-switch. В production — через canary или gradual rollout.
6.  **Анализ и документирование** — что пошло не так? Какие сценарии сработали? Какие паттерны нужно добавить в архитектуру? Ведение runbook.

### Модель зрелости хаоса (Chaos Maturity Model)

Путь внедрения дисциплины в компании обычно проходит через три этапа:

1.  **Начальный (Manual & Staging):** Ручное выключение подов в тестовой среде. Проверка базовых сценариев. Основной фокус — обучение команды и настройка observability.
2.  **Продвинутый (Automated & Guardrails):** Автоматизация через Chaos Mesh/Litmus. Внедрение автоматических Stop-switches на основе метрик Prometheus. Интеграция в CI/CD pipeline.
3.  **Экспертный (Continuous Production Chaos):** Постоянные эксперименты в продакшене под реальной нагрузкой. Использование топологии системы для генерации новых гипотез. Каждый production incident — готовый сценарий для эксперимента.

### Практические сценарии для собеседований

#### Сценарий: проверка resilience паттернов

**Гипотеза:** При задержке 500 мс на ответ от сервиса базы данных для 5% трафика система применит паттерн `Circuit Breaker`, и пользователи увидят данные из кэша. Общий Error Rate не вырастет.

**Реальность без хаос-тестов:** Часто выясняется, что ретраи на уровне API Gateway создают «шторм запросов», исчерпывая пул соединений и роняя сервис целиком.

#### Сценарий: Game Day для database failover

**Цель:** Проверить automatic failover PostgreSQL primary → standby.

**Этапы:**
1. Остановить PostgreSQL primary (pod delete или SIGTERM).
2. Наблюдать: Patroni/Repmgr выполняет failover? Приложение переключается на новый primary?
3. Восстановить старый primary как standby.
4. Проверить data consistency.

**Ожидаемый результат:**
- Failover завершается за < 60 секунд.
- Нет потери данных.
- Приложение продолжает работать.

#### Сценарий: Chaos-тестирование Gateway API

**Гипотеза:** При падении контроллера Gateway API существующая маршрутизация продолжает работать, но новые изменения не применяются.

**Эксперимент:** PodChaos на envoy-gateway-system.

**Проверка:**
- Существующие HTTPRoute продолжают маршрутизировать трафик.
- Новые HTTPRoute не применяются до восстановления контроллера.
- Алерт `GatewayAPIControllerDown` срабатывает.

#### Сценарий: проверка observability

**Гипотеза:** Система мониторинга видит сбой и алертинг уведомляет команду вовремя.

**Метод:** MTTD measurement — время от начала инъекции до срабатывания первого алерта.

**Целевой показатель:** MTTD < 60 секунд.

**Что проверяется:**
- Prometheus собирает метрики за время < scrape_interval.
- Alertmanager отправляет алерт в Slack/Telegram/PagerDuty.
- Grafana dashboard обновляется в реальном времени.
- Jaeger trace показывает точку сбоя.

#### Сценарий: shift-left chaos в CI/CD

**Гипотеза:** Каждый Pull Request должен проходить минимальный хаос-тест в Staging.

**Реализация:**
- GitLab CI stage `chaos` запускает `pod-delete` эксперимент.
- Длительность: 2 минуты.
- Stop condition: error rate > 1%.
- Cleanup: автоматическое удаление CRD.

**Ожидаемый результат:**
- Система выдерживает отказ пода без деградации.
- Pipeline блокируется, если эксперимент провален.

## Практические сценарии

### Пример: Тестирование каскадного сбоя

**Сценарий:** Вводится задержка в 500 мс на ответ от сервиса базы данных для 5% трафика.

**Гипотеза:** Система применит паттерн `Circuit Breaker` для этого сегмента трафика, и пользователи увидят данные из кэша. Общий Error Rate не вырастет.

**Реальность (без хаос-тестов):** Часто выясняется, что ретраи на уровне API Gateway создают «шторм запросов», исчерпывая пул соединений и роняя сервис целиком.

**Манифест для Chaos Mesh (Сетевая задержка):**

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: database-latency-test
spec:
  action: delay
  mode: one
  selector:
    labelSelectors:
      app: db-proxy
  delay:
    latency: "500ms"
    jitter: "100ms"
  duration: "10m"
```

### Chaos-тестирование Gateway API

#### Сценарий 1: Падение Control Plane

**Гипотеза:** При падении контроллера Gateway API существующая маршрутизация продолжает работать, но новые изменения не применяются.

**Эксперимент (Chaos Mesh):**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: kill-gateway-controller
  namespace: chaos-testing
spec:
  action: pod-kill
  mode: all
  selector:
    namespaces:
    - envoy-gateway-system
    labelSelectors:
      control-plane: envoy-gateway-controller
  scheduler:
    cron: "@every 5m"
  duration: "30s"
```

**Проверка:**
- Существующие HTTPRoute продолжают маршрутизировать трафик
- Новые HTTPRoute не применяются до восстановления контроллера
- Алерт GatewayAPIControllerDown срабатывает

#### Сценарий 2: Падение Data Plane Pod

**Гипотеза:** При падении одного Envoy-под трафик автоматически переключается на оставшиеся поды без потерь.

**Эксперимент (Chaos Mesh):**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: kill-envoy-pod
  namespace: chaos-testing
spec:
  action: pod-kill
  mode: one
  selector:
    namespaces:
    - envoy-gateway-system
    labelSelectors:
      gateway.envoyproxy.io/owning-gateway-name: external-gw
  scheduler:
    cron: "@every 10m"
```

**Проверка:**
- Error rate не превышает 1% за 30-секундное окно
- P95 latency не увеличивается более чем на 20%
- Все поды восстанавливаются через 60 секунд

#### Сценарий 3: Сетевая задержка к бэкендам

**Гипотеза:** При задержке 500 мс от бэкенда BackendTrafficPolicy с таймаутами и retry корректно обрабатывает ситуацию.

**Эксперимент (Chaos Mesh):**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: delay-to-backend
  namespace: chaos-testing
spec:
  action: delay
  mode: one
  selector:
    namespaces:
    - production
    labelSelectors:
      app: api-service
  delay:
    latency: "500ms"
    jitter: "100ms"
    correlation: "50"
  duration: "5m"
  direction: to
```

**Проверка:**
- HTTPRoute с retry политикой автоматически повторяет запросы
- Circuit Breaker не срабатывает при малой доле задержек
- Error rate не превышает SLO

#### Сценарий 4: Потеря пакетов

**Гипотеза:** При потере 10% пакетов Envoy корректно обрабатывает TCP retransmissions.

**Эксперимент (Chaos Mesh):**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: packet-loss
  namespace: chaos-testing
spec:
  action: loss
  mode: one
  selector:
    namespaces:
    - envoy-gateway-system
    labelSelectors:
      gateway.envoyproxy.io/owning-gateway-name: external-gw
  loss:
    loss: "10"
    correlation: "25"
  direction: both
  duration: "3m"
```

**Проверка:**
- TCP retransmissions корректно обрабатываются
- Error rate не превышает допустимые пороги
- Мониторинг фиксирует аномалию

#### Сценарий 5: Падение DNS

**Гипотеза:** При недоступности CoreDNS Envoy использует кэш DNS-записей.

**Эксперимент (Litmus):**
```yaml
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: dns-chaos
  namespace: chaos-testing
spec:
  appinfo:
    appns: envoy-gateway-system
    applabel: gateway.envoyproxy.io/owning-gateway-name
    appkind: deployment
  chaosServiceAccount: litmus-admin
  experiments:
  - name: pod-delete
    spec:
      components:
        env:
        - name: TOTAL_CHAOS_DURATION
          value: "60"
        - name: TARGET_PODS
          value: "coredns"
      probe:
      - name: check-gateway-status
        type: httpProbe
        httpProbe/inputs:
          url: http://localhost:19000/ready
          insecureSkipVerify: true
          method:
            get:
              criteria: ==
              responseCode: "200"
        mode: Edge
        runProperties:
          probeTimeout: 5s
          interval: 10s
          retry: 3
```

### Пример: Тестирование Resilience с Toxiproxy и k6

**Сценарий:** Комбинированная нагрузка через k6 + инъекция задержки через Toxiproxy для проверки поведения сервиса при деградации upstream.

**Toxiproxy — запуск прокси с задержкой:**

```bash
# Создаем прокси для целевого сервиса
docker run -d --name toxiproxy -p 8474:8474 -p 8666:8666 shopify/toxiproxy

# Добавляем задержку 300мс на 30 секунд
curl -X POST http://localhost:8474/proxies/api-service/toxics \
  -H "Content-Type: application/json" \
  -d '{"name":"latency","type":"latency","attributes":{"latency":300}}'
```

**k6 — генерация нагрузки:**

```bash
# Запуск теста с проверкой SLO
k6 run --vus 50 --duration 5m script.js
```

**Ожидаемый результат:** p99 latency < 500ms, error rate < 1%, нет panics/OOM.

### Практические инструменты для chaos-тестирования

| Инструмент | Тип сценария | Преимущество |
|:---|:---|:---|
| **Chaos Mesh** | Pod kill, Network delay/loss | Нативная поддержка label selectors, Kubernetes-native |
| **Litmus Chaos** | Pod delete, DNS failure | Простые манифесты, быстрый старт |
| **Toxiproxy** | TCP proxy anomalies | Точная инъекция сбоев на уровне TCP |
| **k6** | Нагрузка + chaos | Комбинирование нагрузки и сбоев |
| **Pumba** | Docker-контейнеры | Хаос-тестирование для Docker (сеть, пауза, удаление) |

### Автоматизация chaos-тестирования

```yaml
# GitHub Actions workflow для chaos-тестирования
name: Chaos Tests

on:
  schedule:
  - cron: "0 2 * * 1"  # Каждый понедельник в 02:00

jobs:
  chaos:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Deploy chaos tests
      run: |
        kubectl apply -f chaos/gateway-api-chaos.yaml
        sleep 300  # Ждём 5 минут

    - name: Validate steady state
      run: |
        ERROR_RATE=$(curl -s http://prometheus:9090/api/v1/query?query=sum(rate(envoy_cluster_upstream_rq_xx{code=~"5.."}[5m]))/sum(rate(envoy_cluster_upstream_rq_total[5m])) | jq '.data.result[0].value[1]' -r)
        if (( $(echo "$ERROR_RATE > 0.05" | bc -l) )); then
          echo "FAIL: Error rate $ERROR_RATE exceeds 5% threshold"
          exit 1
        fi
        echo "PASS: Error rate $ERROR_RATE within SLO"

    - name: Cleanup
      if: always()
      run: kubectl delete -f chaos/gateway-api-chaos.yaml
```

## Операции и команды

### Жизненный цикл эксперимента

Полный цикл chaos-эксперимента состоит из шести этапов. Для каждого этапа указаны типовые операции и инструменты:

| Этап | Операция | Инструмент / Команда |
|:---|:---|:---|
| **1. Определение steady state** | Сбор baseline метрик | `Prometheus: histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[1h])))` |
| **2. Формулировка гипотезы** | Описание сценария в runbook | Markdown, confluence, Git |
| **3. Выбор blast radius** | Ограничение namespace / label | `kubectl apply -f chaos-experiment.yaml` с `mode: one` |
| **4. Настройка probes** | HTTP/tcp/exec пробы | Litmus probes, Chaos Mesh prober |
| **5. Выполнение** | Запуск эксперимента | `kubectl apply -f network-delay.yaml` |
| **6. Остановка и анализ** | Emergency stop | `kubectl delete -f network-delay.yaml`, Alertmanager silence |

### Типовые команды для экспериментов

**Chaos Mesh — управление экспериментами:**

```bash
# Применить эксперимент (сетевая задержка)
kubectl apply -f network-delay.yaml

# Проверить статус эксперимента
kubectl get networkchaos -n chaos-testing

# Посмотреть логи chaos daemon
kubectl logs -n chaos-mesh -l app=chaos-daemon -f

# Принудительная остановка эксперимента
kubectl delete -f network-delay.yaml

# Проверить CRDs
kubectl get crd | grep chaos-mesh
```

**Litmus Chaos — управление экспериментами:**

```bash
# Применить ChaosEngine
kubectl apply -f chaos-engine.yaml

# Проверить статус эксперимента
kubectl get chaosengine -n chaos-testing

# Посмотреть результат
kubectl describe chaosresult -n chaos-testing

# Удалить эксперимент
kubectl delete -f chaos-engine.yaml

# Проверить CRDs
kubectl get crd | grep litmus
```

**Pumba — хаос для Docker-контейнеров:**

```bash
# Пауза контейнера на 30 секунд
pumba pause --duration 30s <container_id>

# Удаление контейнера (SIGKILL)
pumba kill --signal SIGKILL <container_id>

# Сетевая задержка 500мс
pumba netem --duration 60s --delay 500ms <container_id>

# Потеря пакетов 10%
pumba netem --duration 60s --loss 10% <container_id>

# Остановка всех контейнеров образа
pumba stop --duration 60s <image_name>
```

**PromQL — типовые запросы для наблюдения за экспериментом:**

| Операция | Запрос |
|:---|:---|
| **Текущий p99 latency** | `histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))` |
| **Error Rate** | `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))` |
| **Burn Rate (SLO 99.9%)** | `sum(rate(http_requests_total{status=~"5.."}[5m])) / (sum(rate(http_requests_total[5m])) * (1 - 0.999))` |
| **CPU utilization** | `rate(container_cpu_usage_seconds_total[5m]) / rate(container_cpu_cfs_quota_total[5m]) * 100` |
| **Memory utilization** | `container_memory_working_set_bytes / container_spec_memory_limit_bytes * 100` |
| **File descriptors saturation** | `node_filefd_allocated / node_filefd_maximum * 100` |

### Alertmanager — правила для Stop-switch

```yaml
groups:
  - name: chaos_experiment_alerts
    rules:
      - alert: ChaosExperimentCriticalErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
          /
          sum(rate(http_requests_total[5m])) > 0.05
        for: 30s
        labels:
          severity: critical
          experiment: "{{ $labels.experiment }}"
        annotations:
          summary: "Error rate превысил 5%"
          description: "Текущий error rate: {{ $value | humanizePercentage }}"

      - alert: ChaosExperimentLatencyDegradation
        expr: |
          histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
          /
          histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m] offset 1h))) > 1.5
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "p99 latency вырос в 1.5+ раза"
```

### Cleanup — обязательные шаги после эксперимента

```bash
# 1. Удалить все ресурсы chaos
kubectl delete -f chaos-experiment.yaml
kubectl delete -f chaos-engine.yaml

# 2. Проверить отсутствие остаточных ресурсов
kubectl get networkchaos,podchaos,stresschaos -n chaos-testing

# 3. Убедиться, что метрики вернулись к baseline
# Проверка в Prometheus: latency p99, error rate

# 4. Очистить алерты/силуты
# Alertmanager: убрать silence, если создавались временные

# 5. Архивировать результаты
# Сохранить логи, графики, вывод probes в runbook
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **Алерты не срабатывают во время эксперимента** | Метрика не существует или label mismatch | Проверьте `up` и availability probe для целевого сервиса. Убедитесь, что job в Prometheus активен. |
| **False positive: алерт сработал без хаоса** | Сезонный пик или соседний эксперимент | Добавьте `without (instance)` агрегацию, настройте `for:` длительность. Используйте `offset` для сравнения с baseline. |
| **Burn Rate всегда 0** | SLO слишком мягкий или метрика 5xx отсутствует | Проверьте, что `http_requests_total` имеет label `status`. Убедитесь в правильности порога SLO. |
| **Latency p99 скачет без хаоса** | GC pause или cold start | Добавьте `jitter` к baseline, используйте `avg_over_time()` вместо `rate()` для сглаживания. |
| **Error Budget расходуется слишком быстро** | SLO нереалистично низкий или реальная деградация | Пересмотрите SLO. Если деградация реальная — эксперимент корректен, остановите его и разберитесь с проблемой. |
| **Steady State смещается во время эксперимента** | Наличие другого трафика (боты, фоновые задания) | Изолируйте трафик эксперимента (separate path или label). Используйте `sum without (job)` для фильтрации. |
| **Метрики не собираются** | Exporter не настроен или метрики неэкспортируются | Проверьте JMX exporter (Java), pg_stat_statements (PostgreSQL), custom metrics (App). |
| **PromQL возвращает no data** | Интервал сбора слишком большой | Уменьшите `scrape_interval` в Prometheus. Для коротких экспериментов используйте `[1m]` вместо `[5m]`. |
| **Эксперимент не останавливается автоматически** | Stop-switch не настроен или пороги слишком мягкие | Настройте Alertmanager правила с `for:` и severity. Проверьте, что chaos платформа интегрирована с алертингом. |
| **Probe показывает FAIL без причины** | Таймаут probe слишком короткий | Увеличьте `probeTimeout` и `retry` в конфигурации пробы. Проверьте доступность эндпоинта из сети probe. |

## Лучшие практики

### Pre-experiment checks

1.  **Валидируйте Observability ДО эксперимента** — если мониторинг не видит сбой, эксперимент бессмысленен. Проверьте алерты, дашборды, trace coverage.
2.  **Определите stop-switch заранее** — автоматическая остановка по метрикам, а не по таймауту. Таймаут — fallback, а не основной механизм.
3.  **Создайте runbook** — цель, гипотеза, blast radius, baseline метрики, критерии успеха, критерии остановки, контакты ответственных.
4.  **Проверьте blast radius** — убедитесь, что эксперимент затрагивает только целевые ресурсы. Проверьте label selectors, namespace, mode (one vs all).
5.  **Синхронизируйте с DR-планом** — если у вас есть сценарии Disaster Recovery, хаос-эксперименты должны их покрывать (failover БД, восстановление кеша).

### Выполнение экспериментов

6.  **Начинайте с минимального blast radius** — 1% трафика или один под. Никогда не применяйте `mode: all` в production без проверки.
7.  **Используйте probes** — проверяйте steady state во время эксперимента. Без probes эксперимент — не научный метод.
8.  **Сравнивайте с baseline, а не с абсолютными порогами** — 100ms latency приемлемы для одного сервиса и неприемлемы для другого.
9.  **Коррелируйте метрики во времени** — latency spike + error rate spike + saturation spike = деградация. Одиночный спред — возможно, шум.
10. **Учитывайте seasonality** — исключайте из baseline дни распродаж, релизов и патч-вторников.

### Автоматизация и governance

11. **Интегрируйте в CI-CD pipeline** — каждый Pull Request должен проходить минимальный хаос-тест в Staging.
12. **Проводите Game Days** — минимум 1 раз в квартал. Это не только техническая проверка, но и тренировка команды.
13. **Используйте Resilience as Code** — хаос-эксперименты хранятся в Git рядом с манифестами приложения. Процесс review обязателен.
14. **Фиксируйте метрики после эксперимента** — MTTD, MTTR, Time to Signal, blast radius фактический. Это данные для улучшения следующих экспериментов.
15. **Анализируйте production incidents** — каждый production incident — это готовый сценарий для хаос-эксперимента. Воспроизведите отказ в контролируемых условиях.

### Избегайте ошибок

16. **Не полагайтесь на одну метрику** — если latency выросла, но error rate и traffic стабильны, это может быть planned maintenance, а не деградация.
17. **Не игнорируйте L2/L3 при положительных L0/L1** — бизнес-метрики могут не упасть, если кэш работает, а база данных уже мертва.
18. **Не забывайте про retry storm** — error rate может выглядеть нормальной, если клиент ретраит. Смотрите RPS вместе с error rate.
19. **Не используйте average latency** — среднее скрывает хвосты. Используйте p99/p999.
20. **Не оставляйте эксперимент без cleanup** — после остановки убедитесь, что все CRD/политики удалены, метрики вернулись к baseline.

## Дополнительная информация

### Типичные ошибки интерпретации

- **Парадокс среднего:** Средняя задержка (average) остается в норме, но p99.9 вырастает в 10 раз. Хаос-инженерия всегда работает с «хвостами» распределения.
- **Retry Storm:** Метрика Error Rate может выглядеть стабильной, если клиент делает много попыток, но при этом резко растет RPS и задержка. Необходимо анализировать эти метрики в связке.
- **Маскировка сбоя кэшем:** Если при отключении БД сервис продолжает отдавать 200 OK из кэша, эксперимент может показаться успешным. Важно проверять `cache_hit_ratio` и `db_query_duration`.
- **Baseline drift:** Если baseline считается за 7 дней, а в этот период был релиз, то «норма» уже искажена. Пересчитывайте baseline после значимых изменений.

### Интеграция с DORA

Хаос-эксперименты напрямую влияют на метрики DORA:
- **Change Failure Rate (CFR):** Снижается за счет выявления багов конфигурации до деплоя в Prod.
- **MTTR:** Улучшается за счет отработки сценариев восстановления и настройки качественного алертинга.

### См. также

* [Концепция Chaos Monkey](chaos_monkey_concept.md) — классический паттерн случайных отказов.
* [Chaos Engineering — практическое руководство](chaos_engineering_practical.md) — Game Days, диагностика, runbook.
* [Инструменты Chaos Engineering](chaos_engineering_tools.md) — обзор Chaos Mesh, Litmus, Gremlin и Steadybit.
* [Chaos Engineering — тестирование resilience-паттернов](chaos_resilience_patterns_testing.md) — Circuit Breaker, Bulkhead, Rate Limiter.
* [Chaos Engineering — stateful-приложения](chaos_stateful_applications.md) — базы данных, Kafka, etcd под хаосом.
* [Chaos Engineering — service mesh](chaos_service_mesh.md) — Istio/Envoy fault injection и sidecar chaos.
* [Chaos Engineering — application-level chaos](chaos_application_level.md) — exception injection, thread pool exhaustion.
* [Chaos Engineering — advanced blast radius](chaos_advanced_blast_radius.md) — traffic mirroring, progressive rollout.
* [Chaos Engineering — observability](chaos_observability.md) — traces, logs, audit trail.
* [Chaos Engineering — maturity model](chaos_maturity_and_governance.md) — зрелость программы, governance, KPIs.
* [Chaos Engineering — CI/CD pipelines](chaos_cicd_pipelines.md) — интеграция хаоса в конвейер.
* [Chaos Engineering — non-Kubernetes](chaos_non_kubernetes.md) — VM, bare-metal, Docker chaos.
