# kubeconform usage

## Definitions

**Использование kubeconform** — практические сценарии: локальная валидация, CI/CD-интеграция (GitLab CI, GitHub Actions), валидация Helm-чартов и Kustomize.

---

## Basic Concepts

### Форматы вывода для CI/CD

| Формат | Флаг | Описание |
| :--- | :--- | :--- |
| **TAP** | `-output tap` | Test Anything Protocol, парсится в CI |
| **JUnit** | `-output junit` | JUnit XML для Jenkins/GitLab |
| **JSON** | `-output json` | Программная обработка |
| **Text** | `-output text` | Человекочитаемый (по умолчанию) |

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
```

**Валидация из stdin:**

```bash
cat deployment.yaml | kubeconform -
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

---

## Additional Information

### Связанные документы

- [Главная kubeconform](./index.md)
- [Операции kubeconform](./operations.md)
- [Kustomize](../kustomize/kustomize_overview.md) — валидация результатов `kubectl kustomize`
- [Helm](../../ToolsUtilities/Helm/helm_overview.md) — валидация отрендеренных чартов
