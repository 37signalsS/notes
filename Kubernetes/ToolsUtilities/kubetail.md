# Kubetail

## Определения

**Kubetail** (johanhaleby/kubetail) — bash-скрипт для одновременного мониторинга логов нескольких подов в Kubernetes с цветовой индикацией источника. Объединяет логи в один хронологический поток, используя `kubectl logs` под капотом. Последняя версия — `v1.6.22` (ноябрь 2025).

> **Примечание:** Существует также [kubetail-org/kubetail](https://github.com/kubetail-org/kubetail) — отдельный проект (Go + TypeScript), реализующий веб-дашборд и CLI. Это не форк, а независимая разработка.

### Ключевые особенности

- Не требует установки компонентов в кластер — работает с текущим контекстом `kubectl`
- Цветовое кодирование для каждого пода (8 цветов по умолчанию)
- Поддержка выбора по имени, regex, меткам (labels)
- Работа с мультиконтейнерными подами
- Режим реального времени (`tail -f`)

## Основные концепции

### Архитектура работы

```
Kubetail (bash-скрипт)
    ↓
kubectl logs (для каждого пода)
    ↓
Объединение потоков + цветовая маркировка
    ↓
Единый хронологический вывод
```

### Цветовое кодирование

Каждому поду присваивается уникальный цвет для визуального разделения потоков:

- По умолчанию: 8 цветов (циклически)
- Настраивается через переменные окружения
- Помогает визуально отслеживать события в разных компонентах

### Хронологическая сортировка

Логи сортируются по времени получения, создавая единый лог-файл для всех выбранных подов.

## Практические сценарии

### Базовое использование

```bash
# Логи всех подов, имя которых начинается с my-app
kubetail my-app

# Логи с интервалом обновления 5 секунд
kubetail my-app --interval 5

# Только последние 10 строк из каждого пода
kubetail my-app --tail 10
```

### Выбор по меткам (labels)

```bash
# Все поды с меткой app=my-app
kubetail -l app=my-app

# Комбинация меток
kubetail -l app=my-app,version=v1

# Логи в реальном времени по меткам
kubetail -l app=my-app --follow
```

### Регулярные выражения

```bash
# Поды, имя которых соответствует паттерну
kubetail -r '^web-.*'

# Исключить поды по паттерну
kubetail my-app -E '^my-app-broken-.*'
```

### Мультиконтейнерные поды

```bash
# Логи конкретного контейнера во всех подах
kubetail my-app -c app-container

# Логи всех контейнеров в подах
kubetail my-app --all-containers
```

### Исключение подов

```bash
# Исключить конкретные поды из выборки
kubetail my-app -E broken-pod-1 -E broken-pod-2

# Исключить по паттерну
kubetail my-app -E '.*-test-.*'
```

### Работа с неймспейсами

```bash
# Логи из конкретного неймспейса
kubetail my-app -n production

# Логи из всех неймспейсов
kubetail my-app --all-namespaces
```

### Предыдущие логи (для падающих подов)

```bash
# Логи предыдущей инстанции (после CrashLoopBackOff)
kubetail my-app --previous

# Комбинация: текущие + предыдущие
kubetail my-app --previous --follow
```

## Дополнительная информация

### Установка

**macOS (Homebrew):**

```bash
brew install kubetail
```

**Linux (ручная установка):**

```bash
sudo curl -L https://raw.githubusercontent.com/johanhaleby/kubetail/master/kubetail -o /usr/local/bin/kubetail
sudo chmod +x /usr/local/bin/kubetail
```

### Конфигурация

**Переменные окружения:**

| Переменная | Описание | По умолчанию |
| :--- | :--- | :--- |
| `KUBETAIL_COLORS` | Количество цветов | `8` |
| `KUBETAIL_NO_COLOR` | Отключить цвета | `false` |
| `KUBETAIL_TIMESTAMP` | Показывать временные метки | `true` |

**Алиасы для `.bashrc` / `.zshrc`:**

```bash
alias kt='kubetail'
alias kt-prod='kubetail -n production'
alias kt-app='kubetail -l app='
```

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| `kubectl` | Любая | Настроенный и аутентифицированный |
| Bash | 4.0+ | |
| Доступ к Kubernetes API | — | Текущий контекст |

### Ограничения

- **Только follow-режим:** для исторического анализа использовать `kubectl logs` напрямую
- **Нет агрегации:** не сохраняет логи, только стримит в реальном времени
- **Производительность:** при большом количестве подов (>100) может замедляться
- **Нет структурированного поиска:** для поиска — [Loki](../../Loki/loki_stack_setup/loki_installation.md) / [EFK](../MonitoringLogging/EFK/efk_stack_setup_guide.md)

### Сравнение с аналогами

| Инструмент | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **Kubetail** | Простота, 8 цветов, не требует установки в кластер | Только bash, нет GUI |
| [**stern**](https://github.com/stern/stern) | Go-бинарник, быстрее, больше опций | Требует установки |
| [`kubectl logs -l`](../Troubleshooting/troubleshooting_overview.md) | Встроен в kubectl, не требует установки | Нет цветовой индикации |
| [**Loki/Grafana**](../../Loki/loki_stack_setup/loki_installation.md) | Исторический анализ, поиск, дашборды | Требует инфраструктуры |
| [**EFK Stack**](../MonitoringLogging/EFK/efk_stack_setup_guide.md) | Полнотекстовый поиск, аналитика | Ресурсоёмкий |

### Типичные сценарии использования

1. **Отладка распределённых транзакций:** одновременный просмотр логов нескольких микросервисов
2. **Мониторинг деплоя:** наблюдение за стартом подов после `kubectl apply`
3. **Диагностика CrashLoopBackOff:** трассировка падений across реплик
4. **A/B тестирование:** сравнение логов версий `v1` и `v2`

### Связанные документы

- [`kubectl logs`](../Troubleshooting/troubleshooting_overview.md#kubectl-logs-анализ-логов-контейнеров) — базовая команда для просмотра логов
- [Централизованное логирование](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md) — архитектура сбора логов
- [kubetail-org/kubetail](https://github.com/kubetail-org/kubetail) — альтернативный проект (дашборд + CLI, Go/TypeScript)

### Репозиторий и документация

- [GitHub: johanhaleby/kubetail](https://github.com/johanhaleby/kubetail)
