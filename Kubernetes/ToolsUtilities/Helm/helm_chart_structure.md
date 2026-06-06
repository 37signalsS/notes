# Структура Helm-чарта

Стандартная файловая структура Helm-чарта организует шаблоны, конфигурацию и метаданные для воспроизводимого развёртывания в Kubernetes.

---

## Definitions

| Термин | Описание |
|--------|----------|
| **Chart** | Пакет Helm, содержащий шаблоны Kubernetes и конфигурацию. См. [Обзор Helm](./helm_overview.md) для общих концепций |
| **Chart.yaml** | Метаданные чарта: имя, версия, зависимости. Подробнее о версионировании см. [Управление версиями релизов](./helm_release_versioning.md) |
| **values.yaml** | Значения по умолчанию для шаблонов |
| **templates/** | Директория с Go-шаблонами манифестов Kubernetes. См. [Шаблонизация в Helm](./helm_templating.md) |
| **_helpers.tpl** | Вспомогательный файл для переиспользуемых именованных шаблонов |
| **Chart.lock** | Файл с зафиксированными версиями зависимостей |
| **.helmignore**| Файлы для исключения из пакета (аналог .gitignore) |

---

## Basic Concepts

### Обязательная структура

```
mychart/
├── .helmignore         # Файлы для исключения из пакета
├── Chart.yaml          # Метаданные чарта (обязательно)
├── values.yaml         # Значения по умолчанию (обязательно)
├── charts/             # Директория для зависимых чартов
└── templates/          # Шаблоны манифестов (обязательно)
    ├── _helpers.tpl    # Вспомогательные функции
    └── *.yaml          # Манифесты Kubernetes
```

### Файл Chart.yaml

Содержит ключевые метаданные, описывающие чарт.

```yaml
apiVersion: v2           # v2 для Helm 3. Обязательное поле.
name: my-application
description: A Helm chart for Kubernetes

# Тип чарта: 'application' (по умолчанию) или 'library' (не устанавливается, только для переиспользования шаблонов).
type: application

# Версия самого чарта. Должна соответствовать SemVer 2.0.0.
version: 1.2.3

# Версия приложения, развёртываемого этим чартом. Не обязана быть SemVer.
appVersion: "2.0.0"

# Ограничение на совместимые версии Kubernetes (SemVer).
kubeVersion: ">= 1.19.0-0"

dependencies:
  - name: postgresql
    version: "12.x.x"
    repository: https://charts.bitnami.com/bitnami
```

### Файл values.yaml

Определяет параметры для шаблонизации. Используется с [Go templates](./helm_templating.md).

**Централизация конфигурации в `values.yaml`**

Файл `values.yaml` служит центральным местом для управления всеми изменяемыми параметрами чарта. Такой подход решает ключевые проблемы:

| Проблема без централизации | Решение через values.yaml |
|-----------------------------|---------------------------------------------------------|
| Дублирование значений в разных манифестах | Одно значение → использование в нескольких шаблонах |
| Риск рассинхронизации (порт в Deployment ≠ порт в Service) | Синхронизация через одну переменную |
| Ручные правки в шаблонах | Параметризация через плейсхолдеры |
| Сложность поддержки при масштабировании | Централизованное управление конфигурацией. |

**Пример организации:**

```yaml
# values.yaml — централизованная конфигурация
app:
  name: kosms-zero-to-hero
  replicas: 3
  port: 8080
  domain: app.example.com

image:
  repository: nginx
  tag: latest
  pullPolicy: IfNotPresent

service:
  type: ClusterIP

ingress:
  enabled: true
```

**Использование в шаблонах:**

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Values.app.name }}-web
spec:
  replicas: {{ .Values.app.replicas }}
  template:
    spec:
      containers:
        - ports:
            - containerPort: {{ .Values.app.port }}

# templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ .Values.app.name }}-service
spec:
  type: {{ .Values.service.type }}
  ports:
    - targetPort: {{ .Values.app.port }}  # То же значение, что в Deployment

# templates/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .Values.app.name }}-ingress
spec:
  rules:
    - host: {{ .Values.app.domain }}
      http:
        paths:
          - backend:
              service:
                name: {{ .Values.app.name }}-service
                port:
                  number: {{ .Values.app.port }}
```

При изменении порта в `values.yaml` все ресурсы автоматически используют новое значение без риска рассинхронизации.

### Директория templates/

Содержит Go-шаблоны, которые Helm рендерит в манифесты Kubernetes. Поддерживает встроенные объекты: `.Values`, `.Release`, `.Chart`, `.Capabilities`, `.Files`.

**Встроенная переменная `.Chart.Name`:**

Используется для динамической генерации имён ресурсов на основе названия чарта:

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Chart.Name }}-web
  labels:
    app: {{ .Chart.Name }}
```

При имени чарта `kosms-zero-to-hero` ресурс получит имя `kosms-zero-to-hero-web`.

**Локальные переменные в шаблонах:**

Для упрощения повторяющихся конструкций можно объявлять локальные переменные в начале файла шаблона:

```yaml
# templates/ingress.yaml
{{- $domain := .Values.app.domain }}
{{- $port := .Values.app.port }}

apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .Chart.Name }}-ingress
spec:
  rules:
    - host: {{ $domain }}
      http:
        paths:
          - backend:
              service:
                name: {{ .Chart.Name }}-service
                port:
                  number: {{ $port }}
```

Локальные переменные действуют только в пределах одного файла, но делают код чище и проще в поддержке.

### Файл _helpers.tpl

Определяет именованные шаблоны для переиспользования. Использует синтаксис `{{ define }}` и `{{ include }}`.

---

## Дополнительная информация

- **[Шаблонизация в Helm](./helm_templating.md)** — подробное руководство по функциям, объектам и именованным шаблонам в `_helpers.tpl`.
- **[Зависимости и Library Charts](./helm_dependencies_and_library_charts.md)** — создание переиспользуемых библиотечных чартов.
- **[Helm Skeleton Pattern](./helm_skeleton_pattern.md)** — паттерн для стандартизации и масштабирования множества однотипных сервисов.
