# Структура Helm-чарта

Стандартная файловая структура Helm-чарта обеспечивает организацию шаблонов, конфигураций и метаданных для воспроизводимого развёртывания приложений в Kubernetes. Чёткое следование структуре необходимо для корректной работы инструментов автоматизации и предсказуемости рендеринга.

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

---

## Базовые концепции

### Анатомия чарта и корневая директория

Корневой каталог (обычно `mychart/`) включает обязательные и опциональные элементы. Для быстрого развертывания стандартной структуры используется команда:
```bash
helm create mychart
```

**Иерархия файлов:**
```text
mychart/
├── .helmignore          # Исключения (IDE, Git, логи)
├── Chart.yaml           # Метаданные (обязательно)
├── values.yaml          # Значения по умолчанию (обязательно)
├── values.schema.json   # Валидация входных данных
├── README.md            # Документация (автогенерация через helm-docs)
├── charts/              # Директория для зависимостей (подчартов)
├── crds/                # Custom Resource Definitions (без шаблонизации)
├── files/               # Статические файлы (конфиги, скрипты)
└── templates/           # Шаблоны ресурсов (обязательно)
    ├── _helpers.tpl     # Именованные шаблоны и логика
    ├── NOTES.txt        # Текст, выводимый после установки
    ├── tests/           # Тесты работоспособности (helm test)
    └── *.yaml           # Манифесты Kubernetes
```

### Файл Chart.yaml: Метаданные и API

Определяет ключевые характеристики чарта и его зависимости.

```yaml
apiVersion: v2           # v2 для Helm 3+, v1 для Helm 2 (Legacy)
name: my-application     # Имя чарта (должно совпадать с именем папки)
version: 1.2.3           # Версия чарта (SemVer 2.0.0)
appVersion: "2.5.0"      # Версия самого приложения (тег образа)
description: "A Helm chart for Kubernetes"
type: application        # 'application' или 'library' (только шаблоны)

dependencies:
  - name: postgresql
    version: "12.x.x"
    repository: "https://charts.bitnami.com/bitnami"
    condition: postgresql.enabled # Включение через values.yaml
    alias: db                     # Доступ в шаблонах через .Values.db
```

### Директория crds/ и её особенности

Helm обрабатывает `crds/` особым образом:
1.  **Приоритет:** Ресурсы из этой папки устанавливаются **до** рендеринга шаблонов в `templates/`.
2.  **Отсутствие шаблонизации:** Helm не обрабатывает файлы в `crds/` движком Go templates. Это должен быть чистый YAML.
3.  **Жизненный цикл:** По умолчанию Helm не обновляет и не удаляет CRD при обновлении/удалении релиза, чтобы избежать потери данных.

---

## Практические сценарии

### Синхронизация ресурсов через значения

Пример показывает, как централизация в `values.yaml` предотвращает рассинхронизацию портов между Deployment и Service.

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

Для упрощения кода и универсальности используются встроенные переменные и оператор присваивания.

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

Позволяет блокировать установку при некорректных типах данных.

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

### Работа с .Files и NOTES.txt

Директория `files/` позволяет вставлять статический контент, а `NOTES.txt` предоставляет инструкции пользователю.

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
```

### Тестирование (templates/tests/)

Helm-тесты — это поды с аннотацией `"helm.sh/hook": test`. Они запускаются командой `helm test <release>`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: {{ include "mychart.fullname" . }}-test
  annotations:
    "helm.sh/hook": test
spec:
  containers:
    - name: wget
      image: busybox
      command: ['wget']
      args: ['{{ include "mychart.fullname" . }}:80']
  restartPolicy: Never
```

---

## Дополнительная информация

- **[Шаблонизация в Helm](./helm_templating.md)** — функции, циклы и встроенные объекты.
- **[Зависимости и Library Charts](./helm_dependencies_and_library_charts.md)** — управление субчартами.
- **[Практические сценарии](./helm_chart_practical_scenarios.md)** — Umbrella Charts и Shared Charts.
- **[Паттерн Helm Skeleton](./helm_skeleton_pattern.md)** — создание эталонных структур.
