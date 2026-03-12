# Kustomize — Продвинутые возможности

## 1. Генерация ConfigMap и Secret

### Из литералов

```yaml
configMapGenerator:
  - name: app-config
    literals:
      - DATABASE_URL=postgres://localhost:5432/db
      - CACHE_TTL=3600

secretGenerator:
  - name: db-secret
    literals:
      - username=admin
      - password=S3cr3t
```

### Из файлов

```yaml
configMapGenerator:
  - name: nginx-config
    files:
      - nginx.conf

secretGenerator:
  - name: tls-secret
    files:
      - tls.crt
      - tls.key
    type: kubernetes.io/tls
```

### С поведением (behavior)

```yaml
configMapGenerator:
  - name: app-config
    behavior: merge  # merge, replace, create
    literals:
      - NEW_KEY=new_value
```

## 2. Интеграция с Helm

**Гибридный подход:**

```bash
# Генерация базовых манифестов из Helm
helm template my-chart > base/manifest.yaml

# Создание kustomization.yaml для base
cat > base/kustomization.yaml <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - manifest.yaml
EOF

# Применение overlay через kustomize
kubectl apply -k overlays/production/
```

**Подробнее:** [Интеграция Helm + Kustomize](../Helm/Advanced/scenarios.md#2-гибридное-использование-с-kustomize)

## 3. Валидация с kubeconform

```bash
# Валидация результата kustomize
kubectl kustomize overlays/production | kubeconform -summary -

# Или в одном шаге
kubectl kustomize overlays/production | kubeconform -strict -
```

## 4. Связанные документы

- **[Обзор и концепции](./kustomize_overview.md)** — базовые определения
- **[Структура и синтаксис](./kustomize_structure_and_syntax.md)** — структура проекта
- **[Наложения и патчи](./kustomize_overlays_and_patches.md)** — типы патчей
- **[Helm](.../Helm/helm_overview.md)** — шаблонизация и пакетный менеджер
- **[kubeconform](../kubeconform/index.md)** — валидация манифестов
