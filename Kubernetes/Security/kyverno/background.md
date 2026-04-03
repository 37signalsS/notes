# Background Scans Kyverno

## Определения

**Background Scan** — механизм периодического сканирования существующих ресурсов в кластере на соответствие политикам Kyverno.

**Важно**: Background scan **не применяет** политики к существующим ресурсам — он только генерирует отчеты. Политики применяются только к **новым** ресурсам (на этапе admission).

---

## Базовые концепции

### Параметр background

| Значение | Описание |
|----------|----------|
| `true` (по умолчанию) | Фоновое сканирование включено — существующие ресурсы проверяются и добавляются в отчеты |
| `false` | Фоновое сканирование отключено — отчеты формируются только для новых/изменённых ресурсов |

### Как работает Background Scan

1. **Background Controller** периодически сканирует ресурсы в кластере
2. Для каждой политики проверяются существующие ресурсы, подходящие под `match` условия
3. Результаты сканирования записываются в [Policy Reports](./reports.md)
4. При нарушении политики в режиме `audit` — создается запись в отчете
5. При нарушении политики в режиме `enforce` — **ресурс не блокируется** (только отчет)

### Таблица режимов

| Background | Failure Action | Результат для существующих ресурсов |
|------------|----------------|-------------------------------------|
| `true` | `Enforce` | Только отчеты (reports) |
| `true` | `Audit` | Только отчеты (reports) |
| `false` | `Enforce` | Нет отчетов для существующих |
| `false` | `Audit` | Нет отчетов для существующих |

> **Ключевое правило**: Background scan предназначен для **аудита** и **отладки** политик перед переходом в режим enforce.

---

## Практические сценарии

### Отключение Background Scan

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-run-as-non-root
spec:
  background: false  # Отключить фоновое сканирование
  validationFailureAction: Enforce
  rules:
    - name: run-as-non-root
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Container must run as non-root"
        pattern:
          spec:
            securityContext:
              runAsNonRoot: true
```

**Когда отключать**:

- Политики применяются только к новым ресурсам
- Не нужны отчеты для существующих ресурсов
- Экономия ресурсов кластера

### Включение Background Scan

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: audit-security-context
spec:
  background: true  # Включить фоновое сканирование (по умолчанию)
  validationFailureAction: Audit
  rules:
    - name: check-security-context
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "securityContext required"
        pattern:
          spec:
            securityContext:
              runAsNonRoot: true
```

**Когда включать**:

- Аудит существующих ресурсов
- Отладка политик перед `Enforce`
- Мониторинг соответствия стандартам

### Проверка результатов Background Scan

```bash
# Просмотр Policy Reports
kubectl get policyreports -n <namespace>

# Детальная информация
kubectl describe policyreport <name> -n <namespace>

# Просмотр ClusterPolicyReports
kubectl get clusterpolicyreports

# Фильтрация по статусу
kubectl get policyreports -n <namespace> -o jsonpath='{range .items[?(@.summary.fail>0)]}{"Namespace: "}{.metadata.namespace}{" - Fail: "}{.summary.fail}{"\n"}{end}'
```

### Пример отчета

```yaml
apiVersion: wgpolicyk8s.io/v1alpha2
kind: PolicyReport
metadata:
  name: policyreport
  namespace: default
results:
  - category: security
    message: "Container must run as non-root"
    policy: require-run-as-non-root
    result: fail
    resource: pod/my-app
    rule: run-as-non-root
    severity: high
summary:
  error: 0
  fail: 3
  pass: 10
  skip: 0
  warn: 0
```

---

## Дополнительная информация

### Производительность

| Фактор | Влияние | Рекомендация |
|--------|---------|--------------|
| Количество политик | Линейная зависимость | Не более 50-100 политик на кластер |
| Количество ресурсов | Линейная зависимость | Использовать `exclude` для системных namespace |
| Частота сканирования | Настраивается в контроллере | По умолчанию 15 минут |

### Исключения для системных namespace

```yaml
spec:
  background: true
  rules:
    - name: check-security-context
      match:
        resources:
          kinds:
            - Pod
      exclude:
        resources:
          namespaces:
            - kube-system
            - kube-public
            - kyverno
            - policy-reporter
```

### Связанные темы

- [Policy Reporter](./reporter.md) — Web UI для просмотра отчетов
- [Написание политик](./policies/practical_scenarios.md) — параметр `background` в контексте политик
- [Policy Reports](./reports.md) — формат и структура отчетов
