# Лучшие практики написания манифестов Pod в Kubernetes

## Определения

**YAML** — человекочитаемый язык сериализации данных, являющийся стандартом де-факто для описания конфигураций в Kubernetes.

**Манифест** — декларативное описание желаемого состояния объекта. Манифесты позволяют реализовать подход **Infrastructure as Code (IaC)**, обеспечивая версионность и воспроизводимость инфраструктуры.

**Immutable tag** — фиксированная версия образа (например, `1.31.0` или SHA-хеш), которая гарантирует идентичность содержимого при каждом скачивании.

**Graceful Shutdown** — процесс корректного завершения работы приложения, при котором оно успевает обработать текущие запросы и закрыть соединения до принудительной остановки.

**Production Readiness (Готовность к продакшену)** — совокупность требований к конфигурации Pod, обеспечивающих безопасность, надежность, наблюдаемость и корректную работу в условиях реальной эксплуатации.

---

## Базовые концепции

### Декларативный подход и IaC

Всегда используйте YAML-манифесты вместо императивных команд (`kubectl run`, `kubectl expose`).

*   **Контроль версий:** Храните манифесты в Git для отслеживания изменений и возможности отката.
*   **Автоматизация:** Используйте CI/CD для применения изменений (`kubectl apply`).
*   **Валидация:** Проверяйте манифесты инструментами линтинга (например, `kube-linter` или `datree`) перед деплоем.

### Управление образами

1.  **Избегайте `:latest`:** Этот тег непредсказуем. Используйте конкретные версии (SemVer) или SHA-хеш образа.
2.  **ImagePullPolicy:** 
    *   Используйте `IfNotPresent` для фиксированных тегов в Production (ускоряет запуск и экономит трафик).
    *   Используйте `Always` для тега `:latest` (только в Dev/Stage).
3.  **Приватные реестры:** Всегда настраивайте `imagePullSecrets` для доступа к защищенным хранилищам образов.
4.  **Минимизация образа:** Используйте дистрибутивы на основе `scratch` или `distroless` для Production. Чем меньше образ, тем меньше поверхность атаки и быстрее запуск.

### Управление ресурсами и QoS

Явное указание ресурсов критично для стабильности кластера:

*   **Requests:** Минимальный гарантированный объем ресурсов. Используется планировщиком (Scheduler).
*   **Limits:** Максимальный порог потребления. Превышение лимита памяти ведет к `OOMKilled`.
*   **Sidecars:** Всегда указывайте ресурсы для вспомогательных контейнеров (логирование, прокси), чтобы они не вытеснили основное приложение.

**Выбор класса QoS:**

| Класс | Требование | Рекомендация по использованию |
| :--- | :--- | :--- |
| **Guaranteed** | `requests == limits` для CPU и памяти | Критические сервисы (БД, платежные системы). Защита от OOMKiller. |
| **Burstable** | `requests < limits` | Стандартные веб-приложения. Баланс между производительностью и экономией. |
| **BestEffort** | Не указаны requests и limits | Только Dev/Test. Первые в очереди на вытеснение. |

Подробнее о классах обслуживания см. в [QoS и управление ресурсами](../../Scheduling/qos_limit_and_requests.md).

### Проверки состояния (Probes)

1.  **livenessProbe:** Перезапускает контейнер при зависании процесса.
2.  **readinessProbe:** Управляет включением Pod в Service (маршрутизация трафика).
3.  **startupProbe:** Защищает медленно запускающиеся приложения от преждевременного убийства liveness-пробой.
4.  **Best Practice:** Используйте разные эндпоинты для разных проб (например, `/healthz` для liveness и `/ready` для readiness).

**Параметры проб для разных типов приложений:**

| Тип приложения | startupProbe | readinessProbe | livenessProbe |
| :--- | :--- | :--- | :--- |
| **Веб-сервер (Nginx, Go)** | `periodSeconds: 10`, `failureThreshold: 3` | `periodSeconds: 5`, `periodSeconds: 10` | `periodSeconds: 15`, `failureThreshold: 3` |
| **Java/JVM** | `periodSeconds: 10`, `failureThreshold: 30` | `periodSeconds: 10`, `periodSeconds: 5` | `periodSeconds: 20`, `failureThreshold: 3` |
| **База данных** | `periodSeconds: 10`, `failureThreshold: 30` | `periodSeconds: 10`, `periodSeconds: 5` | `periodSeconds: 30`, `failureThreshold: 5` |
| **Batch/job** | Не требуется | `exec` проверка завершения | `exec` проверка зависания |

Детальная настройка в [Пробы в Kubernetes](../probes.md).

### Безопасность (Security Context)

Применяйте принцип наименьших привилегий (Least Privilege) через `securityContext`:

*   **runAsNonRoot: true:** Запрещает запуск от суперпользователя.
*   **allowPrivilegeEscalation: false:** Блокирует повышение прав процессами.
*   **readOnlyRootFilesystem: true:** Делает ФС контейнера неизменяемой (используйте `emptyDir` для `/tmp`).
*   **capabilities: drop: ["ALL"]:** Отключает все потенциально опасные системные вызовы Linux.

**Минимальный безопасный securityContext для Production:**

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 3000
  fsGroup: 2000
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  seccompProfile:
    type: RuntimeDefault
  capabilities:
    drop: ["ALL"]
```

Параметры и профили PSA описаны в [Security Context в Kubernetes](../../Security/pod_security_context.md).

### Метаданные (Labels и Annotations)

*   **Labels (Метки):** Используйте для поиска и выбора объектов (Selectors). Применяйте стандартные метки (`app.kubernetes.io/name`, `app.kubernetes.io/version`).
*   **Annotations (Аннотации):** Используйте для хранения метаданных, не участвующих в выборе объектов (контакты, ссылки, конфигурации для Ingress).
*   **Best Practice:** Используйте аннотации для хранения хеша конфигурации — это позволяет автоматически перезапускать Pod при изменении ConfigMap.

**Стандартные метки (рекомендация SIG-Apps):**

```yaml
labels:
  app.kubernetes.io/name: my-app
  app.kubernetes.io/version: "1.31.0"
  app.kubernetes.io/component: web
  app.kubernetes.io/part-of: my-project
  app.kubernetes.io/managed-by: helm
```

См. подробнее: [Метаданные, метки и аннотации](../../Concepts/metadata_and_labels.md).

### Жизненный цикл и доступность

1.  **terminationGracePeriodSeconds:** Настраивайте под время завершения вашего приложения (по умолчанию 30с). Для БД может потребоваться 60-120с.
2.  **preStop Hook:** Используйте для подготовки к выключению (например, `sleep 5` для завершения обработки сетевых пакетов перед остановкой).
3.  **Pod Disruption Budget (PDB):** Всегда создавайте PDB для Production-нагрузок, чтобы гарантировать доступность при обслуживании узлов. Подробнее: [PDB в Kubernetes](../../Autoscaling/pod_disruption_budget.md).
4.  **Native Sidecars (v1.29+):** Оформляйте вспомогательные сервисы (прокси, агенты) как `initContainers` с `restartPolicy: Always`. Это гарантирует их готовность до старта приложения.
5.  **automountServiceAccountToken:** Устанавливайте `false`, если приложению не нужен доступ к Kubernetes API. Токен ServiceAccount — потенциальный вектор атаки.

**Время завершения для разных типов приложений:**

| Тип приложения | Рекомендуемое `terminationGracePeriodSeconds` | Причина |
| :--- | :--- | :--- |
| Stateless веб-сервер | 30–45 | Быстрое завершение соединений |
| Java/JVM приложение | 60–90 | Время на GC и завершение потоков |
| База данных (Redis, PostgreSQL) | 60–120 | Синхронизация данных, checkpoint |
| Batch/Job | 30–60 | Завершение текущей задачи |

---

## Эталонный Production-манифест

Полный пример манифеста, учитывающего все рекомендации:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: production-app
  namespace: production
  labels:
    app.kubernetes.io/name: web-api
    app.kubernetes.io/version: "1.31.0"
    app.kubernetes.io/component: backend
    app.kubernetes.io/part-of: my-project
    app.kubernetes.io/managed-by: kubectl
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9090"
    prometheus.io/path: "/metrics"
spec:
  # Отключение автоматического монтирования токена ServiceAccount
  automountServiceAccountToken: false

  # Планирование и приоритеты
  priorityClassName: production-high
  terminationGracePeriodSeconds: 45

  # Распределение по узлам (антипаттерн: все Pod на одном узле)
  topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: DoNotSchedule
    labelSelector:
      matchLabels:
        app.kubernetes.io/name: web-api

  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 3000
    fsGroup: 2000
    seccompProfile:
      type: RuntimeDefault

  containers:
  - name: app
    image: my-company.com/web-api:1.31.0
    imagePullPolicy: IfNotPresent

    ports:
    - name: http
      containerPort: 8080
      protocol: TCP

    # Ресурсы (Guaranteed QoS для критических сервисов)
    resources:
      requests:
        cpu: "250m"
        memory: "512Mi"
      limits:
        cpu: "500m"
        memory: "512Mi"

    # Безопасность контейнера
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]

    # Переменные окружения из ConfigMap и Secret
    envFrom:
    - configMapRef:
        name: app-config
    - secretRef:
        name: app-secrets

    # Health Checks (триада)
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
      failureThreshold: 3
    livenessProbe:
      httpGet:
        path: /live
        port: http
      initialDelaySeconds: 15
      periodSeconds: 20
      failureThreshold: 3

    # Точки монтирования для временных данных
    volumeMounts:
    - name: tmp
      mountPath: /tmp
    - name: cache
      mountPath: /var/cache/nginx

    # Lifecycle hooks
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 10"]

  # Временные тома
  volumes:
  - name: tmp
    emptyDir:
      sizeLimit: 100Mi
  - name: cache
    emptyDir:
      sizeLimit: 200Mi
```

---

## Практические сценарии

### Сценарий 1: Projected Volumes для конфигураций

Лучшая практика объединения секретов и конфигов без захламления манифеста:

```yaml
volumes:
- name: all-configs
  projected:
    sources:
    - configMap:
        name: app-config
    - secret:
        name: app-credentials
    - downwardAPI:
        items:
          - path: "pod-info"
            fieldRef:
              fieldPath: metadata.name
```
Подробнее: [Projected Volumes](./volume_types/projected_volumes.md).

### Сценарий 2: Sidecar-контейнер для логирования

Раздельное логирование с нативным sidecar (v1.29+):

```yaml
initContainers:
- name: logshipper
  image: fluentd:v1.16
  restartPolicy: Always
  resources:
    requests: { cpu: "50m", memory: "64Mi" }
    limits: { cpu: "100m", memory: "128Mi" }
  volumeMounts:
  - name: app-logs
    mountPath: /var/log/app
containers:
- name: app
  image: my-app:1.31.0
  volumeMounts:
  - name: app-logs
    mountPath: /var/log/app
volumes:
- name: app-logs
  emptyDir: {}
```

### Сценарий 3: Bash-скрипт для быстрой проверки манифеста

```bash
#!/bin/bash
# check_pod_manifest.sh — проверка Pod манифеста перед деплоем

MANIFEST=$1

if [[ ! -f "$MANIFEST" ]]; then
  echo "Файл не найден: $MANIFEST"
  exit 1
fi

echo "=== Проверка: $MANIFEST ==="

# 1. YAML валидация
kubectl apply --dry-run=client -f "$MANIFEST" 2>/dev/null
if [[ $? -ne 0 ]]; then
  echo "ОШИБКА: YAML невалиден"
  exit 1
fi
echo "YAML валиден"

# 2. Проверка наличия :latest тега
if grep -q "image:.*:latest" "$MANIFEST"; then
  echo "ПРЕДУПРЕЖДЕНИЕ: Обнаружен тег :latest"
fi

# 3. Проверка наличия resources
if ! grep -q "resources:" "$MANIFEST"; then
  echo "ПРЕДУПРЕЖДЕНИЕ: Ресурсы не указаны"
fi

# 4. Проверка securityContext
if ! grep -q "securityContext:" "$MANIFEST"; then
  echo "ПРЕДУПРЕЖДЕНИЕ: securityContext не указан"
fi

# 5. Проверка probes
if ! grep -q "livenessProbe:" "$MANIFEST"; then
  echo "ПРЕДУПРЕЖДЕНИЕ: livenessProbe не указан"
fi

# 6. Проверка terminationGracePeriodSeconds
if ! grep -q "terminationGracePeriodSeconds:" "$MANIFEST"; then
  echo "ПРЕДУПРЕЖДЕНИЕ: terminationGracePeriodSeconds не указан"
fi

echo "=== Проверка завершена ==="
```

---

## Чек-лист перед деплоем (Production Readiness)

Используйте этот чек-лист для валидации каждого Pod манифеста перед применением в Production:

### Безопасность

| Проверка | Статус | Комментарий |
| :--- | :--- | :--- |
| `runAsNonRoot: true` | | Запрет root на хосте |
| `allowPrivilegeEscalation: false` | | Запрет повышения привилегий |
| `readOnlyRootFilesystem: true` | | Неизменяемая ФС (emptyDir для /tmp) |
| `capabilities: drop: ["ALL"]` | | Минимальные привилегии |
| `seccompProfile: RuntimeDefault` | | Фильтрация syscall |
| `automountServiceAccountToken: false` | | Нет лишних токенов |
| Секреты не в env (см. Secret/Projected) | | Конфиденциальность |

### Ресурсы и стабильность

| Проверка | Статус | Комментарий |
| :--- | :--- | :--- |
| `resources.requests` указаны | | Планирование |
| `resources.limits` указаны | | Защита от runaway |
| `requests == limits` для памяти (Guaranteed) | | Защита от OOMKiller |
| `terminationGracePeriodSeconds` настроен | | Корректное завершение |
| `livenessProbe` настроен | | Перезапуск зависших |
| `readinessProbe` настроен | | Маршрутизация трафика |
| `startupProbe` (если долго стартует) | | Защита от преждевременного kill |

### Доступность и распределение

| Проверка | Статус | Комментарий |
| :--- | :--- | :--- |
| `topologySpreadConstraints` или `podAntiAffinity` | | Избежание SPOF |
| `priorityClassName` (если критично) | | Защита от вытеснения |
| PDB создан | | Доступность при обслуживании |
| `replicas >= 2` (если HA) | | Отказоустойчивость |

### Наблюдаемость

| Проверка | Статус | Комментарий |
| :--- | :--- | :--- |
| Стандартные метки `app.kubernetes.io/*` | | Агрегация в мониторинге |
| Аннотации для Prometheus scrape | | Сбор метрик |
| Логи в stdout/stderr | | Сбор через DaemonSet |

---

## Типичные антипаттерны и ошибки

| Антипаттерн | Проблема | Решение |
| :--- | :--- | :--- |
| **`:latest` тег** | Невоспроизводимый деплой, непредсказуемое поведение | Используйте SemVer или SHA-хеш (`image: app:1.31.0`) |
| **Без `resources`** | Конкуренция за ресурсы, OOMKiller, вытеснение критических Pod | Всегда указывайте `requests` и `limits` |
| **Root по умолчанию** | Компрометация хоста при container breakout | `runAsNonRoot: true`, `securityContext` |
| **Без `readinessProbe`** | Трафик на неготовый Pod, 502/504 ошибки | Всегда настраивайте readiness |
| **Без `terminationGracePeriodSeconds`** | Принудительное убийство, потеря соединений | Настройте под время завершения приложения |
| **Секреты в `env`** | Утечка через `kubectl describe pod`, логи, metrics | Используйте Secret или Projected Volumes |
| **Без `topologySpreadConstraints`** | Все Pod на одном узле → SPOF | Распределение по узлам/зонам |
| **`requests > limits`** | Невалидный манифест, ошибка планировщика | `requests` всегда <= `limits` |
| **Без `preStop`** | Мгновенное отключение от Service до обработки запросов | `preStop: sleep 10` |
| **ОдинаковыеProbe endpoints** | Liveness и readiness проверяют одно и то же | Разные эндпоинты: `/healthz` и `/ready` |

**Автоматическая проверка антипаттернов:**
```bash
# Проверка наличия :latest тега
grep -n "image:.*:latest" manifest.yaml

# Проверка отсутствия resources
grep -c "resources:" manifest.yaml
# → 0 = нет ресурсов (ПЛОХО)

# Проверка отсутствия securityContext
grep -c "securityContext:" manifest.yaml
# → 0 = нет контекста безопасности (ПЛОХО)
```

---

## Сравнение стратегий конфигурации

### Типы приложений и рекомендуемые конфигурации

| Тип приложения | QoS класс | Пробы | terminationGracePeriodSeconds | Рекомендации |
| :--- | :--- | :--- | :--- | :--- |
| **Stateless API** | Guaranteed | HTTP | 30–45 | `maxSurge: 1`, `maxUnavailable: 0` |
| **Web-сервер (Nginx)** | Burstable | HTTP | 30 | preStop hook для graceful shutdown |
| **Java/JVM** | Guaranteed | HTTP | 60–90 | startupProbe с `failureThreshold: 30` |
| **База данных** | Guaranteed | Exec | 60–120 | `fsGroup` для доступа к томам |
| **Batch/Job** | BestEffort | Exec | 30–60 | `backoffLimit`, `activeDeadlineSeconds` |
| **Cache (Redis)** | Guaranteed | TCP | 60 | `hostNetwork: false`, `shareProcessNamespace: false` |

### Стратегии обновления Pod в Deployment

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **RollingUpdate** | Поэтапная замена Pod | Стандарт для Production |
| **Recreate** | Удаление всех → создание новых | Критические обновления, несовместимые версии |
| **Blue/Green** | Параллельный запуск → переключение | Мгновенный откат,ゼロダウンтайм |

Подробнее: [Манифест Deployment](../Deployment/deployment_manifest.md).

---

## Продвинутые техники

### Эфемерные контейнеры для отладки

Без перезапуска Pod и без изменения манифеста:

```bash
# Добавление отладочного контейнера
kubectl debug -it <pod-name> --image=busybox:1.36 --target=<container-name>

# Просмотр процессов Pod
kubectl debug <pod-name> --image=busybox:1.36 -- /bin/sh -c "ps aux"

# Проверка сетевой связности
kubectl debug <pod-name> --image=nicolaka/netshoot -- curl -v http://service:8080
```

Подробнее: [Эфемерные контейнеры](./ephemeral_containers.md).

### shareProcessNamespace

Общий PID namespace для Pod позволяет видеть процессы других контейнеров:

```yaml
spec:
  shareProcessNamespace: true
  containers:
  - name: app
    image: my-app:1.31.0
  - name: debug-sidecar
    image: busybox:1.36
    command: ["sleep", "3600"]
    securityContext:
      capabilities:
        add: ["SYS_PTRACE"]
```

**Применение:**
- Sidecar, который анализирует процессы основного контейнера
- Отладка через `/proc/<pid>/` без ephemeral containers
- Мониторинг процессов внутри Pod

### PodOverhead

При использовании RuntimeClass с overhead:

```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: gvisor
overhead:
  podFixed:
    memory: "128Mi"
    cpu: "100m"
```

Kubernetes автоматически учитывает overhead при планировании и расчете QoS.

### PriorityClassName

Защита критических Pod от вытеснения:

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: production-high
value: 1000000
globalDefault: false
description: "Высокий приоритет для Production сервисов"
---
apiVersion: v1
kind: Pod
spec:
  priorityClassName: production-high
  containers:
  - name: app
    image: my-app:1.31.0
```

**Иерархия приоритетов (рекомендуемые значения):**

| PriorityClass | Значение | Пример использования |
| :--- | :--- | :--- |
| `system-critical` | 2000000000 | Kubernetes system components |
| `production-high` | 1000000 | Платежные системы, API |
| `production` | 100000 | Основные сервисы |
| `batch` | 10000 | Batch-задачи |
| `best-effort` | 1000 | Dev/test |

---

## Мониторинг и наблюдаемость

### Аннотации для Prometheus

```yaml
metadata:
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9090"
    prometheus.io/path: "/metrics"
    prometheus.io/scheme: "http"
```

### Метрики для мониторинга Pod

| Метрика | Описание | Источник |
| :--- | :--- | :--- |
| `kube_pod_status_phase` | Текущая фаза Pod | kube-state-metrics |
| `kube_pod_container_status_restarts_total` | Количество перезапусков | kube-state-metrics |
| `container_memory_working_set_bytes` | Использование памяти | cAdvisor |
| `container_cpu_usage_seconds_total` | Использование CPU | cAdvisor |
| `kube_pod_status_ready` | Готовность Pod | kube-state-metrics |

### Alerting Rules (Пример)

```yaml
groups:
- name: pod-alerts
  rules:
  - alert: PodCrashLooping
    expr: rate(kube_pod_container_status_restarts_total[15m]) > 0.1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Pod {{ $labels.pod }} перезапускается"

  - alert: PodNotReady
    expr: kube_pod_status_ready{condition="true"} == 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Pod {{ $labels.pod }} не готов"
```

---

## Troubleshooting: типичные ошибки манифестов

### Ошибка 1: Pod не запускается (Pending)

**Причины:**
- Нет узлов с достаточными ресурсами (resource pressure)
- Violates PodAntiAffinity / topologySpreadConstraints
- `priorityClassName` ссылается на несуществующий объект

**Диагностика:**
```bash
kubectl describe pod <pod-name> | grep -A 5 "Events"
kubectl get events --field-selector involvedObject.name=<pod-name>
```

### Ошибка 2: CrashLoopBackOff

**Причины:**
- Приложение падает при запуске (ошибка конфигурации, зависимости)
- OOMKilled (недостаточно `limits.memory`)
- livenessProbe убивает приложение до готовности

**Диагностика:**
```bash
kubectl logs <pod-name> --previous
kubectl describe pod <pod-name> | grep -i "oom\|killed"
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'
```

### Ошибка 3: ReadinessProbe fails

**Причины:**
- Приложение ещё не готово
- Неправильный эндпоинт (path/port)
- Слишком частые проверки

**Решение:**
```bash
# Проверка эндпоинта вручную
kubectl exec <pod-name> -- curl -s http://localhost:8080/ready

# Увеличение времени готовности
# Добавить в манифест:
#   readinessProbe:
#     initialDelaySeconds: 15
#     periodSeconds: 10
```

### Ошибка 4: ImagePullBackOff

**Причины:**
- Неправильное имя образа или тег
- Приватный реестр без `imagePullSecrets`
- Нет сетевого доступа к реестру

**Решение:**
```bash
# Проверка доступа к реестру
kubectl get secrets | grep docker-registry
kubectl get pod <pod-name> -o jsonpath='{.spec.imagePullSecrets}'

# Создание секрета
kubectl create secret docker-registry regcred \
  --docker-server=my-registry.com \
  --docker-username=user \
  --docker-password=pass
```

### Ошибка 5: Ошибка валидации манифеста

**Причины:**
- Синтаксическая ошибка YAML
- Невалидное поле в spec
- Отсутствует обязательное поле

**Диагностика:**
```bash
# Валидация без применения
kubectl apply --dry-run=client -f manifest.yaml

# Линтинг
kube-linter lint manifest.yaml
datree test manifest.yaml
```

---

## Дополнительная информация

**Связанные темы:**

* [Пробы в Kubernetes](../probes.md) — детальный разбор Liveness/Readiness/Startup.
* [QoS и управление ресурсами](../../Scheduling/qos_limit_and_requests.md) — как лимиты влияют на приоритет Pod.
* [Security Context в Kubernetes](../../Security/pod_security_context.md) — настройки PSA и изоляции.
* [Бюджет прерывания подов (PDB)](../../Autoscaling/pod_disruption_budget.md) — управление доступностью.
* [Метаданные, метки и аннотации](../../Concepts/metadata_and_labels.md) — стандарты именования.
* [Жизненный цикл Pod](./pod_lifecycle_and_state.md) — подробности фаз и Graceful Shutdown.
