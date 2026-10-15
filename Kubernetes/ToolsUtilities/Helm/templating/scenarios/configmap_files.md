# Работа с ConfigMap и внешними файлами в Helm

---

## Определения

**.Files** — встроенный объект Helm, предоставляющий доступ к статическим файлам внутри директории чарта. Позволяет считывать конфигурации, скрипты, сертификаты и бинарные данные для вставки в манифесты Kubernetes.

**.helmignore** — файл правил исключения (аналогично `.gitignore`), указывающий Helm, какие файлы и директории не должны участвовать в упаковке чарта и быть доступны через `.Files`.

**Экранирование шаблонизатора** — прием, позволяющий сохранить конструкцию `{{ ... }}` в итоговом файле (например, в конфигурации Prometheus или Nginx) без попытки Helm интерпретировать её как собственную переменную.

**Checksum-аннотация** — аннотация в `spec.template.metadata.annotations` Deployment/StatefulSet/DaemonSet, содержащая хеш-сумму отрендеренного ConfigMap или Secret. Изменение хеша при `helm upgrade` вынуждает Kubernetes инициировать Rolling Update.

---

## Базовые концепции

### Особенности объекта .Files

- **Область доступа:** Доступны только файлы внутри директории чарта. Файлы в `templates/` недоступны через `.Files`, так как они зарезервированы для движка шаблонов.
- **Пути:** Указываются относительно корня чарта (например, `files/config.json`). Использование `../` для выхода за пределы чарта запрещено из соображений безопасности.
- **Исключения:** Файлы, указанные в `.helmignore`, полностью игнорируются объектом `.Files`.
- **Кэширование:** Helm кэширует содержимое файлов в течение одного запуска рендеринга. При повторном вызове `.Files.Get` для того же пути возвращается закэшированное значение. Это означает, что функция `tpl`, применённая к содержимому файла, не будет перевычислена при повторном обращении к тому же файлу в рамках одного релиза.
- **Лимиты Kubernetes:** Суммарный размер ConfigMap или Secret не может превышать **1 MiB** (1 048 576 байт). Лимит связан с ограничениями производительности etcd. При превышении API-сервер отклоняет запрос с ошибкой `RequestEntityTooLarge`. Большие бинарные файлы (образы, архивы, модели ML) следует хранить во внешних хранилищах (Object Storage, NFS) или использовать Persistent Volumes.

### Методы работы с данными

| Метод | Возвращаемый тип | Описание |
|-------|------------------|----------|
| `.Files.Get "path"` | `string` | Содержимое файла как строка (UTF-8). |
| `.Files.GetBytes "path"` | `[]byte` | Содержимое файла как массив байтов (для бинарных данных). |
| `.Files.Glob "pattern"` | `File` (map) | Словарь, где ключ — путь, а значение — содержимое (поддерживает glob-шаблоны, включая рекурсию через `**`). |
| `.Files.Lines "path"` | `[]string` | Построчное чтение файла для итерации в циклах. |
| `.AsConfig` | `string` (YAML) | Хелпер для Glob: формирует блок `data` для ConfigMap. Ключи в результате — только имена файлов (без директорий). |
| `.AsSecrets` | `string` (YAML) | Хелпер для Glob: формирует блок `data` для Secret (Base64). Ключи в результате — только имена файлов. |

### Глобальный контекст и функции

При использовании `.Files.Glob` внутри блоков `range` или `with` контекст (`.`) смещается на текущий элемент. Для доступа к корневому `.Files` используйте глобальный контекст (`$.Files`):

```yaml
{{- range $path, $content := $.Files.Glob "configs/**" }}
{{ base $path }}: |
{{ $content | nindent 2 }}
{{- end }}
```

Функция `base` (из библиотеки Sprig) возвращает последний элемент пути (имя файла без директорий), что позволяет сохранить короткие ключи в ConfigMap при рекурсивном обходе.

### Правила .helmignore

Файл `.helmignore` поддерживает стандартные wildcard-символы:

```text
# Исключить документацию и мета-файлы
*.md
*.txt
LICENSE

# Исключить директории полностью
tests/
docs/
.git/
.helmignore

# Исключить локальные конфиги разработчика
*.local
.env*
!.env.production

# Исключить бинарники, но разрешить сертификаты
*.bin
*.exe
!certs/*.pem
```

**Важно:** `.helmignore` влияет только на упаковку чарта (`helm package`) и доступ через `.Files`. Файлы, добавленные через `--set-file` или переданные напрямую в `helm install`, могут обойти это ограничение.

---

## Практические сценарии

### Вставка текстовой конфигурации

Используется для вставки готовых файлов настроек (Nginx, JSON, YAML) в `ConfigMap`.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
data:
  # nindent 4 необходим для сохранения структуры YAML
  nginx.conf: |
    {{ .Files.Get "configs/nginx.conf" | nindent 4 }}
```

### Обработка бинарных данных (binaryData)

Если файл содержит нетекстовые данные (например, иконку или скомпилированный плагин), используйте `.Files.GetBytes` и поле `binaryData`.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-assets
binaryData:
  logo.png: {{ .Files.GetBytes "assets/logo.png" | b64enc }}
```

### Рекурсивный массовый импорт (Glob + base)

Позволяет автоматически добавить все файлы из `configs/` (включая поддиректории) в один `ConfigMap`, сохраняя короткие имена ключей:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-configs
data:
{{- range $path, $content := $.Files.Glob "configs/**" }}
{{ base $path }}: |
{{ $content | nindent 2 }}
{{- end }}
```

### Массовый импорт с AsConfig

Используйте `.AsConfig` для быстрого создания ConfigMap из всех файлов директории. Ключи будут совпадать с именами файлов:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-scripts
data:
{{ (.Files.Glob "scripts/*.sh").AsConfig | nindent 2 }}
```

**Результат рендеринга:**
```yaml
data:
  backup.sh: |
    #!/bin/bash
    ...
  restore.sh: |
    #!/bin/bash
    ...
```

### Построчная обработка (Files.Lines)

Пример создания списка разрешенных IP-адресов из внешнего текстового файла.

```yaml
data:
  whitelist.conf: |
    {{- range .Files.Lines "files/ips.txt" }}
    allow {{ . }};
    {{- end }}
```

### Динамический рендеринг (Files + tpl)

Если внешний файл сам является шаблоном и должен использовать переменные из `values.yaml`.

```yaml
data:
  app-config.yaml: |
{{ tpl (.Files.Get "configs/app.yaml.tpl") . | nindent 4 }}
```

> **См. также:** Паттерн хранения конфигурационных файлов в директории `config/` с рендерингом секретов через `consul-template` + `Vault` и использованием `subPath` для монтирования — в [CI-рендеринг конфигов через consul-template + Vault](./config-rendering-pattern.md).

### Условный импорт по окружению

Импортируйте разные файлы конфигурации в зависимости от окружения (development, staging, production):

```yaml
data:
{{- if eq .Values.environment "production" }}
  app.yaml: |
    {{ .Files.Get "configs/prod/app.yaml" | nindent 4 }}
{{- else if eq .Values.environment "staging" }}
  app.yaml: |
    {{ .Files.Get "configs/staging/app.yaml" | nindent 4 }}
{{- else }}
  app.yaml: |
    {{ .Files.Get "configs/dev/app.yaml" | nindent 4 }}
{{- end }}
```

### Immutable ConfigMap с checksum-аннотацией

Для Production рекомендуется комбинировать `immutable: true` с checksum-аннотацией в Deployment. Это гарантирует, что обновление конфигурации требует явного изменения версии:

```yaml
# templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
immutable: true
data:
  nginx.conf: |
    {{ .Files.Get "configs/nginx.conf" | nindent 4 }}

---
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
```

При каждом изменении файла хеш меняется, что вызывает Rolling Update. ConfigMap при этом остается неизменяемым на стороне API Server, что защищает от ручных правок (`kubectl edit`).

### Экранирование синтаксиса {{ }}

Если в файле конфигурации (например, для Prometheus) должны остаться фигурные скобки, используйте разрыв строки кавычками или переменную.

```yaml
data:
  alert-rules.yaml: |
    groups:
      - name: example
        rules:
          - alert: HighLoad
            expr: node_load1 > `{{` .Values.maxLoad `}}`
```
*Результат: `expr: node_load1 > {{ .Values.maxLoad }}`*

---

## Дополнительная информация

### Валидация и проверка (CI/CD)

Перед применением чарта в Production выполните минимум три проверки:

**1. Валидация Helm-шаблонов:**
```bash
# Проверка синтаксиса всех шаблонов без установки
helm lint ./mychart

# Рендеринг и проверка YAML-структуры
helm template myapp ./mychart --values values-prod.yaml | kubeconform -strict -

# Dry-run на стороне сервера (требует доступ к кластеру)
helm install myapp ./mychart --values values-prod.yaml --dry-run --debug
```

**2. Валидация политик (OPA/Conftest):**
```bash
# Проверка отрендеренных манифестов на соответствие политикам
helm template myapp ./mychart | conftest test -
```

**3. Проверка контрольных сумм:**
```bash
# Убедитесь, что checksum-аннотация в Deployment совпадает с актуальным содержимым ConfigMap
RENDERED=$(helm template myapp ./mychart | grep -A1 "checksum/config")
echo "$RENDERED"
```

### Устранение неисправностей

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `file not found` | Путь указан не от корня чарта или файл в `.helmignore` | Проверьте путь относительно `Chart.yaml` и содержимое `.helmignore`. |
| `request is too large` | ConfigMap/Secret превысил 1 MiB | Разбейте на несколько ConfigMap или вынесите файлы в Docker-образ/PV. |
| Некорректные отступы | Использование `indent` вместо `nindent` (или наоборот) для block scalar `|` | `indent` не добавляет перенос строки в начале, `nindent` добавляет. Для выражений в колонке 0 используйте `indent`; для выражений с отступом — `nindent`. См. [Паттерн config/ + tpl + subPath](./config-rendering-pattern.md). |
| Ошибки бинарных данных | Попытка вставить байты в поле `data` | Используйте `binaryData` и `b64enc` для любых не-UTF8 файлов. |
| `nil pointer evaluating field .Files` | Файл находится в `templates/` | Переместите файл в корень чарта или поддиректорию, но не в `templates/`. |
| Пустой ConfigMap после Glob | Паттерн не совпал ни с одним файлом | Проверьте регистр букв в путях (Glob чувствителен к регистру) и наличие файлов в `.helmignore`. |

### Безопасность и контроль доступа

**RBAC:**
```bash
# Проверка прав ServiceAccount на чтение ConfigMap
kubectl auth can-i get configmap/app-config \
  --as=system:serviceaccount:production:app-sa \
  --namespace=production

# Просмотр всех прав ServiceAccount
kubectl auth can-i --list \
  --as=system:serviceaccount:production:app-sa \
  --namespace=production
```

**Volume Mount Security:**
```yaml
# Рекомендуемое монтирование ConfigMap как read-only
volumes:
  - name: app-config
    configMap:
      name: {{ include "myapp.fullname" . }}-config
      items:
        - key: nginx.conf
          path: nginx.conf
      defaultMode: 420
      optional: false

containers:
  - name: app
    volumeMounts:
      - name: app-config
        mountPath: /etc/app/config
        readOnly: true
```

### Мониторинг и аудит

**Отслеживание изменений ConfigMap:**
```bash
# Просмотр истории изменений ConfigMap (если включен audit)
kubectl get configmap app-config -o jsonpath='{.metadata.annotations}' -n production

# Проверка, кто изменил ConfigMap последним (через describe)
kubectl describe configmap app-config -n production
# → Events:  Normal  Updated  2m  configmap-controller  Updated configmap
```

**Аудит через аннотации (Best Practice):**
```yaml
metadata:
  annotations:
    description: "Увеличен таймаут подключения к БД"
    last-modified-by: "devops-team"
    changed-at: "2026-09-02T14:30:00Z"
```

### Лучшие практики

1. **Валидация существования:** Перед вызовом `.Files.Get` убедитесь, что файл существует, либо используйте функции проверки, чтобы избежать падения рендеринга.
2. **Чистота чарта:** Используйте `.helmignore` для исключения документации (`README.md`), тестов и локальных конфигов, чтобы они не попали в `Glob`.
3. **Безопасность Secret:** Метод `.AsSecrets` выполняет Base64 кодирование, но **не шифрует** данные. Для чувствительных данных используйте `helm-secrets` или `SealedSecrets`.
4. **Кодировка:** Всегда сохраняйте текстовые файлы в **UTF-8 без BOM**. Другие кодировки могут вызвать ошибки в движке Go Templates.
5. **Неизменяемость:** Используйте `immutable: true` для всех стабильных Production-конфигураций. Это снижает нагрузку на API-сервер и защищает от случайных правок.
6. **Разделение ответственности:** Не смешивайте конфигурации разных окружений в одном ConfigMap. Используйте отдельные ConfigMap или ветвление по `.Values.environment`.
7. **Идемпотентность:** Для обновления ConfigMap всегда используйте `helm upgrade` с флагом `--reuse-values`, а не `kubectl apply` напрямую, чтобы не нарушить историю релизов Helm.
8. **Ограничение размера:** Если размер конфигурации приближается к 1 MiB, разделите её на несколько ConfigMap или используйте тома (PVC). Для хранения больших наборов правил (например, Prometheus recording rules или Nginx includes) предпочитайте внешний файловый сервер или Git-синхронизацию (Reloader).

### Интеграция с Reloader

Для приложений, которые не поддерживают автоматическую перезагрузку при изменении ConfigMap, используйте контроллер Reloader. Добавьте аннотации к Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  annotations:
    configmap.reloader.stakater.com/reload: "{{ include \"myapp.fullname\" . }}-config"
```

Это заменит необходимость в checksum-аннотациях и обеспечит Rolling Update без изменения шаблонов Helm.

### Очистка и управление жизненным циклом

**Поиск неиспользуемых ConfigMap:**
```bash
# Найти ConfigMap, не используемые в переменных окружения или томах
kubectl get configmap -A -o json | jq -r '
  .items[] |
  select(.metadata.name | test("^kube-root-ca.crt$") | not) |
  .metadata.namespace + "/" + .metadata.name
' | while read ns_name; do
  ns=$(echo "$ns_name" | cut -d/ -f1)
  name=$(echo "$ns_name" | cut -d/ -f2)
  if ! kubectl get pods -n "$ns" -o json | jq -e \
    ".items[] | .spec.containers[].env[]? | select(.valueFrom.configMapKeyRef.name == \"$name\")" > /dev/null 2>&1 \
    && ! kubectl get pods -n "$ns" -o json | jq -e \
    ".items[] | .spec.volumes[]? | select(.configMap.name == \"$name\")" > /dev/null 2>&1; then
    echo "Не используется: $ns_name"
  fi
done
```

**Проверка после деплоя:**
```bash
# Верификация: ConfigMap существует и содержит ожидаемые ключи
kubectl get configmap myapp-config -n production -o jsonpath='{.data}' | jq 'keys'

# Проверка контрольной суммы файла внутри пода
kubectl exec -n production deploy/myapp -- sh -c \
  "sha256sum /etc/app/config/nginx.conf"
```

### См. также
- [Встроенные объекты Helm](../objects.md) — справочник по всем свойствам `.Files`.
- [Функции Helm](../functions.md) — детали работы `tpl`, `b64enc`, `base` и `nindent`.
- [Автоматический перезапуск подов](./restart_on_change.md) — паттерн checksum-аннотаций для Rolling Update при изменении ConfigMap.
- [CI-рендеринг конфигов через consul-template + Vault](./config-rendering-pattern.md) — паттерн хранения конфигурации в `config/` с рендерингом секретов и `subPath`-монтированием.
