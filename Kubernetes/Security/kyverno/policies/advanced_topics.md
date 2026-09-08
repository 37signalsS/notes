# Политики Kyverno: Продвинутые возможности

## Определения

**Переменные и контекст** — механизмы динамической подстановки данных из admission-запроса, внешних источников (ConfigMap, API) или системных метаданных в правила политики. Это позволяет создавать гибкие, контекстно-зависимые правила, которые адаптируются к пользователю, окружению или внешним реестрам. Подробный разбор синтаксиса приведен в **[Типах правил (rules.md)](../rules.md#переменные-и-контекст)**.

**Функциональные методы CEL** — встроенные функции Common Expression Language для эффективной обработки массивов и объектов без использования циклов `foreach`. Поддерживаются в `ValidatingPolicy` и нативных `ValidatingAdmissionPolicy`.

**SSRF Protection (Server-Side Request Forgery)** — механизм безопасности Kyverno, ограничивающий доступ `apiCall` только к разрешенным внутренним и внешним хостам через систему белых (`allowlist`) и черных (`blocklist`) списков. Настройка SSRF-защиты выполняется через флаги контроллера или CR `ConfigMap` Kyverno.

**Автогенерация правил (Autogen)** — механизм Kyverno, автоматически генерирующий идентичные проверки для `Pod`, `Deployment`, `ReplicaSet`, `StatefulSet`, `DaemonSet`, `Job` и `CronJob`. Управление через аннотацию `policies.kyverno.io/autogen-controllers`. При использовании в `ValidatingPolicy` autogen работает иначе — контрольные точки определяются через `matchConstraints.resourceRules`.

---

## Основные концепции

### 1. Функциональное программирование на CEL

В современных версиях (v1.17+) Kyverno практически полностью перешел на CEL для обработки логики. Основные методы обработки данных:

| Метод | Описание | Пример применения |
| :--- | :--- | :--- |
| **`.all(x, cond)`** | Возвращает `true`, если условие истинно для всех элементов. | Проверка всех контейнеров на `readOnlyRootFilesystem`. |
| **`.exists(x, cond)`** | Возвращает `true`, если хотя бы один элемент удовлетворяет условию. | Поиск привилегированного контейнера в поде. |
| **`.filter(x, cond)`** | Создает новый массив из элементов, удовлетворяющих условию. | Извлечение только `initContainers` для специфической проверки. |
| **`.map(x, expr)`** | Преобразует каждый элемент массива. | Получение списка имен всех образов в поде. |
| **`.orValue(val)`** | Предоставляет значение по умолчанию для необязательных полей. | Обработка отсутствующего блока `securityContext`. |
| **`has(obj, field)`** | Проверяет наличие поля в объекте (CEL v2). | Избежание паники при обращении к необязательным полям. |
| **`size(x)`** | Возвращает длину массива или строки. | Проверка минимального количества элементов. |
| **`string(x)`**, **`int(x)`** | Явное приведение типов. | Конвертация строковых значений из лейблов для числовых сравнений. |

**Важные особенности CEL:**
- CEL **не поддерживает** неявные преобразования типов (в отличие от JMESPath). Например, `size(5)` вызовет ошибку — нужно `string(5)`.
- Для работы с отсутствующими полями используйте `has()` перед обращением к ним.
- Строка `variables` недоступна напрямую в `ValidatingPolicy` v2 — данные из контекста доступны через `variables.<name>` или напрямую.

### 2. Динамический контекст и внешние данные

Kyverno поддерживает три уровня работы с внешними данными, различающихся по производительности и актуальности:

1.  **GlobalContext (Асинхронный/Кэшированный)**:
    *   **Принцип**: Данные загружаются в фоновом режиме и хранятся в памяти контроллера.
    *   **Latency**: Близка к нулю (`O(1)`).
    *   **Применение**: Тяжелые справочники (список команд, реестр разрешенных образов).
    *   **Настройка**: Через CR `GlobalContextEntry` (v1.15+). Поддерживает `kubernetesResource` (ConfigMap/Secret) и `apiCall` (HTTP). Интервал обновления задается через `periodSeconds` в `apiCall`.
2.  **ConfigMap (Синхронный/Локальный)**:
    *   **Принцип**: Считывание данных из `ConfigMap` в реальном времени.
    *   **Latency**: Низкая (запрос к локальному etcd).
    *   **Применение**: Конфигурации, меняющиеся нечасто, но требующие точности.
3.  **apiCall / serviceCall (Синхронный/Внешний)**:
    *   **Принцип**: HTTP-запрос к внешнему сервису или K8s API.
    *   **Latency**: Высокая (зависит от сети). Требует настройки `timeoutSeconds`.
    *   **Применение**: Проверка квот в реальном времени, внешние системы авторизации.
    *   **Безопасность**: Всегда используйте `onFailure: Ignore` для предотвращения блокировки кластера при недоступности внешней системы.

### 3. Архитектура V2 (CEL-first) vs V1 (JMESPath)

| Аспект | V1 (ClusterPolicy) | V2 (ValidatingPolicy / MutatingPolicy) |
| :--- | :--- | :--- |
| **Язык** | JMESPath + YAML шаблоны | CEL |
| **Выполнение** | Webhook Kyverno (сетевой вызов) | Нативно в API-сервере (VAP) |
| **Задержка** | 5-15 мс (зависит от сети) | <1 мс (нативная интеграция) |
| **Отказоустойчивость** | Зависит от `failurePolicy` | Политика продолжает работать при недоступности контроллера |
| **Autogen** | Через аннотацию `policies.kyverno.io/autogen-controllers` | Определяется через `matchConstraints.resourceRules` |
| **Использование контекста** | `{{ request.object }}` | `object`, `request` |

### 4. Управление autogen

Для `ClusterPolicy` v1 Kyverno автоматически генерирует правила для контроллеров (Deployment, StatefulSet и т.д.). Управление поведением:

```yaml
metadata:
  annotations:
    # Включить autogen (по умолчанию)
    policies.kyverno.io/autogen-controllers: "Deployment,ReplicaSet,StatefulSet,DaemonSet"
    # Отключить полностью — только для Pod
    policies.kyverno.io/autogen-controllers: "none"
```

**Важно**: При использовании `ValidatingPolicy` v2 autogen отключен по умолчанию. Необходимо явно указывать целевые ресурсы в `matchConstraints`.

---

## Практические сценарии

### 1. Сложная CEL-валидация вложенных объектов

Проверка, что ни один контейнер не использует запрещенные порты, с учетом опциональности полей:

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: restrict-ports-cel
spec:
  validations:
    - expression: |
        (object.spec.containers + object.spec.?initContainers.orValue([])).all(c,
          !has(c.ports) || c.ports.all(p, p.containerPort != 22 && p.containerPort != 3389)
        )
      message: "Использование портов 22 (SSH) и 3389 (RDP) запрещено."
```

### 2. Использование apiCall с защитой SSRF и обработкой ошибок

Запрос к внешнему сервису для проверки «владельца» Namespace. Обратите внимание на использование `allowlist` в конфигурации контроллера для работы этой политики.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: check-namespace-owner
spec:
  rules:
    - name: call-external-api
      context:
        - name: owner-info
          apiCall:
            method: GET
            urlPath: "https://inventory.corp.internal/api/v1/owner/{{request.object.metadata.name}}"
            jmesPath: "owner.team"
      validate:
        message: "Namespace должен принадлежать зарегистрированной команде."
        deny:
          conditions:
            all:
              - key: "{{ owner-info }}"
                operator: Equals
                value: "unknown"
```

### 3. Оптимизация через GlobalContext

Вместо `apiCall` для каждого пода используем кэшированный список разрешенных реестров:

```yaml
# Определение GlobalContextEntry
apiVersion: kyverno.io/v1alpha2
kind: GlobalContextEntry
metadata:
  name: trusted-registries-cache
spec:
  kubernetesResource:
    group: ""
    version: "v1"
    kind: ConfigMap
    name: allowed-registries
    namespace: kyverno
---
# Использование в политике
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: restrict-image-registries
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  context:
    - name: allowed-registries
      globalContextEntry: trusted-registries-cache
  validations:
    - expression: |
        object.spec.containers.all(c,
          variables.allowed-registries.data.list.split(",").exists(r,
            c.image.startsWith(r.trim())
          )
        )
      message: "Образы разрешены только из доверенных реестров."
```

### 4. Исключения через PolicyException (DevOps-сценарий)

Вместо ослабления глобальной политики используйте точечные исключения. Это позволяет командам приложений запускать критичные сервисы без нарушения общих стандартов кластера:

```yaml
apiVersion: kyverno.io/v1
kind: PolicyException
metadata:
  name: legacy-app-exception
  namespace: team-backend
spec:
  exceptions:
    - policyName: disallow-privileged-containers
      ruleNames:
        - check-privileged
  match:
    any:
      - resources:
          kinds:
            - Pod
          namespaces:
            - team-backend
          names:
            - legacy-*
```

**Важно**: `PolicyException` требует отдельного RBAC-контроля. Рекомендуется выделить отдельную группу через `ClusterRoleBinding` с правами на создание `policyexceptions`.

### 5. Мутация существующих ресурсов (mutateExisting)

При обновлении политики Kyverno может применить изменения к уже запущенным ресурсам. Это критично для безопасного обновления политик без пересоздания подов:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-security-label-existing
spec:
  rules:
    - name: label-existing-deployments
      match:
        any:
          - resources:
              kinds: [Deployment]
      mutate:
        targets:
          - apiVersion: apps/v1
            kind: Deployment
            namespace: "{{ request.namespace }}"
        patchStrategicMerge:
          metadata:
            labels:
              security-scan: "enabled"
              last-audit: "{{ time_now_utc() }}"
```

**Требования к RBAC**: Контроллер `background-controller` должен иметь права на чтение и изменение целевых ресурсов. См. [агрегированные роли](../additional.md).

### 6. Валидация ResourceQuota перед деплоем (preventive check)

Перед деплоем проверяем, что запрошенные ресурсы не превышают квоты Namespace. Это предотвращает промахи планировщика и оставление подов в статусе `Pending`:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: check-resource-quota
spec:
  rules:
    - name: validate-cpu-request
      context:
        - name: quota-data
          apiCall:
            urlPath: "/api/v1/namespaces/{{request.namespace}}/resourcequotas"
            jmesPath: "items[0].status.hard.cpu"
      validate:
        message: "Запрошенный CPU ({{ request.object.spec.containers[0].resources.requests.cpu }}) превышает квоту Namespace."
        deny:
          conditions:
            all:
              - key: "{{ request.object.spec.containers[0].resources.requests.cpu }}"
                operator: GreaterThan
                value: "{{ quota-data }}"
```

### 7. Генерация NetworkPolicy для сегментации.Namespace (GitOps)

Автоматическая сегментация: только разрешенные сервисы имеют доступ к новому Namespace:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: generate-network-segmentation
spec:
  rules:
    - name: create-default-deny
      match:
        any:
          - resources:
              kinds: [Namespace]
              annotations:
                kyverno.io/generate-networkpolicy: "true"
      generate:
        synchronize: true
        apiVersion: networking.k8s.io/v1
        kind: NetworkPolicy
        name: default-deny-all
        namespace: "{{ request.object.metadata.name }}"
        data:
          spec:
            podSelector: {}
            policyTypes:
              - Ingress
              - Egress
```

### 8. Ограничение тегов образов (запрет `:latest`)

Запрет использования тегов `:latest` для предсказуемости деплоев:

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: disallow-latest-tag
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  validations:
    - expression: |
        object.spec.containers.all(c, !c.image.endsWith(":latest"))
      message: "Тег ':latest' запрещён. Используйте конкретную версию или дайджест."
```

---

## Дополнительная информация

### Рекомендации по оптимизации производительности

| Фактор | Рекомендация | Техническое обоснование |
| :--- | :--- | :--- |
| **Выбор движка** | **CEL** предпочтительнее JMESPath. | CEL компилируется и выполняется нативно в K8s (VAP), JMESPath интерпретируется вебхуком. |
| **Внешние данные** | Используйте **GlobalContext**. | Минимизирует сетевой оверхед и нагрузку на внешние API. |
| **Объем контекста** | Фильтруйте данные через `jmesPath` в `apiCall`. | Чем меньше данных передается в контекст правила, тем быстрее работает политика. |
| **Безопасность** | Всегда настраивайте `onFailure: Ignore` для `apiCall`. | Предотвращает блокировку кластера при недоступности внешней системы. |
| **Autogen** | Отключайте autogen в `ValidatingPolicy` v2 явно. | Избегает непреднамеренного расширения области действия на все контроллеры. |
| **Лимит правил** | Не более 5 правил в одной политике. | Снижает задержку Admission Webhook при использовании V1. |

**Конкретные метрики (2026):**
- ВAP (CEL): **<1 мс** задержка на проверку (нативно в API-сервере).
- Webhook Kyverno (JMESPath): **5-15 мс** (включая сетевой вызов и обработку).
- При 3+ правилах VAP выигрывает **40-60%** по сравнению с JMESPath (без сетевого оверхеда).

### Переход с JMESPath на CEL

При миграции на стандарты 2026 года учитывайте:

1. **Типизация**: В CEL отсутствуют многие неявные преобразования типов, характерные для JMESPath. Используйте явное приведение (`int()`, `string()`).
2. **Циклы**: Конструкции `foreach` заменяются на функциональные методы `.all()`, `.exists()`, `.map()`.
3. **Проверка полей**: CEL имеет строгую проверку наличия полей через `has()`.
4. **Шаблоны YAML**: Конструкции `pattern` с якорями (`?*`, `^(field)`) заменяются на выражения CEL.
5. **Пример мутации**:
   - **V1 (JMESPath)**: `mutate.patchStrategicMerge.spec.containers[0].resources.limits.memory: "512Mi"`
   - **V2 (CEL)**: Используйте `MutationConfiguration` с `patchType: JSONPatch` или `strategic` для аналогичных операций.

**Стратегия миграции:**
1. Начинайте с простых validate-политик ( замена `pattern` на CEL-выражения).
2. Проверяйте через `kyverno test` перед применением.
3. Используйте `validationFailureAction: Audit` для первичной валидации.
4. Мигрируйте мутации последними — они требуют перехода на `MutatingPolicy`.

### Типичные ошибки и диагностика

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Политика не применяется к существующим ресурсам | Отсутствует фоновое сканирование или `mutateExisting` | Убедитесь, что `spec.background: true` и используйте `targets` в mutate. |
| `generate` не создает ресурсы в новом NS | Нет триггера или проблемы с RBAC | Проверьте `updaterequests` и права контроллера. |
| Ошибка `validation failed` при валидации | Несовпадение шаблона с реальным манифестом | Используйте `kubectl get policyreport -A` для диагностики. |
| Мутация не применяется к Pod | Pod создан до применения политики | Используйте `mutateExisting` + `background: true`. |
| CEL-политика не работает в VAP-режиме | Ошибка в выражении CEL или неверный `matchConstraints` | Проверьте логи Admission Controller, используйте `dryRun=Server`. |
| `PolicyException` не действует | Имя политики или правила не совпадает | Проверьте `policyName` и `ruleNames` в `PolicyException`. |

### Best Practices для DevOps/SRE

1. **Именование правил**: Используйте описательные имена в формате `verb-noun-condition` (например, `deny-privileged-containers`, `mutate-add-default-labels`).
2. **Тестируйте перед применением**: Используйте `kyverno test` для проверки политик:
   ```bash
   kyverno test ./policies/ --detailed-results
   ```
3. **Начинайте с Audit Mode**: Перед `Enforce` установите `validationFailureAction: Audit` для мониторинга влияния политик.
4. **Исключайте системные Namespace**: Всегда добавляйте `exclude` для `kube-system`, `kyverno`, `istio-system`.
5. **Используйте Preconditions**: Для сложной логики вместо вложенных `match` блоков.
6. **Документируйте политики**: Добавляйте аннотации с описанием назначения правила (`policies.kyverno.io/title`, `policies.kyverno.io/description`).
7. **CI/CD интеграция**: Запускайте `kyverno apply` в пайплайне перед `kubectl apply` для раннего обнаружения нарушений.
8. **Мониторинг**: Настройте алерты на рост `policy_report_results` в Prometheus для обнаружения роста нарушений.

### См. также

- **[Типы правил и их синтаксис (rules.md)](../rules.md)** — полный справочник по структуре.
- **[Библиотека практических примеров (practical_scenarios.md)](./practical_scenarios.md)** — расширенный набор CEL-сценариев.
- **[Агрегированные роли и GlobalContext (additional.md)](../additional.md)** — настройка прав и кэширования.
- **[Определения и структура политик](./definitions_and_concepts.md)** — база для написания манифестов.
