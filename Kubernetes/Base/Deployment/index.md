# Deployment в Kubernetes

Декларативное управление жизненным циклом stateless-приложений и подов.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes (v1.16+ для использования `apps/v1`)
- Установленный и настроенный `kubectl` с доступом к кластеру
- Базовое понимание объектов [Pod](../Pod/pod_overview.md) и [ReplicaSet](../replicaset.md)
- Для production-среды: настроенные [ResourceQuota](../../Scheduling/qos_limit_and_requests.md) и [LimitRange](../../Scheduling/qos_limit_and_requests.md) в неймспейсе

## 1. Определения

**Deployment** — высокоуровневый объект Kubernetes, предназначенный для декларативного описания желаемого состояния приложения. Он обеспечивает автоматическое развертывание, масштабирование и обновление групп идентичных подов.

### Ключевые характеристики
- **Stateless-ориентированность:** В отличие от [StatefulSet](../StatefulSet/statefulset_overview.md), поды в Deployment взаимозаменяемы и не имеют стабильных сетевых идентификаторов или привязки к конкретным томам (за исключением `emptyDir` или сетевых хранилищ без привязки к узлу).
- **Автоматизация Rollout:** Управление процессом выкатки новых версий с возможностью автоматического отката при сбоях.
- **Самоисцеление:** Контроллер Deployment постоянно сравнивает текущее состояние кластера с желаемым (Desired State), пересоздавая поды в случае их удаления или падения узла.

**Схема управления:** `Deployment` → [`ReplicaSet`](../replicaset.md) → [`Pod`](../Pod/pod_overview.md)

Deployment реализует паттерн «контроллер». Он не управляет подами напрямую, а делегирует это `ReplicaSet`. При обновлении манифеста Deployment создает новый `ReplicaSet` и постепенно переносит нагрузку со старого на новый, обеспечивая Zero-Downtime.

### Владелец ресурса (Owner References)

Механизм `ownerReferences` в метаданных ресурсов обеспечивает каскадное управление:
- `Pod` содержит ссылку на `ReplicaSet`.
- `ReplicaSet` содержит ссылку на `Deployment`.

При удалении Deployment сборщик мусора (Garbage Collector) Kubernetes автоматически удаляет все связанные ReplicaSets и Pods. Исключение — использование `propagationPolicy: Orphan`, при котором дочерние ресурсы сохраняются.

## 2. Базовые концепции

### Анатомия манифеста

Ключевые параметры спецификации (`spec`):

- **`replicas`**: Целевое количество экземпляров. Рекомендуется минимум 2 для исключения простоев при плановых работах на узлах (Eviction).
- **`selector`**: Механизм связи Deployment с подами.
  - Поле `spec.selector.matchLabels` является **неизменяемым** после создания объекта.
  - Ошибка в селекторе приведет к тому, что Deployment не «увидит» свои поды и начнет создавать их бесконечно.
- **`template`**: Шаблон пода. Любое изменение в этом блоке (образ, переменные окружения, метки) инициирует создание новой ревизии (Rollout).
- **`minReadySeconds`**: Время задержки перед тем, как под будет считаться «готовым» (available). Важно для приложений с долгим временем инициализации (Java, тяжелые фреймворки).
- **`revisionHistoryLimit`**: Количество сохраняемых старых `ReplicaSet`. По умолчанию 10. Позволяет делать `rollback`. Нулевое значение отключает возможность отката.
- **`progressDeadlineSeconds`**: Таймаут (по умолчанию 600с) на выполнение операции обновления. Если процесс застрял, статус изменится на `False`.

### Базовый пример манифеста

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
  labels:
    app: web-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web-app
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: web-app
    spec:
      containers:
      - name: web
        image: nginx:1.27-alpine
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
          limits:
            cpu: "200m"
            memory: "256Mi"
        readinessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 15
          periodSeconds: 20
```

Детальный разбор всех полей, Production-манифест с полной безопасностью и лучшие практики см. в [Манифест и лучшие практики](./deployment_manifest.md).

### Управление ресурсами и безопасность

Для обеспечения стабильности в продакшене внутри `template.spec` должны быть определены:
- **Resources (Requests/Limits):** Гарантируют предсказуемое планирование подов на узлы и предотвращают OOM (Out Of Memory) для всего узла. См. [Управление ресурсами](../../Scheduling/qos_limit_and_requests.md).
- **Security Context:** Настройка прав доступа (runAsUser, readOnlyRootFilesystem). По умолчанию поды не должны запускаться от `root`. См. [Pod Security Context](../../Security/pod_security_context.md).
- **Readiness/Liveness Probes:** Критически важны для стратегии `RollingUpdate`. Без них Kubernetes начнет удалять старые поды до того, как новые реально смогут принимать трафик. См. [Пробы в Kubernetes](../probes.md).

### Стратегии обновления

| Стратегия | Описание | Параметры |
| :--- | :--- | :--- |
| **`RollingUpdate`** (default) | Постепенная замена старых подов новыми. Поддерживает доступность сервиса. | `maxSurge`, `maxUnavailable` |
| **`Recreate`** | Сначала удаляются все старые поды, затем создаются новые. Гарантированный Downtime. | Нет |

> **Архитектурные паттерны:** Стратегии **Blue-Green** и **Canary** не являются встроенными типами `spec.strategy.type`. Они реализуются внешними инструментами (ArgoCD, Flagger, Istio) или манипуляциями с сервисами и несколькими Deployment. Подробнее в [сравнении стратегий](../../../CI-CD/Deployment_Strategies/comparison.md).

#### Особенности стратегии Recreate

Используется редко, в основном для приложений, которые:
- Не поддерживают одновременную работу разных версий кода с одной БД (схемы миграций).
- Требуют эксклюзивного доступа к ресурсу (например, `ReadWriteOnce` тома в некоторых облаках).
- Используются в Dev-средах, где экономия ресурсов важнее доступности.

#### Настройка RollingUpdate: maxSurge и maxUnavailable

Эти параметры определяют «агрессивность» и безопасность обновления:
- **`maxSurge`**: Сколько дополнительных подов можно создать сверх `replicas`.
  - Значение `25%` (или `1` при малом числе реплик) — безопасный стандарт.
  - Позволяет ускорить выкатку, если в кластере достаточно свободных ресурсов.
- **`maxUnavailable`**: Сколько подов могут быть недоступны одновременно.
  - Значение `0` гарантирует, что количество живых подов никогда не упадет ниже желаемого (требует наличия ресурсов для `maxSurge`).
  - Значение `100%` эквивалентно стратегии `Recreate`.

### Условия состояния (Status Conditions)

Deployment отслеживает свой прогресс через `status.conditions`:
- **Available**: `True` означает, что приложение работает и доступно пользователям.
- **Progressing**: `True` во время выполнения Rollout. Если новый ReplicaSet не отвечает (например, `ImagePullBackOff`), через `progressDeadlineSeconds` состояние перейдет в `False` с ошибкой `ProgressDeadlineExceeded`.
- **ReplicaFailure**: Проблемы на уровне создания подов (квоты, права, отсутствие узлов).

### Перекрывающиеся обновления (Rollover)

Если вы отправите второе обновление (`v3`), пока еще идет первое (`v1` -> `v2`), контроллер не будет ждать завершения `v2`. Он начнет масштабировать `v2` вниз и сразу перейдет к `v3`. Это критически важно для быстрой доставки горячих исправлений (Hotfixes).

## 3. Практические сценарии

### Быстрый старт и базовое управление

```bash
# Применение манифеста
kubectl apply -f deployment.yaml

# Обновление образа с сохранением причины (Senior Practice)
kubectl set image deployment/my-app nginx=nginx:1.29.0 --record

# Примечание: Флаг --record считается устаревшим, лучше использовать аннотации:
kubectl annotate deployment/my-app kubernetes.io/change-cause="Обновление до 1.29.0 для фикса CVE-123"

# Просмотр истории ревизий
kubectl rollout history deployment/my-app

# Откат к конкретной ревизии
kubectl rollout undo deployment/my-app --to-revision=2

# Пауза и возобновление (для внесения множества правок без лишних Rollouts)
kubectl rollout pause deployment/my-app
# ... внесение изменений в ConfigMap/Limits ...
kubectl rollout resume deployment/my-app
```

### Масштабирование

```bash
# Масштабирование до конкретного числа реплик
kubectl scale deployment/my-app --replicas=5

# Масштабирование через императивное изменение манифеста
kubectl patch deployment my-app -p '{"spec":{"replicas":5}}'

# Автоматическое масштабирование по нагрузке (требует HPA)
kubectl autoscale deployment/my-app --min=2 --max=10 --cpu-percent=80
```

Важно: при масштабировании **не создается новая ревизия** — контроллер просто меняет количество реплик в текущем активном ReplicaSet. Подробнее см. [HPA](../../Autoscaling/HPA/index.md).

### Принудительный перезапуск (Restart)

```bash
# Перезапуск всех подов Deployment (без изменения манифеста)
kubectl rollout restart deployment/my-app

# Полезные сценарии:
# - Применение нового ConfigMap/Secret, подключенного через ENV
# - Обновление образа с мутабельным тегом (нестабильная практика)
# - Сброс состояния при обнаружении утечек памяти
```

### Анализ состояния и валидация

```bash
# Проверка перед применением (Dry-Run на клиенте)
kubectl apply -f deployment.yaml --dry-run=client

# Проверка перед применением (Dry-Run на сервере — полная валидация)
kubectl apply -f deployment.yaml --dry-run=server

# Детальный просмотр статуса
kubectl rollout status deployment/my-app
# → Waiting for deployment "my-app" rollout to finish: 1 of 3 updated replicas are available...
# → deployment "my-app" successfully rolled out

# Список всех ReplicaSet для данного деплоя (поиск старых версий)
kubectl get rs -l app=my-app

# Просмотр конкретной ревизии
kubectl rollout history deployment/my-app --revision=3
```

Команда `kubectl get deploy` предоставляет краткую сводку:
- **READY**: Сколько подов прошли `readinessProbe` из общего числа.
- **UP-TO-DATE**: Сколько подов запущено с последней версией шаблона.
- **AVAILABLE**: Поды, которые работают дольше `minReadySeconds` и прошли пробы.
- **AGE**: Время жизни Deployment.

### Диагностика при сбоях

#### Быстрая диагностика

```bash
# Просмотр событий Deployment
kubectl describe deployment my-app

# Просмотр событий конкретного пода
kubectl describe pod <pod-name>

# Просмотр логов упавшего пода (включая предыдущий контейнер)
kubectl logs <pod-name> --previous

# Просмотр всех подов с проблемами в неймспейсе
kubectl get pods --field-selector=status.phase!=Running -n <namespace>
```

#### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`ImagePullBackOff`** | Неверное имя образа, отсутствие тега, проблемы с авторизацией | Проверить `imagePullSecrets`, имя реестра и тег образа |
| **`CrashLoopBackOff`** | Ошибка приложения, мисконфигурация, неверные переменные окружения | Читать логи: `kubectl logs <pod> --previous` |
| **`OOMKilled`** | Превышение `limits.memory` | Увеличить лимит памяти или оптимизировать приложение |
| **`Pending`** | Недостаточно ресурсов, Taints, Affinity | Проверить `kubectl describe pod`, квоты и политики планирования |
| **`ProgressDeadlineExceeded`** | Обновление зависло на `progressDeadlineSeconds` | Проверить readinessProbe, логи новых подов |

Подробный алгоритм диагностики при зависании обновлений, разбор параметров `maxSurge`/`maxUnavailable` и реальные кейсы сбоев доступны в отдельном руководстве:
[Устранение неполадок Deployment и RollingUpdate](./troubleshooting.md).

### Лучшие практики (Best Practices)

1. **Принцип неизменяемости образов:** Используйте конкретные теги (например, `nginx:1.27-alpine`), никогда `:latest`. Это делает деплой невоспроизводимым и ломает механизм отката. Для критических сред используйте хеши образов (`sha256:...`).
2. **Обязательные Resources:** Всегда указывайте `requests` и `limits` для CPU и памяти. Для памяти рекомендуется `requests == limits` (класс **Guaranteed**), чтобы защитить от OOMKiller. См. [Управление ресурсами](../../Scheduling/qos_limit_and_requests.md).
3. **Readiness Probe — обязательно:** Без неё Kubernetes начнет удалять старые поды до того, как новые реально смогут принимать трафик. Используйте HTTP-пробы вместо TCP (TCP-сокет открывается ОС задолго до готовности приложения).
4. **maxUnavailable: 0 для Zero-Downtime:** Гарантирует, что старые поды не будут удалены, пока новые не станут `Ready`. Требует наличия ресурсов для `maxSurge`.
5. **Безопасность:** Запускайте контейнеры от непривилегированного пользователя (`runAsNonRoot: true`, `runAsUser: 1000`). Отключайте автомонтирование ServiceAccount Token, если приложению не нужен доступ к API. См. [Pod Security Context](../../Security/pod_security_context.md).
6. **Graceful Termination:** Приложение должно корректно обрабатывать `SIGTERM`. Увеличивайте `terminationGracePeriodSeconds` для тяжелых приложений (Java, БД-клиенты). Используйте `preStop` хуки для плавного дренажа соединений.
7. **Распределение по узлам:** Используйте `podAntiAffinity` или `topologySpreadConstraints`, чтобы поды одного сервиса не оказались на одном узле (SPOF). См. [Affinity](../../Scheduling/affinity.md).
8. **Минимальная история:** Устанавливайте `revisionHistoryLimit: 3–5` вместо дефолтных 10. Это снижает нагрузку на `etcd`.

### Ограничения и особенности (Edge Cases)

1. **Неизменяемость селектора:** Поле `spec.selector` является **неизменяемым** после создания Deployment. Для изменения селектора требуется пересоздание объекта (`kubectl delete` → `kubectl apply`).
2. **Конфликт с ResourceQuota:** Параметр `maxSurge` может временно поднять потребление ресурсов выше лимита неймспейса. Проверяйте квоты: `kubectl describe quota -n <namespace>`.
3. **Рекурсивное создание подов:** Ошибка в селекторе приведет к тому, что Deployment не «увидит» свои поды и начнет создавать их бесконечно. Всегда проверяйте `kubectl get rs` перед первым применением.
4. **HPA и RollingUpdate:** Если используется Horizontal Pod Autoscaler, настраивайте его на **Deployment**, а не на ReplicaSet. Иначе при Rollout HPA может масштабировать старый (неактивный) ReplicaSet.
5. **Размер кластера:** При нехватке ресурсов в кластере обновление с `maxUnavailable: 0` зависнет — контроллер не удалит старые поды, пока новые не получат ресурсы. Планируйте запас мощности.
6. **Длинные startup-процессы:** Для приложений с долгим временем инициализации (Java, Spring Boot) обязательно используйте `startupProbe`, иначе `livenessProbe` будет убивать под до готовности.

## 4. Дополнительная информация

### Базовые руководства
- [Манифест и лучшие практики](./deployment_manifest.md) — детальный разбор YAML, ресурсов и проб.
- [Устранение неполадок и RollingUpdate](./troubleshooting.md) — глубокая диагностика и разбор стратегий обновления.
- [Управление жизненным циклом](./lifecycle_management.md) — пауза, возобновление и глубокое управление ревизиями.

### Безопасность и production
- [Безопасность Deployment](./deployment_security_hardening.md) — hardened манифест для продакшена.
- [Production Checklist](./production_checklist.md) — чеклист перед деплоем.

### Продвинутые стратегии
- [Продвинутые стратегии отката](./advanced_rollback_strategies.md) — автоматический откат по метрикам и GitOps.
- [Progressive Delivery](./progressive_delivery.md) — Argo Rollouts, Flagger, Canary, Blue-Green.
- [Deployment с Service Mesh](./deployment_with_servicemesh.md) — Istio, Gateway API, circuit breaking.
- [Deployment с GitOps](./deployment_with_gitops.md) — ArgoCD, Flux, reconciliation.

### Мониторинг и диагностика
- [Мониторинг и наблюдаемость](./deployment_monitoring_observability.md) — метрики, алерты, dashboards.
- [Продвинутые сценарии диагностики](./advanced_troubleshooting_scenarios.md) — реальные кейсы из продакшена.

### Смежные темы
- [Сравнение стратегий развертывания](../../../CI-CD/Deployment_Strategies/comparison.md) — детальное сравнение RollingUpdate, Canary и Blue-Green.
- [HPA (Horizontal Pod Autoscaler)](../../Autoscaling/HPA/index.md) — автоматическое масштабирование Deployment на основе метрик.
- [Pod Security Context](../../Security/pod_security_context.md) — безопасность на уровне контейнеров.
- [Управление ресурсами](../../Scheduling/qos_limit_and_requests.md) — лимиты и реквесты CPU/RAM.
