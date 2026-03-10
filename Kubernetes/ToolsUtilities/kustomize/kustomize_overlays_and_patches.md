# Kustomize — Наложения и патчи

## 1. Типы патчей

### Strategic Merge Patch (полный объект)

```yaml
# patches/deployment-patch.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: myapp
        env:
        - name: NEW_VAR
          value: "value"
```

### JSON Patch (RFC 6902)

```yaml
# patches/json-patch.yaml
- op: replace
  path: /spec/replicas
  value: 5
- op: add
  path: /spec/template/spec/containers/0/env/-
  value:
    name: FEATURE_FLAG
    value: "enabled"
```

### Патч через inline (в kustomization.yaml)

```yaml
patches:
  - target:
      kind: Deployment
      name: myapp
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 10
```

## 2. Практические сценарии

### 2.1. Применение конфигурации

**Просмотр результата (dry-run):**

```bash
# Просмотр сгенерированных манифестов
kubectl kustomize overlays/production/

# Сохранение в файл
kubectl kustomize overlays/production/ > manifests.yaml
```

**Применение к кластеру:**

```bash
# Применение staging конфигурации
kubectl apply -k overlays/staging/

# Применение production конфигурации
kubectl apply -k overlays/production/
```

**Удаление:**

```bash
kubectl delete -k overlays/staging/
```

### 2.2. Валидация с kubeconform

```bash
# Валидация результата kustomize
kubectl kustomize overlays/production | kubeconform -summary -

# Или в одном шаге
kubectl kustomize overlays/production | kubeconform -strict -
```

## 3. Связанные документы

- **[Обзор и концепции](./kustomize_overview.md)** — базовые определения
- **[Структура и синтаксис](./kustomize_structure_and_syntax.md)** — структура проекта
- **[Продвинутые возможности](./kustomize_advanced_features.md)** — генерация ConfigMap/Secret, интеграция с Helm
- **[kubeconform](../kubeconform/index.md)** — валидация манифестов
