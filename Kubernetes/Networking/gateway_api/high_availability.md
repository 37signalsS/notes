# Высокая доступность Gateway API

## Определения

**PodDisruptionBudget (PDB)** — Kubernetes ресурс, ограничивающий количество одновременно недоступных подов при добровольных операциях (drain, eviction, upgrade). Защищает Data Plane Gateway API от потери доступности при обновлении узлов или масштабировании кластера.

**Anti-Affinity** — правило Kubernetes Scheduling, предотвращающее размещение подов одного компонента на одном узле. Обеспечивает отказоустойчивость при падении отдельного node.

**Leader Election** — механизм координации Control Plane подов, при котором только один под (лидер) выполняет активную работу, а остальные находятся в режиме ожидания. Гарантирует отсутствие конфликтов при управлении ресурсами Gateway API.

**Disaster Recovery (DR)** — стратегия восстановления инфраструктуры Gateway API после катастрофических сбоев (потеря кластера, data center). Включает резервное копирование конфигураций и процедуры восстановления.

## Предварительные требования

| Компонент | Минимальная версия | Проверка |
|:---|:---|:---|
| Kubernetes | 1.25+ | `kubectl version --short` |
| Gateway API CRD | v1.0+ | `kubectl get crd gateways.gateway.networking.k8s.io` |
| Контроллер Gateway API | Зависит от реализации | `kubectl get pods -n <controller-ns>` |

## Базовые концепции

### Два уровня отказоустойчивости

Gateway API имеет две независимые плоскости, требующие отдельных стратегий HA:

1. **Control Plane (контроллер):** отвечает за мониторинг ресурсов и генерацию конфигурации. При падении контроллера существующая конфигурация Data Plane продолжает работать, но изменения не применяются.

2. **Data Plane (Envoy/NGINX/Traefik):** непосредственно обрабатывает трафик. При падении Data Plane трафик теряется до восстановления.

### Характерные задержки при падении компонентов

| Компонент | Эффект падения | Время восстановления |
|:---|:---|:---|
| Control Plane (1 replica) | Нет новых изменений, трафик продолжает работать | До перезапуска пода (обычно 10-30s) |
| Data Plane Pod | Потеря части трафика (зависит от количества подов) | До готовности нового пода + propagation |
| Контроллер + Data Plane | Полная потеря трафика | Критично: требует немедленного восстановления |

## Практические сценарии

### Настройка PodDisruptionBudget для Envoy Gateway

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: envoy-gateway-pdb
  namespace: envoy-gateway-system
spec:
  minAvailable: 1  # Как минимум 1 под должен быть доступен
  selector:
    matchLabels:
      gateway.envoyproxy.io/owning-gateway-name: ""
```

> **Важно:** Установите `replicas >= 2` перед созданием PDB, иначе drain узла будет заблокирован.

### Настройка PodDisruptionBudget для NGINX Gateway Fabric

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: nginx-gateway-pdb
  namespace: nginx-gateway
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: nginx-gateway-fabric
```

### Настройка PodDisruptionBudget для Traefik

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: traefik-pdb
  namespace: traefik
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
```

### Горизонтальное масштабирование Data Plane

**Envoy Gateway (через Helm values):**
```yaml
# values.yaml
config.envoyGateway.configGatewayShippingToRateLimitService: false
envoyGateway:
  configDeployment:
    provider:
      type: Kubernetes
      kubernetes:
        envoyHpa:
          minReplicas: 2
          maxReplicas: 10
```

**NGINX Gateway Fabric (kubectl):**
```bash
# Масштабирование Control Plane
kubectl scale deployment ngf-nginx-gateway-fabric \
  -n nginx-gateway \
  --replicas=3

# Масштабирование Data Plane (если используется отдельный deployment)
kubectl scale deployment nginx-gateway \
  -n nginx-gateway \
  --replicas=3
```

**Traefik (Helm values):**
```yaml
# values.yaml
deployment:
  replicas: 3
  podAnnotations:
    prometheus.io/scrape: "true"
```

### Anti-Affinity для разнесения подов по узлам

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: envoy-gateway
  namespace: envoy-gateway-system
spec:
  replicas: 3
  template:
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: gateway.envoyproxy.io/owning-gateway-name
                  operator: In
                  values: [""]
              topologyKey: kubernetes.io/hostname
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            gateway.envoyproxy.io/owning-gateway-name: ""
```

### Топологическое распределение по зонам (TopologySpreadConstraints)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: envoy-gateway
  namespace: envoy-gateway-system
spec:
  replicas: 3
  template:
    spec:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: envoy-gateway
```

### Защита Control Plane (Leader Election)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: envoy-gateway
  namespace: envoy-gateway-system
spec:
  replicas: 2  # Один лидер + один standby
  template:
    spec:
      containers:
      - name: envoy-gateway
        args:
        - --leader-elect  # Включить leader election
        - --leader-elect-id=envoy-gateway
        - --leader-elect-namespace=envoy-gateway-system
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: 2000m
            memory: 2Gi
```

### Disaster Recovery: бэкап и восстановление

**Бэкап конфигурации Gateway API:**
```bash
#!/bin/bash
# backup-gateway-api.sh

BACKUP_DIR="/backup/gateway-api/$(date +%Y%m%d-%H%M%S)"
mkdir -p $BACKUP_DIR

# Бэкап всех ресурсов Gateway API
kubectl get gatewayclass,httproute,gateway,referencegrant,backendtlspolicy \
  -A -o yaml > $BACKUP_DIR/all-resources.yaml

# Бэкап по отдельности (для удобства восстановления)
kubectl get gatewayclass -A -o yaml > $BACKUP_DIR/gatewayclasses.yaml
kubectl get gateway -A -o yaml > $BACKUP_DIR/gateways.yaml
kubectl get httproute -A -o yaml > $BACKUP_DIR/httproutes.yaml
kubectl get referencegrant -A -o yaml > $BACKUP_DIR/referencegrants.yaml
kubectl get backendtlspolicy -A -o yaml > $BACKUP_DIR/backendtlspolicies.yaml

# Бэкап CRD
kubectl get crd | grep gateway.networking.k8s.io > $BACKUP_DIR/crd-list.txt

echo "Бэкап сохранен в $BACKUP_DIR"
```

**Восстановление после сбоя:**
```bash
# 1. Восстановление CRD (если необходимо)
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml

# 2. Переустановка контроллера (пример для Envoy Gateway)
helm repo add envoygateway https://envoyproxy.github.io/gateway-helm/
helm install eg envoygateway/gateway-helm \
  --version v1.8.0 \
  -n envoy-gateway-system \
  --create-namespace

# 3. Восстановление ресурсов
kubectl apply -f /backup/gateway-api/<timestamp>/gatewayclasses.yaml
kubectl apply -f /backup/gateway-api/<timestamp>/gateways.yaml
kubectl apply -f /backup/gateway-api/<timestamp>/referencegrants.yaml
kubectl apply -f /backup/gateway-api/<timestamp>/httproutes.yaml
kubectl apply -f /backup/gateway-api/<timestamp>/backendtlspolicies.yaml

# 4. Проверка восстановления
kubectl get gateway,httproute -A
# → Все ресурсы должны быть в Accepted: True
```

### Регулярный крон-бэкап через CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: gateway-api-backup
  namespace: kube-system
spec:
  schedule: "0 2 * * *"  # Каждый день в 02:00
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: gateway-backup-sa
          containers:
          - name: backup
            image: bitnami/kubectl:1.28
            command:
            - /bin/sh
            - -c
            - |
              BACKUP_DIR="/backup/$(date +%Y%m%d)"
              mkdir -p $BACKUP_DIR
              kubectl get gatewayclass,gateway,httproute,referencegrant,backendtlspolicy \
                -A -o yaml > $BACKUP_DIR/gateway-api.yaml
          restartPolicy: OnFailure
```

## Troubleshooting

### Типичные ошибки HA

| Симптом | Причина | Решение |
|:---|:---|:---|
| PDB блокирует drain узла | `minAvailable` больше текущего количества подов | Увеличить replicas или уменьшить minAvailable |
| Два контроллера конфликтуют | Leader election не настроен | Добавить флаг `--leader-elect` |
| Трафик падает при обновлении узла | PDB не настроен или replicas=1 | Создать PDB с minAvailable: 1, увеличить replicas |
| Data Plane не распределяется по зонам | topologySpreadConstraints отсутствуют | Добавить constraints с правильным labelSelector |

### Проверка HA конфигурации

```bash
# Проверка PDB
kubectl get pdb -A
# → Все PDB должны показывать DISABLED или CURRENT/DESIRED

# Проверка что replicas >= minAvailable
kubectl get deployment -n envoy-gateway-system -o wide
kubectl get pdb -n envoy-gateway-system -o yaml | grep minAvailable

# Проверка anti-affinity
kubectl get pod -n envoy-gateway-system -o jsonpath='{range .items[*]}{.spec.nodeName}{"\t"}{.metadata.name}{"\n"}{end}'
# → Поды должны быть на разных узлах

# Проверка leader election
kubectl logs -n envoy-gateway-system -l control-plane=envoy-gateway-controller | grep leader
# → "leader elected: true"
```

## Best Practices

### Рекомендуемая конфигурация HA

| Компонент | replicas | PDB | Anti-Affinity | TopologySpread |
|:---|:---|:---|:---|:---|
| **Control Plane** | 2-3 | `minAvailable: 1` | `preferredDuringScheduling` | по зонам |
| **Data Plane (Envoy)** | 2-6 | `minAvailable: 1` | `requiredDuringScheduling` | по зонам |
| **Data Plane (NGINX)** | 2-4 | `minAvailable: 1` | `preferredDuringScheduling` | по зонам |

### Рекомендации

1. **Всегда используйте PDB:**
   - Даже при replicas=2, PDB защищает от одновременного удаления обоих подов
   - Используйте `minAvailable` вместо `maxUnavailable` для большей предсказуемости

2. **Разделяйте Control Plane и Data Plane:**
   - Control Plane и Data Plane в отдельных deployment'ах
   - Независимое масштабирование
   - Отдельные PDB

3. **Тестируйте HA регулярно:**
   - Simulate node drain: `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data`
   - Проверяйте что трафик не прерывается
   - Тестируйте failover control plane

4. **Настройте readiness/liveness probes:**
   ```yaml
   readinessProbe:
     httpGet:
       path: /ready
       port: 19000
     initialDelaySeconds: 10
     periodSeconds: 5
   livenessProbe:
     httpGet:
       path: /ready
       port: 19000
     initialDelaySeconds: 30
     periodSeconds: 10
   ```

5. **Документируйте процедуру failover:**
   - Пошаговая инструкция для операторов
   - Contact list для эскалации
   - Regular drill schedule

## Дополнительная информация

### Связанные ресурсы

- [Определения Gateway API](./definitions.md) — общие концепции архитектуры
- [Envoy Gateway](./envoy_gateway.md) — настройка EG с HA
- [NGINX Gateway Fabric](./nginx_gateway_fabric.md) — HA для NGF
- [Traefik](./traefik.md) — HA для Traefik
- [Мониторинг](./monitoring.md) — SLI/SLO для HA метрик

**Родительская тема:** [Gateway API](./definitions.md)
