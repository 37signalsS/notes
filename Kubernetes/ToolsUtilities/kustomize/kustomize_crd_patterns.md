# Kustomize — Работа с CRD и OpenAPI

## 1. Определения

**Custom Resource Definition (CRD)** — пользовательский ресурс Kubernetes, расширяющий API кластера. Kustomize «не знает» структуру CRD «из коробки», что приводит к проблемам при наложении патчей и добавлении меток.

**OpenAPI Integration** — механизм Kustomize для получения знаний о структуре CRD через пользовательские OpenAPI-схемы. Позволяет корректно применять `commonLabels`, `patches` и другие трансформации к кастомным ресурсам.

**CRD-паттерн** — рекомендуемый способ организации Kustomize-проекта, работающего с операторами и их CRD: установка CRD из base + application overlay для кастомных ресурсов.

## 2. Основные концепции

### Проблема: Kustomize не понимает CRD

Стандартные Kubernetes-ресурсы (Deployment, Service) имеют предопределённые ключи слияния (например, `name` для контейнеров). Kustomize использует их для Strategic Merge Patch. Но CRD (Istio VirtualService, Cert-Manager Certificate) Kustomize не знает, и:

1. **Strategic Merge Patch** работает как полная замена (`replace`), а не слияние
2. **`commonLabels`** могут добавляться в неправильные поля (вместо `spec.template.metadata.labels` — в корень)
3. **Патчи** могут случайно удалить целые секции CRD

**Решение:** всегда используйте **JSON Patch** для CRD вместо Strategic Merge.

### Два подхода к интеграции CRD

| Подход | Описание | Когда использовать |
| :--- | :--- | :--- |
| **JSON Patch** | Точечные операции `add/replace/remove` | Когда Kustomize не знает схему CRD |
| **OpenAPI схема** | Предоставление Kustomize схемы CRD | Когда нужна интеграция с `commonLabels`, Strategic Merge |

### Структура проекта с CRD

```text
my-operator/
├── base/
│   ├── crd/
│   │   ├── crd.yaml               # CustomResourceDefinition
│   │   └── kustomization.yaml
│   └── app/
│       ├── certificate.yaml        # Custom Resource (cert-manager)
│       ├── virtualservice.yaml     # Custom Resource (Istio)
│       └── kustomization.yaml
├── overlays/
│   ├── staging/
│   │   └── kustomization.yaml
│   └── production/
│       └── kustomization.yaml
└── schemas/
    └── cert-manager-crd.json       # OpenAPI-схема для CRD
```

## 3. Практические сценарии

### 3.1. CRD установка из base

```yaml
# base/crd/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - crd.yaml

# base/crd/crd.yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: certificates.cert-manager.io
spec:
  group: cert-manager.io
  names:
    kind: Certificate
    listKind: CertificateList
    plural: certificates
    singular: certificate
  scope: Namespaced
  versions:
    - name: v1
      served: true
      storage: true
```

**Overlay для production:**
```yaml
# overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base/crd          # Сначала CRD
  - ../../base/app          # Затем ресурсы, использующие CRD

# Важно: CRD должны быть применены ДО custom resources
```

### 3.2. JSON Patch для CRD (cert-manager Certificate)

```yaml
# overlays/production/kustomization.yaml
patches:
  # Duration сертификата
  - target:
      group: cert-manager.io
      kind: Certificate
      name: my-app-tls
    patch: |-
      - op: replace
        path: /spec/duration
        value: 2160h
      - op: replace
        path: /spec/renewBefore
        value: 360h

  # Self-signed issuer → cluster issuer
  - target:
      group: cert-manager.io
      kind: Certificate
      name: my-app-tls
    patch: |-
      - op: replace
        path: /spec/issuerRef/name
        value: letsencrypt-prod
      - op: replace
        path: /spec/issuerRef/kind
        value: ClusterIssuer
```

**Почему JSON Patch, а не Strategic Merge:**
```yaml
# НЕПРАВИЛЬНО (Strategic Merge): Kustomize не знает cert-manager Certificate
patches:
  - target:
      group: cert-manager.io
      kind: Certificate
      name: my-app-tls
    patch: |-
      apiVersion: cert-manager.io/v1
      kind: Certificate
      metadata:
        name: my-app-tls
      spec:
        duration: 2160h
        renewBefore: 360h
# → Kustomize может ПОЛНОСТЬЮ заменить spec, удалив secretName, dnsNames и т.д.

# ПРАВИЛЬНО (JSON Patch): точечная модификация
patches:
  - target:
      group: cert-manager.io
      kind: Certificate
      name: my-app-tls
    patch: |-
      - op: replace
        path: /spec/duration
        value: 2160h
# → Меняет ТОЛЬКО duration, остальные поля остаются
```

### 3.3. Istio VirtualService через JSON Patch

```yaml
# overlays/production/kustomization.yaml
patches:
  # Добавление routing rule
  - target:
      group: networking.istio.io
      kind: VirtualService
      name: my-app
    patch: |-
      - op: add
        path: /spec/http/0/route/0/weight
        value: 90
      - op: add
        path: /spec/http/0/route/-
        value:
          destination:
            host: my-app-canary
            port:
              number: 8080
          weight: 10

  # Timeout
  - target:
      group: networking.istio.io
      kind: VirtualService
      name: my-app
    patch: |-
      - op: add
        path: /spec/http/0/timeout
        value: 30s
      - op: add
        path: /spec/http/0/retries
        value:
          attempts: 3
          perTryTimeout: 10s
```

### 3.4. Prometheus ServiceMonitor через Kustomize

```yaml
# base/monitoring/service-monitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app: my-app
  endpoints:
    - port: metrics
      interval: 15s
```

```yaml
# overlays/production/kustomization.yaml
patches:
  # Изменение interval для production
  - target:
      group: monitoring.coreos.com
      kind: ServiceMonitor
      name: my-app
    patch: |-
      - op: replace
        path: /spec/endpoints/0/interval
        value: 30s

  # Добавление additionalLabels
  - target:
      group: monitoring.coreos.com
      kind: ServiceMonitor
      name: my-app
    patch: |-
      - op: add
        path: /metadata/labels/environment
        value: production
```

### 3.5. OpenAPI-схема для CRD

```yaml
# kustomization.yaml
openapi:
  path: schemas/cert-manager-crd.json
```

**Генерация OpenAPI-схемы:**
```bash
# Из API-сервера кластера (если CRD установлены)
kubectl get --raw /openapi/v2 | jq '.definitions["io.cert-manager.v1.Certificate"]' > schemas/cert-manager-crd.json

# Или скачать из репозитория оператора
curl -sL https://raw.githubusercontent.com/cert-manager/cert-manager/master/deploy/crds/charts/cert-manager/crds/certificates.yaml \
  | python3 -c "
import sys, yaml
crd = yaml.safe_load(sys.stdin)
schema = crd['spec']['versions'][0]['schema']['openAPIV3Schema']
print(json.dumps(schema, indent=2))
" > schemas/cert-manager-crd.json
```

### 3.6. commonLabels с OpenAPI

После предоставления OpenAPI-схемы Kustomize понимает структуру CRD и правильно добавляет `commonLabels`:

```yaml
# kustomization.yaml
openapi:
  path: schemas/cert-manager-crd.json

commonLabels:
  team: backend
  environment: production
```

**Без OpenAPI:**
```yaml
# commonLabels добавляются в КОРЕНЬ CRD (неправильно)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  labels:
    team: backend           # ← Kustomize добавляет сюда
    environment: production
spec:
  ...

# С OpenAPI:
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  labels:
    team: backend           # ← И в корень, и в шаблон (правильно)
    environment: production
spec:
  secretTemplate:
    labels:
      team: backend         # ← Kustomize也知道, куда добавить
      environment: production
```

## 4. Дополнительная информация

### Рекомендации

1. **Всегда JSON Patch для CRD** — если нет OpenAPI-схемы
2. **Устанавливайте CRD отдельно** — перед application resources
3. **Храните OpenAPI-схемы в Git** — для воспроизводимости
4. **Тестируйте патчи** — `kustomize build` + `kubeconform` с CRD-схемами

### См. также

- [OpenAPI в Kustomize](https://kubectl.docs.kubernetes.io/references/kustomize/kustomization/openapi/) — официальная документация
- [Продвинутые возможности](./kustomize_advanced_features.md) — OpenAPI Integration
- [Debugging Kustomize](./kustomize_debugging.md) — диагностика ошибок с CRD
