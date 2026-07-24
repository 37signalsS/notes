# Автоматический перезапуск подов (Restart on Change)

---

## Определения

**Checksum-аннотации (аннотации контрольной суммы)** — специальные метаданные, размещаемые в секции `spec.template.metadata.annotations` контроллеров Kubernetes (Deployment, StatefulSet, DaemonSet). Они содержат криптографический хеш (SHA-256) отрендеренного содержимого конфигурационных файлов (ConfigMap или Secret). Изменение этого хеша при обновлении чарта вынуждает Kubernetes запустить процесс плавного обновления (Rolling Update) для применения новых настроек.

---

## Основные концепции

### Принцип работы

1. В спецификацию шаблона пода (`spec.template`) добавляется аннотация, имя которой обычно начинается с `checksum/` (например, `checksum/config`).
2. В качестве значения аннотации вычисляется хеш-сумма от содержимого файлов конфигурации с помощью функций Helm.
3. При выполнении команды `helm upgrade` Helm заново рендерит все шаблоны. Если данные в ConfigMap или Secret изменились, итоговая строка хеша также изменится.
4. Kubernetes отслеживает изменения в `spec.template`. Любое изменение в этой секции (включая только аннотации) приводит к созданию новой ревизии ReplicaSet (для Deployment) и инициации Rolling Update.

### Почему это необходимо

Kubernetes обладает специфическим поведением при обновлении внешних конфигураций:
- **Переменные окружения (`env`, `envFrom`):** Значения считываются только в момент старта контейнера. Если ConfigMap в API обновится, переменные в уже запущенном поде останутся старыми до ручного перезапуска.
- **Тома (`volumes`):** Изменения в ConfigMap/Secret синхронизируются на файловую систему пода через `kubelet` с задержкой (по умолчанию до 1-2 минут). Однако большинство современных приложений считывают конфиг один раз при старте и не отслеживают изменения файлов (отсутствие механизма Hot Reload через `inotify`).

Использование паттерна "Restart on Change" гарантирует, что приложение всегда работает с актуальной конфигурацией, так как обновление настроек автоматически влечет за собой контролируемый перезапуск всех экземпляров приложения.

### Ключевые функции Helm

| Функция | Назначение в контексте паттерна |
| :--- | :--- |
| `print` | Формирует полный путь к файлу шаблона внутри чарта для функции `include`. |
| `include` | Рендерит указанный шаблон и возвращает результат как строку, что позволяет передавать его в пайплайн. |
| `sha256sum` | Генерирует SHA-256 отпечаток. Альтернативы из Sprig: `sha1sum`, `adler32sum` (менее надежны). |
| `tpl` | Позволяет обработать строку как полноценный шаблон Helm (полезно для динамических конфигов в `values.yaml`). |

---

## Практические сценарии

### Deployment с ConfigMap

Использование глобального контекста `$` позволяет корректно вычислять пути даже внутри вложенных циклов (`range`).

**templates/configmap.yaml:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
data:
  app.conf: |
    server_port: {{ .Values.server.port | default 8080 }}
    log_level: {{ .Values.logging.level | default "info" }}
```

**templates/deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app: {{ include "myapp.name" . }}
  template:
    metadata:
      annotations:
        # Автоматический перезапуск при изменении configmap.yaml
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
        - name: app
          image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
          volumeMounts:
            - name: config-volume
              mountPath: /etc/app
      volumes:
        - name: config-volume
          configMap:
            name: {{ include "myapp.fullname" . }}-config
```

### StatefulSet и DaemonSet

Для этих контроллеров механизм идентичен — аннотация должна находиться строго внутри `spec.template.metadata`.

**templates/daemonset.yaml:**
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: {{ include "myapp.fullname" . }}-agent
spec:
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
        - name: agent
          image: {{ .Values.agent.image }}
          volumeMounts:
            - name: config
              mountPath: /etc/agent
      volumes:
        - name: config
          configMap:
            name: {{ include "myapp.fullname" . }}-config
```

### Сценарий с Secret (Обновление паролей)

Это наиболее частый кейс, когда нужно принудительно обновить поды после смены учетных данных.

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

**templates/deployment.yaml (фрагмент):**
```yaml
spec:
  template:
    metadata:
      annotations:
        checksum/secret: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
```

### Динамические файлы и циклы (Files.Glob)

Если ConfigMap собирается из множества файлов в папке (например, `configs/`), можно вычислить суммарный хеш всех файлов. Это гарантирует перезапуск при изменении любого файла в директории.

```yaml
annotations:
  # Вычисляет хеш от путей и содержимого всех файлов в папке configs
  checksum/all-configs: {{ range $path, $bytes := $.Files.Glob "configs/**" }}{{ $path }}{{ $bytes | sha256sum }}{{ end | sha256sum }}
```

### Хеширование нескольких ресурсов в одну аннотацию

Если приложение зависит от десятка ConfigMap, созданных циклом, можно собрать их хеши в одну строку:

```yaml
annotations:
  checksum/configs: {{ range $name, $val := .Values.configs }}{{ $name }}{{ $val | toYaml | sha256sum }}{{ end | sha256sum }}
```

---

## Разбор работы аннотации

Рассмотрим подробно, как Helm вычисляет значение:

```yaml
checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
```

1. **`$.Template.BasePath`**: Переменная возвращает относительный путь к папке `templates` (например, `my-app/templates`). Использование `$` гарантирует доступ к корню даже из вложенных областей видимости.
2. **`print ... "/configmap.yaml"`**: Соединяет путь и имя файла. Результат: `my-app/templates/configmap.yaml`.
3. **`include ... .`**: Рендерит указанный файл как именованный шаблон, передавая текущий контекст. В результате мы получаем полный текст ConfigMap в виде строки.
4. **`| sha256sum`**: Полученная строка передается в функцию хеширования. Результат — строка из 64 символов (например, `9f86d081884c...`).

---

## Тонкости и нюансы

### Влияние пробелов и комментариев

Функция `sha256sum` работает на уровне байтов. Изменение форматирования (добавление пробела, пустой строки или комментария) в файле ConfigMap изменит его хеш. Kubernetes воспримет это как изменение конфигурации и перезапустит поды, даже если параметры приложения не поменялись.

### include против template

Это критическое различие для пайплайнов Helm:
- **`template`**: Директива Go-шаблонов. Вставляет содержимое, но не возвращает его как строковое значение. Его нельзя передать в пайплайн (`|`).
- **`include`**: Функция Helm. Возвращает результат рендеринга как строку. Только её можно использовать совместно с `sha256sum`.

### Обработка динамических шаблонов (tpl)

Если ваши файлы конфигурации в `values.yaml` сами содержат логику Helm (например, `url: http://{{ .Release.Name }}-svc`), обычный `include` может не учесть изменения переменных, если он просто читает файл. Для корректного хеширования таких файлов используется функция `tpl`:

```yaml
# Читаем файл и рендерим его как шаблон перед вычислением хеша
checksum/config: {{ tpl ($.Files.Get "configs/app.conf") . | sha256sum }}
```

---

## Проверка и отладка

### Ручная проверка в кластере

Чтобы убедиться, что аннотация добавлена и имеет значение, используйте `kubectl`:

```bash
# Просмотр аннотаций в текущем Deployment
kubectl get deployment my-app -o jsonpath='{.spec.template.metadata.annotations}'
```

### Отладка через Helm

Перед деплоем проверьте, как Helm вычисляет хеш, используя `helm template`:

```bash
helm template my-release ./my-chart --debug
```
В выводе вы увидите реальное значение хеша в секции `annotations`.

---

## Ограничения

- **Только Helm-операции**: Перезапуск происходит только при выполнении `helm upgrade`. Ручное изменение ConfigMap через `kubectl edit` не обновит аннотацию в Deployment.
- **Динамические значения**: Функции типа `randAlphaNum` или `now` внутри хешируемых файлов приведут к перезапускам при **каждом** деплое.
- **Внешние данные**: Если ConfigMap/Secret заполняются внешними операторами (например, Vault или External Secrets) уже после деплоя чарта, Helm не сможет отследить их изменения, так как хеш вычисляется в момент рендеринга чарта на стороне клиента.

---

## Дополнительная информация

- [Функции Helm](../functions.md) — подробный справочник по `sha256sum`, `include`, `tpl`.
- [Обновление и Rollout ConfigMap](../../../../Base/ConfigMap/update_and_rollout.md) — базовые принципы работы конфигураций в Kubernetes.
- [stakater/Reloader](../../../reloader/reloader_overview.md) — описание контроллера, который автоматически отслеживает изменения Secret/ConfigMap без правки шаблонов.
