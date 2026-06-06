# Библиотека политик Kyverno: Практические примеры

## Определения

**Политика (Policy)** — основной декларативный ресурс Kyverno, содержащий набор правил для проверки, изменения или создания объектов Kubernetes.

**Типы политик**:
- **ClusterPolicy**: Глобальный ресурс кластера (cluster-scoped), правила которого применяются ко всем пространствам имен (**Namespaces**) в кластере.
- **Policy**: Локальный ресурс (namespace-scoped), действующий только в рамках конкретного пространства имен.

---

## Основные концепции

### Структура манифеста политики

Примеры в данной библиотеке написаны на языке **YAML (Yet Another Markup Language)** и используют стандартную структуру ресурсов Kyverno ([детальный разбор синтаксиса в типах правил](../rules.md)):

| Поле | Описание | Возможные значения |
|------|----------|--------------------|
| `validationFailureAction` | Режим реакции на нарушение. | `Audit` (запись в отчет), `Enforce` (блокировка). |
| `background` | Фоновое сканирование ресурсов. | `true` (аудит запущенных объектов), `false`. |
| `match` / `exclude` | Условия выбора или исключения ресурсов. | `kinds` (типы), `namespaces`, `subjects`. |

---

## Практические сценарии

### 1. Требование запуска от имени non-root пользователя

Базовая мера безопасности, предотвращающая запуск контейнеров с правами суперпользователя для уменьшения поверхности атаки.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-run-as-non-root
  annotations:
    policies.kyverno.io/title: Require Non-Root User
    policies.kyverno.io/category: Security
    policies.kyverno.io/severity: high
    policies.kyverno.io/description: "Контейнеры должны запускаться от имени non-root пользователя."
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: check-run-as-non-root
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Контейнер должен запускаться от имени пользователя с UID (User Identifier, идентификатор пользователя) > 0"
        pattern:
          spec:
            =(securityContext):
              runAsUser: ">0"
```

---

### 2. Запрет использования HostPath томов

Предотвращает монтирование файловой системы хоста внутрь контейнера, что является критической уязвимостью.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-host-path
  annotations:
    policies.kyverno.io/title: Deny HostPath Volumes
    policies.kyverno.io/category: Security
    policies.kyverno.io/severity: high
spec:
  validationFailureAction: Enforce
  background: true
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
        message: "Использование HostPath запрещено корпоративными стандартами безопасности"
```

---

### 3. Автоматическое добавление настроек безопасности (Мутация)

Автоматизирует процесс приведения ресурсов к безопасному виду, добавляя `securityContext`, если он не был указан разработчиком.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-default-security-context
  annotations:
    policies.kyverno.io/title: Add Default Security Context
    policies.kyverno.io/category: Security
spec:
  rules:
    - name: add-security-context
      match:
        resources:
          kinds:
            - Pod
      mutate:
        patchStrategicMerge:
          spec:
            securityContext:
              runAsNonRoot: true
              runAsUser: 1000
              fsGroup: 1000
```

---

### 4. Синхронизация секретов между Namespace (Генерация)

Пример копирования секрета с учетными данными для Docker Registry во все создаваемые пространства имен.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: copy-docker-registry-secret
spec:
  rules:
    - name: copy-secret
      match:
        resources:
          kinds:
            - Namespace
      generate:
        kind: Secret
        name: docker-registry-credentials
        namespace: "{{request.object.metadata.name}}"
        clone:
          namespace: template-namespace # Эталонный namespace
          name: docker-registry-credentials
        synchronize: true
```

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **Постепенное внедрение**: Всегда начинайте с режима `Audit`. Проверяйте результаты в **[Policy Reports (Отчетах)](../reports.md)** перед переходом к `Enforce`.
2.  **Фоновая проверка**: Не отключайте `background: true`, если хотите видеть нарушения в уже запущенных ресурсах через отчеты или **[Policy Reporter](../reporter.md)**.
3.  **Аннотации**: Используйте стандартные аннотации `policies.kyverno.io/category` для группировки политик в дэшбордах.
4.  **Системные исключения**: Добавляйте `exclude` для критических пространств имен (например, `kube-system`), чтобы политики валидации не нарушили работу кластера.

### Связанные темы

- [Типы правил](../rules.md) — детальный синтаксис (match, validate, mutate, generate).
- [Основные концепции](../concepts.md) — архитектура контроллеров допуска.
- [Определения и структура](./definitions_and_concepts.md) — детальный разбор полей манифеста.
- [Расширенные возможности](./advanced_topics.md) — переменные и конструкции циклов.
