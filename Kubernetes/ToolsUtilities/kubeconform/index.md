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

**Go:** `go install github.com/yannh/kubeconform/cmd/kubeconform@latest`

**Homebrew:** `brew install kubeconform`

**Docker:** `docker run --rm -i ghcr.io/yannh/kubeconform:latest - -summary`

**Бинарный файл:** скачать с [GitHub Releases](https://github.com/yannh/kubeconform/releases) и поместить в `$PATH`.

---

## Practical Scenarios

Практические сценарии разделены на два документа:

- **[Использование](./usage.md)** — локальная валидация, CI/CD (GitLab CI, GitHub Actions), интеграция с Helm и Kustomize
- **[Операции](./operations.md)** — офлайн-режим, валидация CRD, флаги, сравнение с аналогами, лучшие практики

---

## Additional Information

### Связанные инструменты

- **[Kustomize](../kustomize/kustomize_overview.md)** — валидация результатов `kubectl kustomize`
- **[Helm](../../ToolsUtilities/Helm/helm_overview.md)** — валидация отрендеренных чартов
- **[GitOps](../../../GitOps/GitOps_overview.md)** — интеграция в GitOps-пайплайны

### Ресурсы

- [GitHub: yannh/kubeconform](https://github.com/yannh/kubeconform)
- [Схемы Kubernetes JSON](https://github.com/yannh/kubernetes-json-schema)
