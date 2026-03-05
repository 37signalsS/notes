# kubeconform

## 1. Определения

**`kubeconform`** — это высокопроизводительный валидатор манифестов Kubernetes, который проверяет их на соответствие официальным схемам JSON Schema API Kubernetes.

## 2. Основные концепции

### Ключевые особенности

| Особенность | Описание |
| :--- | :--- |
| **Высокая производительность** | Параллельная обработка файлов, кэширование схем, в 10-100 раз быстрее kubeval |
| **Интеграция с CI/CD** | Возвращает ненулевой код выхода при ошибках, поддержка TAP/JUnit форматов |
| **Поддержка CRD** | Валидация Custom Resources при указании пути к OpenAPI схемам |
| **Офлайн-режим** | Работа без интернета при предварительно загруженных схемах |
| **Гибкость ввода** | Поддержка файлов, директорий, stdin, Helm-чартов |
| **Кэширование схем** | Локальное кэширование для ускорения повторных проверок |

### Архитектура

```
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

**Через Go:**

```bash
go install github.com/yannh/kubeconform/cmd/kubeconform@latest
```

**Через Homebrew (macOS/Linux):**

```bash
brew install kubeconform
```

**Бинарный файл:**

```bash
# Linux amd64
curl -LO https://github.com/yannh/kubeconform/releases/latest/download/kubeconform-linux-amd64.tar.gz
tar -xzf kubeconform-linux-amd64.tar.gz
sudo mv kubeconform /usr/local/bin/
chmod +x /usr/local/bin/kubeconform

# macOS arm64
curl -LO https://github.com/yannh/kubeconform/releases/latest/download/kubeconform-darwin-arm64.tar.gz
tar -xzf kubeconform-darwin-arm64.tar.gz
sudo mv kubeconform /usr/local/bin/
```

**Docker:**

```bash
docker run --rm -i ghcr.io/yannh/kubeconform:latest - -summary
```

## 3. Практические сценарии

### 3.1. Локальная валидация

**Проверка отдельных файлов:**

```bash
kubeconform deployment.yaml service.yaml configmap.yaml
```

**Рекурсивная проверка директории:**

```bash
kubeconform -R ./manifests/
```

**Проверка с подробным выводом:**

```bash
kubeconform -verbose ./manifests/
```

**Валидация из stdin:**

```bash
cat deployment.yaml | kubeconform -
```

### 3.2. Интеграция в CI/CD

**GitLab CI:**

```yaml
validate-k8s-manifests:
  image: ghcr.io/yannh/kubeconform:latest
  stage: test
  script:
    - echo "Validating Kubernetes manifests..."
    - kubeconform -summary -output tap 'manifests/**/*.yaml'
  rules:
    - changes:
        - manifests/**/*.yaml
```

**GitHub Actions:**

```yaml
name: Validate Kubernetes Manifests
on:
  push:
    paths:
      - 'manifests/**/*.yaml'
  pull_request:
    paths:
      - 'manifests/**/*.yaml'
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run kubeconform
        uses: yannh/kubeconform-action@v1
        with:
          manifest_path: manifests/
          output_format: tap
          strict: true
```

**Форматы вывода для CI:**

| Формат | Флаг | Описание |
| :--- | :--- | :--- |
| **TAP** | `-output tap` | Test Anything Protocol, парсится в CI |
| **JUnit** | `-output junit` | JUnit XML для интеграции с Jenkins/GitLab |
| **JSON** | `-output json` | JSON для программной обработки |
| **Text** | `-output text` | Человекочитаемый текст (по умолчанию) |

### 3.3. Валидация Helm-чартов

**Рендеринг и валидация:**

```bash
# Простая валидация
helm template my-chart | kubeconform -

# С параметрами
helm template my-chart --values values-prod.yaml | kubeconform -summary -

# Валидация с указанием версии Kubernetes
helm template my-chart | kubeconform -kubernetes-version 1.31.0 -
```

**Проверка чарта перед установкой:**

```bash
helm lint my-chart && helm template my-chart | kubeconform -summary -
```

### 3.4. Валидация Kustomize

**Проверка результатов kustomize:**

```bash
kubectl kustomize overlays/production | kubeconform -summary -
```

**В одном конвейере:**

```bash
#!/bin/bash
set -e

echo "Building Kustomize overlay..."
kubectl kustomize overlays/production > /tmp/manifests.yaml

echo "Validating with kubeconform..."
kubeconform -summary -strict /tmp/manifests.yaml

echo "Validation passed!"
```

### 3.5. Офлайн-валидация

**Загрузка схем для офлайн-работы:**

```bash
# Создание локального кэша схем
mkdir -p ~/kubeconform-schemas
kubeconform -list-schemas > schemas.txt

# Загрузка схем (скрипт)
while read schema; do
  curl -L "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/master/${schema}" \
    -o "~/kubeconform-schemas/${schema}"
done < schemas.txt
```

**Использование локальных схем:**

```bash
kubeconform -schema-location ~/kubeconform-schemas/{{ .ResourceKind }}.yaml manifests/
```

### 3.6. Валидация CRD

**С указанием путей к схемам CRD:**

```bash
kubeconform \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{ .Group }}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json' \
  manifests/
```

**С локальными CRD схемами:**

```bash
kubeconform \
  -schema-location default \
  -schema-location './crd-schemas/{{ .ResourceKind }}.json' \
  manifests/
```

### 3.7. Строгая валидация

**Режим strict (запрет дополнительных полей):**

```bash
kubeconform -strict deployment.yaml
```

**С указанием версии Kubernetes:**

```bash
# Валидация против конкретной версии K8s
kubeconform -kubernetes-version 1.31.0 manifests/

# Валидация против master-ветки
kubeconform -kubernetes-version master manifests/
```

## 4. Дополнительная информация

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes схемы | 1.20+ | Поддержка до 1.32+ |
| Go | 1.21+ | Для сборки из исходников |

### Флаги командной строки

| Флаг | Описание |
| :--- | :--- |
| `-R` | Рекурсивная проверка директорий |
| `-summary` | Вывод краткой сводки в конце |
| `-verbose` | Подробный вывод по каждому файлу |
| `-strict` | Строгий режим (запрет дополнительных полей) |
| `-output <format>` | Формат вывода (text, json, tap, junit) |
| `-kubernetes-version <ver>` | Версия Kubernetes для схем |
| `-schema-location <url>` | Путь к схемам (поддержка шаблонов) |
| `-ignore-missing-schemas` | Не ошибаться при отсутствии схем |
| `-skip-tls` | Пропускать проверку TLS для удалённых схем |
| `-cache <dir>` | Директория для кэширования схем |

### Сравнение с аналогами

| Инструмент | Производительность | CRD | Офлайн | CI/CD форматы |
| :--- | :--- | :--- | :--- | :--- |
| **kubeconform** | ⚡⚡⚡ | ✅ | ✅ | TAP, JUnit, JSON |
| **kubeval** | ⚡ | ❌ | ❌ | Text |
| **kube-linter** | ⚡⚡ | ✅ | ✅ | SARIF, JSON |

### Лучшие практики

1. **Интегрируйте в pre-commit хуки** для раннего обнаружения ошибок
2. **Используйте кэширование схем** для ускорения CI/CD
3. **Валидируйте против конкретной версии** Kubernetes вашего кластера
4. **Используйте strict режим** для предотвращения опечаток
5. **Настройте CRD схемы** для кастомных ресурсов

### Связанные документы

- **[Kustomize](./kustomize_overview.md)** — валидация результатов kustomize
- **[Helm](./Helm/helm_overview.md)** — валидация Helm-чартов
- **[GitOps](../../GitOps/GitOps_overview.md)** — интеграция в GitOps-пайплайны

### Репозиторий и документация

- [GitHub: yannh/kubeconform](https://github.com/yannh/kubeconform)
- [Схемы Kubernetes JSON](https://github.com/yannh/kubernetes-json-schema)
