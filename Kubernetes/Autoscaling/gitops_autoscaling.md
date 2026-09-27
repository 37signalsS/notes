# GitOps для Autoscaling: управление HPA, VPA, CA через Git

## Определения

**GitOps** — методология, при которой конфигурация кластера хранится в Git, а синхронизация состояния происходит автоматически через контроллеры (ArgoCD, Flux). Git выступает как единый источник истины (SSoT) для всех манифестов, включая autoscaling.

**ignoreDifferences** — параметр ArgoCD, позволяющий игнорировать определённые поля при сверке состояния Git и кластера. Критичен для HPA и VPA, которые управляют полями, которые GitOps-агент может пытаться откатить.

**drift detection** — механизм обнаружения расхождений между состоянием в Git и фактическим состоянием кластера. GitOps-агент периодически проверяет и синхронизирует изменения.

---

## Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая | Примечание |
|-----------|-------------------|---------------|------------|
| ArgoCD | 2.8+ | 2.10+ | Pull-based GitOps |
| Flux | 2.0+ | 2.2+ | Pull-based GitOps |
| HPA | autoscaling/v2 | autoscaling/v2 | Управление replicas |
| VPA | autoscaling.k8s.io/v1 | autoscaling.k8s.io/v1 | Рекомендации ресурсов |

---

## Теоретический блок

### Проблема: конфликт GitOps и Autoscaling

HPA и VPA управляют полями Deployment/Pod, которые GitOps-агент может откатить:

```
HPA управляет:    .spec.replicas
VPA рекомендует:  .spec.template.spec.containers[].resources.requests
                  .spec.template.spec.containers[].resources.limits

ArgoCD сверяет:   ВСЕ поля манифеста с Git
Результат:        ArgoCD пытается откатить изменения HPA/VPA → вечный OutOfSync
```

**Решение:** Использовать `ignoreDifferences` в ArgoCD или annotations в манифестах.

### Модели управления autoscaling в GitOps

| Модель | Описание | Плюсы | Минусы |
|--------|----------|-------|--------|
| **Static** | HPA/VPA манифесты в Git, без автообновлений | Полный контроль, версионирование | Нет автоматического подбора ресурсов |
| **Semi-auto** | HPA в Git, VPA в режиме Off (только рекомендации) | Контроль replicas, аналитика ресурсов | VPA не применяет рекомендации автоматически |
| **Auto** | HPA + VPA Auto, GitOps игнорирует динамические поля | Полная автоматизация | Сложность отладки, риск дрейфа |

### Конфликт ArgoCD + HPA

**Проблема:** HPA изменяет `.spec.replicas`, ArgoCD видит дрейф и откатывает количество реплик.

**Решение 1: ignoreDifferences в ArgoCD**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
spec:
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas  # Игнорировать изменения replicas (HPA)
    - group: autoscaling
      kind: HorizontalPodAutoscaler
      jqPathExpressions:
        - '.status.conditions[] | select(.type == "ScalingLimited")'  # Игнорировать статус
```

**Решение 2: Убрать replicas из Git-манифеста**

```yaml
# В Git манифесте НЕТ поля replicas — HPA управляет им полностью
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  # replicas ОТСУТСТВУЕТ — HPA будет единственным источником
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
        - name: app
          image: my-app:v1.0
          resources:
            requests:
              cpu: 200m
              memory: 256Mi
```

### Конфликт ArgoCD + VPA

**Проблема:** VPA Auto изменяет `resources.requests` и `resources.limits`, ArgoCD откатывает.

**Решение 1: VPA в режиме Off**

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: my-app-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  updatePolicy:
    updateMode: "Off"  # Только рекомендации, без применения
```

**Решение 2: ignoreDifferences для VPA**

```yaml
# В ArgoCD Application
ignoreDifferences:
  - group: apps
    kind: Deployment
    jqPathExpressions:
      - '.spec.template.spec.containers[] | .resources'
```

**Решение 3: HPA + VPA разные метрики**

```yaml
# HPA по CPU, VPA по памяти (или наоборот)
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa
spec:
  metrics:
    - type: Resource
      resource:
        name: cpu  # HPA масштабирует по CPU
        target:
          type: Utilization
          averageUtilization: 70
---
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: my-app-vpa
spec:
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
      - containerName: "*"
        controlledResources: ["memory"]  # VPA управляет только памятью
```

---

## Практический блок

### ArgoCD: Манифест autoscaling

```yaml
# Structure: gitops-repo/apps/my-app/
# ├── deployment.yaml
# ├── hpa.yaml
# ├── vpa.yaml
# ├── pdb.yaml
# └── kustomization.yaml

# hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa
  annotations:
    argocd.argoproj.io/sync-wave: "1"  # Синхронизировать после Deployment
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 120
```

### Flux: Манифест autoscaling

```yaml
# Kustomization для Flux
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: my-app
  namespace: flux-system
spec:
  interval: 5m
  path: ./apps/my-app
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
  healthChecks:
    - apiVersion: apps/v1
      kind: Deployment
      name: my-app
      namespace: default
  timeout: 3m
```

### VPA рекомендации → Git (ручной паттерн)

```bash
# 1. Получить рекомендации VPA
kubectl get vpa my-app-vpa -o jsonpath='{.status.recommendation.containerRecommendations[0]}'

# 2. Обновить манифест в Git
# (автоматизация через CronJob или CI/CD pipeline)

# 3. ArgoCD синхронизирует
argocd app sync my-app
```

### Автоматизация: CronJob для VPA → Git

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: vpa-to-git
  namespace: monitoring
spec:
  schedule: "0 */6 * * *"  # Каждые 6 часов
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: vpa-git-updater
          containers:
            - name: updater
              image: bitnami/kubectl:latest
              command:
                - /bin/sh
                - -c
                - |
                  # Получаем рекомендации VPA
                  RECOMMENDATION=$(kubectl get vpa my-app-vpa -o jsonpath='{.status.recommendation.containerRecommendations[0].target}')
                  
                  # Обновляем Deployment в Git через API
                  # (установите kustomize или yq для рендеринга)
                  
                  # Пример: обновление через kubectl (в GitOps-цикле)
                  kubectl patch deployment my-app -p "{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"app\",\"resources\":$(echo $RECOMMENDATION | jq -c .)}]}}}}"
          restartPolicy: OnFailure
```

### Renovate для обновления версий autoscaling

```json
// renovate.json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:base"],
  "kubernetes": {
    "enabled": true
  },
  "regexManagers": [
    {
      "fileMatch": ["apps/.+\\.yaml$"],
      "matchStrings": ["image: registry.k8s.io/autoscaling/cluster-autoscaler:v(\\d+\\.\\d+\\.\\d+)"],
      "datasourceTemplate": "docker",
      "depNameTemplate": "registry.k8s.io/autoscaling/cluster-autoscaler"
    }
  ]
}
```

---

## Дополнительная информация

### Best Practices

1. **HPA replicas в Git:** Не храните `.spec.replicas` в Git, если используется HPA — пусть HPA управляет
2. **VPA в Off:** Для GitOps рекомендуется `updateMode: "Off"` — только рекомендации
3. **ignoreDifferences:** Всегда настраивайте для HPA/VPA в ArgoCD
4. **sync-wave:** Используйте аннотации `argocd.argoproj.io/sync-wave` для порядка синхронизации (Deployment → HPA → PDB)
5. **Health checks:** Настройте health checks для HPA/VPA в ArgoCD
6. **Drift detection:** Включите `selfHeal: true` для автоматического исправления дрейфа

### Типичные ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| ArgoCD показывает OutOfSync для HPA | HPA изменил replicas | `ignoreDifferences` для `/spec/replicas` |
| VPA откатывает resources | ArgoCD восстанавливает requests из Git | VPA в режиме Off или `ignoreDifferences` |
| HPA + ArgoCD: бесконечный цикл | ArgoCD откатывает, HPA меняет обратно | Убрать replicas из Git-манифеста |
| Flux: конфликт с VPA | Flux восстанавливает resources | `spec.postRenderers` для игнорирования |

### См. также

- [HPA: Основы](HPA/index.md) — базовая конфигурация HPA
- [VPA: Глубокое погружение](vpa_detailed.md) — режимы VPA
- [ConfigMap + GitOps](../Base/ConfigMap/best_practices.md#сценарий-1-управление-жизненным-циклом-через-gitops) — паттерны GitOps
- [ArgoCD: ignoreDifferences](../Troubleshooting/Common_Errors/hpa_troubleshooting.md) — диагностика HPA + GitOps
- [Progressive Delivery](../../GitOps/Concepts/progressive_delivery_gitops.md) — canary/blue-green с autoscaling
