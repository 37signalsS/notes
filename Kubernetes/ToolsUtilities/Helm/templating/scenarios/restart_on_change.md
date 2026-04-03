# Rolling Update on ConfigMap Change

---

## Definitions

**Checksum-аннотации** — аннотации в `spec.template.metadata.annotations` Deployment/StatefulSet, содержащие SHA256-хеш содержимого ConfigMap или Secret. Изменение хеша вызывает rolling update подов.

---

## Basic Concepts

### Принцип работы

1. В `spec.template.metadata.annotations` Deployment/StatefulSet добавляется аннотация с хешем.
2. Значение аннотации — SHA256-хеш отрендеренного содержимого шаблона ConfigMap.
3. При `helm upgrade` содержимое ConfigMap меняется → хеш меняется → Kubernetes видит изменение в `spec.template.metadata` → rolling update.

### Почему это работает

Kubernetes не отслеживает изменения ConfigMap/Secret автоматически. Поды используют смонтированные данные, но не перезапускаются при их изменении. Изменение аннотаций в `spec.template` — единственный стандартный способ вызвать rolling update без внешних контроллеров (stakater/reloader).

### Какие функции используются

| Функция | Назначение |
|---------|------------|
| `print` | Конкатенация строк для пути к файлу |
| `include` | Чтение отрендеренного содержимого файла шаблона |
| `sha256sum` | Вычисление SHA256-хеша строки |

Подробнее о функциях: [Функции Helm](../functions.md).

---

## Practical Scenarios

### Deployment с ConfigMap

**templates/configmap.yaml:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
data:
  app.conf: |
    {{ .Values.appConfig | nindent 4 }}
```

**templates/deployment.yaml:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print .Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
        - name: app
          image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
          volumeMounts:
            - name: config
              mountPath: /etc/config
      volumes:
        - name: config
          configMap:
            name: {{ include "myapp.fullname" . }}-config
```

### StatefulSet с ConfigMap

**templates/statefulset.yaml:**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print .Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
        - name: app
          image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
          volumeMounts:
            - name: config
              mountPath: /etc/config
      volumes:
        - name: config
          configMap:
            name: {{ include "myapp.fullname" . }}-config
```

Механизм идентичен Deployment — аннотация в `spec.template.metadata.annotations`.

### Secret вместо ConfigMap

Для секретов принцип тот же:

**templates/secret.yaml:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "myapp.fullname" . }}-secret
type: Opaque
data:
  db-password: {{ .Values.db.password | b64enc | quote }}
```

**templates/deployment.yaml:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  template:
    metadata:
      annotations:
        checksum/secret: {{ include (print .Template.BasePath "/secret.yaml") . | sha256sum }}
    spec:
      containers:
        - name: app
          env:
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: {{ include "myapp.fullname" . }}-secret
                  key: db-password
```

### Несколько ConfigMap

Если ConfigMap несколько, каждая аннотируется отдельно:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  template:
    metadata:
      annotations:
        checksum/app-config: {{ include (print .Template.BasePath "/configmap.yaml") . | sha256sum }}
        checksum/nginx-config: {{ include (print .Template.BasePath "/nginx-configmap.yaml") . | sha256sum }}
```

Изменение любого из ConfigMap изменит соответствующий хеш и вызовет rolling update.

---

## Dissecting the Annotation

Разбор выра:

```yaml
checksum/config: {{ include (print .Template.BasePath "/configmap.yaml") . | sha256sum }}
```

1. `.Template.BasePath` — путь к директории `templates/` (например, `./myapp/templates`)
2. `print .Template.BasePath "/configmap.yaml"` — конкатенация: `./myapp/templates/configmap.yaml`
3. `include ... .` — рендерит файл configmap.yaml с текущим контекстом (`.Values`, `.Release`, `.Chart`)
4. `| sha256sum` — вычисляет SHA256-хеш отрендеренного содержимого

Результат — строка вроде `a1b2c3d4e5f6...`, которая меняется при любом изменении в ConfigMap.

---

## Limitations

- **Только при `helm upgrade`** — хеш пересчитывается при рендеринге, не при изменении ConfigMap извне (`kubectl edit configmap`).
- **Не работает при `helm template`** — функция `include` требует доступа к API кластера.
- **Не отслеживает `kubectl edit`** — внешние изменения ConfigMap не влияют на хеш.

---

## Additional Information

Функции `sha256sum`, `include` — в [Функции Helm](../functions.md). Условное добавление аннотаций — в [Условная логика](./conditionals.md). Альтернативный подход (внешний контроллер) — [stakater/reloader](https://github.com/stakater/Reloader).
