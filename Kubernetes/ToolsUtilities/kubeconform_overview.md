# Kubeconform — высокопроизводительная валидация манифестов

## Определения

**Kubeconform** — это современный инструмент командной строки (CLI) для проверки (валидации) манифестов Kubernetes на соответствие официальным схемам JSON Schema API. Написанный на языке Go, он ориентирован на максимальную производительность в CI/CD конвейерах и является стандартом де-факто, полностью заменившим устаревший проект `kubeval`.

Инструмент проверяет структуру YAML/JSON файлов, типы данных и обязательные поля, предотвращая ошибки конфигурации до момента их применения в кластере.

## Основные концепции

### Ключевые особенности

| Особенность | Описание |
| :--- | :--- |
| **Производительность** | Многопоточная обработка файлов и кэширование схем в памяти позволяют проверять тысячи манифестов за секунды. |
| **CI/CD-интеграция** | Нативная поддержка форматов отчетов TAP, JUnit и JSON для интеграции с тестовыми фреймворками. |
| **Поддержка CRD** | Возможность валидации Custom Resources через внешние OpenAPI-схемы или каталоги (например, Datree). |
| **Офлайн-режим** | Работа в изолированных средах (Air-gapped) с использованием локальных копий схем. |
| **Гибкость ввода** | Поддержка рекурсивного поиска, стандартного ввода (stdin) и интеграция с выводом Helm/Kustomize. |

### Архитектура процесса

```text
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Манифесты     │ ──> │   kubeconform    │ ──> │    Отчет об     │
│   (.yaml/.json) │     │   (валидация)    │     │    ошибках      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               v
                        ┌──────────────────┐
                        │  Схемы Kubernetes│
                        │  (локально или   │
                        │   Remote HTTP)   │
                        └──────────────────┘
```

### Установка

Актуальная версия на середину 2026 года — **v0.8.0**.

**Go (сборка из исходников):**
```bash
go install github.com/yannh/kubeconform/cmd/kubeconform@v0.8.0
```

**Homebrew (macOS/Linux):**
```bash
brew install kubeconform
```

**Docker:**
```bash
# Использование официального образа
docker run --rm -i ghcr.io/yannh/kubeconform:v0.8.0 -summary < deployment.yaml
```

**Бинарный файл:**
Скачайте актуальный релиз со страницы [GitHub Releases](https://github.com/yannh/kubeconform/releases) и переместите его в директорию, указанную в переменной `$PATH`.

### Флаги командной строки (v0.8.0)

| Флаг | Описание |
| :--- | :--- |
| `-R` | Рекурсивный поиск манифестов в поддиректориях. |
| `-summary` | Вывод краткой статистики (количество файлов, ресурсов, ошибок) в конце работы. |
| `-verbose` | Подробный отчет по каждому проверенному ресурсу. |
| `-strict` | Строгий режим: отклонять манифесты с полями, отсутствующими в схеме. |
| `-output <format>` | Формат вывода: `text`, `json`, `tap`, `junit`. |
| `-kubernetes-version <ver>` | Версия Kubernetes для выбора схем (например, `1.35.0`). |
| `-schema-location <url>` | Путь к схемам. Поддерживает шаблоны `{{ .ResourceKind }}`, `{{ .Group }}`. |
| `-ignore-missing-schemas` | Игнорировать ресурсы, для которых не найдена схема (полезно для CRD). |
| `-n <workers>` | (v0.8.0) Количество параллельных воркеров (по умолчанию равно числу CPU). |
| `-cache <dir>` | Директория для локального кэширования загруженных схем. |

### Форматы вывода для автоматизации

| Формат | Флаг | Описание |
| :--- | :--- | :--- |
| **TAP** | `-output tap` | Test Anything Protocol — стандарт для интеграции с тестовыми системами. |
| **JUnit** | `-output junit` | XML-отчет, нативно поддерживаемый Jenkins, GitLab CI и Azure DevOps. |
| **JSON** | `-output json` | Машиночитаемый формат для кастомных скриптов обработки. |
| **Text** | `-output text` | Человекочитаемый формат (по умолчанию). |

### Сравнение с аналогами

| Инструмент | Производительность | Поддержка CRD | Офлайн | CI/CD форматы |
| :--- | :--- | :--- | :--- | :--- |
| **kubeconform** | Высокая (Go, параллелизм) | Да | Да | TAP, JUnit, JSON |
| **kubeval** | Низкая (Deprecated) | Нет | Нет | Text |
| **kube-linter** | Средняя | Да | Да | SARIF, JSON |

## Практические сценарии

### Локальная валидация

**Проверка отдельных файлов:**
```bash
kubeconform deployment.yaml service.yaml configmap.yaml
# [Результат] deployment.yaml - Deployment is valid
```

**Рекурсивная проверка директории:**
```bash
kubeconform -R ./manifests/
```

**Валидация потока из stdin:**
```bash
cat deployment.yaml | kubeconform -
```

### Строгая валидация под конкретную версию

Режим `strict` критически важен для обнаружения опечаток в названиях полей.

```bash
# Проверка против версии 1.35.0 (Penelope)
kubeconform -strict -kubernetes-version 1.35.0 manifests/
```

### Интеграция в CI/CD

**GitLab CI:**
```yaml
validate-manifests:
  image: ghcr.io/yannh/kubeconform:v0.8.0
  stage: test
  script:
    - kubeconform -summary -strict -output tap 'manifests/**/*.yaml'
```

**GitHub Actions:**
```yaml
steps:
  - uses: actions/checkout@v4
  - name: Run kubeconform
    uses: yannh/kubeconform-action@v1
    with:
      manifest_path: manifests/
      output_format: tap
      strict: true
      kube_version: 1.35.0
```

### Валидация Helm и Kustomize

Инструменты шаблонизации должны проверяться в "отрендеренном" виде.

**Helm:**
```bash
helm template my-chart | kubeconform -summary -strict
```

**Kustomize:**
```bash
kubectl kustomize overlays/production | kubeconform -summary -strict
```

### Офлайн-валидация

Для работы в изолированных окружениях необходимо подготовить локальный кэш схем.

**Скрипт для подготовки локального кэша:**
```bash
#!/bin/bash
mkdir -p ~/kubeconform-schemas
# Список базовых схем (пример)
schemas=("deployment" "service" "configmap" "ingress")

for schema in "${schemas[@]}"; do
  curl -L "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/master/${schema}-v1.json" \
    -o "~/kubeconform-schemas/${schema}.json"
done
```

**Использование локальных схем:**
```bash
kubeconform -schema-location '~/kubeconform-schemas/{{ .ResourceKind }}.json' manifests/
```

### Валидация CRD (Custom Resources)

Для проверки ресурсов операторов рекомендуется использовать каталог Datree или свои OpenAPI схемы.

**Использование каталога Datree:**
```bash
kubeconform \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{ .Group }}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json' \
  -ignore-missing-schemas \
  manifests/
```

## Дополнительная информация

### Лучшие практики

1.  **Strict Mode в CI:** всегда используйте `-strict`, чтобы блокировать манифесты с опечатками, которые Kubernetes может молча проигнорировать.
2.  **Версионность:** указывайте `-kubernetes-version`, точно соответствующую версии вашего кластера, чтобы избежать использования удаленных API.
3.  **Кэширование:** в пайплайнах настраивайте кэширование директории схем (`-cache`), чтобы ускорить выполнение и уменьшить нагрузку на GitHub/S3.
4.  **Комбинация с Dry-run:** используйте `kubeconform` (схемы) вместе с `kubectl apply --dry-run=client` (логика сервера) для максимальной надежности.
5.  **Параллелизм:** на больших репозиториях (1000+ файлов) используйте флаг `-n` для явного указания количества потоков, если лимиты контейнера ограничены.

### Связанные инструменты

- **[Kustomize](../kustomize/kustomize_overview.md)** — генерация манифестов через оверлеи.
- **[Helm](../Helm/helm_overview.md)** — управление пакетными конфигурациями.
- **[GitOps](../../../GitOps/GitOps_overview.md)** — методология доставки манифестов.

### Ресурсы

- [GitHub: yannh/kubeconform](https://github.com/yannh/kubeconform)
- [Схемы Kubernetes JSON (Fork от yannh)](https://github.com/yannh/kubernetes-json-schema)
- [Каталог схем CRD от Datree](https://github.com/datreeio/CRDs-catalog)
