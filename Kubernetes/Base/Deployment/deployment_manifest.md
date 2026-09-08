# Манифест Kubernetes Deployment и лучшие практики

Руководство по созданию отказоустойчивых, безопасных и масштабируемых манифестов для stateless-приложений: полный разбор полей объекта `Deployment`, шаблона пода и практические сценарии применения.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes с включенной стабильной API-группой `apps/v1` (v1.16+).
- Установленный и настроенный `kubectl` с правами на `get`, `apply`, `describe`, `annotate`, `rollout`.
- Манифесты, хранящиеся в системе контроля версий (Git) — обязательное условие воспроизводимости и отката.
- Базовое понимание объектов [Deployment](./index.md), [ReplicaSet](../replicaset.md) и [Pod](../Pod/pod_overview.md).
- Для продвинутой валидации: `kubeconform` или аналогичный линтер манифестов (см. [Kubeconform](../../ToolsUtilities/kubeconform_overview.md)).
- Для production-среды: настроенные [ResourceQuota/LimitRange](../../Scheduling/qos_limit_and_requests.md) и [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md).

## 1. Определения

**Манифест Deployment** — декларативное описание желаемого состояния приложения, включающее параметры запуска контейнеров, стратегии обновления, требования к ресурсам и правила размещения в кластере.

**Production-манифест** — манифест, отвечающий требованиям безопасности (Security Context, изоляция), надежности (resources, пробы, стратегии обновления) и наблюдаемости (стандартные метки, аннотации для сбора метрик).

Общее описание и концепции см. в основном разделе: **[Kubernetes Deployment](./index.md)**.

## 2. Базовые концепции

### Полная структура манифеста

Манифест `Deployment` состоит из четырех логических блоков:

```text
apiVersion: apps/v1            # стабильная API-группа
kind: Deployment
metadata                       # имя, namespace, labels, annotations
spec:
  replicas                     # целевое число подов
  selector                     # связь Deployment с подами (НЕИЗМЕНЯЕМ после создания)
  strategy                     # RollingUpdate (по умолчанию) или Recreate
  revisionHistoryLimit         # глубина истории ReplicaSets (по умолчанию 10)
  progressDeadlineSeconds      # таймаут rollout (по умолчанию 600с)
  minReadySeconds              # удержание пода в Ready перед признанием Available
  paused                       # пауза процесса обновления
  template:                    # шаблон пода (PodSpec): containers, volumes, securityContext...
status                         # только для чтения, генерируется контроллером
```

Изменение **любого** поля внутри `spec.template` создает новую ревизию и инициирует плавный перенос реплик (Rollout). Изменение полей уровня `spec` (например, `replicas`, `paused`) новой ревизии не создает.

### Эталонный Production-манифест

Пример манифеста, учитывающего требования безопасности, надежности и наблюдаемости:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-frontend
  namespace: production
  labels:
    app.kubernetes.io/name: frontend
    app.kubernetes.io/component: web
    app.kubernetes.io/part-of: my-project
  annotations:
    kubernetes.io/change-cause: "Начальная выкатка"
    prometheus.io/scrape: "true"
    prometheus.io/port: "8080"
    prometheus.io/path: "/metrics"
spec:
  replicas: 3
  revisionHistoryLimit: 5
  progressDeadlineSeconds: 600
  minReadySeconds: 10
  selector:
    matchLabels:
      app.kubernetes.io/name: frontend
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  template:
    metadata:
      labels:
        app.kubernetes.io/name: frontend
    spec:
      # Безопасность и управление доступом
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 2000
      automountServiceAccountToken: false

      # Планирование и приоритеты
      priorityClassName: production-high
      terminationGracePeriodSeconds: 60

      containers:
      - name: web-container
        image: my-registry.com/frontend:1.4.2 # Senior practice: конкретный тег
        imagePullPolicy: IfNotPresent

        ports:
        - name: http
          containerPort: 8080

        # Переменные окружения из ConfigMap и Secret
        envFrom:
        - configMapRef:
            name: app-config
        - secretRef:
            name: app-secrets

        # Ресурсы (обязательно requests == limits для памяти в критических сервисах)
        resources:
          requests:
            cpu: "250m"
            memory: "512Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"

        # Hardening контейнера (минимум привилегий)
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop: ["ALL"]

        # Письменные каталоги для read-only rootfs
        volumeMounts:
        - name: tmp
          mountPath: /tmp

        # Триада проб (Health Checks)
        startupProbe:
          httpGet:
            path: /healthz
            port: http
          failureThreshold: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: http
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /live
            port: http
          initialDelaySeconds: 15
          periodSeconds: 20

      volumes:
      - name: tmp
        emptyDir:
          sizeLimit: 50Mi
```

> Полный изолированный вариант с `seccompProfile`, `runAsGroup`, sidecar-логированием и projected-томами см. в [Лучшие практики манифестов Pod](../Pod/pod_best_practices.md).

### Ключевые поля объекта Deployment (spec)

| Поле | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `apiVersion: apps/v1` | Стабильная API-группа для Deployment (GA). | Всегда `apps/v1`. |
| `metadata.name` | Уникальное имя объекта в неймспейсе. | `kebab-case`, без точек в конце. |
| `metadata.namespace` | Неймспейс размещения. | Задавайте явно, не полагайтесь на `default`. |
| `spec.replicas` | Целевое количество подов (по умолчанию 1). | Минимум 2 для исключения простоев при eviction узлов. При масштабировании ревизия не создается. |
| `spec.selector` | Связь Deployment с подами (`matchLabels`, `matchExpressions`). | **Неизменяем** после создания. Метки в `template` обязаны его удовлетворять. |
| `spec.template` | Шаблон пода. | Любое изменение внутри — новая ревизия (Rollout). |
| `spec.strategy` | Тип обновления: `RollingUpdate` или `Recreate`. | `RollingUpdate` — стандарт; `Recreate` — только когда версии кода не могут работать одновременно (миграции схем БД). |
| `spec.revisionHistoryLimit` | Сколько старых ReplicaSet хранить для отката (по умолчанию 10). | 3–5 достаточно для отката. Большие значения нагружают `etcd`. |
| `spec.progressDeadlineSeconds` | Таймаут на прогресс rollout (по умолчанию 600с). | Не снижайте без причины — при «горячих» релизах. |
| `spec.minReadySeconds` | Время удержания пода в `Ready` до признания его `Available`. | 30–60 для сервисов с медленным «прогревом» (Java, кеши). |
| `spec.paused` | Пауза процесса обновления. | Полезно при внесении пачки изменений, чтобы не плодить промежуточные ревизии. |

### Ключевые поля шаблона пода (Pod Spec)

| Поле | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `priorityClassName` | Определяет важность пода при нехватке ресурсов. | Используйте для критических сервисов, чтобы предотвратить их вытеснение. |
| `image` | Образ контейнера. | Конкретный тег (`1.4.2`) или `sha256:...`. Запрещен `:latest`. |
| `imagePullPolicy` | Правило скачивания образа. | `IfNotPresent` для экономии трафика. `Always` — только если вы используете мутабельные теги (антипаттерн). По умолчанию: `Always` для тега `latest`/без тега, иначе `IfNotPresent`. |
| `ports` | Сетевые порты контейнера. | Именованные порты (`name: http`) — на них можно ссылаться в пробах и Service. |
| `resources` | `requests` (гарантия планировщика) и `limits` (потолок). | Всегда задавайте. Для памяти в критических сервисах `requests == limits` (класс QoS **Guaranteed**). См. [QoS и управление ресурсами](../../Scheduling/qos_limit_and_requests.md). |
| `securityContext` | Права и изоляция процесса (уровень пода и контейнера). | `runAsNonRoot: true`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: ["ALL"]`. См. [Security Context](../../Security/pod_security_context.md). |
| `automountServiceAccountToken` | Автомонтирование токена доступа к API. | `false`, если приложению не нужен доступ к Kubernetes API (защита от атак). |
| `terminationGracePeriodSeconds` | Время на завершение работы (SIGTERM). | По умолчанию 30с. Увеличивайте для тяжелых приложений (DB, Java) для чистого закрытия соединений. Должен покрывать `preStop` + дренаж. |
| `restartPolicy` | Политика перезапуска контейнеров. | Для Deployment допустимо **только** `Always` (значение по умолчанию). |
| `containers[].name` | Имя контейнера в поде. | Уникальное в пределах пода, обязательное поле. |
| `startupProbe` | Проверка успешного старта (отключает до готовности liveness/readiness). | Обязательна для приложений со стартом > 10с. Подробности в [Пробы](../probes.md). |
| `readinessProbe` | Готовность принимать трафик (включение в Endpoints). | Обязательна для корректного RollingUpdate. Предпочитайте `httpGet` с отдельным эндпоинтом, а не TCP. См. [Пробы](../probes.md). |
| `livenessProbe` | Жизнеспособность процесса (перезапуск при зависании). | Не должна проверять внешние зависимости (БД). См. [Пробы](../probes.md). |
| `envFrom` / `env` | Переменные окружения из ConfigMap/Secret или inline. | `envFrom` — массовое подключение; `env.valueFrom` — точечное. Секреты предпочтительно монтировать томами, а не передавать через env. |
| `volumeMounts` / `volumes` | Тома (ConfigMap, Secret, emptyDir, projected). | Для `readOnlyRootFilesystem` монтируйте `emptyDir` в `/tmp` и другие письменные каталоги. |
| `initContainers` | Этап подготовки перед основным контейнером. | Используйте для миграций БД, ожидания зависимостей, генерации конфигурации. |
| `lifecycle.preStop` | Hook перед завершением пода (SIGTERM). | `sleep` для дренажа соединений и компенсации задержки обновления Endpoints. |
| `nodeSelector` / `affinity` / `tolerations` | Правила размещения по узлам. | См. [Affinity и Anti-Affinity](../../Scheduling/affinity.md) и [Taints и Tolerations](../../Scheduling/taints_and_tolerations.md). |

### Метаданные, метки и аннотации

Использование стандартных меток (`app.kubernetes.io/*`) позволяет инструментам мониторинга (Prometheus) и визуализации (Lens, Dashboard) корректно группировать ресурсы.

Минимальный набор меток (рекомендация SIG-Apps):

```yaml
labels:
  app.kubernetes.io/name: frontend      # имя приложения
  app.kubernetes.io/version: "1.4.2"    # версия образа
  app.kubernetes.io/component: web      # роль в архитектуре
  app.kubernetes.io/part-of: my-project # общий проект
```

**Полезные аннотации:**
- `kubernetes.io/change-cause` — краткое описание причины изменения (отображается в `kubectl rollout history`).
- `prometheus.io/scrape: "true"`, `prometheus.io/port`, `prometheus.io/path` — автоматический сбор метрик.
- `deployment.kubernetes.io/revision` — номер текущей ревизии (управляется контроллером, только чтение).
- Хеш конфигурации (например, `configmap-hash`), если вы хотите автоматически перезапускать поды при изменении ConfigMap.

### Конфигурация приложения: ConfigMap и Secret

Способы подключения конфигурации в Deployment:

1. **Массово через `envFrom`** (все ключи объекта становятся переменными окружения):

```yaml
envFrom:
- configMapRef:
    name: app-config
- secretRef:
    name: app-secrets
```

2. **Точечно через `env.valueFrom`** (конкретный ключ в переменную):

```yaml
env:
- name: LOG_LEVEL
  valueFrom:
    configMapKeyRef:
      name: app-config
      key: log-level
- name: DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: app-secrets
      key: db-password
```

3. **Томами** (для файлов конфигурации, доверенных сертификатов):

```yaml
volumeMounts:
- name: app-config-volume
  mountPath: /etc/app
  readOnly: true
volumes:
- name: app-config-volume
  configMap:
    name: app-config
```

**Критическое отличие от Docker Compose:** изменение содержимого ConfigMap/Secret **не инициирует Rollout** — поды продолжат работать со старой конфигурацией. Для принудительного применения изменений используйте `kubectl rollout restart deployment/<name>` или аннотацию-хеш конфигурации в шаблоне (последнее автоматически создает новую ревизию при изменении ConfigMap).

> Антипаттерн — секреты в `env` из манифеста (видимы через `kubectl describe`). Управление секретами см. в [Sealed Secrets](../../Security/sealed_secrets_overview.md).

## 3. Практические сценарии

### Валидация манифеста перед применением

Проверка манифеста — обязательный шаг перед деплоем:

```bash
# 1. Синтаксическая проверка (клиентская, без обращения к кластеру)
kubectl apply -f deployment.yaml --dry-run=client
# → deployment.apps/my-app created (dry run)

# 2. Серверная валидация (полная проверка схемы и admission-контроллеров)
kubectl apply -f deployment.yaml --dry-run=server
# → deployment.apps/my-app created (server dry run)

# 3. Разница между желаемым и фактическим состоянием (обертка над server dry-run)
kubectl diff -f deployment.yaml
# → +/- строки отличий от текущего объекта

# 4. Валидация схемы без кластера (в CI/CD, не зависит от доступа)
kubeconform -strict -summary deployment.yaml
# → deployment.yaml - OK
```

Пояснения:
- `--dry-run=client` — только локальный разбор YAML; не ловит ошибки схемы.
- `--dry-run=server` — отправляет объект в admission-цепочку без сохранения; ловит невалидные поля и нарушения политик (PSA, Kyverno).
- `kubeconform` — офлайн-валидация по JSON-схемам; подходит для конвейеров без доступа к кластеру. Подробнее: [Kubeconform](../../ToolsUtilities/kubeconform_overview.md).

### Применение манифеста и управление образом

```bash
# Применение (декларативное, идемпотентное)
kubectl apply -f deployment.yaml
# → deployment.apps/my-app created

# Зафиксировать причину изменения (заменяет устаревший флаг --record)
kubectl annotate deployment/my-app kubernetes.io/change-cause="Обновление до 1.4.2: CVE-2026-xxx"
# → deployment.apps/my-app annotated

# Обновление образа с сохранением причины
kubectl set image deployment/my-app web-container=my-registry.com/frontend:1.4.3
kubectl annotate deployment/my-app kubernetes.io/change-cause="1.4.3: фикс бага N"
kubectl rollout status deployment/my-app
# → deployment "my-app" successfully rolled out

# Высокоуровневая валидация результата
kubectl get deploy my-app
# → NAME      READY   UP-TO-DATE   AVAILABLE   AGE
# → my-app    3/3     3            3           5m
```

Для массовых однотипных правок (например, версия во всех манифестах) используйте Kustomize/Helm — см. [Kustomize](../../ToolsUtilities/kustomize/kustomize_overview.md).

### Равномерное распределение (Topology Spread Constraints)

Для обеспечения высокой доступности (HA) на уровне дата-центров используйте распределение по зонам:

```yaml
spec:
  template:
    spec:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: "topology.kubernetes.io/zone"
        whenUnsatisfiable: DoNotSchedule # Жесткое ограничение
        labelSelector:
          matchLabels:
            app.kubernetes.io/name: frontend
```

- `maxSkew: 1` — допустимая разница в количестве подов между зонами не более 1.
- `topologyKey` — диапазон распределения: `kubernetes.io/hostname` (по узлам) или `topology.kubernetes.io/zone` (по зонам).
- `whenUnsatisfiable: DoNotSchedule` запрещает планирование, если ограничение невыполнимо; `ScheduleAnyway` — «мягкий» режим.

Подробное сравнение с `podAntiAffinity` и операторы — в [Affinity и Anti-Affinity](../../Scheduling/affinity.md).

### Контроль размещения (Node Affinity, Taints и Tolerations)

```yaml
spec:
  template:
    spec:
      nodeSelector:            # только узлы с такой меткой
        disktype: ssd
      tolerations:             # разрешение на узлы с taint
      - key: "dedicated"
        operator: "Equal"
        value: "gpu"
        effect: "NoSchedule"
      affinity:
        podAntiAffinity:       # не размещать поды этого приложения на одном узле
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchLabels:
                  app.kubernetes.io/name: frontend
              topologyKey: kubernetes.io/hostname
```

`nodeAffinity` дает больше выразительности, чем `nodeSelector` (операторы `In`, `NotIn`, `Exists` и т.д.). Для критических сервисов предпочтителен `podAntiAffinity` или `topologySpreadConstraints` вместо раздувания одного узла. Детали — в [Affinity](../../Scheduling/affinity.md) и [Taints/Tolerations](../../Scheduling/taints_and_tolerations.md).

### Тонкая настройка RollingUpdate

| Конфигурация | Результат | Кейс использования |
| :--- | :--- | :--- |
| `maxUnavailable: 0`, `maxSurge: 1` | Сначала +1 новый, потом -1 старый. | **Стандарт.** Гарантирует 100% доступность во время обновления. |
| `maxUnavailable: 25%`, `maxSurge: 0` | Сначала -25% старых, потом +25% новых. | Экономия ресурсов в кластере за счет временной деградации мощности. |
| `maxUnavailable: 25%`, `maxSurge: 25%` | Параллельный обмен «старый → новый» по 25%. | Значения по умолчанию; сбалансированная скорость и безопасность. |

Правила расчета:
- Допустимы абсолютные числа и проценты; при использовании процентов значения округляются вверх для `maxSurge` и вниз для `maxUnavailable`.
- `maxSurge` требует свободных ресурсов в кластере (взаимодействие с ResourceQuota — см. [Ограничения и особенности](#ограничения-и-особенности-edge-cases)).
- `maxUnavailable: 100%` семантически эквивалентно стратегии `Recreate`.

### initContainers: миграции и подготовка данных

Этап подготовки выполняется до запуска основного контейнера и идеально подходит для миграций БД:

```yaml
initContainers:
- name: run-migrations
  image: my-registry.com/migrator:1.4.2
  command: ["/bin/migrate", "-f", "/migrations"]
  envFrom:
  - configMapRef:
      name: app-config
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
  resources:
    requests: { cpu: "100m", memory: "128Mi" }
    limits: { cpu: "200m", memory: "256Mi" }
```

- Под не получит статус `Running`, пока все `initContainers` не завершатся успешно. Поэтому пробы основного контейнера не сработают преждевременно.
- Для миграций с гонкой нескольких реплик предусмотрите блокировки (lock/advisory lock) или выполняйте миграции отдельным Job — иначе параллельные реплики применят миграцию одновременно.
- Sidecar-контейнеры (v1.29+): `initContainers` с `restartPolicy: Always` для агентов логирования/прокси. См. [Native Sidecar](../Pod/pod_sidecar_patterns.md).

### Чистое завершение (Graceful Termination) и preStop

Последовательность штатного завершения пода при обновлении:

1. API-сервер помечает под как `Terminating` и удаляет его IP из Endpoints сервиса.
2. Запускается `preStop` (если задан).
3. Основному процессу контейнера отправляется `SIGTERM`.
4. По истечении `terminationGracePeriodSeconds` — `SIGKILL`.

```yaml
spec:
  terminationGracePeriodSeconds: 60
  containers:
  - name: web-container
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 10"]
```

`preStop sleep` компенсирует время распространения обновления Endpoints по сети (в kube-proxy и Ingress) и предотвращает 5xx на «полумертвый» под. Подробный разбор механизма — в [Graceful Shutdown](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md).

### Взаимодействие HPA и Deployment

- HPA масштабирует объект `Deployment`, изменяя `spec.replicas`. Масштабирование не создает ревизию.
- Настраивайте HPA на **Deployment**, не на ReplicaSet, иначе во время Rollout он может масштабировать неактивный старый RS.
- Учитывайте сочетание HPA с `maxUnavailable: 0`: при нехватке узлов HPA и RollingUpdate конкурируют за ресурсы.

Подробности — в [HPA](../../Autoscaling/HPA/index.md).

## 4. Дополнительная информация

### Лучшие практики (Best Practices)

1.  **Принцип неизменяемости (Immutability):**
    - Запрещено использовать `:latest`. Это делает деплой невоспроизводимым и ломает механизм отката.
    - Используйте хеши образов (`sha256:...`) для максимальной безопасности в критических средах.
2.  **Resources (QoS):**
    - Всегда указывайте `requests` и `limits`.
    - Для памяти рекомендуется устанавливать `requests == limits` (класс **Guaranteed**), чтобы защитить приложение от OOMKiller при фрагментации памяти на узле. См. [Управление ресурсами](../../Scheduling/qos_limit_and_requests.md).
3.  **Безопасность (Security by Design):**
    - `readOnlyRootFilesystem: true` — защищает от изменения кода в контейнере (при этом монтируйте `emptyDir` для `/tmp`).
    - `runAsNonRoot: true` и `allowPrivilegeEscalation: false` — обязательные требования для всех production-нагрузок.
    - `capabilities: drop: ["ALL"]` и `seccompProfile: RuntimeDefault` закрывают вектор эскалации привилегий. См. [Pod Security Context](../../Security/pod_security_context.md).
4.  **Graceful Termination:**
    - Приложение должно корректно обрабатывать сигнал `SIGTERM`.
    - Используйте `preStop` хуки, если приложение не умеет завершаться само (например, для плавного вывода из Nginx upstream).
5.  **Аффинити и распределение:**
    - Используйте `podAntiAffinity` или `topologySpreadConstraints`, чтобы поды одного сервиса не оказывались на одном узле (избегание Single Point of Failure). См. [Affinity и Anti-Affinity](../../Scheduling/affinity.md).
    - Для защиты от плановых обслуживаний узлов создавайте [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md).
6.  **Валидация в CI/CD:**
    - Перед merge/pr запускайте `kubeconform` или `--dry-run=server`. Это отсекает ошибки схемы до применения.
    - Используйте `kubectl diff` для контроля изменений перед production-деплоем.
7.  **Триада проб:**
    - `readinessProbe` обязательна — без нее RollingUpdate удаляет старые поды до готовности новых.
    - `startupProbe` — для приложений со стартом > 10с, чтобы не раздувать `initialDelaySeconds`.
    - `livenessProbe` не должна проверять внешние зависимости. См. [Пробы](../probes.md).
8.  **minReadySeconds:**
    - Устанавливайте 30–60 для выявления ошибок, возникающих не сразу после старта (прогрев кешей, ленивая инициализация).
9.  **Документирование изменений:**
    - Всегда заполняйте аннотацию `kubernetes.io/change-cause` — она видна в `kubectl rollout history deployment/<name>`.
10. **Минимальная история:**
    - `revisionHistoryLimit: 3–5` вместо дефолтных 10 снижает нагрузку на `etcd`.

### Ограничения и особенности (Edge Cases)

1. **Неизменяемость селектора:** Поле `spec.selector` нельзя изменить после создания Deployment. Для замены селектора пересоздайте объект (`kubectl delete` → `kubectl apply`), предварительно проверив, что поды не удаляются напрасно.
2. **`restartPolicy` не `Always`:** Для Deployment допустимо только `Always`. Попытка задать `OnFailure` или `Never` будет отклонена валидацией API.
3. **Изменение ConfigMap/Secret не инициирует Rollout:** Поды продолжат работать со старой конфигурацией. Используйте `kubectl rollout restart` или аннотацию-хеш конфигурации.
4. **`replicas: 0`:** Обновление шаблона при нуле реплик не инициирует создание подов — rollout «завершится» сразу. Для временной остановки это ожидаемо, для выкатки — нет.
5. **`maxSurge` и ResourceQuota:** Всплеск новых подов может временно превысить квоту неймспейса, и обновление застрянет. Проверяйте `kubectl describe quota -n <namespace>`.
6. **`maxUnavailable: 0` при нехватке ресурсов:** Контроллер не удалит старые поды, пока новые не получат ресурсы. Планируйте запас мощности кластера.
7. **Процентные значения `maxSurge`/`maxUnavailable`:** Округляются вверх (`maxSurge`) и вниз (`maxUnavailable`). При малом числе реплик явные числа предсказуемее процентов.
8. **Долгий старт без `startupProbe`:** `livenessProbe` будет убивать под до готовности (цикл `CrashLoopBackOff`). Всегда давайте приложению окно на старт.
9. **`paused: true` и `progressDeadlineSeconds`:** Пока rollout на паузе, таймер прогресса не «тикает»; при возобновлении отсчет продолжается. Не забудьте `resume`.
10. **HPA при Rollout:** При масштабировании во время обновления HPA управляет `replicas` Deployment целиком — следите, чтобы autoscaler не «съедал» мощность, выделенную под `maxSurge`.

### Диагностика и Troubleshooting

Быстрые проверки уровня манифеста:

```bash
# Применение зависло — условия объекта
kubectl describe deployment my-app | grep -A5 Conditions

# Поды не стартуют (ImagePullBackOff / CrashLoopBackOff)
kubectl get pods -l app.kubernetes.io/name=frontend
kubectl logs <pod> --previous

# Изменение ConfigMap не подхватилось — принудительный перезапуск
kubectl rollout restart deployment/my-app
```

Полный алгоритм диагностики зависших обновлений, разбор `maxSurge`/`maxUnavailable` и реальные кейсы сбоев — в **[Устранение неполадок Deployment](./troubleshooting.md)**.

### См. также

- [Обзор Deployment](./index.md) — концепции контроллера и управление состоянием.
- [Управление жизненным циклом Deployment](./lifecycle_management.md) — ревизии, откат, пауза и возобновление.
- [Пробы в Kubernetes](../probes.md) — детальная настройка триады проверок.