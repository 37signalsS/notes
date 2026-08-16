# Канареечное развертывание (Canary Deployment)

## Определения

**Канареечное развертывание (Canary Deployment)** — стратегия выпуска, при которой новая версия приложения (**Canary**) выкатывается для небольшой контролируемой группы пользователей или доли трафика, в то время как основная масса продолжает использовать стабильную версию (**Stable** / **Baseline**). Подход позволяет оценить влияние изменений в реальных условиях и минимизировать «радиус поражения» (blast radius) при обнаружении багов перед полным развертыванием.

- **Радиус поражения (Blast Radius)** — объем потенциального негативного воздействия на систему или пользователей в случае сбоя. Canary минимизирует этот показатель.
- **Прогрессивная поставка (Progressive Delivery)** — методология, развивающая Continuous Delivery, которая включает Canary-релизы и автоматизированное управление трафиком на основе метрик.
- **Анализ канарейки (Canary Analysis)** — процесс автоматического сравнения метрик новой версии с эталонной (Baseline) для принятия решения о продвижении или откате.
- **Гейтинг (Gating)** — механизм блокировки или разрешения перехода на следующий этап раскатки на основе результатов анализа.

## Основные концепции

### Цели и предпосылки

**Основная цель:** Снижение риска инцидентов путем раннего обнаружения технических и бизнес-регрессий на малой доле реального трафика.

**Принципы:**
- **Минимальное воздействие:** Новая версия сначала доступна лишь 1–5% пользователей.
- **Реальный трафик:** Тестирование происходит в боевых условиях с настоящими запросами.
- **Постепенность:** Поэтапное увеличение нагрузки или откат при обнаружении аномалий.

**Ключевые предпосылки:**
- **Разделение трафика (Traffic Splitting)** — возможность точно направлять процент трафика или сегментировать его по атрибутам (headers, cookies).
- **Продвинутая наблюдаемость** — раздельный сбор метрик для разных версий для их прямого сравнения.
- **Автоматизированное управление** — наличие контроллеров, способных принимать решения об увеличении веса или откате на основе анализа данных.

### Архитектура и компоненты

Реализация Canary требует взаимодействия нескольких уровней инфраструктуры:
1.  **Уровень маршрутизации (Traffic Routing):** Компонент, способный разделять входящий поток запросов (L7 Load Balancer, Ingress, Gateway API или Service Mesh).
2.  **Уровень управления (Controller):** Оркестратор или оператор, который управляет жизненным циклом ревизий и изменяет веса в маршрутизаторе (например, Argo Rollouts, Flagger).
3.  **Уровень наблюдаемости (Observability):** Система сбора метрик (Prometheus), обеспечивающая разделение данных по версиям для анализа.
4.  **Уровень принятия решений (Analysis Engine):** Алгоритм или сервис, выполняющий статистическое сравнение метрик (Golden Signals) Stable vs Canary.

### Этапы и жизненный цикл

1.  **Подготовка (Baseline):** Рекомендуется запустить "контрольную группу" (Baseline) — инстанс старой версии в тех же условиях, что и Canary, для максимально точного сравнения метрик.
2.  **Развертывание (Canary Deploy):** Запуск Canary-версии с 0% трафика. Проверка готовности (Readiness Probes).
3.  **Начальный сегмент (Initial Rollout):** Направление малой доли (1–5%) трафика на новую версию.
4.  **Анализ (Analysis Phase):** Сравнение ключевых показателей здоровья (SRE Golden Signals) между Stable (или Baseline) и Canary.
5.  **Прогрессивная раскатка (Step-by-step Rollout):** Поэтапное увеличение доли трафика (10% → 25% → 50%) при отсутствии аномалий.
6.  **Финальное продвижение (Promotion):** Перевод 100% трафика на новую версию, которая теперь становится основной.
7.  **Очистка (Cleanup):** Удаление старой версии ресурсов и ReplicaSet.

### Требования к инфраструктуре и инструменты

Для реализации Canary недостаточно простого балансировщика, требуется интеллектуальное управление L7-трафиком:
- **Ingress-контроллеры:** NGINX Ingress (через аннотации `canary-*`), Traefik, Emissary-ingress.
- **Gateway API:** Современный стандарт Kubernetes (2026) для управления трафиком (`HTTPRoute` веса).
- **Service Mesh:** Istio, Linkerd (TrafficSplit), Consul Connect.
- **Контроллеры прогрессивной доставки:**
  - **Argo Rollouts** — заменяет стандартный Deployment на объект `Rollout`, управляющий стратегиями.
  - **Flagger** — оператор, использующий Service Mesh или Ingress для автоматизации Canary.

## Практические сценарии

### 1. Нативная реализация в Kubernetes (Standard)

В стандартном Kubernetes Canary реализуется через создание двух Deployment с общими метками для селектора одного Service. Распределение трафика в этом случае пропорционально количеству реплик.

1.  **Стабильная версия (90% трафика):**
    ```yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: app-stable
    spec:
      replicas: 9
      selector:
        matchLabels:
          app: my-app
      template:
        metadata:
          labels:
            app: my-app
            version: stable
        spec:
          containers:
          - name: app
            image: my-app:v5
    ```

2.  **Канареечная версия (10% трафика):**
    ```yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: app-canary
    spec:
      replicas: 1
      selector:
        matchLabels:
          app: my-app
      template:
        metadata:
          labels:
            app: my-app
            version: canary
        spec:
          containers:
          - name: app
            image: my-app:v6
    ```

3.  **Общий Service:**
    ```yaml
    apiVersion: v1
    kind: Service
    metadata:
      name: my-app-service
    spec:
      ports:
      - port: 80
      selector:
        app: my-app  # Выбирает поды обоих Deployment
    ```

**Управление трафиком:**
Распределение трафика можно динамически изменять, масштабируя количество реплик в каждом Deployment с помощью `kubectl`:
```bash
# Увеличение доли Canary до ~18% (2 из 11 подов)
kubectl scale deployment/app-canary --replicas=2
```

### 2. Реализация через Kubernetes Gateway API (Стандарт 2026)

Современный способ управления трафиком без использования проприетарных аннотаций. Используется ресурс `HTTPRoute`.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: shop-api
spec:
  parentRefs:
  - name: internal-gateway
  rules:
  - backendRefs:
    - name: shop-api-stable
      port: 8080
      weight: 90
    - name: shop-api-canary
      port: 8080
      weight: 10
```

### 3. Реализация через Istio (Service Mesh)

Istio позволяет управлять весами трафика на уровне виртуальной сети, не изменяя физическое количество реплик.

```yaml
# DestinationRule определяет подмножества на основе меток
apiVersion: networking.istio.io/v1alpha3
kind: DestinationRule
metadata:
  name: app-destination
spec:
  host: my-app-service
  subsets:
  - name: stable
    labels:
      version: stable
  - name: canary
    labels:
      version: canary

---
# VirtualService распределяет веса между подмножествами
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: app-virtualservice
spec:
  hosts:
  - my-app-service
  http:
  - route:
    - destination:
        host: my-app-service
        subset: stable
      weight: 90
    - destination:
        host: my-app-service
        subset: canary
      weight: 10
```

### 4. Автоматизация через Argo Rollouts

Декларативное описание шагов раскатки и анализа.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: payment-service
spec:
  replicas: 10
  strategy:
    canary:
      steps:
      - setWeight: 10
      - pause: {duration: 5m}
      - analysis:
          templates:
          - templateName: success-rate-check
      - setWeight: 50
      - pause: {duration: 10m}
```

### 5. Docker Swarm + Traefik

Реализация через взвешенные сервисы в Traefik.

```yaml
services:
  app-stable:
    image: my-app:v1
    deploy:
      labels:
        - "traefik.http.services.app.loadbalancer.weighted.services.app-stable.weight=90"

  app-canary:
    image: my-app:v2
    deploy:
      replicas: 1
      labels:
        - "traefik.http.services.app.loadbalancer.weighted.services.app-canary.weight=10"
```

### 6. Использование флагов функций (Feature Toggles)

Альтернатива на уровне приложения — управление логикой через [флаги функций](../Testing/feature_toggles/scenarios.md). Позволяет реализовать Canary для конкретных пользователей (например, по ID или региону) даже без поддержки на уровне сети.

## Автоматизация трафика в CI-пайплайнах (Push-метод)

В 2026 году, если не используются специализированные операторы (ArgoCD/Flagger), управление трафиком в Push-модели (например, через GitLab CI или GitHub Actions) реализуется путем императивного обновления манифестов управления трафиком (`VirtualService` в Istio или `HTTPRoute` в Gateway API/Cilium) напрямую из пайплайна.

### Логика взаимодействия пайплайна

1.  **Деплой Canary:** CI-пайплайн разворачивает новую версию Deployment (v2) с `replicas: 1`.
2.  **Инициализация весов:** Пайплайн устанавливает начальный вес (например, 5%) для v2 в ресурсе маршрутизации.
3.  **Итеративная раскатка:** Цикл в скрипте увеличивает вес с шагом N%, ожидая стабилизации метрик на каждой итерации.
4.  **Валидация (Gating):** Выполнение HTTP-запроса к API мониторинга (Prometheus) для проверки SRE Golden Signals.
5.  **Завершение:** Если 100% достигнуто — v2 становится Stable, старый Deployment удаляется.

### Практический пример: Использование kubectl patch

Для автоматизации без правки YAML-файлов в репозитории используется команда `kubectl patch`, которая позволяет изменять веса "на лету" прямо из CI-раннера.

#### Сценарий для Istio (VirtualService)
```bash
# Установка веса 20% для canary подмножества
kubectl patch virtualservice my-app --type=json -p='[
  {"op": "replace", "path": "/spec/http/0/route/0/weight", "value": 80},
  {"op": "replace", "path": "/spec/http/0/route/1/weight", "value": 20}
]'
```

#### Сценарий для Cilium / Gateway API (HTTPRoute)
```bash
# Установка веса 10% для новой версии (второй backendRef)
kubectl patch httproute shop-api --type=json -p='[
  {"op": "replace", "path": "/spec/rules/0/backendRefs/0/weight", "value": 90},
  {"op": "replace", "path": "/spec/rules/0/backendRefs/1/weight", "value": 10}
]'
```

### Пример bash-скрипта для пайплайна (Canary Loop)

Этот скрипт можно использовать в `step` пайплайна для постепенной раскатки с проверкой ошибок.

```bash
#!/bin/bash
set -e

APP_NAME="shop-api"
STEP=10
PAUSE=60 # секунд между шагами
MAX_ERROR_RATE=5 # % ошибок для отката

for weight in $(seq $STEP $STEP 100); do
  echo "--- Step: Canary Weight $weight% ---"
  
  # 1. Применяем веса (Gateway API / Cilium)
  kubectl patch httproute $APP_NAME --type=json -p="[
    {\"op\": \"replace\", \"path\": \"/spec/rules/0/backendRefs/0/weight\", \"value\": $((100 - weight))},
    {\"op\": \"replace\", \"path\": \"/spec/rules/0/backendRefs/1/weight\", \"value\": $weight}
  ]"

  if [ "$weight" -lt 100 ]; then
    echo "Waiting $PAUSE seconds for metrics collection..."
    sleep $PAUSE

    # 2. Проверка метрик через Prometheus API
    # Пример запроса: процент 5xx ошибок за последнюю минуту
    ERRORS=$(curl -s "http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~'5..',app='$APP_NAME-canary'}[1m]))/sum(rate(http_requests_total{app='$APP_NAME-canary'}[1m]))*100" | jq -r '.data.result[0].value[1]')
    
    if (( $(echo "$ERRORS > $MAX_ERROR_RATE" | bc -l) )); then
      echo "CRITICAL: Error rate is $ERRORS%. Rolling back to 0%!"
      kubectl patch httproute $APP_NAME --type=json -p='[{"op": "replace", "path": "/spec/rules/0/backendRefs/0/weight", "value": 100}, {"op": "replace", "path": "/spec/rules/0/backendRefs/1/weight", "value": 0}]'
      exit 1
    fi
  fi
done

echo "Canary deployment successful!"
```

### Особенности для Cilium
При использовании Cilium в качестве Service Mesh (через Gateway API), пайплайн взаимодействует с теми же ресурсами `HTTPRoute`. Cilium на базе eBPF обеспечивает мгновенное применение новых весов без перезагрузки прокси-серверов, что делает Push-модель очень отзывчивой.

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Недостаточно трафика для анализа** | Слишком малый процент Canary (1%) при низкой нагрузке. | Увеличить вес до 5–10% или продлить время анализа. |
| **Ложные срабатывания (False Positives)** | Сравнение Canary с общим пулом Stable, а не с Baseline. | Запустить Baseline-инстанс одновременно с Canary. |
| **"Отравление" данных (Data Poisoning)** | Canary пишет несовместимые данные в общую БД. | Использовать обратно-совместимые миграции (Expand-Contract). |
| **Sticky Session Issues** | Пользователи "прыгают" между версиями при ротации. | Использовать `Session Affinity` на уровне балансировщика. |
| **Лаг метрик (Metrics Lag)** | Prometheus собирает метрики раз в 60с, а анализ идет каждые 30с. | Согласовать интервал анализа с интервалом сбора метрик. |

## Дополнительная информация

### Мониторинг и корректировка

Поскольку при Canary-развертывании новая версия обрабатывает реальный пользовательский трафик (даже малую его часть), наличие надежного мониторинга является критическим условием.

-   **Инструменты:** Основной стек для наблюдения — **Prometheus** (сбор метрик), **Grafana** (визуализация) и нативные метрики Kubernetes.
-   **Процесс:**
    1.  **Наблюдение:** Отслеживание ошибок, задержек и потребления ресурсов сразу после подачи трафика на Canary.
    2.  **Анализ:** Сравнение показателей Canary с Baseline.
    3.  **Решение:** На основе данных принимается решение:
        *   **Scale-up:** Увеличение веса Canary (продвижение релиза).
        *   **Rollback:** Немедленный откат при обнаружении всплеска ошибок или деградации производительности.

Подробные примеры настройки и ключевые показатели описаны в разделе **[Мониторинг Kubernetes — обзор](../../Prometheus/kubernetes/overview.md)**.

### Анализ метрик и автоматическое принятие решений (Gating)

Ключевым элементом является **Analysis Stage** — автоматическая проверка метрик перед переходом к следующему шагу. Подробные примеры запросов описаны в [Мониторингу и оценке трафика при Canary](./canary_monitoring_and_gating.md).

**Критичные метрики:**
- **HTTP Error Rate** — рост 5xx ошибок.
- **Latency (p99)** — замедление ответов.
- **Resource Usage** — утечки памяти или аномальное потребление CPU на новой версии.

### Сравнение Canary и A/B тестирования

| Характеристика | Canary Deployment | A/B Testing |
| :--- | :--- | :--- |
| **Цель** | Техническая стабильность и безопасность | Проверка бизнес-гипотез и UX |
| **Аудитория** | Случайная доля трафика (или внутренние пользователи) | Специфические бизнес-сегменты |
| **Метрики** | Ошибки, задержки, потребление ресурсов | Конверсия, клики, время на странице |
| **Управление** | Обычно через инфраструктуру (L7 Routing) | Обычно через код или SaaS-платформы |

### Лучшие практики

- **Начинайте с малого:** 1%–2% трафика достаточно для выявления критических ошибок.
- **Определите Baseline:** Сравнивайте Canary не с абсолютными числами, а с текущим поведением Stable версии в тот же момент времени.
- **Graceful Shutdown:** Убедитесь, что приложение корректно завершает запросы при удалении подов.
- **Автоматизируйте откат:** Ручное вмешательство при сбое Canary нивелирует преимущества скорости; используйте автоматические пороги.
- **Проверка на "отравление" кэша:** Если Canary пишет в БД или кэш несовместимые данные, это может аффектить Stable версию.
- **Долгоживущие соединения:** Настраивайте `Connection Draining` для WebSocket и gRPC при переключении трафика.

### Рекомендованные ссылки

- [Мониторинг и оценка трафика при Canary](./canary_monitoring_and_gating.md) — детализация процесса анализа и PromQL примеры.
- [Управление трафиком в Service Mesh](../../Service_Mesh/traffic_management.md) — современные стандарты (Gateway API/GAMMA) для Canary.
- [Обзор стратегий развертывания](../Core_Concepts/deployment_strategies.md) — сравнение с Blue/Green и Rolling Update.
- [Сравнение стратегий развертывания](./comparison.md) — матрица выбора подходов.
- [Expand-Contract: миграции БД](../../Databases/Concepts/migrations/expand_contract.md) — обеспечение совместимости данных.
