# Написание политик Kyverno

## Типы политик

* **Policy**: Namespace-scoped — применяется к ресурсам в конкретном namespace.
* **ClusterPolicy**: Cluster-scoped — применяется ко всему кластеру.

Для применения политики к нескольким namespace рекомендуется использовать **ClusterPolicy**.

## Структура политики

Политика состоит из:
1. **metadata**: Имя, аннотации
2. **spec**: Спецификация политики
   * `background`: Включить/выключить фоновое сканирование (по умолчанию `true`)
   * `failureAction`: Действие при нарушении политики (`enforce` — запретить, `audit` — только отчет)
   * `rules`: Набор правил (минимум одно)

## Правила (rules)

Каждое правило содержит:
* `match`: Условие применения политики к ресурсам
* `exclude`: Условие исключения ресурсов
* Тип правила: `validate`, `mutate`, `generate`, `deny`

### Match и Exclude

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

## Валидация с помощью pattern

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

## Запрещающие правила (deny)

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

## Примеры политик

### Требование non-root пользователя

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

### Запрет HostPath

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

## Важные замечания

1. **Background scan не применяется к существующим ресурсам** — политика срабатывает только при CREATE/UPDATE.
2. По умолчанию все примеры политик в документации используют `failureAction: audit`.
3. Для полной защиты необходимо переключить на `failureAction: Enforce`.
4. Политики применяются к **Pod** — Kyverno проверяет итоговый Pod, сгенерированный из Deployment/StatefulSet/DaemonSet и т.д.
