# Метаданные, метки и аннотации в Kubernetes

## Определения

В Kubernetes каждый объект (Pod, Service, ConfigMap) содержит поле **`metadata`**, которое используется для его идентификации, организации и управления жизненным циклом. Основными инструментами структурирования данных являются метки и аннотации.

*   **Метаданные (Metadata)** — системные данные, описывающие объект (имя, UID, версия ресурса).
*   **Метки (Labels)** — пары «ключ-значение», используемые для **идентификации** и группировки объектов. Метки индексируются и используются селекторами.
*   **Аннотации (Annotations)** — пары «ключ-значение» для хранения **дополнительных данных**, не предназначенных для идентификации. Они не индексируются и не используются для поиска.

## Поля метаданных (Metadata Fields)

Помимо пользовательских меток, поле `metadata` содержит критически важные системные поля:

*   **`name`**: Уникальное имя объекта в рамках одного **Namespace**.
*   **`namespace`**: Логическое пространство имен. Если не указано, используется `default`.
*   **`uid`**: Глобально уникальный идентификатор (UUID), генерируемый API-сервером.
*   **`resourceVersion`**: Используется для оптимистичной блокировки при параллельных изменениях.
*   **`generation`**: Номер версии спецификации объекта (`spec`).
*   **`ownerReferences`**: Список объектов-владельцев (например, Deployment владеет ReplicaSet). Используется механизмом Garbage Collection для каскадного удаления.
*   **`finalizers`**: Список блокировок, препятствующих удалению объекта до выполнения определенных условий (очистка внешних ресурсов оператором).
*   **`managedFields`**: Метаданные о том, какой компонент (например, `kubectl` или `helm`) управляет конкретными полями объекта (Server-Side Apply).

## Основные концепции

### Метки (Labels) и селекторы

Метки позволяют организовывать объекты в наборы, значимые для пользователей, без изменения структуры API.

**Синтаксис ключей:**
*   **Префикс (опционально)**: DNS-поддомен (до 253 символов). Рекомендуется использовать для разделения ответственности (например, `company.com/env`).
*   **Имя**: Обязательно (до 63 символов).
*   **Пример**: `app.kubernetes.io/name: "nginx"`.

**Типы селекторов (Label Selectors):**
1.  **На основе равенства (Equality-based)**:
    *   `env = production`
    *   `tier != frontend`
2.  **На основе множеств (Set-based)**:
    *   `env in (prod, staging)`
    *   `tier notin (backup)`
    *   `partition` (выбор объектов, у которых просто *есть* такой ключ).
    *   **`matchExpressions`**: Позволяет использовать логические операторы (`In`, `NotIn`, `Exists`, `DoesNotExist`) в манифестах контроллеров.

### Рекомендованные метки (Well-known Labels)

Kubernetes стандартизирует набор меток для обеспечения совместимости между инструментами (Helm, ArgoCD, мониторинг).

| Ключ | Описание |
| :--- | :--- |
| `app.kubernetes.io/name` | Имя приложения (например, `mysql`) |
| `app.kubernetes.io/instance` | Уникальное имя экземпляра (например, `mysql-abcxzy`) |
| `app.kubernetes.io/version` | Версия (SemVer) |
| `app.kubernetes.io/component` | Роль (например, `database`, `api`) |
| `app.kubernetes.io/part-of` | Родительская система (например, `wordpress`) |
| `app.kubernetes.io/managed-by` | Инструмент управления (`helm`, `argocd`) |

**Топологические метки (автоматически проставляются облачными провайдерами):**
*   `topology.kubernetes.io/zone`: Зона доступности (например, `ru-central1-a`).
*   `topology.kubernetes.io/region`: Регион.
*   `kubernetes.io/hostname`: Имя узла.
*   `kubernetes.io/os` / `kubernetes.io/arch`: ОС и архитектура процессора.

### Аннотации (Annotations)

Используются для данных, которые не подходят для селекторов, но важны для контроллеров или инструментов.

**Типовые сценарии использования:**
*   **Конфигурация Ingress**: `nginx.ingress.kubernetes.io/rewrite-target: /`.
*   **Мониторинг**: `prometheus.io/scrape: "true"`.
*   **Отслеживание изменений**: `kubernetes.io/change-cause`: "Update to image v2" (отображается в истории ревизий).
*   **FinOps**: `finance.com/cost-center: "marketing"` для биллинга.
*   **Security**: `sidecar.istio.io/inject: "true"` для внедрения прокси.

## Практические сценарии

### Работа с метками через kubectl

```bash
# Показать все метки подов
kubectl get pods --show-labels

# Добавить метку существующему объекту
kubectl label nodes worker-1 disktype=ssd

# Удалить метку (минус после ключа)
kubectl label nodes worker-1 disktype-

# Поиск по селектору
kubectl get pods -l "env in (production, staging),tier=frontend"

# Перезапись существующей метки
kubectl label pods my-pod env=prod --overwrite
```

### Использование matchExpressions в Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
spec:
  selector:
    matchExpressions:
      - {key: tier, operator: In, values: [frontend, api]}
      - {key: env, operator: NotIn, values: [dev]}
```

### Фиксация причины изменения (Change Cause)

При обновлении образа можно добавить аннотацию, которая будет видна в `kubectl rollout history`:

```bash
kubectl annotate deployment/my-app kubernetes.io/change-cause="Обновление образа до v1.2.3"
```

## Дополнительная информация

**Best Practices (2025/2026):**
1.  **Избегайте «голых» ключей**: Не используйте `env: prod`, используйте `my-company.com/env: prod`. Это предотвращает конфликты с чартами сторонних поставщиков.
2.  **Валидация (Policy-as-Code)**: Используйте **Kyverno** или **OPA Gatekeeper** для обязательного требования меток `owner` и `project` при создании ресурсов.
3.  **Лимиты размера**: Суммарный объем метаданных объекта (Labels + Annotations) ограничен **256KB** (лимит etcd). Не храните в аннотациях огромные конфигурационные файлы; используйте для этого `ConfigMaps`.
4.  **Селекторы неизменны**: В ресурсах типа `Deployment` поле `spec.selector` является неизменяемым после создания. Изменение меток в `template.metadata.labels` без обновления селектора приведет к тому, что контроллер перестанет «видеть» старые поды.

**См. также:**
*   **[Namespaces в Kubernetes](../Base/namespace.md)** — контекст имен.
*   **[Affinity и Anti-Affinity](../Scheduling/affinity.md)** — планирование на основе меток.
*   **[Сетевые политики](../Networking/Network/network_policy.md)** — изоляция трафика по меткам.
*   **[Архитектура Control Plane](./control_plane_architecture.md)** — роль etcd в хранении метаданных.
