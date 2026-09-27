# Alertmanager StatefulSet: Манифест и конфигурация

## Определения

**Alertmanager StatefulSet** — основной ресурс Kubernetes для развёртывания Alertmanager. Использование StatefulSet вместо Deployment обеспечивает стабильные сетевые идентификаторы (например, `alertmanager-0`), что критически важно для работы Gossip-протокола кластеризации, и гарантирует привязку PersistentVolume для сохранения состояния (silences, журнал уведомлений).

**Расширение переменных окружения (External Variable Expansion)** — функция Alertmanager (v0.27+), позволяющая динамически подставлять значения из ENV напрямую в `alertmanager.yml` через синтаксис `${VAR_NAME}`, что исключает хранение секретов в ConfigMap.

## Предварительные требования

- Namespace `monitoring` создан и активен: `kubectl get ns monitoring`.
- Создан [Kubernetes Secret](./secrets.md) с реальными значениями (`smtp.password`, `telegram.token`, `telegram.chat_id`).
- Создан [ConfigMap с конфигурацией](./alertmanager-config.md) `alertmanager-config` и, при необходимости, [ConfigMap с шаблонами](./alertmanager-templates.md) `alertmanager-templates`.
- Создан [Headless Service](./services.md) `alertmanager-mesh` в namespace `monitoring`.
- В кластере доступна StorageClass для динамического provisioning PVC (`kubectl get storageclass`).
- `kubectl` настроен с правами на создание ресурсов в namespace `monitoring`.

> **См. также:** [Развёртывание Alertmanager в Kubernetes](../../../alertmanager.md#развёртывание-в-kubernetes-через-манифесты).

---

## Основные концепции

### Почему StatefulSet, а не Deployment

Alertmanager хранит состояние (silences, история отправки уведомлений) на диске и использует Gossip-протокол для синхронизации между репликами. StatefulSet предоставляет гарантии, которых нет у Deployment:

| Гарантия | StatefulSet | Deployment |
| :--- | :--- | :--- |
| Стабильное DNS-имя | `alertmanager-0`, `alertmanager-1` | Случайное имя при каждом пересоздании |
| Стабильное хранилище | Каждый под имеет свой PVC (`volumeClaimTemplates`) | Общий набор томов или `emptyDir` |
| Порядок запуска | Последовательный (0 → 1 → 2) | Одновременный |
| Порядочный останов | Последовательный (2 → 1 → 0) | Одновременный |

Deployment подходит для stateless-приложений. Для Alertmanager StatefulSet является обязательным выбором в production-средах.

### Структура пода и безопасность

В современных инсталляциях (2025–2026) акцент делается на безопасности и нативной интеграции с секретами Kubernetes.

| Компонент | Назначение |
| :--- | :--- |
| **Alertmanager** | Образ `prom/alertmanager:v0.27.0`. Флаг `--config.expand-external-variables` активирует подстановку ENV. |
| **SecurityContext** | Запуск от non-root пользователя (`uid: 65534`) для минимизации привилегий контейнера. |
| **Кластеризация** | Использование флага `--cluster.peer` для связи реплик через Headless Service. |
| **Пробы (Probes)** | Проверки `/-/healthy` и `/-/ready` для управления трафиком и автоматического перезапуска при сбоях. |

### Pod Management Policy

Параметр `podManagementPolicy` управляет поведением контроллера при создании и удалении подов:

- **`OrderedReady` (по умолчанию):** поды создаются и удаляются последовательно, один за другим. Контроллер дожидается Ready состояния каждого пода перед созданием следующего. Подходит для production, так как исключает перегрузку кластера при старте.
- **`Parallel`:** поды создаются и удаляются одновременно. Ускоряет процесс, но увеличивает пиковую нагрузку на API-сервер и хранилище. Используется для не критичных к порядку запуска stateful-приложений.

### Update Strategy

Параметр `updateStrategy` определяет поведение при изменении манифеста StatefulSet (например, обновление образа или изменение ресурсов):

- **`RollingUpdate` (по умолчанию):** поды обновляются последовательно от старшего индекса к младшему. Контроллер ждет Ready каждого нового пода перед удалением старого.
  - `partition: N` — обновляются только поды с индексом ≥ N. Используется для canary-развёртывания: сначала обновляется одна реплика, проверяется стабильность, затем partition снимается (`partition: 0`).
  - `maxUnavailable` (K8s 1.35+ Beta) — позволяет обновлять несколько подов параллельно, ускоряя rollout при условии, что PDB разрешает временное уменьшение доступных реплик.
- **`OnDelete`:** автоматического обновления нет. После изменения манифеста поды нужно удалять вручную. Контроллер создаст новые поды с новой ревизией только после явного `kubectl delete pod`. Подходит для сценариев, где требуется полный контроль над процессом обновления.

### PersistentVolumeClaim Retention Policy

Начиная с Kubernetes 1.32 (GA), параметр `persistentVolumeClaimRetentionPolicy` позволяет гибко управлять судьбой PVC при удалении или масштабировании StatefulSet:

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `whenDeleted` | Что делать с PVC при полном удалении StatefulSet. | `Retain` — PVC сохраняются. |
| `whenScaled` | Удалять ли PVC при уменьшении количества реплик. | `Delete` — PVC для удалённых индексов удаляются. |

Для production рекомендуется явно указывать политики, чтобы избежать утечек дискового пространства при неконтролируемом удалении ресурсов.

### Схема томов (Volumes)

| Том | Источник | Точка монтирования | Описание |
| :--- | :--- | :--- | :--- |
| `config` | ConfigMap | `/etc/alertmanager` | Содержит основной файл конфигурации с плейсхолдерами. |
| `templates` | ConfigMap | `/etc/alertmanager/templates` | Кастомные Go-шаблоны оформления уведомлений. |
| `data` | PVC | `/alertmanager` | Персистентное хранилище (1Gi, ReadWriteOnce). |

---

## Практические сценарии

### Манифест StatefulSet (Production-ready)

Пример конфигурации с пробами, ресурсами и безопасным контекстом.

**`alertmanager-statefulset.yaml`**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: alertmanager
  namespace: monitoring
spec:
  serviceName: alertmanager-mesh
  replicas: 3
  podManagementPolicy: OrderedReady
  updateStrategy:
    type: RollingUpdate
  revisionHistoryLimit: 10
  selector:
    matchLabels:
      app: alertmanager
  template:
    metadata:
      labels:
        app: alertmanager
    spec:
      securityContext:
        runAsUser: 65534
        runAsGroup: 65534
        fsGroup: 65534
      serviceAccountName: alertmanager
      containers:
        - name: alertmanager
          image: prom/alertmanager:v0.27.0
          args:
            - "--config.file=/etc/alertmanager/alertmanager.yml"
            - "--storage.path=/alertmanager"
            - "--data.retention=120h"
            - "--config.expand-external-variables"
            - "--cluster.listen-address=0.0.0.0:9094"
            - "--cluster.peer=alertmanager-mesh.monitoring.svc.cluster.local:9094"
          ports:
            - name: web
              containerPort: 9093
            - name: mesh
              containerPort: 9094
          resources:
            requests: { cpu: 100m, memory: 128Mi }
            limits: { cpu: 200m, memory: 256Mi }
          livenessProbe:
            httpGet: { path: /-/healthy, port: web }
            initialDelaySeconds: 30
            timeoutSeconds: 5
          readinessProbe:
            httpGet: { path: /-/ready, port: web }
            initialDelaySeconds: 15
            timeoutSeconds: 5
          env:
            - name: SMTP_PASSWORD
              valueFrom: { secretKeyRef: { name: alertmanager-secret, key: smtp.password } }
            - name: TELEGRAM_TOKEN
              valueFrom: { secretKeyRef: { name: alertmanager-secret, key: telegram.token } }
            - name: TELEGRAM_CHAT_ID
              valueFrom: { secretKeyRef: { name: alertmanager-secret, key: telegram.chat_id } }
          volumeMounts:
            - name: config
              mountPath: /etc/alertmanager
            - name: templates
              mountPath: /etc/alertmanager/templates
              readOnly: true
            - name: alertmanager-data
              mountPath: /alertmanager
      volumes:
        - name: config
          configMap: { name: alertmanager-config }
        - name: templates
          configMap: { name: alertmanager-templates }
  volumeClaimTemplates:
    - metadata:
        name: alertmanager-data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources: { requests: { storage: 1Gi } }
```

**Пояснение ключевых параметров:**

| Параметр | Значение | Обоснование |
| :--- | :--- | :--- |
| `serviceName` | `alertmanager-mesh` | Должен совпадать с Headless Service для корректного DNS. |
| `replicas` | `3` | Минимальное количество для HA. При потере quorum (2 из 3) кластер продолжает работать. |
| `--data.retention=120h` | `120h` | Хранение silences и журнала уведомлений. Подберите значение под ваши требования. |
| `--cluster.peer` | FQDN Headless Service | Gossip-протокол использует DNS для обнаружения пиров. |
| `revisionHistoryLimit` | `10` | Количество сохранённых ревизий для `rollout undo`. |
| `readOnly: true` | для `templates` | Защита от случайной записи в ConfigMap-том. |

### ServiceAccount и RBAC

Для соблюдения принципа минимальных привилегий создайте отдельный ServiceAccount для Alertmanager. Манифест RBAC приведён в [secrets.md](./secrets.md#rbac-ограничение-доступа-к-секретам).

### Применение манифеста

```bash
# Dry-run перед применением
kubectl apply -f alertmanager-statefulset.yaml --dry-run=client
# → statefulset.apps/alertmanager created (dry run)

# Применение
kubectl apply -f alertmanager-statefulset.yaml
# → statefulset.apps/alertmanager created

# Если StatefulSet уже существует — обновление
kubectl apply -f alertmanager-statefulset.yaml
# → statefulset.apps/alertmanager configured
```

### Проверка rollout'а

```bash
# Ожидание готовности всех реплик
kubectl rollout status statefulset/alertmanager -n monitoring --timeout=180s
# → statefulset rolling rollout complete: 3 pods

# Мониторинг создания подов в реальном времени
kubectl get pods -n monitoring -l app=alertmanager -w
# → alertmanager-0   1/1     Running   0          30s
# → alertmanager-1   1/1     Running   0          1m
# → alertmanager-2   1/1     Running   0          1m30s
```

### Проверка PVC

```bash
# Список PVC, созданных через volumeClaimTemplates
kubectl get pvc -n monitoring
# NAME                  STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# alertmanager-data-0   Bound    pvc-8f3b2c1d-4e5f-4a6b-8c9d-0e1f2a3b4c5d   1Gi        RWO            standard        2m
# alertmanager-data-1   Bound    pvc-9g4c3d2e-5f6a-4b7c-9d0e-1f2a3b4c5d6e   1Gi        RWO            standard        2m
# alertmanager-data-2   Bound    pvc-0h5d4e3f-6a7b-4c8d-0e1f-2a3b4c5d6e7f   1Gi        RWO            standard        2m
```

### Проверка DNS имён

Для проверки DNS-обнаружения подов StatefulSet и Headless Service используйте команды из [Сетевой доступ: Сервисы и Ingress](./services.md#dns-проверка-изнутри-кластера).

### Проверка кластеризации

```bash
# Проверка API кластеризации
kubectl exec -n monitoring alertmanager-0 -c alertmanager -- \
  curl -s http://localhost:9093/api/v2/status | jq .
# → {
#     "cluster": {
#       "status": "ready",
#       "peers": [
#         {"name": "alertmanager-0", "address": "10.244.0.10:9094"},
#         {"name": "alertmanager-1", "address": "10.244.0.11:9094"},
#         {"name": "alertmanager-2", "address": "10.244.0.12:9094"}
#       ]
#     }
#   }
```

### Масштабирование

```bash
# Масштабирование до 5 реплик
kubectl scale statefulset/alertmanager -n monitoring --replicas=5
# → statefulset.apps/alertmanager scaled

# Проверка появления новых подов и PVC
kubectl get pods -n monitoring -l app=alertmanager -w
kubectl get pvc -n monitoring
```

При уменьшении количества реплик (`whenScaled: Delete`) PVC для удалённых индексов будут удалены автоматически.

### Обновление образа (Rolling Update)

```bash
# Обновление до новой версии
kubectl set image statefulset/alertmanager \
  -n monitoring \
  alertmanager=prom/alertmanager:v0.28.0
# → statefulset.apps/alertmanager image updated

# Отслеживание прогресса (обновление идёт от старшего индекса к младшему)
kubectl rollout status statefulset/alertmanager -n monitoring --timeout=180s
# → statefulset rolling rollout complete: 3 pods

# Проверка истории ревизий
kubectl rollout history statefulset/alertmanager -n monitoring
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         <none>
```

#### Canary-обновление через partition

Для критических сред используйте partition для поэтапного обновления:

```bash
# Обновить только последнюю реплику (alertmanager-2)
kubectl patch statefulset/alertmanager -n monitoring -p '{
  "spec": {
    "updateStrategy": {
      "type": "RollingUpdate",
      "rollingUpdate": {
        "partition": 2
      }
    }
  }
}'

# После проверки стабильности — обновить все реплики
kubectl patch statefulset/alertmanager -n monitoring -p '{
  "spec": {
    "updateStrategy": {
      "rollingUpdate": {
        "partition": 0
      }
    }
  }
}'
```

### Перезапуск после изменения ConfigMap

```bash
# При изменении ConfigMap поды не перезапускаются автоматически
kubectl apply -f alertmanager-config.yaml
kubectl rollout restart statefulset/alertmanager -n monitoring

# Ожидание завершения перезапуска
kubectl rollout status statefulset/alertmanager -n monitoring --timeout=180s

# Для автоматического перезапуска используйте checksum-аннотации
kubectl annotate statefulset/alertmanager -n monitoring \
  kubectl.kubernetes.io/restartedAt="$(date -Iseconds)" \
  --overwrite
```

### Отладка проблем запуска

#### CrashLoopBackOff

```bash
# Получение логов пода
kubectl logs -n monitoring alertmanager-0 -c alertmanager --previous
# → panic: unable to load configuration...

# Распространённые причины:
# - Ошибка синтаксиса в alertmanager.yml
# - Отсутствие Secret (проверка RBAC)
# - Несовместимость версии Alertmanager с директивами конфигурации
```

#### ImagePullBackOff / ErrImagePull

```bash
# Проверка описания пода
kubectl describe pod -n monitoring alertmanager-0
# → Warning  Failed     5s (x3 over 15s)  kubelet
# → Failed to pull image "prom/alertmanager:v0.27.0": rpc error: ...

# Решения:
# - Проверить доступность образа: docker pull prom/alertmanager:v0.27.0
# - Проверить ImagePullSecret (если образ в приватном реестре)
# - Исправить тег образа в манифесте
```

#### Pod в состоянии Pending

```bash
# Проверка событий пода
kubectl describe pod -n monitoring alertmaker-0
# → Warning  FailedScheduling  0/3 nodes are available: 3 Insufficient cpu.

# Решения:
# - Увеличить requests в StatefulSet
# - Проверить доступность StorageClass: kubectl get storageclass
# - Проверить ResourceQuota в namespace
```

### Проверка состояния кластера

```bash
# Просмотр активных алертов
kubectl exec -n monitoring alertmanager-0 -c alertmanager -- \
  amtool alert --query='.status.firing'
# → alertmanager-0  firing   critical  TestAlert  2025-01-15 10:00:00

# Валидация конфигурации
kubectl exec -n monitoring alertmanager-0 -c alertmanager -- \
  amtool check-config /etc/alertmanager/alertmanager.yml
# → Checking /etc/alertmanager/alertmanager.yml
# → SUCCESS

# Просмотр дерева маршрутизации
kubectl exec -n monitoring alertmanager-0 -c alertmanager -- \
  amtool config routes show
```

---

## Рекомендации

- **Версионирование:** храните манифесты StatefulSet в Git с версионированием. При изменении увеличивайте ревизию в имени файла или используйте аннотации.
- **Immutable ConfigMap:** для production рассмотрите `immutable: true` в metadata ConfigMap (см. [Конфигурация (ConfigMap)](./alertmanager-config.md#gitops-паттерн-configmap--secret--statefulset)).
- **Порядок обновления:** Always update configuration before restarting pods. Используйте `kubectl apply` для ConfigMap, затем `kubectl rollout restart` для StatefulSet.
- **Область видимости переменных:** переменные ENV подставляются только в `alertmanager.yml`. Шаблоны (`*.tmpl`) не имеют доступа к ENV напрямую.
- **Чек-лист после изменений:**
  1. `kubectl apply` ConfigMap.
  2. `kubectl rollout restart statefulset/alertmanager -n monitoring`.
  3. `kubectl rollout status statefulset/alertmanager -n monitoring --timeout=180s`.
  4. `kubectl exec` с `amtool check-config` и `curl /api/v2/status`.
  5. Отправить тестовый алерт через `curl -XPOST http://alertmanager/api/v1/alerts`.

---

## Очистка ресурсов

```bash
# Удалить StatefulSet (PVC сохраняются по умолчанию)
kubectl delete statefulset alertmanager -n monitoring

# Удалить PVC (если данные больше не нужны)
kubectl delete pvc -n monitoring -l app=alertmanager

# Проверить отсутствие StatefulSet
kubectl get statefulset -n monitoring
# → No resources found

# Проверить отсутствие подов
kubectl get pods -n monitoring -l app=alertmanager
# → No resources found
```

> **Примечание:** Services и ConfigMap не удаляются при удалении StatefulSet. При необходимости полностью очистить namespace, удалите ресурсы в обратном порядке применения (см. [intro.md](./intro.md#очистка-ресурсов)).

---

## Устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Pod в CrashLoopBackOff | Ошибка синтаксиса в `alertmanager.yml` или отсутствие Secret | `kubectl logs -n monitoring alertmanager-0 -c alertmanager` | Исправить YAML, проверить Secret и RBAC |
| Pod в ImagePullBackOff | Образ не найден или нет прав на pull | `kubectl describe pod -n monitoring alertmanager-0` | Исправить тег образа или ImagePullSecret |
| Pod в Pending | Недостаточно ресурсов или отсутствует StorageClass | `kubectl describe pod -n monitoring alertmanager-0` — искать `FailedScheduling` | Увеличить requests, проверить StorageClass |
| Горячий перезапуск падает | ConfigMap смонтирован, но под не перезапущен | `kubectl rollout status statefulset/alertmanager -n monitoring` | Выполнить `kubectl rollout restart` |
| Gossip-рассинхронизация | Headless Service не настроен или порт 9094 закрыт | `kubectl get endpointslices -n monitoring -l kubernetes.io/service-name=alertmanager-mesh` | См. [Сетевой доступ: Сервисы и Ingress](./services.md#устранение-неисправностей) |
| PVC в статусе Pending | Нет доступного StorageClass или квоты | `kubectl describe pvc alertmanager-data-0 -n monitoring` | Проверить StorageClass и ResourceQuota |
| Алерты не доставляются | Конфигурация не применена или переменные не подставлены | `kubectl exec ... amtool check-config /etc/alertmanager/alertmanager.yml` | Проверить синтаксис и флаг `--config.expand-external-variables` |

---

## Дополнительная информация

- **[Конфигурация Alertmanager](./alertmanager-config.md)** — синтаксис `alertmanager.yml` и плейсхолдеры.
- **[Шаблоны сообщений](./alertmanager-templates.md)** — подключение и использование Go Templates.
- **[Сетевой доступ: Сервисы и Ingress](./services.md)** — описание Headless Service для кластеризации.
- **[Секреты Kubernetes](./secrets.md)** — подготовка ключей в Secret для ENV-подстановки.
- **[Введение в tutorial](./intro.md)** — порядок применения манифестов и общая архитектура.
