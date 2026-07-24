# Kubeconform

## Определения

**Kubeconform** — это высокопроизводительный инструмент для валидации манифестов Kubernetes. Он проверяет соответствие YAML и JSON файлов официальным схемам JSON Schema API Kubernetes. Инструмент написан на языке Go, использует параллельную обработку и работает в десятки раз быстрее своего предшественника `kubeval`.

## Основные концепции

### Ключевые особенности

| Особенность | Описание |
| :--- | :--- |
| **Производительность** | Реализован на Go с поддержкой параллельной валидации файлов и кэширования схем. |
| **CI/CD-интеграция** | Возвращает ненулевой код выхода при обнаружении ошибок; поддерживает форматы TAP, JUnit и JSON. |
| **Поддержка CRD** | Позволяет валидировать Custom Resources при указании путей к соответствующим OpenAPI-схемам. |
| **Офлайн-режим** | Может работать полностью автономно, используя предварительно загруженные локальные схемы. |
| **Гибкость ввода** | Поддерживает чтение из файлов, директорий, стандартного ввода (stdin), а также работу с результатами Helm и Kustomize. |

### Архитектура процесса

```text
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Манифесты     │ ──> │   kubeconform    │ ──> │    Отчёт об     │
│   (.yaml/.yml)  │     │   (валидация)    │     │    ошибках      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               v
                        ┌──────────────────┐
                        │  Схемы Kubernetes│
                        │  (локально или   │
                        │   GitHub)        │
                        └──────────────────┘
```

### Установка

**Go (сборка из исходников):**
```bash
go install github.com/yannh/kubeconform/cmd/kubeconform@latest
# → инструмент будет установлен в $GOPATH/bin
```

**Homebrew (macOS/Linux):**
```bash
brew install kubeconform
# → "kubeconform" is now available in your PATH
```

**Docker:**
```bash
docker run --rm -i ghcr.io/yannh/kubeconform:latest - -summary < deployment.yaml
# → Summary: 1 resource found in 1 file - Valid
```

**Бинарный файл:**
Скачайте актуальный релиз со страницы [GitHub Releases](https://github.com/yannh/kubeconform/releases) и переместите его в директорию, указанную в переменной `$PATH`.

### Флаги командной строки

| Флаг | Описание |
| :--- | :--- |
| `-R` | Рекурсивный поиск манифестов в поддиректориях. |
| `-summary` | Вывод краткой статистики (количество файлов, ресурсов, ошибок) в конце работы. |
| `-verbose` | Подробный отчет по каждому проверенному ресурсу. |
| `-strict` | Строгий режим: отклонять манифесты с полями, отсутствующими в схеме. |
| `-output <format>` | Формат вывода: `text`, `json`, `tap`, `junit`. |
| `-kubernetes-version <ver>` | Версия Kubernetes для выбора схем (например, `1.32.0`, `master`). |
| `-schema-location <url>` | Путь к схемам. Поддерживает шаблоны `{{ .ResourceKind }}`, `{{ .Group }}`. |
| `-ignore-missing-schemas` | Игнорировать ресурсы, для которых не найдена схема (полезно для CRD). |
| `-skip-tls` | Отключить проверку TLS-сертификатов при загрузке схем по HTTPS. |
| `-cache <dir>` | Директория для локального кэширования загруженных схем. |

### Форматы вывода для автоматизации

| Формат | Флаг | Описание |
| :--- | :--- | :--- |
| **TAP** | `-output tap` | Test Anything Protocol — стандарт для интеграции с тестовыми системами. |
| **JUnit** | `-output junit` | XML-отчёт, который нативно поддерживается Jenkins, GitLab CI и Azure DevOps. |
| **JSON** | `-output json` | Машиночитаемый формат для интеграции с кастомными скриптами обработки. |
| **Text** | `-output text` | Человекочитаемый формат (используется по умолчанию). |

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
# → deployment.yaml - Deployment is valid
```

**Рекурсивная проверка директории:**
```bash
kubeconform -R ./manifests/
# → [выводит список проверенных файлов]
```

**Валидация потока из stdin:**
```bash
cat deployment.yaml | kubeconform -
# → stdin - Deployment is valid
```

### Строгая валидация под конкретную версию

Режим `strict` критически важен для обнаружения опечаток в названиях полей (например, `replicas` vs `replications`).

```bash
# Проверка против версии 1.32.0
kubeconform -strict -kubernetes-version 1.32.0 manifests/
# → [выводит ошибки при наличии неизвестных полей]
```

### Интеграция в CI/CD

**GitLab CI:**
```yaml
validate-manifests:
  image: ghcr.io/yannh/kubeconform:latest
  stage: test
  script:
    - kubeconform -summary -strict -output tap 'manifests/**/*.yaml'
# → [TAP отчет будет отображен в логах джобы]
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
```

### Валидация Helm и Kustomize

Инструменты шаблонизации часто генерируют манифесты, которые нужно проверять в "отрендеренном" виде.

**Helm:**
```bash
helm template my-chart | kubeconform -summary -strict
# → Summary: 12 resources found in 1 file - Valid
```

**Kustomize:**
```bash
kubectl kustomize overlays/production | kubeconform -summary -strict
# → Summary: 20 resources found in 1 file - Valid
```

### Офлайн-валидация

Для работы в изолированных окружениях необходимо заранее подготовить локальный кэш схем.

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
# → Схемы загружены в локальную директорию
```

**Использование локальных схем:**
```bash
kubeconform -schema-location '~/kubeconform-schemas/{{ .ResourceKind }}.json' manifests/
```

### Валидация CRD (Custom Resources)

Для проверки ресурсов операторов (например, Cert-Manager или Prometheus) необходимо подключить внешние каталоги схем.

**Использование каталога Datree:**
```bash
kubeconform \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{ .Group }}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json' \
  manifests/
# → [Валидация системных ресурсов K8s + CRD]
```

## Дополнительная информация

### Лучшие практики

1.  **Strict Mode в CI:** Всегда используйте `-strict`, чтобы не пропускать опечатки, которые Kubernetes может проигнорировать при `apply`.
2.  **Версионность:** Указывайте `-kubernetes-version`, соответствующую версии вашего кластера, чтобы избежать использования устаревших API.
3.  **Кэширование:** В CI-пайплайнах настраивайте кэширование директории схем (`-cache`), чтобы ускорить выполнение и уменьшить нагрузку на внешние репозитории.
4.  **Комбинация с Dry-run:** Используйте `kubeconform` совместно с `kubectl apply --dry-run=client` для максимальной надежности.

### Связанные инструменты

- **[Kustomize](../kustomize/kustomize_overview.md)** — генерация манифестов через оверлеи.
- **[Helm](../Helm/helm_overview.md)** — управление пакетными конфигурациями.
- **[GitOps](../../../GitOps/GitOps_overview.md)** — методология непрерывной доставки манифестов.

### Ресурсы

- [GitHub: yannh/kubeconform](https://github.com/yannh/kubeconform)
- [Схемы Kubernetes JSON](https://github.com/yannh/kubernetes-json-schema)
- [Каталог схем CRD (Datree)](https://github.com/datreeio/CRDs-catalog)
