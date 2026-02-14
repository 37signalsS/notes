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
| **_helpers.tpl** | Вспомогательные шаблоны и функции |
| **Chart.lock** | Файл с зафиксированными версиями зависимостей |

---

## Основные концепции

### Обязательная структура

```
mychart/
├── Chart.yaml          # Метаданные чарта (обязательно)
├── values.yaml         # Значения по умолчанию (обязательно)
└── templates/          # Шаблоны манифестов (обязательно)
    ├── _helpers.tpl    # Вспомогательные функции
    └── *.yaml          # Манифесты Kubernetes
```

### Файл Chart.yaml

Содержит метаданные чарта. Подробнее о различиях форматов v1 и v2 см. [Сравнение Helm v2 и v3](./helm_v2_vs_v3.md).

```yaml
apiVersion: v2           # v2 для Helm 3, v1 для Helm 2
name: my-application
description: A Helm chart for Kubernetes
type: application        # application или library
version: 1.2.3          # Версия чарта (SemVer)
appVersion: "2.0.0"     # Версия приложения
dependencies:           # Зависимости (только apiVersion: v2)
  - name: postgresql
    version: "12.x.x"
    repository: https://charts.bitnami.com/bitnami
```

### Файл values.yaml

Определяет параметры для шаблонизации. Используется с [Go templates](./helm_templating.md).

```yaml
replicaCount: 3

image:
  repository: nginx
  tag: latest
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 80

ingress:
  enabled: true
  hosts:
    - host: app.example.com
```

### Директория templates/

Содержит Go-шаблоны, которые Helm рендерит в манифесты Kubernetes. Поддерживает встроенные объекты: `.Values`, `.Release`, `.Chart`, `.Capabilities`, `.Files`. См. подробнее в [Шаблонизация в Helm](./helm_templating.md).

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

```bash
# Разработка
helm install app ./chart -f values.yaml -f values-dev.yaml -n dev

# Staging
helm install app ./chart -f values.yaml -f values-staging.yaml -n staging

# Production
helm install app ./chart -f values.yaml -f values-production.yaml -n prod --atomic
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

### Работа с зависимостями

```bash
# Обновление зависимостей и создание Chart.lock
helm dependency update

# Построение зависимостей из Chart.lock
helm dependency build
```

---

## Дополнительная информация

- [Обзор Helm](./helm_overview.md) — общие концепции и жизненный цикл
- [Шаблонизация в Helm](./helm_templating.md) — работа с Go-шаблонами, встроенные объекты, функции Sprig
- [Управление версиями релизов](./helm_release_versioning.md) — версионирование чартов, ревизии релизов, откаты
- [Сравнение Helm v2 и v3](./helm_v2_vs_v3.md) — различия в форматах чартов и хранении релизов
