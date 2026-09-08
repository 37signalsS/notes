# Структура Helm-чарта

Стандартная файловая структура Helm-чарта обеспечивает организацию шаблонов, конфигураций и метаданных для воспроизводимого развёртывания приложений в Kubernetes. Чёткое следование структуре необходимо для корректной работы инструментов автоматизации и предсказуемости рендеринга. Helm обрабатывает файлы в определённом порядке: сначала устанавливаются CRD из директории `crds/`, затем рендерятся шаблоны из `templates/`, и наконец выполняются тесты из `templates/tests/`. Этот порядок гарантирует, что пользовательские ресурсы имеют доступ к установленным Custom Resource Definitions.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Chart (Чарт)** | Пакет Helm, содержащий все необходимые ресурсы для запуска приложения в Kubernetes. |
| **Chart.yaml** | Манифест метаданных: имя, версия, тип приложения и список зависимостей. |
| **values.yaml** | Файл со значениями параметров по умолчанию, используемыми при рендеринге шаблонов. |
| **templates/** | Директория с шаблонами манифестов на языке Go templates. |
| **_helpers.tpl** | Вспомогательный файл, содержащий именованные шаблоны (partials) для повторного использования. |
| **crds/** | Директория для Custom Resource Definitions, которые Helm устанавливает перед основными ресурсами. |
| **Chart.lock** | Файл фиксации версий зависимостей (генерируется автоматически при `dependency update`). |
| **.helmignore** | Список файлов и паттернов для исключения из пакета (аналог `.gitignore`). |
| **values.schema.json** | JSON-схема для валидации структуры и типов данных в `values.yaml`. |
| **files/** | Директория для статических файлов (конфигурационные скрипты, свойства, двоичные данные), которые внедряются в ресурсы через `.Files.Get`. |
| **charts/** | Директория для загруженных зависимостей (подчартов), используется при ручном управлении зависимостями. |
| **README.md** | Документация чарта, автогенерируется инструментами вроде `helm-docs`. |

---

## Предварительные требования

| Компонент | Минимальная версия | Рекомендация |
|-----------|-------------------|--------------|
| **Kubernetes** | 1.24+ | 1.28+ (поддержка Server-Side Apply, стабильные CRD) |
| **Helm** | 3.12+ | 3.19+ / 4.x (поддержка `values.schema.json` 2020-12, `--atomic`, `--wait` для SSA) |
| **kubectl** | 1.24+ | Совпадает с версией кластера |
| **Git** | 2.0+ | Для управления версиями чарта |

**Состояние окружения:**
- Настроенный `kubeconfig` с правами на создание ресурсов в целевом namespace.
- Доступ к репозиториям Helm-чартов (если используются внешние зависимости) или локальный каталог для подчартов.

---

## Базовые концепции

### Принцип обработки файлов и жизненный цикл релиза

Helm не обрабатывает все файлы единообразно. Жизненный цикл установки чарта состоит из следующих этапов:

1. **Загрузка и валидация Chart.yaml**: Проверка `apiVersion`, `name`, `version` на соответствие SemVer 2.0.0. При `apiVersion: v2` поддерживаются зависимости, `apiVersion: v1` (устарел, Helm 2 Legacy) не поддерживает зависимости.
2. **Фиксация зависимостей (Chart.lock)**: Если присутствует `Chart.lock`, Helm использует зафиксированные версии подчартов. При отсутствии — резолвит версии из `Chart.yaml` и генерирует `Chart.lock`.
3. **Установка CRD**: Все файлы из `crds/` копируются в API-сервер Kubernetes до рендеринга шаблонов. Helm не управляет ими после установки (не обновляет и не удаляет при `helm upgrade`/`helm uninstall`), чтобы предотвратить потерю данных.
4. **Рендеринг шаблонов**: Файлы из `templates/` обрабатываются движком Go templates с контекстом `.` (Values, Chart, Release, Capabilities, Files). Результат — набор YAML-манифестов.
5. **Валидация значений**: Если присутствует `values.schema.json`, Helm проверяет типы и обязательные поля в `values.yaml` перед рендерингом.
6. **Применение ресурсов**: Рендеренные манифесты отправляются в Kubernetes API-сервер.
7. **Выполнение тестов**: При явном вызове `helm test` запускаются поды с аннотацией `helm.sh/hook: test`.

**Почему такая структура?** Разделение на `crds/`, `templates/`, `files/` позволяет Helm оптимизировать установку: CRD требуют приоритета, так как ресурсы в шаблонах могут зависеть от них; статические файлы из `files/` не обрабатываются шаблонизатором, что упрощает внедрение двоичных данных или больших конфигураций.

### Анатомия чарта и корневая директория

Корневой каталог (обычно `mychart/`) включает обязательные и опциональные элементы. Для быстрого развертывания стандартной структуры используется команда:
```bash
helm create mychart
```

**Иерархия файлов:**
```text
mychart/
├── .helmignore          # Исключения (IDE, Git, логи, временные файлы)
├── Chart.yaml           # Метаданные (обязательно)
├── Chart.lock           # Зафиксированные версии зависимостей (автогенерация)
├── values.yaml          # Значения по умолчанию (обязательно)
├── values.schema.json   # Валидация входных данных
├── README.md            # Документация (автогенерация через helm-docs)
├── charts/              # Директория для зависимостей (подчартов), если не используется виртуальное хранилище
├── crds/                # Custom Resource Definitions (без шаблонизации)
├── files/               # Статические файлы (конфиги, скрипты, сертификаты)
└── templates/           # Шаблоны ресурсов (обязательно)
    ├── _helpers.tpl     # Именованные шаблоны и логика
    ├── NOTES.txt        # Текст, выводимый после установки
    ├── tests/           # Тесты работоспособности (helm test)
    └── *.yaml           # Манифесты Kubernetes
```

### Файл Chart.yaml: Метаданные и API

Определяет ключевые характеристики чарта и его зависимости. Поля `name` и `version` используются для идентификации пакета в репозиториях.

```yaml
apiVersion: v2           # v2 для Helm 3+, v1 для Helm 2 (Legacy) — не рекомендуется
name: my-application     # Имя чарта (должно совпадать с именем папки; только буквы, цифры, `-`, `_`, `.`)
version: 1.2.3           # Версия чарта (SemVer 2.0.0; увеличивается при каждом изменении чарта)
appVersion: "2.5.0"      # Версия самого приложения (тег образа; не используется Helm для сравнения)
description: "A Helm chart for Kubernetes"
type: application        # 'application' (развёртывание) или 'library' (только шаблоны для других чартов)
keywords:                 # Опционально: для поиска в репозиториях
  - web
  - nginx
maintainers:             # Опционально: контакты для обратной связи
  - name: Ivan Petrov
    email: ivan@example.com
home: https://example.com/docs # Опционально: ссылка на документацию приложения
sources:                 # Опционально: ссылки на исходный код
  - https://github.com/example/my-app
dependencies:
  - name: postgresql
    version: "12.x.x"
    repository: "https://charts.bitnami.com/bitnami"
    condition: postgresql.enabled # Включение через values.yaml
    alias: db                     # Доступ в шаблонах через .Values.db
    tags:                         # Опционально: группировка зависимостей
      - database
    import-values:                # Опционально: импорт значений из подчарта
      - child: server.auth existingSecret
        parent: .Values.global.auth
```

**Важные ограничения:**
- `name` не может содержать заглавные буквы, пробелы или символы, отличные от `[A-Za-z0-9_.-]`.
- `version` и `appVersion` не обязательно синхронизированы: `version` — версия чарта, `appVersion` — версия приложения.

### Директория crds/ и её особенности

Helm обрабатывает `crds/` особым образом:
1.  **Приоритет:** Ресурсы из этой папки устанавливаются **до** рендеринга шаблонов в `templates/`. Это гарантирует, что CRD существует в API-сервере до создания Custom Resource.
2.  **Отсутствие шаблонизации:** Helm не обрабатывает файлы в `crds/` движком Go templates. Это должен быть чистый YAML. Шаблонизация CRD невозможна; для условной установки используйте поле `condition` в зависимостях или отдельный чарт.
3.  **Жизненный цикл:** По умолчанию Helm не обновляет и не удаляет CRD при обновлении/удалении релиза, чтобы избежать потери данных. При принудительном удалении используйте `helm uninstall --cascade=orphan` или удаляйте CRD вручную через `kubectl delete crd <name>`.

**Почему CRD не шаблонятся?** CRD являются кластерными ресурсами; их рендеринг с переменными может привести к недетерминированному состоянию API-сервера. Helm 3+ поддерживает установку CRD только как статические YAML.

### Директория charts/ и управление зависимостями

Директория `charts/` содержит загруженные подчарты. Helm ищет зависимости в следующем порядке:
1.  В виртуальном хранилище (`helm dependency build` загружает в `charts/`).
2.  В репозиториях, указанных в `Chart.yaml`.
3.  В локальном каталоге `charts/`.

**Файл Chart.lock** фиксирует точные версии и хеши зависимостей. Его изменение вручную приводит к недетерминированным сборкам и запрещено. Для обновления зависимостей используйте:
```bash
helm dependency update ./mychart
```
Это обновит `Chart.lock` и загрузит актуальные версии в `charts/`.

### Директория files/ и внедрение статического контента

Директория `files/` позволяет включать статические файлы в чарт без обработки шаблонизатором. Это полезно для:
- Конфигурационных скриптов (setup.sh, init.sql).
- Сертификатов и ключей (TLS).
- Двоичных файлов (JAR-архивы, образы).

Доступ к файлам осуществляется через объект `.Files` в шаблонах:
```yaml
data:
  config.yaml: |
{{ .Files.Get "files/config.yaml" | indent 4 }}
```

**Ограничения:**
- Файлы в `files/` индексируются при рендеринге; очень большие файлы (>1 МБ) могут замедлить установку.
- Бинарные файлы лучше упаковывать в ConfigMap через `.Files.Get` или хранить во внешнем хранилище.

### Директория .helmignore

Аналог `.gitignore` для чартов. Указывает файлы, которые исключаются из пакета `.tgz` при `helm package` и из отображаемого списка в `helm inspect`. Это уменьшает размер чарта и исключает служебные файлы из релиза.

**Пример `.helmignore`:**
```
# Игнорировать IDE и системные файлы
.idea/
.vscode/
*.swp
*.swo

# Исключить тестовые артефакты
tests/fixtures/
*.test.yaml

# Исключить документацию из пакета (если не требуется)
README.md
docs/
```

### README.md и документация

Файл `README.md` в корне чарта должен содержать описание чарта, параметры `values.yaml`, инструкции по установке и примеры. Для автоматической генерации используйте `helm-docs`:
```bash
helm-docs
```
Инструмент анализирует комментарии в `values.yaml` и генерирует таблицу параметров. Это поддерживает документацию в актуальном состоянии при изменении чарта.

---

## Практические сценарии

### Создание чарта с нуля

**Шаг 1: Инициализация структуры**
```bash
mkdir myapp && cd myapp
helm create .
```
Команда генерирует минимальную структуру. Удалите ненужные ресурсы (service, ingress, serviceaccount), если приложение их не использует.

**Шаг 2: Определение метаданных (Chart.yaml)**
Заполните `name`, `version`, `appVersion`, `description`. Укажите тип `application`.

**Шаг 3: Определение конфигурационных параметров (values.yaml)**
Вынесите все изменяемые параметры в `values.yaml`: имя приложения, namespace, образ, порты, ресурсы, количество реплик. Используйте вложенные структуры для группировки:
```yaml
app:
  name: myapp
  namespace: default
  port: 8080

image:
  repository: nginx
  tag: "1.25.0"
  pullPolicy: IfNotPresent

replicaCount: 3

resources:
  limits:
    cpu: 500m
    memory: 256Mi
  requests:
    cpu: 250m
    memory: 128Mi
```

**Шаг 4: Создание шаблонов (templates/)**
Начните с Deployment, Service, ConfigMap (если требуется). Используйте значения из `values.yaml` через `.Values.<key>`. Для имён используйте хелперы из `_helpers.tpl`:
```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{ include "myapp.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      {{ include "myapp.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{ include "myapp.selectorLabels" . | nindent 8 }}
    spec:
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - name: http
              containerPort: {{ .Values.app.port }}
          resources:
            {{ toYaml .Values.resources | nindent 12 }}
```

**Шаг 5: Валидация**
Выполните проверку перед коммитом:
```bash
helm lint ./myapp
helm template myapp ./myapp
```

### Синхронизация ресурсов через значения

Централизация в `values.yaml` предотвращает рассинхронизацию портов между Deployment и Service.

**Файл `values.yaml`:**
```yaml
app:
  name: my-service
  port: 8080
image:
  repository: nginx
  tag: 1.25.0
```

**Шаблон `templates/deployment.yaml`:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Values.app.name }}
spec:
  template:
    spec:
      containers:
        - name: web
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          ports:
            - containerPort: {{ .Values.app.port }} # Прямая ссылка на values
```

**Шаблон `templates/service.yaml`:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ .Values.app.name }}
spec:
  ports:
    - port: 80
      targetPort: {{ .Values.app.port }} # Синхронизация с контейнером
```

### Локальные переменные и динамические имена

Для упрощения кода и универсальности используются встроенные переменные и оператор присваивания. Локальные переменные вычисляются один раз и переиспользуются в шаблоне, что уменьшает дублирование и ускоряет рендеринг.

```yaml
{{- $fullName := include "mychart.fullname" . -}}
{{- $port := .Values.app.port -}}

metadata:
  name: {{ $fullName }}-web
  labels:
    app: {{ .Chart.Name }} # Использование имени из Chart.yaml
spec:
  ports:
    - port: {{ $port }}
```

### Валидация через values.schema.json

Позволяет блокировать установку при некорректных типах данных. Helm использует схему для валидации перед рендерингом шаблонов.

```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "app": {
      "type": "object",
      "properties": {
        "port": {
          "type": "integer",
          "minimum": 1,
          "maximum": 65535
        }
      },
      "required": ["port"]
    }
  }
}
```

**Валидация через helm lint:**
```bash
helm lint ./mychart -f values.yaml
# → result: 1 chart(s) linted, 0 chart(s) failed
```

### Работа с .Files и NOTES.txt

Директория `files/` позволяет вставлять статический контент, а `NOTES.txt` предоставляет инструкции пользователю после установки.

```yaml
# templates/configmap.yaml
data:
  setup.sh: |
{{ .Files.Get "files/setup.sh" | indent 4 }}
```

**Пример NOTES.txt:**
```text
Приложение {{ .Release.Name }} успешно установлено!

Доступ по адресу: http://{{ .Values.app.name }}.{{ .Release.Namespace }}.svc.cluster.local

Для проверки работоспособности выполните:
  kubectl get pods -n {{ .Release.Namespace }} -l app.kubernetes.io/instance={{ .Release.Name }}

Для обновления конфигурации:
  helm upgrade {{ .Release.Name }} ./mychart -f values.yaml
```

### Валидация чарта

Многоуровневая проверка предотвращает развёртывание нерабочих конфигураций.

**1. Линтинг (статический анализ):**
```bash
helm lint ./mychart
# → result: 1 chart(s) linted, 0 chart(s) failed
```

**2. Локальный рендеринг (без кластера):**
```bash
helm template myapp ./mychart -f values.yaml
# Выводит готовые YAML-манифесты для проверки
```

**3. Server-side Dry-run (с подключением к кластеру):**
```bash
helm install myapp ./mychart --dry-run --debug
# Проверяет права, схемы CRD, квоты namespace без применения изменений
```

### Упаковка и публикация чарта

**Шаг 1: Упаковка**
```bash
helm package ./mychart
# → result: myapp-1.2.3.tgz
```

**Шаг 2: Индексация репозитория**
```bash
helm repo index . --url https://charts.example.com
```
Генерирует файл `index.yaml` с метаданными всех чартов в каталоге.

**Шаг 3: Локальный Helm-репозиторий**
Для раздачи чартов внутри сети используйте простой HTTP-сервер с поддержкой `index.yaml` или встроенный:
```bash
helm serve --repo-path ./charts-repo --url http://localhost:8879
```
Добавьте репозиторий на клиенте:
```bash
helm repo add local http://localhost:8879
helm repo update
helm install myapp local/myapp
```

### Управление зависимостями (подчарты)

Подчарты позволяют переиспользовать общую логику (например, PostgreSQL, Redis) между несколькими чартами.

**Добавление зависимости:**
```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm dependency up ./mychart
```
Генерирует `charts/postgresql-12.x.x.tgz` и обновляет `Chart.lock`.

**Ручное указание зависимостей в Chart.yaml:**
```yaml
dependencies:
  - name: postgresql
    version: "12.5.0"
    repository: "oci://registry.example.com/charts"
    condition: postgresql.enabled
    alias: db
```

**Важно:** Не добавляйте файлы подчартов вручную в `charts/` без обновления `Chart.lock`. Helm игнорирует неучтённые подчарты.

### Тестирование (templates/tests/)

Helm-тесты — это поды с аннотацией `"helm.sh/hook": test`. Они запускаются командой `helm test <release>` и предназначены для проверки работоспособности после установки.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: {{ include "mychart.fullname" . }}-test
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-delete-policy": hook-succeeded,hook-failed # Очистка после теста
spec:
  containers:
    - name: wget
      image: busybox:1.36
      command: ['wget']
      args: ['{{ include "mychart.fullname" . }}:80']
  restartPolicy: Never
```

**Запуск теста:**
```bash
helm install myapp ./mychart
# → result: NAME: myapp, LAST DEPLOYED: ..., STATUS: deployed

helm test myapp
# → result: POD myapp-test: Container reachable on port 80
```

### _helpers.tpl: лучшие практики

Именованные шаблоны в `_helpers.tpl` используются для переиспользования логики имён, меток и селекторов.

**Структура хелпера:**
```yaml
{{/*
Создаёт полное имя чарта с суффиксом release.
*/}}
{{- define "mychart.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Общие метки.
*/}}
{{- define "mychart.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
```

**Правила:**
- Хелперы не должны содержать сложную бизнес-логику; только переиспользуемые фрагменты имён и меток.
- Используйте `define` с осмысленными именами, соответствующими имени чарта.
- Избегайте глубокой вложенности шаблонов — это усложняет отладку.

---

## Troubleshooting

### Ошибки рендеринга шаблонов

**Симптом:** `template: mychart/templates/deployment.yaml:10:19: executing "mychart.tmpl" at <.Values.app.port>: nil pointer evaluating interface {}.port`
**Причина:** В `values.yaml` отсутствует ключ `app.port` или он имеет неверную структуру.
**Решение:**
1. Проверьте `values.yaml` на наличие нужного ключа.
2. Выполните `helm template` с флагом `--debug` для точного определения строки ошибки.
3. Убедитесь, что `values.schema.json` корректно описывает обязательные поля.

### Несоответствие версий зависимостей

**Симптом:** `Error: failed to download "postgresql" (hint: running `helm repo update` may help)`
**Причина:** В `Chart.lock` зафиксирована версия, отсутствующая в репозитории.
**Решение:**
```bash
helm repo update
helm dependency update ./mychart
```
Если обновление не помогает, проверьте доступность версии в репозитории или измените `version` в `Chart.yaml`.

### Ошибки валидации CRD

**Симптом:** `Error: unable to recognize "": no matches for kind "CustomResourceDefinition" in version "apiextensions.k8s.io/v1"`
**Причина:** CRD из `crds/` не установлен до рендеринга шаблонов (старая версия Helm) или API-сервер не поддерживает версию CRD.
**Решение:**
1. Убедитесь, что используется Helm 3.7+ (поддержка `crds/` появилась в 3.7).
2. Проверьте версию `apiVersion` в CRD (`v1` для Kubernetes 1.16+).
3. Установите CRD вручную: `kubectl apply -f crds/my-crd.yaml` перед `helm install`.

### Проблемы с values.schema.json

**Симптом:** `values.schema.json` игнорируется, установка проходит с неверными типами.
**Причина:** Файл имеет некорректный JSON или неподдерживаемый `$schema`.
**Решение:**
1. Проверьте JSON на валидность: `jq . values.schema.json`.
2. Убедитесь, что `$schema` указывает на поддерживаемую версию (2020-12).
3. Helm 3.10+ полностью поддерживает `values.schema.json`; для старых версий используйте плагины.

### Проблемы с зависимостями

**Симптом:** `Error: failed to render chart: missing label 'myapp'`
**Причина:** Подчарт не найден в `charts/` или не загружен.
**Решение:**
1. Убедитесь, что `charts/` содержит `.tgz` файл подчарта.
2. Выполните `helm dependency build ./mychart` для загрузки.
3. Проверьте `Chart.lock` на наличие записи о зависимости.

---

## Best Practices

### Версионирование
- Используйте SemVer 2.0.0 для `version` в `Chart.yaml`. Увеличивайте `patch` при исправлениях, `minor` при добавлении функций, `major` при несовместимых изменениях.
- `appVersion` должно соответствовать тегу образа приложения (например, `v2.5.0`). Не добавляйте префикс `v` в `version` чарта.
- Фиксируйте версии зависимостей в `Chart.lock` и никогда не изменяйте их вручную.

### Безопасность
- **Никогда не храните секреты (пароли, токены, ключи) в `values.yaml` или шаблонах.** Используйте Kubernetes Secrets, HashiCorp Vault или `sops` с `helm-secrets`.
- Устанавливайте чарты с флагом `--atomic`: при ошибке установка автоматически откатывается.
- Используйте `--verify` и подписи GPG для чартов из недоверенных репозиториев.

### Именование и организация
- Имена чартов в нижнем регистре, без пробелов: `myapp`, not `MyApp`.
- Группируйте связанные конфигурации в `values.yaml` по доменам: `image`, `ingress`, `monitoring`.
- Используйте `alias` для зависимостей, если имя подчарта конфликтует с именем ресурса в шаблонах.

### Управление окружением
- Создавайте отдельные файлы `values` для каждого окружения: `values-dev.yaml`, `values-prod.yaml`.
- Применяйте значения в порядке переопределения (младший файл перезаписывает старший):
  ```bash
  helm upgrade --install myapp ./mychart -f values.yaml -f values-prod.yaml
  ```
- Используйте `--namespace` и `--create-namespace` для изоляции окружений.

### Фиксация артефактов
- Храните упакованные чарты (`.tgz`) и `values.yaml` для каждого релиза в системах управления конфигурациями (Git).
- Используйте `helm get values <release>` и `helm get manifest <release>` для аудита развёрнутых релизов.

---

## Очистка окружения

### Удаление релиза
```bash
helm uninstall myapp --namespace prod
```
По умолчанию Helm удаляет все ресурсы, созданные чартом, кроме CRD. Для принудительного удаления CRD используйте:
```bash
kubectl delete crd <crd-name>
```

### Откат релиза
```bash
helm rollback myapp 2 --namespace prod
```
Откатывает релиз к предыдущей ревизии ( `2` — номер ревизии). Просмотреть историю ревизий:
```bash
helm history myapp --namespace prod
```

### Очистка локального кэша
```bash
helm cache clean
helm repo list
```
Удаляет кэшированные чарты и неиспользуемые репозитории.

---

## Крайние случаи и ограничения

### Обновление CRD
Helm не обновляет CRD автоматически при `helm upgrade`. Если требуется обновление схемы CRD:
1. Вручную примените обновлённый YAML: `kubectl apply -f crds/my-crd.yaml`.
2. Или используйте `helm upgrade --force` с обновлённым CRD в `crds/` (работает не для всех версий Helm).
3. Будьте осторожны: обновление CRD может привести к потере данных или недоступности контроллера.

### Большие values.yaml и наследование
При больших конфигурациях (>1000 строк) разбейте `values.yaml` на несколько файлов и применяйте их вместе:
```bash
helm install myapp ./chart -f values/base.yaml -f values/ingress.yaml -f values/monitoring.yaml
```
Порядок файлов критичен: последний файл имеет наивысший приоритет.

### Двоичные файлы в files/
Helm кодирует содержимое `files/` в base64 при внедрении в шаблоны через `.Files.Get`. Для очень больших двоичных файлов (>1 МБ) лучше использовать ConfigMap с `binaryData` или внешнее хранилище, чтобы избежать превышения лимита размера etcd.

### Лимиты размера шаблонов
Helm рендерит весь чарт в память. При очень больших чартах (>10 МБ сгенерированных YAML) возможна ошибка `out of memory`. В таких случаях разбейте чарт на несколько релизов или используйте Kustomize для генерации базовых манифестов.

---

## Дополнительная информация

- **[Шаблонизация в Helm](./helm_templating.md)** — функции, циклы и встроенные объекты.
- **[Зависимости и Library Charts](./helm_dependencies_and_library_charts.md)** — управление субчартами.
- **[Практические сценарии](./helm_chart_practical_scenarios.md)** — Umbrella Charts и Shared Charts.
- **[Паттерн Helm Skeleton](./helm_skeleton_pattern.md)** — создание эталонных структур.
- **[Паттерны и устранение неисправностей](./Advanced/patterns_troubleshooting.md)** — системная диагностика Helm.
