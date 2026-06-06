# CRD (Custom Resource Definition) — пользовательские ресурсы

## Определения

**Custom Resource Definition (CRD)** — это механизм расширения **API (Application Programming Interface)** Kubernetes, позволяющий добавлять собственные типы ресурсов без разработки отдельного API‑сервера.

С помощью CRD формируется контракт: имя ресурса, API‑группа и версия, допустимые поля, правила валидации и доступные подресурсы. Реализацию логики согласования состояния (reconciliation) выполняет [оператор](./kubernetes_operators.md) (контроллер), используя эти ресурсы.

## Основные концепции

### Ключевые элементы CRD

- **Группа и версии (Group and Versions):**
  - `group`: логическое пространство именования (например, `example.io`).
  - `versions`: список версий (`v1alpha1`, `v1beta1`, `v1`). Указывается `served` (доступность через API) и `storage` (версия для хранения в **etcd**).
- **Имена (Names):**
  - `names.kind`: имя типа в CamelCase (например, `Backup`).
  - `shortNames`: короткие псевдонимы для `kubectl` (например, `bk`).
- **Область видимости (Scope):** `Namespaced` (в рамках пространства имён) или `Cluster` (глобально).
- **Схема (Schema):** `openAPIV3Schema` описывает структуру и типы полей на основе OpenAPI v3.
- **Подресурсы (Subresources):**
  - `status`: отделяет желаемое состояние (`spec`) от фактического (`status`), которым управляет контроллер. Позволяет разграничивать права **RBAC (Role-Based Access Control)**.
  - `scale`: интеграция с механизмами **HPA (Horizontal Pod Autoscaler)**.
- **Представление (Printing):** `additionalPrinterColumns` настраивает вывод колонок в `kubectl get`.

### Валидация и финализаторы

Схема CRD обеспечивает серверную валидацию и установку значений по умолчанию (`default`).

**Финализаторы (Finalizers)** используются для управляемого удаления. Когда у объекта есть финализатор, удаление через `kubectl delete` не происходит мгновенно: устанавливается `metadata.deletionTimestamp`. Объект остается в системе, пока контроллер не выполнит очистку (например, удаление внешних ресурсов) и не снимет финализатор.

### Жизненный цикл ресурса

1. **Установка CRD**: регистрация типа в API.
2. **Создание экземпляра**: валидация по схеме, применение значений по умолчанию, сохранение в etcd.
3. **Реконсиляция**: [оператор](./kubernetes_operators.md) обнаруживает объект и выполняет действия.
4. **Удаление**: запуск финализаторов и физическая очистка данных.

### Версионирование и конвертация

CRD поддерживает публикацию нескольких версий API одновременно. При этом только одна версия может быть помечена как `storage: true` — в ней данные сохраняются в etcd.

Для преобразования данных между версиями используются стратегии:

- **`None`**: прямое сопоставление полей (если схемы идентичны).
- **`Webhook`**: API-сервер вызывает внешний вебхук для трансформации объекта. Это позволяет изменять структуру схемы без потери данных.

## Практические сценарии

### Пример манифеста CRD

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
  - name: v1alpha1
    served: true
    storage: true
    schema:
      openAPIV3Schema:
        type: object
        required: ["spec"]
        properties:
          spec:
            type: object
            required: ["target","schedule"]
            properties:
              target:
                type: string
              schedule:
                type: string
              retentionDays:
                type: integer
                minimum: 1
                default: 7
          status:
            type: object
            properties:
              phase:
                type: string
                enum: ["Pending","Running","Succeeded","Failed"]
    subresources:
      status: {}
    additionalPrinterColumns:
    - name: Schedule
      type: string
      jsonPath: .spec.schedule
    - name: Phase
      type: string
      jsonPath: .status.phase
```

### Экземпляр пользовательского ресурса

```yaml
apiVersion: example.io/v1alpha1
kind: Backup
metadata:
  name: db-nightly
spec:
  target: postgres-prod
  schedule: "0 3 * * *"
  retentionDays: 14
```

## Дополнительная информация

- **CRD vs Aggregated API**: CRD — стандартный способ расширения через **YAML (YAML Ain't Markup Language)** манифесты. Aggregated API требует написания собственного API-сервера и используется для сложной логики, не вписывающейся в декларативную схему.
- **[Операторы Kubernetes](./kubernetes_operators.md)** — реализация логики управления CRD.
- **[Архитектура плоскости управления](./control_plane_architecture.md)** — общая схема работы API-сервера и etcd.
