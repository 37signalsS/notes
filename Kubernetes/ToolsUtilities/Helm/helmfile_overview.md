# Helmfile: декларативный оркестратор для Helm

Инструмент декларативного управления множеством Helm-релизов. Описывает желаемое состояние релизов в YAML-файле, выполняя соответствующие команды Helm.

---

## Definitions

| Термин | Описание |
|--------|----------|
| **Helmfile** | Декларативный оркестратор для Helm. Описывает релизы, версии, values и namespace в `helmfile.yaml`. См. [Обзор Helm](./helm_overview.md) для общих концепций |
| **helmfile.yaml** | Основной файл конфигурации. Поддерживает Go-шаблонизацию для динамической генерации конфигурации |
| **Release (Релиз)** | Элемент списка `releases` в helmfile.yaml — один Helm-релиз для развёртывания |

---

## Basic Concepts

### Ключевые возможности

| Возможность | Описание |
|-------------|----------|
| Декларативность | Все релизы, чарты, версии, values и namespace в одном YAML-файле |
| Шаблонизация | `helmfile.yaml` — Go-шаблон: динамическая генерация конфигурации по окружениям, переменным окружения, условная логика |
| Предпросмотр (`diff`) | Интеграция с плагином [helm-diff](./helm_plugins.md) для безопасного развёртывания |
| Параллельное выполнение | Параллельная установка/обновление нескольких релизов |
| Интеграция с `helm-secrets` | Хранение секретов в зашифрованном виде в Git (GitOps) |

### Основные команды

| Команда | Описание |
|---------|----------|
| `helmfile repos` | Синхронизация репозиториев из `helmfile.yaml` |
| `helmfile diff` | Показ запланированных изменений для всех релизов |
| `helmfile apply` | Применение изменений (установка/обновление релизов) |
| `helmfile sync` | Псевдоним для `apply` |
| `helmfile destroy` | Удаление всех релизов, описанных в файле |

Фильтрация по селектору:

```bash
helmfile -l name=loki apply
```

---

## Practical Scenarios

### Пример helmfile.yaml

```yaml
# helmfile.yaml

# Глобальные настройки
helmDefaults:
  wait: true
  waitForJobs: true
  timeout: 300
  atomic: true

# Репозитории
repositories:
  - name: grafana
    url: https://grafana.github.io/helm-charts
  - name: prometheus-community
    url: https://prometheus-community.github.io/helm-charts

# Релизы
releases:
  - name: loki
    namespace: logging
    chart: grafana/loki-stack
    version: 2.9.10
    values:
      - loki:
          auth_enabled: false

  - name: prometheus
    namespace: monitoring
    chart: prometheus-community/kube-prometheus-stack
    version: 45.2.1
    # Установка только если $PROMETHEUS_ENABLED = "true"
    installed: '{{ env "PROMETHEUS_ENABLED" | default "false" }}'
    values:
      - grafana:
          enabled: true
          adminPassword: '{{ requiredEnv "GRAFANA_ADMIN_PASSWORD" }}'
```

### Управление секретами через переменные окружения

Helmfile позволяет передавать секреты через переменные окружения вместо хранения в `values.yaml`.

```yaml
# helmfile.yaml
releases:
  - name: redis
    chart: bitnami/redis
    values:
      - auth:
          password: '{{ requiredEnv "REDIS_PASSWORD" }}'
```

```bash
export REDIS_PASSWORD="my-secret-password"
helmfile apply
```

`requiredEnv` прервёт выполнение, если переменная не установлена. Альтернатива с default: `{{ env "REDIS_PASSWORD" | default "default-password" }}`.

### Выборочное развёртывание через селекторы

Для работы с конкретным релизом используется флаг `-l` (`--selector`):

```bash
# Показать изменения только для loki
helmfile -l name=loki diff

# Применить изменения только для loki
helmfile -l name=loki apply
```

Релизы должны иметь уникальные имена (`name` в секции `releases`). Селекторы снижают риск случайного воздействия на другие компоненты системы.

---

## Additional Information

Альтернатива Helmfile — [Helmwave](./helmwave_overview.md) (Go, Go-шаблоны для всей конфигурации). См. [Advanced index](./Advanced/index.md) для выбора инструментов декларативного управления.

Для оркестрации сотни однотипных микросервисов с общим shared-чартом см. [Практические сценарии: shared-чарт для 100 микросервисов](./helm_chart_practical_scenarios.md).
