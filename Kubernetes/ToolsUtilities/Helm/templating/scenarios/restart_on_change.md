# Автоматический перезапуск подов (Restart on Change)

---

## Определения

**Checksum-аннотации (аннотации контрольной суммы)** — метаданные в секции `spec.template.metadata.annotations` ресурсов Deployment или StatefulSet, содержащие хеш-сумму алгоритма SHA-256 (Secure Hash Algorithm 256-bit) от содержимого ConfigMap или Secret. Изменение хеша вызывает автоматическое плавное обновление (rolling update) подов.

---

## Основные концепции

### Принцип работы

1. В блок `spec.template.metadata.annotations` Deployment или StatefulSet добавляется аннотация с вычисленным хешем.
2. Значением аннотации является SHA-256 хеш отрендеренного содержимого шаблона ConfigMap.
3. При выполнении команды `helm upgrade` содержимое ConfigMap изменяется → хеш пересчитывается и меняется → Kubernetes обнаруживает изменение в `spec.template.metadata` → инициируется процесс rolling update.

### Почему это работает

Kubernetes не отслеживает изменения в ресурсах ConfigMap или Secret автоматически для уже запущенных подов. Поды используют смонтированные данные, но не перезапускаются при их обновлении. Изменение аннотаций в спецификации шаблона пода (`spec.template`) — это единственный стандартный нативный способ вызвать rolling update без использования внешних контроллеров (таких как stakater/Reloader).

### Какие функции используются

| Функция | Назначение |
|---------|------------|
| `print` | Конкатенация строк для формирования пути к файлу |
| `include` | Выполнение рендеринга и чтение содержимого файла шаблона |
| `sha256sum` | Вычисление SHA-256 хеша от переданной строки |

Подробнее о доступных функциях: [Функции Helm](../functions.md).

---

## Практические сценарии

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

Механизм полностью идентичен Deployment — аннотация размещается в `spec.template.metadata.annotations`.

### Secret вместо ConfigMap

Для работы с секретами применяется тот же принцип:

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

Если приложение использует несколько конфигурационных файлов, каждый из них аннотируется отдельно:

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

Изменение любого из подключенных ConfigMap приведёт к изменению соответствующего хеша и вызовет rolling update.

---

## Разбор работы аннотации

Детальный разбор выражения шаблонизатора:

```yaml
checksum/config: {{ include (print .Template.BasePath "/configmap.yaml") . | sha256sum }}
```

1. `.Template.BasePath` — возвращает путь к директории `templates/` (например, `myapp/templates`).
2. `print .Template.BasePath "/configmap.yaml"` — выполняет конкатенацию строк, формируя полный путь: `myapp/templates/configmap.yaml`.
3. `include ... .` — рендерит указанный файл (в данном случае `configmap.yaml`) с передачей текущего контекста исполнения (`.Values`, `.Release`, `.Chart`).
4. `| sha256sum` — вычисляет хеш SHA-256 от полученного на предыдущем шаге отрендеренного содержимого.

Результат — уникальная строка (например, `a1b2c3d4e5f6...`), которая будет меняться при любом (даже минимальном) изменении внутри исходного ConfigMap.

---

## Ограничения

- **Работает только при `helm upgrade`** — хеш пересчитывается исключительно в момент рендеринга шаблонов через Helm. Это не работает при прямом редактировании ConfigMap через `kubectl edit configmap`.
- **Не работает при `helm template`** — функция `include` для вычисления хеша требует полного контекста, что может вызывать предупреждения при локальном рендеринге без кластера.
- **Внешние изменения игнорируются** — любые изменения ConfigMap, выполненные в обход Helm, не повлияют на хеш и не вызовут перезапуск.

---

## Дополнительная информация

- [Функции Helm](../functions.md) — подробности о работе функций `sha256sum` и `include`.
- [Условная логика](./conditionals.md) — применение условного добавления аннотаций.
- [stakater/Reloader](../../../reloader/reloader_overview.md) — альтернативный подход к перезапуску с использованием внешнего Kubernetes-контроллера.
- [Обновление и Rollout ConfigMap](../../../../Base/ConfigMap/update_and_rollout.md) — общие концепции обновления конфигураций в Kubernetes.
