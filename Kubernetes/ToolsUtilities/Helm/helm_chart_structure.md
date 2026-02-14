# Структура Helm-чарта

Стандартная файловая структура Helm-чарта обеспечивает организацию шаблонов, конфигурации и метаданных.

## Определения

| Термин | Описание |
|--------|----------|
| **Chart.yaml** | Метаданные чарта: имя, версия, зависимости |
| **values.yaml** | Значения по умолчанию для шаблонов |
| **templates/** | Go-шаблоны манифестов Kubernetes |
| **_helpers.tpl** | Вспомогательные шаблоны и функции |

## Основные концепции

### Обязательные файлы

```
mychart/
├── Chart.yaml          # Метаданные чарта
├── values.yaml         # Значения по умолчанию
└── templates/          # Шаблоны манифестов
    ├── _helpers.tpl    # Вспомогательные функции
    ├── deployment.yaml
    ├── service.yaml
    └── ingress.yaml
```

### Chart.yaml

```yaml
apiVersion: v2
name: my-application
description: A Helm chart for Kubernetes
type: application
version: 1.2.3          # Версия чарта
appVersion: "2.0.0"     # Версия приложения
dependencies:
  - name: postgresql
    version: "12.x.x"
    repository: https://charts.bitnami.com/bitnami
```

### values.yaml

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

## Практические сценарии

### Создание чарта

```bash
helm create mychart
cd mychart
```

### Структура production-чарта

```
production-chart/
├── Chart.yaml
├── Chart.lock              # Зафиксированные версии зависимостей
├── values.yaml             # Базовые значения
├── values-production.yaml  # Переопределения для prod
├── templates/
│   ├── _helpers.tpl
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secrets.yaml
│   └── tests/
│       └── test-connection.yaml
└── charts/                 # Загруженные зависимости
    └── postgresql-12.1.0.tgz
```

### Валидация структуры

```bash
# Проверка синтаксиса
helm lint .

# Рендер шаблонов
helm template myrelease .

# Проверка с реальным кластером
helm install --dry-run --debug myrelease .
```

## Дополнительная информация

- [Обзор Helm](./helm_overview.md) — общие концепции
- [Шаблонизация в Helm](./helm_templating.md) — работа с Go-шаблонами
- [Управление версиями релизов](./helm_release_versioning.md) — версионирование
