# Chaos Engineering: Обзор

## Определения

**Chaos Engineering (Хаос-инженерия)** — это дисциплина, основанная на проведении контролируемых экспериментов в распределенных системах для формирования уверенности в их способности выдерживать турбулентные условия в промышленной эксплуатации.

В отличие от классического тестирования, хаос-инженерия рассматривает систему как живой организм с высокой степенью неопределенности. Цель дисциплины — не подтверждение корректности логики, а опровергнуть гипотезу об устойчивости и выявить скрытые системные дефекты (например, каскадные сбои, некорректные таймауты, ошибки конфигурации) до того, как они приведут к реальному инциденту.

### Хаос-инженерия vs Fault Injection

| Аспект | Fault Injection (Инъекция сбоев) | Chaos Engineering (Хаос-инженерия) |
|:---|:---|:---|
| **Подход** | Тестирование конкретного условия (например, диск полон). | Эксперимент над системой в целом для поиска неизвестных уязвимостей. |
| **Цель** | Проверить конкретный механизм защиты. | Сформировать уверенность в устойчивом состоянии (Steady State). |
| **Масштаб** | Часто ограничивается одним компонентом. | Фокусируется на взаимодействии распределенных узлов. |

## Основные концепции

### Ключевые принципы хаоса

1.  **Формирование гипотезы об устойчивом состоянии (Steady State):** Определение измеримых показателей (SLI), которые описывают нормальное поведение системы. В 2026 году акцент сместился с системных метрик (CPU/RAM) на бизнес-метрики (количество успешных транзакций в секунду).
2.  **Варьирование событий реального мира:** Симуляция событий с учетом вероятности их возникновения: отказ ЦОД, потеря пакетов в межоблачном соединении, аномальные скачки трафика.
3.  **Эксперименты в продакшене:** Распределенные системы ведут себя непредсказуемо под нагрузкой. Тестирование в Staging полезно для базовой проверки, но только Production дает истинную уверенность.
4.  **Автоматизация:** Интеграция в CI/CD и использование «хаос-платформ» для регулярного проведения тестов без участия человека.
5.  **Ограничение радиуса поражения (Blast Radius):** Жесткий контроль области воздействия. Эксперимент должен затрагивать минимально возможное количество пользователей и немедленно прекращаться при нарушении SLO.

### Механизмы повышения устойчивости

*   **Выявление скрытых зависимостей:** Инъекция задержек (Latency Injection) вскрывает синхронные вызовы в цепочках микросервисов, которые должны были быть асинхронными.
*   **Валидация механизмов защиты:** Проверка работоспособности паттернов Circuit Breaker, Bulkhead, Retry policies и Fallback-логики.
*   **Калибровка наблюдаемости (Observability):** Проверка того, что система мониторинга (Prometheus, OpenTelemetry) видит сбой, а алертинг уведомляет команду вовремя.
*   **Resilience Engineering:** Хаос-инженерия является инструментом для достижения Resilience — способности системы адаптироваться к изменениям и поглощать сбои без потери функциональности.

## Практические сценарии

### Модель зрелости хаоса (Chaos Maturity Model)

Путь внедрения дисциплины в компании обычно проходит через три этапа:
1.  **Начальный (Manual & Staging):** Ручное выключение подов в тестовой среде. Проверка базовых сценариев.
2.  **Продвинутый (Automated & Guardrails):** Автоматизация через Chaos Mesh/Litmus. Внедрение автоматических Stop-switches (аварийных остановок) на основе метрик Prometheus.
3.  **Экспертный (Continuous Production Chaos):** Постоянные эксперименты в продакшене под реальной нагрузкой. Использование AI для генерации новых гипотез на основе топологии системы.

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

## Дополнительная информация

### Сравнение: Тестирование vs Хаос-инженерия

| Характеристика | Классическое тестирование (QA) | Хаос-инженерия (SRE) |
|:---|:---|:---|
| **Предмет** | Проверка бизнес-логики и контрактов. | Проверка системных свойств и устойчивости. |
| **Цель** | Подтвердить, что система работает «как задумано». | Найти ситуации, когда система ведет себя «неожиданно». |
| **Среда** | Staging / Pre-prod. | Продакшен (целевое состояние). |
| **Результат** | Исправление багов в коде. | Устранение архитектурных рисков и улучшение мониторинга. |

### Учения Game Days

**Game Days** — это формализованные командные тренировки по реагированию на сбои. 

*   **Участники:** Разработчики, SRE, DevOps, иногда представители бизнеса.
*   **Роли:** «Мастер Хаоса» (планирует и вносит сбой), «Исполнители» (диагностируют и восстанавливают).
*   **Фокус:** Не только техническое решение, но и «мышечная память» команды: насколько быстро поняли проблему, сработал ли алертинг, актуален ли Runbook.

### См. также

* [Концепция Chaos Monkey](chaos_monkey_concept.md) — классический паттерн случайных отказов.
* [Метрики в Chaos Engineering](chaos_engineering_metrics.md) — как измерять Steady State и Blast Radius.
* [Инструменты Chaos Engineering](chaos_engineering_tools.md) — обзор Chaos Mesh, Litmus, Gremlin и Steadybit.
* [SRE: SLA, SLO, SLI и метрики надежности](../Concepts/sre_concepts_main.md) — фундамент для гипотез.
* [Управление трафиком в Service Mesh](../Service_Mesh/traffic_management.md) — механизмы Fault Injection на уровне L7.

---

## Хаос-тестирование Gateway API

### Сценарий 1: Падение Control Plane

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

### Сценарий 2: Падение Data Plane Pod

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

### Сценарий 3: Сетевая задержка к бэкендам

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
- HTTPRoute с retry política автоматически повторяет запросы
- Circuit Breaker не срабатывает при малой доле задержек
- Error rate не превышает SLO

### Сценарий 4: Потеря пакетов

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

### Сценарий 5: Падение DNS

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

### Практические инструменты для chaos-тестирования Gateway API

| Инструмент | Тип сценария | Преимущество |
|:---|:---|:---|
| **Chaos Mesh** | Pod kill, Network delay/loss | natively поддерживает label selectors |
| **Litmus Chaos** | Pod delete, DNS failure | Простые манифесты, быстрый старт |
| **Toxiproxy** | TCP proxy anomalies | Точная инъекция сбоев на уровне TCP |
| **k6** | Нагрузка + chaos | Комбинирование нагрузки и сбоев |

### Автоматизация chaos-тестирования

```yaml
# GitHub Actions workflow для chaos-тестирования Gateway API
name: Gateway API Chaos Tests

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
