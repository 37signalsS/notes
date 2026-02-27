# Kyverno: Движок политик для Kubernetes

## Определения

* **Kyverno**: Открытый policy-движок для Kubernetes (<https://kyverno.io/>), позволяющий управлять политиками с помощью YAML-манифестов. Предназначен для автоматизации безопасности, обеспечения соответствия требованиям и внедрения лучших практик непосредственно в кластере Kubernetes.

## Основные концепции

Kyverno функционирует как Admission Controller в Kubernetes, перехватывая запросы к API-серверу и применяя к ним заданные политики.

### Как работает Kyverno (Admission Webhooks)

При деплое манифеста в Kubernetes:
1. Манифест отправляется в Kubernetes API
2. Манифест проходит через цепочку webhook-ов
3. Kyverno подключается к двум типам webhook:
   - **Mutating Admission Webhook**: Может изменять (мутировать) манифест перед сохранением в etcd
   - **Validating Admission Webhook**: Проверяет манифест на соответствие политикам
4. После прохождения цепочки манифест сохраняется в etcd

Kyverno работает **только с манифестами**, а не с запущенными приложениями.

### Ключевой функционал

* **Валидация манифестов**: Проверка ресурсов (подов, деплойментов и т.д.) на соответствие определенным правилам безопасности, ограничениям или рекомендациям.
* **Мутация ресурсов**: Автоматическое изменение или добавление параметров к ресурсам Kubernetes перед их сохранением в etcd (например, добавление `securityContext` или лейблов).
* **Генерация ресурсов**: Создание новых ресурсов на основе уже существующих или клонирование ресурсов между пространствами имен (например, автоматическая генерация `NetworkPolicy` для новых пространств имен или копирование `Secret` из шаблонного namespace).
* **Очистка ресурсов (Pruning)**: Удаление устаревших или неиспользуемых объектов.
* **Встроенный аудит**: Предоставление детальных отчетов о применении политик и выявленных нарушениях.
* **Поддержка использования вне кластера**: Возможность применения политик и проверки манифестов с помощью CLI, в CI/CD пайплайнах или через JSON-интерфейс.

### Типы правил (Rules)

* **generate**: Создание или клонирование ресурсов.
  * `clone`: Копирование `Secret` или `ConfigMap` из другого namespace.
  * `synchronize`: Синхронизация скопированного ресурса с источником (при изменении оригинала).
* **mutate**: Автоматическое добавление или изменение полей в ресурсах.
  * `patchStrategicMerge`: JSON patch для изменения полей.
  * `imagePullPolicy`: Автоматическое добавление `imagePullSecrets` к подам.
* **validate**: Валидация ресурсов на соответствие правилам.
  * `pattern`: Шаблон, которому должен соответствовать манифест.
  * `deny`: Запрещающее правило с условиями.
  * `foreach`: Применение правила к каждому элементу массива.
* **verifyImages**: Проверка подписей образов (Cosign, KMS и т.д.).

## Написание политик

### Типы политик

* **Policy**: Namespace-scoped — применяется к ресурсам в конкретном namespace.
* **ClusterPolicy**: Cluster-scoped — применяется ко всему кластеру.

Для применения политики к нескольким namespace рекомендуется использовать **ClusterPolicy**.

### Структура политики

Политика состоит из:
1. **metadata**: Имя, аннотации
2. **spec**: Спецификация политики
   * `background`: Включить/выключить фоновое сканирование (по умолчанию `true`)
   * `failureAction`: Действие при нарушении политики (`enforce` — запретить, `audit` — только отчет)
   * `rules`: Набор правил (минимум одно)

### Правила (rules)

Каждое правило содержит:
* `match`: Условие применения политики к ресурсам
* `exclude`: Условие исключения ресурсов
* Тип правила: `validate`, `mutate`, `generate`, `deny`

#### Match и Exclude

```yaml
match:
  any:
    - resources:
        kinds:
          - Pod
        namespaces:
          - default
          - user1
          - user2
        operations:
          - CREATE
          - UPDATE
```

* `any` / `all`: Логическое объединение условий
* `kinds`: Типы ресурсов (Pod, Deployment, Service и т.д.)
* `namespaces`: Namespace для применения
* `operations`: Операции (CREATE, UPDATE, DELETE)

### Валидация с помощью pattern

Правило `validate` с типом `pattern` проверяет манифест на соответствие шаблону:

```yaml
rules:
  - name: require-run-as-non-root
    match:
      resources:
        kinds:
          - Pod
    validate:
      failureAction: Enforce
      message: "Container must run as non-root user"
      pattern:
        spec:
          =(securityContext):
            runAsNonRoot: true
            runAsUser: ">0"
```

**Якоря (anchors)**:
* `(field)`: Опциональное поле — если присутствует, проверяется условие
* `=(field)`: Обязательное поле
* `>(n)`, `>=(n)`, `=(n)`, `<(n)`, `<=(n)`: Числовые сравнения
* `*`: Wildcard (любое значение)

### Запрещающие правила (deny)

Правило `deny` использует условия для запрета:

```yaml
rules:
  - name: deny-host-path
    match:
      resources:
        kinds:
          - Pod
    deny:
      conditions:
        - key: "{{ request.object.spec.volumes[*].hostPath }}"
          operator: AnyNotIn
          value:
            - ""
            - null
      message: "HostPath volumes are forbidden"
```

Условия работают с **AdmissionReview** — JSON-объект, содержащий информацию о запросе.

### Примеры политик

#### Требование non-root пользователя

Требует обязательного наличия `securityContext` с `runAsUser > 0`:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-run-as-non-root
spec:
  validationFailureAction: Enforce
  rules:
    - name: run-as-non-root-user
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "runAsUser must be greater than 0"
        pattern:
          spec:
            =(securityContext):
              runAsUser: ">0"
    - name: run-as-non-root-group
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "runAsGroup must be greater than 0"
        pattern:
          spec:
            =(securityContext):
              runAsGroup: ">0"
```

#### Запрет HostPath

Запрещает использование `hostPath` volumes:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-host-path
spec:
  validationFailureAction: Enforce
  rules:
    - name: deny-host-path
      match:
        resources:
          kinds:
            - Pod
      deny:
        conditions:
          - key: "{{ request.object.spec.volumes[*].hostPath }}"
            operator: AnyNotIn
            value:
              - ""
              - null
        message: "HostPath volumes are forbidden"
```

**Примечание**: Данная политика не перехватывает `PersistentVolume` с типом `Local`. Необходимо создавать отдельную политику для PV.

### Важные замечания

1. **Background scan не применяется к существующим ресурсам** — политика срабатывает только при CREATE/UPDATE.
2. По умолчанию все примеры политик в документации используют `failureAction: audit`.
3. Для полной защиты необходимо переключить на `failureAction: Enforce`.
4. Политики применяются к **Pod** — Kyverno проверяет итоговый Pod, сгенерированный из Deployment/StatefulSet/DaemonSet и т.д.

## Практические сценарии

* **Применение политик безопасности в реальном времени**: В отличие от [Kubesec](./kubesec.md), который проверяет YAML-манифесты *до* развертывания, Kyverno позволяет проводить валидацию и мутацию ресурсов *во время* развертывания через Admission Controller. Это обеспечивает автоматическое применение политик к ресурсам, попадающим в кластер.
* **Автоматизация соответствия стандартам**: Kyverno позволяет обеспечить непрерывное соблюдение внутренних или внешних стандартов безопасности (например, PCI DSS, GDPR) путем определения соответствующих политик.
* **Внедрение лучших практик**: Автоматическое добавление `securityContext` или других настроек безопасности к подам, что способствует повышению общей защищенности кластера.
* **Инфраструктура как код и политики как код**: Kyverno позволяет определить политики в виде кода (YAML-файлов) и управлять ими как частью репозитория, что упрощает их версионирование, тестирование и развертывание.
* **Управление сетевыми политиками**: Автоматическая генерация `NetworkPolicy` для изоляции приложений в разных пространствах имен.
* **Управление секретами Docker Registry**: Автоматическое копирование `Secret` с креденшенами доступа к приватному Docker Registry из шаблонного namespace при создании новых namespace. Политика `generate` с параметром `clone` копирует `Secret` из `namespace: template` во вновь созданные namespace. Политика `mutate` автоматически добавляет `imagePullSecrets` к подам, если они обращаются к закрытому registry.

Kyverno фокусируется на управлении и применении политик к ресурсам, развертываемым в кластере, в то время как [kube-bench](./kube-bench.md) аудирует конфигурацию самого кластера на соответствие CIS Benchmark.

## Установка

Установка Kyverno в кластер Kubernetes осуществляется через **Helm Chart**.

При установке разворачиваются **4 компонента**:

* **Admission Controller**: Обрабатывает mutating и validating admission webhook-запросы.
* **Background Controller**: Обрабатывает создание и обновление ресурсов в фоновом режиме.
* **Cleanup Controller**: Удаляет ресурсы, помеченные на очистку.
* **Reports Controller**: Генерирует отчеты о применении политик.

## Интеграция с Argo CD

При совместном использовании Kyverno и Argo CD необходимо учитывать ряд нюансов для корректной работы.

### Конфликт меток (Resource Tracking)

Argo CD и Kyverno используют одинаковый механизм отслеживания ресурсов через метки (`labels`). Для предотвращения конфликта необходимо перевести Argo CD на использование **annotations** вместо labels.

* **Решение**: В `values.yaml` Argo CD указать параметр `resourceTrackingMethod: annotation`.

### Server-side Diff

Argo CD по умолчанию сравнивает манифесты из Git с состоянием в кластере. При использовании Kyverno (который может мутировать манифесты) возникает бесконечный цикл синхронизации.

* **Решение**: Включить `server-side diff` в Argo CD.
  * Глобально: в `values.yaml` параметр `controller.diff.serverSide: true`.
  * Для конкретного приложения: аннотация `argocd.argoproj.io/compare-options: ServerSideDiff=true`.

### Mutation Webhooks

Kyverno может изменять (мутировать) манифесты в процессе admission. Argo CD необходимо учитывать эти изменения при сравнении.

* **Решение**: Добавить аннотацию `argocd.argoproj.io/sync-option: IncludeMutationWebhook=true` к приложению в Argo CD.
* **Примечание**: Работает только при включенном `server-side diff`.

### Aggregated Roles

Kyverno использует Aggregated Cluster Roles, что приводит к динамическому изменению ролей. Argo CD может некорректно обрабатывать эти изменения.

* **Решение**: В `values.yaml` Argo CD указать `resource.compare: ignoreAggregatedRoles: true`.

### Важное примечание по установке

При установке Kyverno через Argo CD **обязательно** использовать параметр `spec.syncPolicy.automated.applyServerSide: true`. Параметр `spec.syncPolicy.automated.replace: true` использовать **нельзя** (на момент съемки видео в документации была ошибка).

## Policy Reports (Отчеты)

Kyverno автоматически генерирует отчеты о применении политик.

### Типы отчетов

* **PolicyReport**: Namespace-scoped ресурс — создается для политик типа `Policy`.
* **ClusterPolicyReport**: Cluster-scoped ресурс — создается для политик типа `ClusterPolicy`.

### Как работают отчеты

* Отчеты создаются автоматически при создании/обновлении ресурсов, к которым применяются политики.
* Отчеты хранятся в **etcd** как обычные Kubernetes-ресурсы (отдельная БД не требуется).
* При удалении ресурса соответствующая запись удаляется из отчета.
* Отчеты отражают **текущее состояние кластера**, историческая информация не сохраняется.
* Формат отчетов соответствует стандарту **Policy Report Working Group** — универсальный формат, поддерживаемый различными policy-движками.

### Структура отчета

* **metadata**: Имя, namespace, информация об объекте.
* **results**: Массив результатов применения политик.
  * `category`: Категория политики (например, security, best-practices).
  * `message`: Сообщение о результате.
  * `policy`: Имя примененной политики.
  * `result`: Статус результата.
* **summary**: Сводка по количеству ошибок, предупреждений, пропусков.
* **scope**: Информация об объекте, к которому применяется политика.

### Статусы результатов (result)

* **pass**: Ресурс прошел проверку политики.
* **skip**: Политика не выполнялась (например, сработал `policy exception`).
* **fail**: Ресурс не прошел проверку (политика запретила).
* **warn**: Ресурс прошел, но выдано предупреждение (если в политике установлена аннотация `policies.kyverno.io/validation-failure-action: warn`).
* **error**: Ошибка при обработке политики.

## Background Scans

Kyverno периодически сканирует существующие ресурсы в кластере на соответствие политикам.

* **По умолчанию**: `background: true` — фоновое сканирование включено.
* При `background: false`: Фоновое сканирование отключено, отчеты генерируются только при создании/обновлении ресурсов (admission time).

**Важно**: Background scan **не применяет** политики к существующим ресурсам — он только генерирует отчеты. Политики применяются только к **новым** ресурсам (на этапе admission).

| Background | Enforce | Audit | Результат для существующих ресурсов |
|------------|---------|-------|-----------------------------------|
| true       | да      | да    | Только отчеты (reports)           |
| false      | да      | да    | Нет отчетов                       |

Background scan полезен для:
* Аудита кластера
* Отладки политик перед переходом в режим enforce

## Policy Reporter

Policy Reporter — это отдельное приложение для удобного просмотра и управления отчетами Kyverno.

### Возможности Policy Reporter

* **Web UI**: Графический интерфейс для просмотра отчетов, группировка по категориям, фильтрация.
* **Metrics**: Генерация метрик для Prometheus/Grafana.
* **REST API**: Встроенный API для интеграции с внешними системами.
* **Централизованный сбор**: Возможность агрегировать отчеты с нескольких namespace в одно место (для больших инфраструктур).
* **Уведомления**: Отправка уведомлений в Discord, Telegram и другие мессенджеры.
* **Генерация отчетов**: Возможность экспортировать отчеты в различных форматах.

### Установка

Устанавливается через Helm Chart. Основные параметры:

```yaml
metrics:
  enabled: true

ui:
  enabled: true

api:
  enabled: true
```

## Дополнительная информация

### Aggregated Cluster Roles

По умолчанию Kyverno не имеет прав на создание некоторых ресурсов (например, `Secret`). Для расширения прав используются **Aggregated Cluster Roles**.

* **Mechanism**: Создание `ClusterRole` с лейблом `kyverno.io/aggregate-to-<controller>-controller: "true"`, где `<controller>` — один из: `admission`, `background`, `reports`, `cleanup`.
* **Controllers**:
  * `admission-controller`: Обрабатывает запросы admission webhooks.
  * `background-controller`: Обрабатывает создание и обновление ресурсов.
  * `reports-controller`: Обрабатывает Policy Reports.
  * `cleanup-controller`: Обрабатывает удаление ресурсов.
* **Пример**: Для генерации `Secret` необходимы права `create` на ресурсы `Secret` с лейблом `kyverno.io/aggregate-to-background-controller: "true"`.

### Историческая справка

В Kubernetes 1.25 были удалены **Pod Security Policies (PSP)**. Kyverno рассматривался как одна из альтернатив для замены PSP, наряду с другими решениями, такими как OPA Gatekeeper.
