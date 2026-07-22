# CRD (Custom Resource Definition) — пользовательские ресурсы

## Определения

**Custom Resource Definition (CRD)** — это мощный механизм расширения **API (Application Programming Interface)** Kubernetes, позволяющий создавать собственные типы ресурсов (Kind) без необходимости разработки и развертывания отдельного API-сервера.

С помощью CRD формируется декларативный контракт:
*   **Схема данных**: описание полей, их типов и правил валидации.
*   **Метаданные**: API-группа, версия и область видимости (Namespaced или Cluster).
*   **Поведение**: интеграция со стандартными механизмами K8s (RBAC, HPA, Finalizers).

Логику обработки этих ресурсов (сверку желаемого и фактического состояний) реализует внешний компонент — [контроллер или оператор](./kubernetes_operators.md).

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

### Подресурсы (Subresources)
*   **`/status`**: Критически важен для производительности. Позволяет контроллеру обновлять статус ресурса, не изменяя `metadata.generation` спецификации. Это предотвращает бесконечные циклы реконсиляции.
*   **`/scale`**: Позволяет внешним инструментам (например, HPA) масштабировать ваш ресурс так же, как стандартные Deployment.

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
