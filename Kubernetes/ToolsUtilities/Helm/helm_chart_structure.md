# Структура Helm-чарта

Стандартная файловая структура Helm-чарта организует шаблоны, конфигурацию и метаданные для воспроизводимого развёртывания в Kubernetes.

---

## Определения

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

## Основные концепции

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

# Версия приложения, развертываемого этим чартом. Не обязана быть SemVer.
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

**Принцип единого источника правды (SSoT):**

`values.yaml` должен быть единственным источником истины для всех изменяемых параметров чарта. Это решает ключевые проблемы:

| Проблема без SSoT | Решение через values.yaml |
|-------------------|---------------------------|
| Дублирование значений в разных манифестах | Одно значение → использование в нескольких шаблонах |
| Риск рассинхронизации (порт в Deployment ≠ порт в Service) | Синхронизация через одну переменную |
| Ручные правки в шаблонах | Параметризация через плейсхолдеры |
| Сложность поддержки при масштабировании | Централизованное управление конфигурацией |

**Пример организации:**

```yaml
# values.yaml — единый источник правды
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

Содержит Go-шаблоны, которые Helm рендерит в манифесты Kubernetes. Поддерживает встроенные объекты: `.Values`, `.Release`, `.Chart`, `.Capabilities`, `.Files`. См. подробнее в [Шаблонизация в Helm](./helm_templating.md).

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

Определяет именованные шаблоны для переиспользования. Использует синтаксис `{{ define }}` и `{{ include }}`. Примеры использования см. в [Шаблонизация в Helm](./helm_templating.md#практические-сценарии).

---

## Практические сценарии

### Создание нового чарта

```bash
helm create mychart
cd mychart
```

Команда генерирует чарт с примерами шаблонов и `_helpers.tpl`.

### Структура production-чарта

```
production-chart/
├── Chart.yaml              # Метаданные
├── Chart.lock              # Зафиксированные версии зависимостей
├── values.yaml             # Базовые значения
├── values-production.yaml  # Переопределения для prod
├── values-staging.yaml     # Переопределения для staging
├── templates/
│   ├── _helpers.tpl        # Вспомогательные функции
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secrets.yaml
│   ├── hpa.yaml            # HorizontalPodAutoscaler
│   ├── pdb.yaml            # PodDisruptionBudget
│   └── tests/              # Тесты для helm test
│       └── test-connection.yaml
└── charts/                 # Загруженные зависимости (после helm dependency update)
    └── postgresql-12.1.0.tgz
```

### Многоокружная стратегия через values-файлы

Для управления конфигурациями в разных окружениях (dev, staging, production) используется несколько `values` файлов.

**Подход:**

1. **`values.yaml` (файл по умолчанию):**
    * Содержит "безопасные" и минимальные значения. Многие функции по умолчанию отключены (`ingress.enabled: false`, `autoscaling.enabled: false`).
    * Служит основной документацией для чарта. В нем полезно оставлять закомментированные блоки, демонстрирующие структуру сложных параметров (например, `resources` или `affinity`), чтобы пользователи знали, что они могут сконфигурировать.

    ```yaml
    # values.yaml
    replicaCount: 1

    ingress:
      enabled: false

    # Ресурсы по умолчанию не заданы, но показана структура для пользователя
    # resources:
    #   limits:
    #     cpu: 100m
    #     memory: 128Mi
    #   requests:
    #     cpu: 100m
    #     memory: 128Mi
    ```

2. **`values-<окружение>.yaml` (файл переопределения):**
    * Содержит только те значения, которые отличаются от `values.yaml` и специфичны для конкретного окружения.

    ```yaml
    # values-production.yaml
    replicaCount: 3

    ingress:
      enabled: true
      hosts:
        - host: myapp.prod.com
      tls:
       - secretName: myapp-prod-tls
         hosts:
           - myapp.prod.com

    resources:
      limits:
        cpu: 2000m
        memory: 4Gi
      requests:
        cpu: 1000m
        memory: 2Gi
    ```

**Применение:**

При установке или обновлении чарта флаг `-f` (или `--values`) можно указывать несколько раз. Файлы применяются последовательно, и каждое последующее значение перезаписывает предыдущее.

```bash
# Сначала загружается values.yaml, затем его значения перезаписываются из values-dev.yaml
helm install app ./chart -f values.yaml -f values-dev.yaml -n dev

# Для production
helm upgrade app ./chart -f values.yaml -f values-production.yaml -n prod --atomic
```

### Валидация структуры

```bash
# Проверка синтаксиса чарта
helm lint .

# Локальный рендер шаблонов без кластера
helm template myrelease .

# Рендер с values-файлом
helm template myrelease . -f values-production.yaml

# Проверка с подключением к кластеру (dry-run)
helm install --dry-run --debug myrelease .
```

**Команда `helm template`:**

Рендерит шаблоны на локальной машине без подключения к кластеру. Полезна для:

- Визуальной проверки итоговых манифестов
- Отладки шаблонов перед коммитом
- Генерации манифестов для применения через `kubectl apply -f`

**Флаг `--debug` при dry-run:**

Позволяет проверять шаблоны с незакоммиченными изменениями без риска поломать развёртывание:

```bash
# Рендер с отладочной информацией
helm install --dry-run --debug myrelease .
```

### Работа с зависимостями

```bash
# Обновление зависимостей и создание Chart.lock
helm dependency update

# Построение зависимостей из Chart.lock
helm dependency build
```

---

## Дополнительная информация

* [Обзор Helm](./helm_overview.md) — общие концепции и жизненный цикл
* [Шаблонизация в Helm](./helm_templating.md) — работа с Go-шаблонами, встроенные объекты, функции Sprig
* [Управление версиями релизов](./helm_release_versioning.md) — версионирование чартов, ревизии релизов, откаты
* [Сравнение Helm v2 и v3](./helm_v2_vs_v3.md) — различия в форматах чартов и хранении релизов
