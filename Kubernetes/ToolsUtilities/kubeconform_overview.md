# kubeconform

## Definitions

**`kubeconform`** — высокопроизводительный валидатор манифестов Kubernetes, проверяющий соответствие официальным схемам JSON Schema API Kubernetes. Написан на Go, работает в 10–100 раз быстрее kubeval.

---

## Basic Concepts

### Ключевые особенности

| Особенность | Описание |
| :--- | :--- |
| **Производительность** | Параллельная обработка, кэширование схем |
| **CI/CD-интеграция** | Ненулевой код выхода при ошибках, форматы TAP/JUnit/JSON |
| **Поддержка CRD** | Валидация Custom Resources через OpenAPI-схемы |
| **Офлайн-режим** | Работа с локально загруженными схемами |
| **Гибкость ввода** | Файлы, директории, stdin, Helm-чарты, Kustomize |

### Архитектура

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

**Go:** `go install github.com/yannh/kubeconform/cmd/kubeconform@latest`

**Homebrew:** `brew install kubeconform`

**Docker:** `docker run --rm -i ghcr.io/yannh/kubeconform:latest - -summary`

**Бинарный файл:** скачать с [GitHub Releases](https://github.com/yannh/kubeconform/releases) и поместить в `$PATH`.

### Флаги командной строки

| Флаг | Описание |
| :--- | :--- |
| `-R` | Рекурсивная проверка директорий |
| `-summary` | Краткая сводка в конце вывода |
| `-verbose` | Подробный вывод по каждому файлу |
| `-strict` | Запрет дополнительных полей в манифестах |
| `-output <format>` | Формат: text, json, tap, junit |
| `-kubernetes-version <ver>` | Версия K8s для схем (например, `1.31.0`, `master`) |
| `-schema-location <url>` | Путь к схемам с поддержкой шаблонов `{{ .ResourceKind }}` |
| `-ignore-missing-schemas` | Пропуск ресурсов без схем |
| `-skip-tls` | Отключение проверки TLS для удалённых схем |
| `-cache <dir>` | Директория кэширования схем |

### Форматы вывода для CI/CD

| Формат | Флаг | Описание |
| :--- | :--- | :--- |
| **TAP** | `-output tap` | Test Anything Protocol, парсится в CI |
| **JUnit** | `-output junit` | JUnit XML для Jenkins/GitLab |
| **JSON** | `-output json` | Программная обработка |
| **Text** | `-output text` | Человекочитаемый (по умолчанию) |

### Сравнение с аналогами

| Инструмент | Производительность | CRD | Офлайн | CI/CD форматы |
| :--- | :--- | :--- | :--- | :--- |
| **kubeconform** | Высокая (Go, параллелизм) | Да | Да | TAP, JUnit, JSON |
| **kubeval** | Низкая | Нет | Нет | Text |
| **kube-linter** | Средняя | Да | Да | SARIF, JSON |

---

## Practical Scenarios

### Локальная валидация

**Отдельные файлы:**

```bash
kubeconform deployment.yaml service.yaml configmap.yaml
```

**Рекурсивная проверка директории:**

```bash
kubeconform -R ./manifests/
```

**Подробный вывод:**

```bash
kubeconform -verbose ./manifests/
# → результат с деталями для каждого файла
```

**Валидация из stdin:**

```bash
cat deployment.yaml | kubeconform -
```

### Строгая валидация

**Режим strict (отклонение неизвестных полей):**

```bash
kubeconform -strict deployment.yaml
```

**Против конкретной версии K8s:**

```bash
kubeconform -kubernetes-version 1.31.0 manifests/
kubeconform -kubernetes-version master manifests/
```

### Интеграция в CI/CD

**GitLab CI:**

```yaml
validate-k8s-manifests:
  image: ghcr.io/yannh/kubeconform:latest
  stage: test
  script:
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

### Валидация Helm-чартов

```bash
helm template my-chart | kubeconform -
helm template my-chart --values values-prod.yaml | kubeconform -summary -
helm template my-chart | kubeconform -kubernetes-version 1.31.0 -
helm lint my-chart && helm template my-chart | kubeconform -summary -
```

### Валидация Kustomize

```bash
kubectl kustomize overlays/production | kubeconform -summary -
```

**Конвейер kustomize → kubeconform:**

```bash
#!/bin/bash
set -e
kubectl kustomize overlays/production > /tmp/manifests.yaml
kubeconform -summary -strict /tmp/manifests.yaml
```

### Офлайн-валидация

**Подготовка локального кэша схем:**

```bash
mkdir -p ~/kubeconform-schemas
kubeconform -list-schemas > schemas.txt

while read schema; do
  curl -L "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/master/${schema}" \
    -o "~/kubeconform-schemas/${schema}"
done < schemas.txt
```

**Использование:**

```bash
kubeconform -schema-location '~/kubeconform-schemas/{{ .ResourceKind }}.yaml' manifests/
```

### Валидация CRD

**Удалённые схемы (datree CRDs catalog):**

```bash
kubeconform \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{ .Group }}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json' \
  manifests/
```

**Локальные CRD-схемы:**

```bash
kubeconform \
  -schema-location default \
  -schema-location './crd-schemas/{{ .ResourceKind }}.json' \
  manifests/
```

---

## Additional Information

### Лучшие практики

1. Интеграция в pre-commit хуки для раннего обнаружения ошибок.
2. Кэширование схем для ускорения CI/CD.
3. Валидация против версии K8s целевого кластера.
4. Использование `-strict` для предотвращения опечаток.
5. Настройка `-schema-location` для CRD.

### Связанные инструменты

- [Kustomize](../kustomize/kustomize_overview.md) — валидация результатов `kubectl kustomize`
- [Helm](../Helm/helm_overview.md) — валидация отрендеренных чартов
- [GitOps](../../../GitOps/GitOps_overview.md) — интеграция в GitOps-пайплайны

### Ресурсы

- [GitHub: yannh/kubeconform](https://github.com/yannh/kubeconform)
- [Схемы Kubernetes JSON](https://github.com/yannh/kubernetes-json-schema)