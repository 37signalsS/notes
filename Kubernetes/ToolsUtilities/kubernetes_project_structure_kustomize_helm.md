# Структура проекта Kubernetes с использованием Kustomize и Helm

```
k8s-project/
├── base/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   ├── ingress.yaml
│   └── kustomization.yaml
├── overlays/
│   ├── dev/
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   ├── configmap.yaml
│   │   └── ingress.yaml
│   ├── staging/
│   └── prod/
└── helm/
    ├── Chart.yaml
    ├── values.yaml
    └── values/
        ├── dev-values.yaml
        ├── staging-values.yaml
        └── prod-values.yaml
```

## Описание компонентов

### `base/`

Содержит общие (shared) манифесты Kubernetes, которые являются основой для всех сред.

*   **`deployment.yaml`**: Манифест Deployment.
*   **`service.yaml`**: Определение Service для предоставления доступа к приложению.
*   **`configmap.yaml`**: ConfigMap для неконфиденциальных конфигураций.
*   **`ingress.yaml`**: Ingress для маршрутизации трафика в приложение.
*   **`kustomization.yaml`**: Конфигурация Kustomize для объединения ресурсов.

### `overlays/`

Содержит специфичные для каждой среды конфигурации.

*   **`dev/`**: Конфигурации для среды разработки.
    *   **`kustomization.yaml`**: Переопределения для среды разработки.
    *   **`namespace.yaml`**: Для изоляции ресурсов в среде Dev.
    *   **`configmap.yaml`**: Для переопределения специфичных для Dev конфигураций.
    *   **`ingress.yaml`**: Пользовательские конфигурации домена и SSL для Dev.
*   **`staging/`**: Переопределения для среды staging. Имеет ту же структуру, что и `dev`.
*   **`prod/`**: Переопределения для производственной среды. Имеет ту же структуру, что и `dev` и `staging`.

### `helm/`

Для шаблонизации манифестов Kubernetes.

*   **`Chart.yaml`**: Метаданные Helm-чарта.
*   **`values.yaml`**: Общие значения по умолчанию для Helm-чарта.
*   **`values/`**: Специфичные для сред значения Helm.
    *   **`dev-values.yaml`**: Специфичные конфигурации для Dev.
    *   **`staging-values.yaml`**: Специфичные конфигурации для Staging.
    *   **`prod-values.yaml`**: Специфичные конфигурации для Production.
