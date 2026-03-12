# kubeconform

## Определения

**`kubeconform`** — это высокопроизводительный валидатор манифестов Kubernetes, который проверяет их на соответствие официальным схемам JSON Schema API Kubernetes.

---

## Basic Concepts

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

---

## Файлы

| Файл | Описание |
|------|----------|
| [usage.md](./usage.md) | Локальная валидация, CI/CD, Helm, Kustomize |
| [operations.md](./operations.md) | Офлайн-валидация, CRD, флаги, сравнение, лучшие практики |

---

## Additional Information

### Связанные документы

- **[Kustomize](./kustomize_overview.md)** — валидация результатов kustomize
- **[Helm](../Helm/helm_overview.md)** — валидация Helm-чартов
- **[GitOps](../../../GitOps/GitOps_overview.md)** — интеграция в GitOps-пайплайны

### Репозиторий и документация

- [GitHub: yannh/kubeconform](https://github.com/yannh/kubeconform)
- [Схемы Kubernetes JSON](https://github.com/yannh/kubernetes-json-schema)
