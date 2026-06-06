# Отчеты Kyverno (Policy Reports)

## Определения

**Policy Report** — стандартизированный формат отчетов о применении политик, разработанный **Policy Report Working Group (WG, рабочая группа по отчетам политик)** в рамках сообщества Kubernetes.

**Типы отчетов**:

- **PolicyReport** — ресурс в рамках пространства имен (namespace-scoped), создается для политик типа `Policy`.
- **ClusterPolicyReport** — ресурс в масштабе кластера (cluster-scoped), создается для политик типа `ClusterPolicy`.

---

## Основные концепции

### Как работают отчеты

| Характеристика | Описание |
|----------------|----------|
| **Создание** | Автоматически при создании или обновлении ресурсов, к которым применяются политики. |
| **Хранение** | В **etcd** (распределенное хранилище данных Kubernetes) как обычные ресурсы. |
| **Удаление** | При удалении ресурса соответствующая запись автоматически удаляется из отчета. |
| **Историчность** | Отчеты отражают **текущее состояние**; история изменений в них не сохраняется. |
| **Формат** | Соответствует стандарту **Policy Report WG** — универсальному формату для различных инструментов безопасности. |

### Структура манифеста отчета

Пример YAML (Yet Another Markup Language) манифеста:

```yaml
apiVersion: wgpolicyk8s.io/v1alpha2
kind: PolicyReport
metadata:
  name: policyreport
  namespace: default
scope:
  apiVersion: v1
  kind: Namespace
  name: default
results:
  - category: security
    message: "Container must run as non-root user"
    policy: require-run-as-non-root
    result: fail
    resource: pod/my-app
    rule: run-as-non-root
    severity: high
    timestamp:
      nanos: 0
      seconds: 1678901234
summary:
  error: 0
  fail: 3
  pass: 15
  skip: 0
  warn: 1
```

### Поля результата

| Поле | Описание | Пример |
|------|----------|--------|
| `category` | Категория политики | `security`, `best-practices` |
| `message` | Описание результата проверки | "Container must run as non-root" |
| `policy` | Название примененной политики | `require-run-as-non-root` |
| `result` | Статус (результат) проверки | `pass`, `fail`, `warn`, `skip`, `error` |
| `resource` | Ссылка на ресурс | `pod/my-app` |
| `rule` | Название конкретного правила | `run-as-non-root` |
| `severity` | Уровень критичности | `low`, `medium`, `high`, `critical` |

### Статусы результатов

| Статус | Описание | Условие присвоения |
|--------|----------|---------------------|
| **pass** | Пройдено | Ресурс полностью соответствует правилам политики. |
| **fail** | Ошибка | Ресурс нарушает правила (в режиме `audit` или `enforce`). |
| **warn** | Предупреждение | Используется при мягких проверках или переходных периодах. |
| **skip** | Пропущено | Правило не применимо к ресурсу (например, из-за `exclude`). |
| **error** | Системная ошибка | Произошел сбой при попытке обработать ресурс. |

---

## Практические сценарии

### Просмотр отчетов через kubectl

```bash
# Список отчетов в конкретном пространстве имен
kubectl get policyreports -n <namespace>
# → NAME           PASS   FAIL   WARN   ERROR   SKIP   AGE
# → policyreport   15     3      1      0       0      10m

# Список отчетов масштаба кластера
kubectl get clusterpolicyreports

# Детальный просмотр отчета
kubectl describe policyreport <name> -n <namespace>

# Поиск отчетов с нарушениями (fail > 0)
kubectl get policyreports -n <namespace> -o jsonpath='{range .items[?(@.summary.fail>0)]}{"Namespace: "}{.metadata.namespace}{" - Fail: "}{.summary.fail}{"\n"}{end}'
```

### Анализ нарушений в кластере

```bash
# Вывод всех ресурсов, нарушающих политики
kubectl get clusterpolicyreports -o jsonpath='{range .items[*].results[?(@.result=="fail")]}{"Policy: "}{.policy}{" Resource: "}{.resource}{" Message: "}{.message}{"\n"}{end}'

# Статистика нарушений по политикам
kubectl get clusterpolicyreports -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.summary.fail}{"\n"}{end}' | sort -k2 -nr
```

### Визуализация и мониторинг

Для удобной работы с отчетами рекомендуется использовать **Policy Reporter** ([подробнее](./reporter.md)). Он предоставляет:

- **UI** (User Interface, пользовательский интерфейс) для поиска и фильтрации.
- **REST API** (Representational State Transfer Application Programming Interface) для интеграции.
- Отправку уведомлений в Slack, Telegram или Discord.

Метрики для Prometheus (система мониторинга):

```prometheus
# Общее количество результатов по статусам
policy_report_result_total{result="fail", policy="require-run-as-non-root"}

# Сводная статистика по пространству имен
policy_report_summary_fail{namespace="default"}
```

---

## Дополнительная информация

### Настройка метаданных через аннотации

Аннотации в политиках определяют, как информация будет отображаться в отчетах:

| Аннотация | Пример значения | Назначение |
|-----------|-----------------|------------|
| `policies.kyverno.io/title` | "Require Non-Root User" | Человекочитаемое название. |
| `policies.kyverno.io/category` | "Security" | Группировка в интерфейсе. |
| `policies.kyverno.io/severity` | "high" | Определение приоритета исправления. |

### Ограничения системы отчетов

1. **Нагрузка на etcd**: При очень большом количестве ресурсов (десятки тысяч) объем отчетов может существенно увеличить нагрузку на хранилище данных Kubernetes.
2. **Отсутствие истории**: Policy Reports показывают только срез на текущий момент. Для хранения истории необходимо настроить экспорт логов или использовать внешние инструменты.
3. **Зависимость от контроллера**: Генерацией отчетов занимается `reports-controller`. Если он остановлен, информация в отчетах перестанет обновляться.

### Связанные темы

- [Policy Reporter](./reporter.md) — визуализация и алертинг.
- [Фоновое сканирование](./background.md) — как Kyverno проверяет существующие ресурсы.
- [Интеграция с Prometheus](./reporter.md#метрики) — мониторинг состояния безопасности.
