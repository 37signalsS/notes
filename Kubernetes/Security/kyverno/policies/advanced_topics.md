# Политики Kyverno: Продвинутые возможности

## Определения

**Переменные и контекст** — механизмы динамической подстановки данных из एडमिशन-запроса, внешних источников (ConfigMap, API) или системных метаданных в правила политики.

**Итерация (Foreach / CEL map)** — логические конструкции для обработки массивов данных (контейнеров, томов, аннотаций). Позволяют применять индивидуальные проверки или мутации к каждому элементу коллекции.

**CEL (Common Expression Language)** — высокопроизводительный язык выражений, ставший стандартом в версиях 1.14+ для написания сложных условий валидации и мутации, обеспечивающий нативную совместимость с Kubernetes.

---

## Основные концепции

### Контекстные переменные

Kyverno предоставляет доступ к широкому набору данных через систему переменных:

| Источник | Переменная | Описание |
| :--- | :--- | :--- |
| **Ресурс (новый)** | `{{request.object}}` | Полный манифест создаваемого или обновляемого ресурса. |
| **Ресурс (старый)** | `{{request.oldObject}}` | Предыдущая версия манифеста (при обновлении). |
| **Пользователь** | `{{request.userInfo}}` | Данные об аккаунте, инициировавшем действие (User, Groups, ServiceAccount). |
| **Пространство имен** | `{{request.namespace}}` | Название Namespace, в котором находится ресурс. |

### Внешний контекст (ConfigMap)

Использование `ConfigMap` позволяет выносить параметры политик (например, списки разрешенных реестров или исключения) во внешние ресурсы, которые можно обновлять без редактирования самой политики.

```yaml
context:
  - name: allowed-images-config
    configMap:
      name: image-whitelist
      namespace: kyverno
```

### Обработка списков: JMESPath vs CEL

С выходом версий 1.14+ Kyverno поддерживает два подхода к обработке массивов:

1.  **JMESPath (традиционный)**: Используется в классических `ClusterPolicy` через конструкцию `foreach` и фильтры.
2.  **CEL (современный)**: Используется в новых ресурсах `ValidatingPolicy` и `MutatingPolicy`. Работает быстрее и лаконичнее.

---

## Практические сценарии

### 1. Проверка всех контейнеров через CEL (Modern)

Использование функциональных методов CEL (`all`, `exists`, `any`) для проверки всей спецификации пода за один проход.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: enforce-read-only-root
spec:
  validations:
    - expression: |
        (object.spec.containers + object.spec.?initContainers.orValue([])).all(c,
          has(c.securityContext) && has(c.securityContext.readOnlyRootFilesystem) &&
          c.securityContext.readOnlyRootFilesystem == true
        )
      message: "Все контейнеры должны использовать только чтение для корневой файловой системы."
```

### 2. Динамическая валидация через ConfigMap

Политика считывает список разрешенных ролей из внешнего `ConfigMap`.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: check-allowed-roles
spec:
  rules:
    - name: validate-role-from-configmap
      context:
        - name: roles-data
          configMap:
            name: approved-roles
            namespace: security-ops
      match:
        any:
          - resources:
              kinds: [RoleBinding]
      validate:
        message: "Роль {{request.object.roleRef.name}} не входит в список разрешенных."
        deny:
          conditions:
            any:
              - key: "{{request.object.roleRef.name}}"
                operator: AnyNotIn
                value: "{{roles-data.data.list}}"
```

### 3. Нормализация данных (CPU и Память)

Использование фильтров для сравнения ресурсов, заданных в разных единицах (например, `100m` vs `0.1`).

```yaml
# Пример в традиционном правиле validate
validate:
  message: "Лимит CPU превышает допустимый максимум."
  deny:
    conditions:
      - key: "{{ request.object.spec.containers[0].resources.limits.cpu | to_number(@) }}"
        operator: GreaterThan
        value: 1
```

---

## Дополнительная информация

### Выбор движка: JMESPath или CEL?

| Характеристика | JMESPath | CEL (Рекомендуется) |
| :--- | :--- | :--- |
| **Производительность** | Средняя | Высокая (компилируемый) |
| **Нативность K8s** | Нет | Да (совместим с VAP) |
| **Генерация ресурсов** | Да (`generate`) | Ограничена (v1.15+) |
| **Отладка** | Сложная | Встроенные сообщения об ошибках |

### Рекомендации по оптимизации

1.  **Использование GlobalContext**: Для данных, запрашиваемых часто (например, внешние API или тяжелые ConfigMap), используйте `GlobalContext` (v1.15+) для кэширования.
2.  **Минимизация внешних вызовов**: Каждый вызов API из политики увеличивает задержку обработки запроса. Используйте кэширование везде, где возможно.
3.  **Безопасность переменных**: Всегда проверяйте наличие данных (`has()` в CEL) перед обращением к ним, чтобы избежать ошибок выполнения политики.
4.  **Policy Reporter**: Используйте визуализацию для отслеживания ошибок выполнения сложных JMESPath выражений.

### См. также

- **[Типы правил (подробно)](../rules.md)** — основы синтаксиса.
- **[Библиотека практических примеров](./practical_scenarios.md)** — CEL и классические сценарии.
- **[Определения и структура](./definitions_and_concepts.md)** — базовые манифесты.
- **[Официальный справочник по CEL](https://kyverno.io/docs/writing-policies/cel/)**
