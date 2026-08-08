# CRD (Custom Resource Definition) — пользовательские ресурсы

## Определение

**Custom Resource Definition (CRD)** — это фундаментальный механизм расширения **API (Application Programming Interface)** Kubernetes. Он позволяет пользователям определять собственные типы ресурсов (Kind) без внесения изменений в исходный код ядра Kubernetes и без развертывания отдельного API-сервера.

CRD выступает в роли **чертежа (blueprint)**, который обучает API-сервер Kubernetes новой схеме данных. После регистрации CRD кластер начинает обрабатывать кастомные объекты (Custom Resources) точно так же, как стандартные `Pod` или `Service`.

**Ключевая роль:** CRD являются основой для реализации паттерна **[Оператор](./kubernetes_operators.md)**, позволяя декларативно описывать сложные системы (например, кластеры баз данных, системы бэкапа или сертификаты) и управлять ими через стандартные инструменты типа `kubectl`.

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
*   **`/status`**: Позволяет контроллеру обновлять статус ресурса, не изменяя `metadata.generation` спецификации. Это критично для предотвращения бесконечных циклов реконсиляции.
*   **`/scale`**: Позволяет внешним инструментам (HPA, `kubectl scale`) управлять количеством реплик в вашем ресурсе.

---

## Жизненный цикл и управление

### Финализаторы (Finalizers)
Механизм управляемого удаления. Если в `metadata.finalizers` есть записи, Kubernetes не удалит объект сразу, а установит `deletionTimestamp`. Контроллер должен:
1. Увидеть метку удаления и выполнить очистку внешних ресурсов (например, удалить БД в облаке).
2. Удалить свою запись из списка финализаторов.
3. Только когда список пуст, объект физически удаляется из `etcd`.

### Версионирование и конвертация
CRD поддерживают одновременное сосуществование нескольких версий (например, `v1alpha1`, `v1`).
*   **Storage Version**: Только одна версия помечается как `storage: true`. В этом формате данные физически хранятся в `etcd`.
*   **Conversion Webhook**: Если структура полей сильно изменилась между версиями, вызывается внешний сервис для трансформации объекта «на лету» при чтении или записи.

---

## Практические сценарии

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
Пользовательские ресурсы полностью интегрированы в систему **[RBAC](../Security/rbac/rbac_overview.md)**. После создания CRD необходимо явно разрешить доступ к нему:
*   Права выдаются на API-группу (например, `example.io`) и ресурс (`backups`).
*   Права на обновление `/status` должны быть выделены отдельно для контроллера.

### Рекомендации (Best Practices)
*   **Используйте CEL**: Избегайте вебхуков валидации, если логику можно описать через CEL. Это снижает нагрузку на сеть и упрощает эксплуатацию.
*   **Статус и observedGeneration**: Всегда включайте `observedGeneration` в статус. Это позволяет пользователю понять, соответствует ли текущий статус последней версии спецификации.
*   **CRD vs API Aggregation**: Используйте CRD в 99% случаев. API Aggregation нужен только если требуется кастомное хранилище (не `etcd`) или специфическая логика API (например, потоковая передача данных).

### См. также
*   [Операторы и контроллеры](./kubernetes_operators.md) — логика управления ресурсами.
*   [Архитектура Control Plane](./control_plane_architecture.md) — как обрабатываются запросы к API.
*   [RBAC — управление доступом](../Security/rbac/rbac_overview.md) — настройка прав на кастомные ресурсы.
