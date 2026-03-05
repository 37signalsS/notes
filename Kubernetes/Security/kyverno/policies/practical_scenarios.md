# Политики Kyverno: Практические сценарии

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

- `(field)` — опциональное поле: если присутствует, проверяется условие
- `=(field)` — обязательное поле
- `>(n)`, `>=(n)`, `=(n)`, `<(n)`, `<=(n)` — числовые сравнения
- `*` — wildcard (любое значение)

---

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

Условия работают с **AdmissionReview** — JSON-объект, содержащий информацию о запросе:

- `request.object` — проверяемый ресурс
- `request.userInfo` — информация о пользователе
- `request.namespace` — namespace операции

---

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
  background: true
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

---

### Запрет HostPath

Запрещает использование `hostPath` volumes:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-host-path
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
        message: "HostPath volumes are forbidden"
```

> **Примечание**: Данная политика не перехватывает `PersistentVolume` с типом `Local`. Необходимо создавать отдельную политику для PV.

---

### Требование limits ресурсов

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-resource-limits
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: require-limits
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "CPU and memory limits are required"
        pattern:
          spec:
            containers:
              - resources:
                  limits:
                    memory: "?*"
                    cpu: "?*"
```

---

### Запрет privileged контейнеров

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-privileged-containers
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: deny-privileged
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Privileged containers are forbidden"
        pattern:
          spec:
            containers:
              - =(securityContext):
                  privileged: false
```

---

### Мутация: Добавление securityContext

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-security-context
spec:
  rules:
    - name: add-default-securitycontext
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

### Генерация: Копирование Secret

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
          namespace: template
          name: docker-registry-credentials
        synchronize: true
```

---

## Ссылки

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Дополнительная информация](./advanced_topics.md) — операторы, переменные, важные замечания
