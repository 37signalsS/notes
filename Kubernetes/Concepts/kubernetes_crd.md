# CRD (Custom Resource Definition) — пользовательские ресурсы

## Определения

**Custom Resource Definition (CRD)** — это мощный механизм расширения **API (Application Programming Interface)** Kubernetes, позволяющий создавать собственные типы ресурсов (Kind) без необходимости разработки и развертывания отдельного API-сервера.

CRD можно рассматривать как **чертеж (blueprint)** пользовательского ресурса. Он определяет:
*   **Схему данных**: описание полей, их типов и правил валидации (OpenAPI v3).
*   **Метаданные**: API-группа, версия и краткие имена (shortNames).
*   **Область видимости (Scope)**: определяет, доступен ли ресурс только в рамках конкретного пространства имен (**Namespaced**) или во всем кластере (**Cluster**).
*   **Поведение**: интеграция со стандартными механизмами K8s (RBAC, HPA, Finalizers).

С помощью CRD вы можете адаптировать Kubernetes под специфические нужды вашего приложения, заставляя кластер «понимать» новые типы объектов (например, `Backup`, `Database`, `Certificate`).

Логику обработки этих ресурсов (сверку желаемого и фактического состояний) реализует внешний компонент — **пользовательский контроллер**, который чаще всего является частью [оператора](./kubernetes_operators.md).

## Основные концепции

### Структурные схемы (Structural Schemas)
Начиная с `apiextensions.k8s.io/v1`, все CRD должны иметь **структурную схему** (`openAPIV3Schema`). Это гарантирует, что API-сервер понимает структуру ресурса для:
*   **Валидации**: Проверка типов данных при создании/обновлении.
*   **Очистки (Pruning)**: Автоматическое удаление полей, не описанных в схеме (защита от "мусора" в etcd).
*   **Defaulting**: Установка значений по умолчанию для пропущенных полей.

### Валидация через CEL (Common Expression Language)
Современный стандарт (K8s 1.25+) — использование **CEL** внутри манифеста CRD через поле `x-kubernetes-validations`. Это позволяет описывать сложную логику без написания Validating Webhooks:
*   **Сравнение полей**: `self.minReplicas <= self.replicas`.
*   **Неизменяемость (Immutability)**: `self == oldSelf` (запрет изменения поля после создания).
*   **Регулярные выражения**: Проверка формата строк на уровне API-сервера.

### Admission Webhooks (Веб-перехватчики допуска)

Если возможностей CEL-валидации недостаточно, Kubernetes позволяет подключить внешние сервисы для обработки запросов к API:

1.  **Mutating Admission Webhook (Мутирующий)**: Вызывается первым. Может изменять объект (например, устанавливать значения по умолчанию, которых нет в схеме, или внедрять дополнительные контейнеры).
2.  **Validating Admission Webhook (Валидирующий)**: Вызывается вторым. Проверяет итоговое состояние объекта и разрешает или отклоняет запрос.

Использование веб-перехватчиков требует наличия запущенного HTTP-сервера с поддержкой TLS и зарегистрированных ресурсов `MutatingWebhookConfiguration` или `ValidatingWebhookConfiguration`.

### Подресурсы (Subresources)
*   **`/status`**: Критически важен для производительности. Позволяет контроллеру обновлять статус ресурса, не изменяя `metadata.generation` спецификации. Это предотвращает бесконечные циклы реконсиляции.
*   **`/scale`**: Позволяет внешним инструментам (например, HPA) масштабировать ваш ресурс так же, как стандартные Deployment.

## Жизненный цикл и использование

1.  **Регистрация**: Создайте YAML-файл с определением `CustomResourceDefinition` и примените его: `kubectl apply -f crd.yaml`. После этого API-сервер начнет распознавать новый тип ресурса.
2.  **Создание экземпляров**: Теперь вы можете создавать объекты этого типа (Custom Resources), используя `kubectl apply -f resource.yaml`.
3.  **Управление**: Пользовательские ресурсы поддерживают стандартные операции `get`, `describe`, `edit`, `delete` через `kubectl`.

### Финализаторы (Finalizers)
Механизм управляемого удаления. Если в `metadata.finalizers` есть записи, K8s не удалит объект сразу, а установит `deletionTimestamp`. Контроллер должен:
1. Выполнить очистку внешних ресурсов (например, удалить БД в облаке).
2. Удалить свою запись из списка финализаторов.
3. Только после этого объект будет физически удален из etcd.

## Версионирование и конвертация

CRD поддерживают одновременное сосуществование нескольких версий (например, `v1alpha1`, `v1beta1`, `v1`).

1.  **Hub-and-Spoke**: Одна версия помечается как `storage: true` (Hub) — в этом формате данные лежат в etcd. Остальные версии (Spokes) конвертируются в Hub при чтении/записи.
2.  **Конвертация**:
    *   `None`: Если схемы версий идентичны (простое переименование версии).
    *   **Webhook**: Вызов внешнего сервиса для трансформации объекта, если структура полей существенно изменилась (например, объединение двух полей в один объект).

## Практические сценарии

### Базовый пример: Ресурс для учета книг
Минимальный манифест CRD с двумя полями в спецификации:

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

**Пример экземпляра (Custom Resource):**
```yaml
apiVersion: packt.com/v1
kind: Book
metadata:
  name: k8s-interview-guide
spec:
  bookName: "K8S руководство по собеседованию"
  year: 2024
```

### Манифест CRD с CEL-валидацией
Пример ресурса для управления резервным копированием:

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
  scope: Namespaced
  versions:
  - name: v1
    served: true
    storage: true
    subresources:
      status: {}
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
```

### Экземпляр кастомного ресурса (CR)

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

## Дополнительная информация

**Best Practices:**
*   **Используйте CEL**: Избегайте вебхуков валидации, если логику можно описать через CEL. Это снижает нагрузку на сеть и упрощает эксплуатацию.
*   **Статус и observedGeneration**: Всегда включайте `observedGeneration` в статус. Это позволяет пользователю понять, соответствует ли текущий статус последней версии спецификации.
*   **RBAC**: Не забывайте создавать роли для доступа к новым CRD. Права на `/status` должны быть выделены отдельно для контроллера. Подробнее: [RBAC в Kubernetes](../Security/rbac/rbac_overview.md).
*   **CRD vs API Aggregation**: Используйте CRD для 99% случаев. API Aggregation нужен только если требуется кастомное хранилище (не etcd) или специфическая логика API (например, потоковая передача данных).

**См. также:**
*   [Операторы и контроллеры](./kubernetes_operators.md) — логика управления ресурсами.
*   [Архитектура API-сервера](./control_plane_architecture.md) — как обрабатываются запросы к CRD.
*   [RBAC — управление доступом](../Security/rbac/rbac_overview.md) — разграничение прав на кастомные ресурсы.
