# Helmwave: декларативный оркестратор для Helm

Helmwave — декларативный Go-инструмент для управления релизами Helm в парадигме Infrastructure as Code (IaC). Позиционируется как более гибкая альтернатива [Helmfile](./helmfile_overview.md).

> **Актуальная версия:** v0.42.3 (декабрь 2025). Проверяйте [github.com/helmwave/helmwave/releases](https://github.com/helmwave/helmwave/releases).

---

## Definitions

| Термин | Описание |
|--------|----------|
| **Helmwave** | Декларативный оркестратор релизов Helm, написанный на Go. Использует Go-шаблоны для всей конфигурации |
| **kubedog** | Библиотека от Flant для отслеживания состояния Kubernetes-ресурсов в реальном времени (события, логи подов) |
| **State directory** | Директория `.helmwave/`, содержащая сгенерированный план развёртывания |
| **helmwave.yml** | Основной файл конфигурации; описывает репозитории, релизы, зависимости и параметры |

---

## Basic Concepts

### Полная шаблонизация на Go

В отличие от Helmfile, где шаблонизируются преимущественно значения, в Helmwave весь `helmwave.yml` может быть шаблоном. Это позволяет динамически формировать списки релизов, параметры и зависимости на основе внешних данных.

### Продвинутое отслеживание ресурсов

Helmwave интегрирован с библиотекой `kubedog` от Flant. Утилита отслеживает состояние Kubernetes-ресурсов в реальном времени, анализируя события и логи подов. Флаги `--wait` и `--atomic` работают надёжнее стандартного механизма Helm.

### Работа с репозиториями

Инструмент спроектирован для работы с чартами, опубликованными в репозиториях Helm, что стимулирует строгую практику версионирования и публикации артефактов.

### Локальный файл состояния

Команды `build` и `up` создают директорию `.helmwave/`, где хранится сгенерированный план развёртывания (state). Фазы планирования и применения разделены, что обеспечивает предсказуемость операций.

### Установка

```bash
# Через установочный скрипт
curl -fsSL https://raw.githubusercontent.com/helmwave/helmwave/main/scripts/install.sh | bash

# Через mise
mise install helmwave

# Проверка версии
helmwave version
```

---

## Practical Scenarios

### Базовый рабочий процесс

Создание файла `helmwave.yml`, описывающего репозитории, релизы и зависимости:

```yaml
# helmwave.yml
version: 0.42.0
project: my-infra
repositories:
  - name: jetstack
    url: https://charts.jetstack.io
releases:
  - name: cert-manager
    namespace: cert-manager
    chart:
      name: jetstack/cert-manager
    version: v1.11.0
    wait: true
```

### Основные команды

```bash
helmwave build    # Генерация и отображение плана развёртывания
helmwave up       # Применение плана
helmwave down     # Удаление всех релизов
helmwave status   # Проверка состояния развёрнутых релизов
helmwave rollback # Откат к предыдущей ревизии
```

### Разделение окружений

Использование Go-шаблонов для динамического выбора конфигурации:

```yaml
# helmwave.yml
{{ $env := env "ENV" "dev" }}
project: my-infra-{{ $env }}
releases:
  - name: app
    namespace: myapp-{{ $env }}
    chart:
      name: myrepo/app
    values:
      - values-{{ $env }}.yaml
```

```bash
ENV=prod helmwave up
```

---

## Additional Information

Helmwave требует понимания Go-шаблонов, но предоставляет мощные возможности для построения сложных CI/CD-пайплайнов. Сравнение с альтернативами: [Helmfile](./helmfile_overview.md), обзор декларативных инструментов в [Advanced Helm — Index](./Advanced/index.md).
