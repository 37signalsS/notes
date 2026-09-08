# CRD (Custom Resource Definition) — пользовательские ресурсы

## Определение

**Custom Resource Definition (CRD)** — это фундаментальный механизм расширения **API (Application Programming Interface)** Kubernetes. Он позволяет пользователям определять собственные типы ресурсов (Kind) без внесения изменений в исходный код ядра Kubernetes и без развертывания отдельного API-сервера.

CRD выступает в роли **чертежа (blueprint)**, который обучает API-сервер Kubernetes новой схеме данных. После регистрации CRD кластер начинает обрабатывать кастомные объекты (Custom Resources) точно так же, как стандартные `Pod` или `Service`.

**Ключевая роль:** CRD являются основой для реализации паттерна **[Оператор](./kubernetes_operators.md)**, позволяя декларативно описывать сложные системы (например, кластеры баз данных, системы бэкапа или сертификаты) и управлять ими через стандартные инструменты типа `kubectl`.

### Архитектурное место в стеке Kubernetes

CRD работает на уровне **API-сервера** — это не отдельный компонент, а часть обработки запросов:

```
kubectl apply -f crd.yaml
        │
        ▼
   API Server ──── Aутентификация (RBAC)
        │
        ▼
   Admission Controllers (Mutating → Validating)
        │
        ▼
   apiextensions-apiserver ──── Регистрация CRD
        │
        ▼
   etcd (хранение схемы в /registry/apiextensions.k8s.io/)
```

После регистрации CRD API-сервер начинает принимать запросы к новому API-группу. Конвертация между версиями, валидация через OpenAPI v3 и CEL, а также подресурсы (`/status`, `/scale`) — все это обрабатывается нативно без внешних зависимостей.

**API-группа CRD:** `apiextensions.k8s.io` (встроена в API-сервер). CRD относятся к **cluster-scoped** ресурсам — они не привязаны к конкретному namespace и доступны глобально.

---

## Основные концепции

### Структурные схемы (Structural Schemas)
Начиная с `apiextensions.k8s.io/v1`, все CRD обязаны использовать **структурную схему** в формате OpenAPI v3 (`openAPIV3Schema`). Это гарантирует, что API-сервер понимает структуру ресурса для:
*   **Валидации**: Проверка типов данных и ограничений при создании или обновлении объекта.
*   **Очистки (Pruning)**: Механизм безопасности, который автоматически удаляет поля, не описанные в схеме, предотвращая накопление "мусора" в `etcd`.
*   **Defaulting**: Автоматическая установка значений по умолчанию для пропущенных полей.

### Валидация через CEL (Common Expression Language)
Современный стандарт (K8s 1.25+) — использование **CEL** внутри манифеста CRD через поле `x-kubernetes-validations`. Это позволяет описывать сложную логику без написания внешних вебхуков:
*   **Межполевая проверка**: `self.minReplicas <= self.replicas`.
*   **Неизменяемость (Immutability)**: `self == oldSelf` (запрет изменения поля после создания).
*   **Регулярные выражения**: Проверка формата строк напрямую на уровне API-сервера.

### Admission Webhooks (Веб-перехватчики допуска)
Если возможностей CEL недостаточно, Kubernetes позволяет подключить внешние сервисы для обработки запросов:
1.  **Mutating Admission Webhook**: Может изменять объект перед сохранением (например, добавлять sidecar-контейнеры или специфические метки).
2.  **Validating Admission Webhook**: Проверяет итоговое состояние объекта и разрешает или отклоняет запрос.

### Подресурсы (Subresources)
*   **`/status`**: Позволяет контроллеру обновлять статус ресурса, не изменяя `metadata.generation` спецификации. Это критично для предотвращения бесконечных циклов реконсиляции. При обновлении `/status` из `spec` не пересчитывается `generation`, что позволяет оператору отличать «внешнее» изменение от «внутреннего».
*   **`/scale`**: Позволяет внешним инструментам (HPA, `kubectl scale`) управлять количеством реплик в вашем ресурсе. Реализует интерфейс `autoscaling/v1` и требует указания полей `spec.replicas` и `status.replicas` (а также опционально `status.selector` и `status.targetSelector`).

**Включение подресурсов в CRD:**
```yaml
subresources:
  status: {}    # включает PUT/PATCH на /status
  scale:        # включает GET/PUT/PATCH на /scale
    specReplicasPath: .spec.replicas
    statusReplicasPath: .status.replicas
    labelSelectorPath: .status.selector    # опционально, для HPA
```

**Важно:** Подресурс `/status` требует отдельного RBAC-разрешения (`update` на подресурс `status`), что позволяет изолировать права контроллера от прав пользователя на изменение `spec`.

## Жизненный цикл и управление

### Финализаторы (Finalizers)
Механизм управляемого удаления. Если в `metadata.finalizers` есть записи, Kubernetes не удалит объект сразу, а установит `deletionTimestamp`. Контроллер должен:
1. Увидеть метку удаления и выполнить очистку внешних ресурсов (например, удалить БД в облаке).
2. Удалить свою запись из списка финализаторов.
3. Только когда список пуст, объект физически удаляется из `etcd`.

### Версионирование и конвертация

CRD поддерживают одновременное сосуществование нескольких версий (например, `v1alpha1`, `v1beta1`, `v1`). Это критично для эволюции API без нарушения обратной совместимости.

*   **Storage Version**: Только одна версия помечается как `storage: true`. В этом формате данные физически хранятся в `etcd`. При обновлении CRD с новой storage version все существующие объекты автоматически конвертируются.
*   **Served Version**: Версии с `served: true` доступны для чтения и записи через API. Клиенты (kubectl, контроллеры) могут запрашивать любую served-версию.
*   **Conversion Webhook**: Если структура полей сильно изменилась между версиями, вызывается внешний сервис для трансформации объекта «на лету» при чтении или записи. Альтернатива — **Rewrite** (K8s 1.15+), который просто переименовывает поля при несущественных изменениях.

**Стратегии конвертации:**

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **None** (по умолчанию) | Версии идентичны по структуре, отличаются только именем | Minor-обновления, переименование полей |
| **Webhook** | Внешний HTTP-сервис конвертирует объект | Сложные изменения структуры, мажорные версии |
| **Rewrite** | Автоматическое переименование полей через `x-kubernetes-list-type` | Простые переименования без изменения логики |

**Пример Conversion Webhook:**
```yaml
conversion:
  strategy: Webhook
  webhook:
    clientConfig:
      service:
        namespace: system
        name: webhook-service
        path: /convert
      caBundle: <base64-encoded-ca>
    conversionReviewVersions: ["v1"]
```

---

## Практические команды

### Управление CRD

```bash
# Получить список всех CRD в кластере
kubectl get crd
# → NAME                          CREATED AT
# → backups.example.io            2025-01-15T10:00:00Z
# → books.packt.com               2025-01-15T09:00:00Z

# Подробная информация о конкретном CRD
kubectl describe crd backups.example.io

# Просмотр определения CRD в YAML
kubectl get crd backups.example.io -o yaml

# Просмотр доступных API-ресурсов (включая кастомные)
kubectl api-resources | grep example.io
# → backups    bk    example.io/v1    true    Backup

# Проверка версий CRD
kubectl get crd backups.example.io -o jsonpath='{.spec.versions[*].name}'
# → v1 v1alpha1

# Удаление CRD (ВНИМАНИЕ: удаляет все экземпляры этого ресурса!)
kubectl delete crd backups.example.io
```

### Управление кастомными ресурсами (CR)

```bash
# Создание CR из манифеста
kubectl apply -f backup-cr.yaml

# Просмотр всех экземпляров кастомного ресурса
kubectl get backups
# → NAME            PHASE      AGE
# → pg-backup-daily Running    5m

# Просмотр с дополнительными колонками (если определены в CRD)
kubectl get backups -o wide

# Детали конкретного CR
kubectl describe backup pg-backup-daily

# Просмотр в YAML
kubectl get backup pg-backup-daily -o yaml

# Обновление CR (изменение spec)
kubectl patch backup pg-backup-daily --type=merge -p '{"spec":{"retentionDays":14}}'

# Удаление CR
kubectl delete backup pg-backup-daily

# Просмотр CR с фильтрацией по label
kubectl get backups -l app=postgres

# Просмотр всех CR определенного типа во всех namespace
kubectl get backups --all-namespaces

# Просмотр events связанных с CR
kubectl get events --field-selector reason=SuccessfulCreate -n default

# Экспорт всех CRD в YAML (для бэкапа)
kubectl get crds -o yaml > crds-backup.yaml

# Экспорт всех экземпляров CR (для бэкапа)
for crd in $(kubectl get crd -o name); do
  kubectl get $(echo $crd | cut -d/ -f2) -A -o yaml >> custom-resources.yaml 2>/dev/null
done
```

### Диагностические команды

```bash
# Проверка доступности API-группы кастомного ресурса
kubectl api-resources --api-group=example.io

# Проверка версий API
kubectl api-versions | grep example.io
# → example.io/v1

# Просмотр схемы валидации CRD
kubectl get crd backups.example.io -o jsonpath='{.spec.versions[0].schema.openAPIV3Schema.properties.spec}' | jq .

# Проверка finalizers на CR
kubectl get backup pg-backup-daily -o jsonpath='{.metadata.finalizers}'

# Проверка status subresource
kubectl get backup pg-backup-daily -o jsonpath='{.status}'

# Принудительное удаление CR с зависшими finalizers
kubectl patch backup pg-backup-daily -p '{"metadata":{"finalizers":null}}' --type=merge

# Проверка conversion webhook (если настроен)
kubectl get crd backups.example.io -o jsonpath='{.spec.conversion}'

# Просмотр RBAC-разрешений для кастомного ресурса
kubectl auth can-i list backups --as=system:serviceaccount:default:my-operator
# → yes

kubectl auth can-i create backups/status --as=system:serviceaccount:default:my-operator
# → yes
```

---

### Сценарий 1: Базовый пример (Ресурс для учета книг)
Минимальный манифест CRD с двумя полями в спецификации.

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: books.packt.com
spec:
  group: packt.com
  names:
    kind: Book
    listKind: BookList
    plural: books
    singular: book
    shortNames: ["bk"]
  scope: Namespaced
  versions:
  - name: v1
    served: true
    storage: true
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec:
            type: object
            properties:
              bookName: {type: string}
              year: {type: integer}
```

**Экземпляр ресурса (Custom Resource):**
```yaml
apiVersion: packt.com/v1
kind: Book
metadata:
  name: k8s-interview-guide
spec:
  bookName: "K8S руководство по собеседованию"
  year: 2024
```

### Сценарий 2: Продвинутый CRD (Система бэкапа с CEL и колонками)
Пример ресурса с использованием подресурсов, CEL-валидации и дополнительных колонок для вывода в `kubectl`.

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: backups.example.io
spec:
  group: example.io
  names:
    kind: Backup
    plural: backups
    singular: backup
    shortNames: [bk]
    categories: ["all", "storage"] # Категории для группировки
  scope: Namespaced
  versions:
  - name: v1
    served: true
    storage: true
    subresources:
      status: {} # Включение подресурса статуса
    schema:
      openAPIV3Schema:
        type: object
        required: ["spec"]
        properties:
          spec:
            type: object
            required: ["target", "retentionDays"]
            properties:
              target:
                type: string
              retentionDays:
                type: integer
                minimum: 1
                maximum: 365
                default: 7
              immutableField:
                type: string
                x-kubernetes-validations:
                  - rule: "self == oldSelf"
                    message: "Это поле нельзя изменить после создания"
          status:
            type: object
            properties:
              phase:
                type: string
              observedGeneration:
                type: integer
              conditions:
                type: array
                items:
                  type: object
                  properties:
                    type: {type: string}
                    status: {type: string}
                    message: {type: string}
    additionalPrinterColumns:
    - name: Target
      type: string
      jsonPath: .spec.target
    - name: Phase
      type: string
      jsonPath: .status.phase
    - name: Age
      type: date
      jsonPath: .metadata.creationTimestamp
```

**Экземпляр кастомного ресурса (CR):**
```yaml
apiVersion: example.io/v1
kind: Backup
metadata:
  name: pg-backup-daily
spec:
  target: "postgres-prod"
  retentionDays: 30
  immutableField: "fixed-value"
```

---

## Дополнительная информация

### Безопасность и RBAC

Пользовательские ресурсы полностью интегрированы в систему **[RBAC](../Security/rbac/rbac_overview.md)**. После создания CRD необходимо явно разрешить доступ к нему.

**API-группа** для кастомных ресурсов формируется по шаблону: `имя-группы` или `имя-группы/версия` (например, `example.io` или `example.io/v1`).

**Пример ClusterRole для доступа к кастомным ресурсам:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: backup-viewer
rules:
- apiGroups: ["example.io"]
  resources: ["backups"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["example.io"]
  resources: ["backups/status"]    # отдельное разрешение на подресурс
  verbs: ["get"]
```

**Пример ClusterRole для полного управления (оператор):**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: backup-operator
rules:
- apiGroups: ["example.io"]
  resources: ["backups"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["example.io"]
  resources: ["backups/status"]
  verbs: ["get", "update", "patch"]
- apiGroups: ["example.io"]
  resources: ["backups/finalizers"]
  verbs: ["update"]
```

**Пример Role для namespace-scoped CRD:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: backup-editor
  namespace: production
rules:
- apiGroups: ["example.io"]
  resources: ["backups"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["example.io"]
  resources: ["backups/status"]
  verbs: ["get", "update", "patch"]
```

**Важные нюансы:**
*   Права на обновление `/status` должны быть выделены отдельно для контроллера. Это предотвращает случайное или злонамеренное изменение статуса пользователями.
*   Права на `/finalizers` необходимы операторам для управления жизненным циклом удаления.
*   Для namespace-scoped CRD используйте `Role` + `RoleBinding`, для cluster-scoped — `ClusterRole` + `ClusterRoleBinding`.
*   При проверке прав используйте `kubectl auth can-i` для отладки RBAC-политик.

### Рекомендации (Best Practices)
*   **Используйте CEL**: Избегайте вебхуков валидации, если логику можно описать через CEL. Это снижает нагрузку на сеть и упрощает эксплуатацию. CEL работает нативно в API-сервере (K8s 1.25+ для CRD, 1.30+ для VAP), не требует внешних сервисов и имеет нулевую задержку сети.
*   **Статус и observedGeneration**: Всегда включайте `observedGeneration` в статус. Это позволяет пользователю понять, соответствует ли текущий статус последней версии спецификации. Контроллер должен обновлять `observedGeneration` при каждом цикле реконсиляции.
*   **CRD vs API Aggregation**: Используйте CRD в 99% случаев. API Aggregation нужен только если требуется кастомное хранилище (не `etcd`) или специфическая логика API (например, потоковая передача данных). CRD проще в управлении, не требует отдельного API-сервера и поддерживает все стандартные механизмы K8s (RBAC, Admission, Webhooks).
*   **Именование CRD**: Используйте обратный доменный формат (`backups.example.io`). Имя CRD должно быть уникальным в кластере. `plural` и `singular` задают URL-пути API. `shortNames` ускоряют работу с `kubectl`.
*   **Структура статуса**: Включайте в `status` стандартные поля: `phase` (текущее состояние), `conditions` (список условий), `observedGeneration` (последняя обработанная версия spec). Это обеспечивает наблюдаемость и совместимость с инструментами мониторинга.
*   **Версионирование**: Начинайте с `v1alpha1` для экспериментов, переходите на `v1beta1` для стабильного API, и `v1` для production. Храните не более 3 версий одновременно. Всегда помечайте storage version.
*   **Ограничение количества CRD**: В кластере не должно быть более 500-1000 CRD. Каждая CRD добавляет нагрузку на API-сервер и увеличивает время старта контроллеров. При большом количестве CRD рассмотрите агрегацию или Hub-and-Spoke модель.

### Ограничения и известные особенности
*   **Размер etcd**: Каждый CR хранится в `etcd` как отдельная запись. При большом количестве CR (десятки тысяч) это может привести к деградации etcd и увеличению задержек API-сервера. Мониторьте размер etcd и количество записей.
*   **Время старта API-сервера**: При большом количестве CRD (>500) время старта API-сервера увеличивается, так как каждая CRD требует регистрации схемы. Используйте кеширование и lazy loading.
*   **Односторонняя конвертация**: Conversion Webhook конвертирует объекты при чтении/записи, но не изменяет данные в `etcd`. При смене storage version все объекты конвертируются автоматически, но это может занять время в больших кластерах.
*   **Нет встроенной ACL**: CRD не имеют встроенных механизмов контроля доступа на уровне полей. Для этого используйте Admission Webhooks или CEL-валидацию с `x-kubernetes-validations`.
*   **Нет каскадного удаления по умолчанию**: При удалении CRD Kubernetes не удаляет автоматически связанные CR. Это может привести к "осиротевшим" ресурсам. Используйте finalizers или仆/disposal-логику в операторе.

### Миграция между версиями CRD

**Безопасная миграция на новую storage version:**

```bash
# 1. Добавьте новую версию как served (но не storage)
kubectl apply -f crd-v2.yaml    # v2: served=true, storage=false

# 2. Убедитесь, что контроллеры поддерживают обе версии
kubectl get crd backups.example.io -o jsonpath='{.spec.versions[*].served}'
# → true true

# 3. Конвертируйте все объекты на новую версию (принудительно)
kubectl get backups -A -o json | \
  kubectl replace -f -    # пересоздает каждый CR, конвертируя в storage version

# 4. Переключите storage на новую версию
kubectl patch crd backups.example.io --type=merge -p '{
  "spec": {
    "versions": [
      {"name": "v1", "served": true, "storage": false},
      {"name": "v2", "served": true, "storage": true}
    ]
  }
}'

# 5. (Опционально) Удалите старую версию после проверки
kubectl patch crd backups.example.io --type=merge -p '{
  "spec": {
    "versions": [
      {"name": "v2", "served": true, "storage": true}
    ]
  }
}'
```

**Рекомендации по миграции:**
*   Всегда тестируйте миграцию в staging-кластере перед production.
*   При использовании Conversion Webhook убедитесь, что webhook доступен и возвращает корректные ответы.
*   Мониторьте `conversion_errors_total` (метрика API-сервера) для обнаружения ошибок конвертации.
*   При большом количестве объектов (>10000) миграция может занять часы — планируйте окно обслуживания.

### См. также
*   [Операторы и контроллеры](./kubernetes_operators.md) — логика управления ресурсами.
*   [Архитектура Control Plane](./control_plane_architecture.md) — как обрабатываются запросы к API.
*   [RBAC — управление доступом](../Security/rbac/rbac_overview.md) — настройка прав на кастомные ресурсы.
