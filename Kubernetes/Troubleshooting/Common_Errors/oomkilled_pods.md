# Поды, убитые из-за нехватки памяти (`OOMKilled`)

## Определения

**`OOMKilled` (Out of Memory Killed)** — причина (`Reason`) завершения контейнера, означающая, что процесс был принудительно завершен ядром ОС узла из-за превышения выделенного лимита памяти. Не является статусом пода.

> - QoS и управление ресурсами: [`qos_limit_and_requests.md`](../../Scheduling/qos_limit_and_requests.md)
> - Eviction: [`pod_evicted.md`](./PodEvicted/definitions.md)
> - Мониторинг ресурсов: [`troubleshooting_overview.md`](../troubleshooting_overview.md)
> - Docker exit codes: [`docker_exit_codes.md`](../../../Docker/Docker_troubleshooting/docker_exit_codes.md)

**Код выхода:** `137` (128 + SIGKILL/9)

## Основные концепции

### Механизм OOM Killer в Kubernetes

```
Приложение потребляет память
    ↓
Превышен limits.memory
    ↓
cgroups сигнализируют ядру
    ↓
OOM Killer завершает процесс (SIGKILL)
    ↓
Контейнер перезапускается (RestartCount++)
```

### Связь с QoS классами

| QoS Класс | Условия | Защита от OOM |
|-----------|---------|---------------|
| **`Guaranteed`** | `requests` == `limits` | Максимальная защита от OOM со стороны узла, но **не защищает** от превышения собственного `limits` |
| **`Burstable`** | `requests` < `limits` | Средняя защита; может быть завершен при нехватке памяти на узле |
| **`BestEffort`** | Нет `requests`/`limits` | Минимальная защита; первый кандидат на OOM |

> **Важно:** Даже под с QoS `Guaranteed` будет завершен с `OOMKilled`, если превысит свой собственный `limits.memory`.

### Типы OOM событий

| Тип | Описание | Причина |
|-----|----------|---------|
| **Container OOM** | Контейнер превысил свой `limits.memory` | Неправильно настроенные лимиты, утечка памяти |
| **Node OOM** | Узел исчерпал всю доступную память | Eviction Manager активируется, выселяет поды |

## Практические сценарии

### Диагностика

#### Шаг 1: Проверка статуса пода

```bash
kubectl describe pod <pod-name>
```

Ищите в выводе:

```
Last State:     Terminated
  Reason:       OOMKilled
  Exit Code:    137
```

#### Шаг 2: Анализ потребления ресурсов

```bash
# Текущее потребление
kubectl top pod <pod-name>

# История потребления (при наличии metrics-server)
kubectl top pod --containers <pod-name>

# Проверка limits в манифесте
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].resources}'
```

#### Шаг 3: Проверка событий узла

```bash
# События на узле, где был запущен под
kubectl get events --field-selector involvedObject.kind=Node --sort-by='.lastTimestamp'

# Лог ядра на узле (требуется SSH-доступ)
ssh <node-name> "dmesg -T | grep -i 'killed process'"
ssh <node-name> "journalctl -k | grep -i 'oom'"
```

#### Шаг 4: Проверка QoS класса пода

```bash
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'
```

### Распространенные случаи и решения

#### 1. Превышение `limits.memory`

**Симптомы:**

- `Exit Code: 137`
- `Reason: OOMKilled`
- Потребление памяти близко к `limits`

**Решение:**

```yaml
resources:
  requests:
    memory: "256Mi"   # Увеличить на основе реального потребления
  limits:
    memory: "512Mi"   # Увеличить, но с запасом
```

> **Best Practice:** Устанавливайте `limits` на 20-30% выше пикового потребления.

#### 2. Утечка памяти в приложении

**Симптомы:**

- Постепенный рост потребления памяти со временем
- Регулярные `OOMKilled` через определенные интервалы
- `OOMKilled` даже при высоких `limits`

**Диагностика:**

```bash
# Непрерывный мониторинг потребления
watch -n 5 'kubectl top pod <pod-name>'

# Логи приложения на ошибки
kubectl logs <pod-name> --previous | grep -i 'memory\|leak\|heap'
```

**Решение:**

- Профилирование приложения (pprof для Go, JFR для Java, tracemalloc для Python)
- Оптимизация кода, исправление утечек
- Настройка GC (для JVM: `-XX:MaxRAMPercentage`)

#### 3. Неправильная настройка для JVM-приложений

**Проблема:** JVM до JDK 8u191 не учитывала лимиты контейнера.

**Решение:**

```yaml
env:
- name: JAVA_TOOL_OPTIONS
  value: "-XX:MaxRAMPercentage=75.0 -XX:InitialRAMPercentage=50.0"
resources:
  limits:
    memory: "1Gi"
  requests:
    memory: "512Mi"
```

> **См. также:** [Docker Java Best Practices](../../../Docker/Dockerfile/Docker_best_practices/java.md)

#### 4. OOM при старте приложения

**Причина:** Приложению требуется больше памяти для инициализации, чем для работы.

**Решение:**

```yaml
# Временное увеличение лимита через HPA с кастомными метриками
# Или использование Startup Probe для отсрочки проверки liveness
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 60  # Дать время на старт
  periodSeconds: 10
```

### Prevention (Профилактика)

#### 1. Настройка мониторинга и алертов

```yaml
# Пример Prometheus alert для OOMKilled
- alert: PodOOMKilled
  expr: kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Pod {{ $labels.pod }} OOMKilled"
    description: "Container {{ $labels.container }} в namespace {{ $labels.namespace }} был завершен из-за нехватки памяти"
```

#### 2. Использование Vertical Pod Autoscaler (VPA)

VPA автоматически рекомендует или устанавливает `requests` и `limits`:

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: my-app-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  updatePolicy:
    updateMode: "Recommendation"  # Или "Auto" для автоматического применения
```

> **См. также:** [`vpa_detailed.md`](../../Autoscaling/vpa_detailed.md)

#### 3. In-Place Pod Resize (Kubernetes 1.35+ stable)

Изменение ресурсов без пересоздания пода:

```bash
kubectl patch pod <pod-name> -p '{"spec":{"containers":[{"name":"app","resources":{"limits":{"memory":"1Gi"}}}]}}'
```

> **См. также:** [`in_place_pod_resize.md`](../../Autoscaling/in_place_pod_resize.md)

#### 4. Best Practices для настройки ресурсов

| Практика | Описание |
|----------|----------|
| **Всегда указывайте `requests` и `limits`** | Избегайте QoS `BestEffort` в production |
| **Используйте `Burstable` для большинства приложений** | Гибкость + защита |
| **`Guaranteed` только для критичных сервисов** | Базы данных, очереди |
| **Регулярный пересмотр** | Анализируйте реальное потребление через Prometheus/Grafana |
| **Тестирование под нагрузкой** | Нагрузочные тесты для определения пикового потребления |

## Дополнительная информация

### Связь с Eviction Manager

При нехватке памяти на узле (`MemoryPressure`), Eviction Manager выселяет поды в порядке:

1. `BestEffort` → 2. `Burstable` → 3. `Guaranteed`

> **См. также:** [`pod_evicted.md`](./PodEvicted/definitions.md), [`qos_limit_and_requests.md`](../../Scheduling/qos_limit_and_requests.md)

### Инструменты анализа памяти

| Язык | Инструмент |
|------|------------|
| **Go** | pprof, delve |
| **Java** | JFR, JMAP, VisualVM |
| **Python** | tracemalloc, memory_profiler |
| **Node.js** | Chrome DevTools, clinic.js |

### Типичные значения для приложений

| Приложение | Requests | Limits |
|------------|----------|--------|
| Nginx | 64Mi | 128Mi |
| Node.js API | 128Mi | 256Mi |
| Java Spring Boot | 512Mi | 1Gi |
| Python Flask | 128Mi | 256Mi |
| PostgreSQL | 256Mi | 512Mi |

> **Примечание:** Значения зависят от конкретной нагрузки и требуют эмпирической настройки.

Подробнее: [Kubernetes Memory Management](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/), [Debug Memory Leaks](https://kubernetes.io/docs/tasks/debug/debug-application/debug-memory-leak/), [JVM in Containers](https://www.oracle.com/java/technologies/javase/8u-release-notes.html#JDK-8u191).
