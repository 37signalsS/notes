# Использование kubeconform

## Определения

**Использование kubeconform** — практические сценарии валидации манифестов Kubernetes, интеграции в CI/CD, Helm и Kustomize.

> **Навигация:** [Главная kubeconform](./index.md) | [Операции](./operations.md)

---

## Practical Scenarios

### Локальная валидация

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

---

### Интеграция в CI/CD

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

---

### Валидация Helm-чартов

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

---

### Валидация Kustomize

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

---

## Additional Information

### Связанные темы

- **[Kustomize](./kustomize_overview.md)** — валидация результатов kustomize
- **[Helm](../Helm/helm_overview.md)** — валидация Helm-чартов
- **[GitOps](../../../GitOps/GitOps_overview.md)** — интеграция в GitOps-пайплайны
