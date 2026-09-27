# vCluster — антипаттерны и ошибки

> Документ описывает типичные ошибки при использовании vCluster, антипаттерны конфигурации, которые приводят к проблемам в продакшне. Обзор архитектуры — в [vcluster_overview.md](./vcluster_overview.md), troubleshooting — в [vcluster_troubleshooting.md](./vcluster_troubleshooting.md), безопасность — в [vcluster_security_and_sync.md](./vcluster_security_and_sync.md).

## Определения

**Антипаттерн (Antipattern)** — распространённое, но ошибочное решение, которое выглядит правильным на первый взгляд, но приводит к проблемам в долгосрочной перспективе.

**Blast Radius (Радиус взрыва)** — область действия инцидента. Чем больше blast radius, тем больше систем затрагивает сбой.

**Configuration Drift** — расхождение между желаемым состоянием (Git) и реальным (кластер). Возникает при ручных изменениях.

**Snowflake Server** — уникальная конфигурация, которую невозможно воспроизвести. Противоположность infrastructure-as-code.

**Single Point of Failure (SPOF)** — компонент, при падении которого вся система становится недоступной.

## Основные концепции

### Антипаттерн 1: Один vCluster на всё

**Описание:** Создание одного vCluster для всех сервисов, всех команд, всех окружений.

**Почему это плохо:**
- Blast radius = весь кластер. Падение etcd = недоступны ВСЕ сервисы.
- Невозможно изолировать ресурсы команд.
- RBAC становится неподдерживаемым.
- Один тенант может исчерпать ресурсы другого.

**Правильный подход:**
```text
Неправильно:                          Правильно:
┌──────────────┐                      ┌──────────────┐
│  vCluster    │                      │  vCluster    │
│  (все)       │                      │  team-alpha  │
└──────────────┘                      ├──────────────┤
                                      │  vCluster    │
                                      │  team-beta   │
                                      ├──────────────┤
                                      │  vCluster    │
                                      │  team-gamma  │
                                      └──────────────┘
```

### Антипаттерн 2: cluster-admin для Syncer

**Описание:** Использование ClusterRoleBinding с `cluster-admin` для ServiceAccount Syncer.

**Почему это плохо:**
- Syncer получает доступ ко ВСЕМУ кластеру.
- Нарушение principle of least privilege.
- Если Syncer скомпрометирован — полный доступ к хосту.

**Правильный подход:**
```yaml
# Минимальный Role для Syncer
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: vcluster-syncer-minimal
  namespace: team-alpha
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "configmaps", "secrets", "events"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses", "networkpolicies"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

### Антипаттерн 3: selfHeal: true + Sleep Mode

**Описание:** Включение selfHeal в ArgoCD для vCluster со включённым Sleep Mode.

**Почему это плохо:**
- ArgoCD обнаруживает отклонение (replicas=0) и восстанавливает до желаемого.
- VCluster просыпается каждые несколько минут.
- Расход CPU/RAM на хосте растёт.
- Экономия от Sleep Mode обнуляется.

**Правильный подход:**
```yaml
# ArgoCD Application
spec:
  syncPolicy:
    automated:
      selfHeal: false  # ОТКЛЮЧИТЬ для vCluster
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
    - group: apps
      kind: StatefulSet
      jsonPointers:
        - /spec/replicas
```

### Антипаттерн 4: port-forward в production

**Описание:** Использование `vcluster connect` (port-forward) для production-доступа.

**Почему это плохо:**
- Port-forward нестабилен при разрыве соединения.
- Нет балансировки нагрузки.
- Нет TLS termination.
- Не масштабируется.

**Правильный подход:**
```yaml
# Gateway API для production
networking:
  gatewayAPI:
    enabled: true
    apiServer:
      enabled: true
      host: "team-alpha.vcluster.example.com"
      gatewayRef:
        name: "external-gateway"
        namespace: "infra"
```

### Антипаттерн 5: Нет бэкапа

**Описание:** Отсутствие автоматического бэкапа Backing Store.

**Почему это плохо:**
- Потеря etcd = потеря ВСЕХ данных кластера.
- Невозможно восстановиться после инцидента.
- Compliance-требования не выполняются.

**Правильный подход:**
```yaml
# CronJob для бэкапа
apiVersion: batch/v1
kind: CronJob
metadata:
  name: vcluster-backup
spec:
  schedule: "0 */4 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: registry.k8s.io/etcd:3.5.13-0
              command:
                - /bin/sh
                - -c
                - |
                  ETCDCTL_API=3 etcdctl snapshot save \
                    /backup/snapshot-$(date +%Y%m%d-%H%M%S).db
```

### Антипаттерн 6: Один updateStrategy для всего

**Описание:** Использование `RollingUpdate` без `maxUnavailable` для Control Plane.

**Почему это плохо:**
- Все поды Control Plane могут обновиться одновременно.
- API-сервер становится недоступным на время обновления.
- Нет контроля над скоростью обновления.

**Правильный подход:**
```yaml
controlPlane:
  statefulSet:
    replicas: 3
    updateStrategy:
      type: RollingUpdate
      rollingUpdate:
        partition: 0
    # maxUnavailable не применим к StatefulSet,
    # но под AntiAffinity гарантирует, что поды на разных узлах
    affinity:
      podAntiAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
                - key: app
                  operator: In
                  values:
                    - vcluster
            topologyKey: kubernetes.io/hostname
```

### Антипаттерн 7: generic sync без проверки CRD

**Описание:** Включение generic sync для всех CRD без проверки совместимости.

**Почему это плохо:**
- Некоторые CRD несовместимы с синхронизацией.
- Конфликты имён между vCluster.
- Дублирование объектов на хосте.

**Правильный подход:**
```yaml
# Явное указание CRD для синхронизации
sync:
  toHost:
    customResources:
      certificates.cert-manager.io:
        enabled: true
        patches:
          - path: spec.secretName
            expression: '"vc-" + value'
      # Не включать ненужные CRD
```

### Антипаттерн 8: Нет PDB для Control Plane

**Описание:** Отсутствие PodDisruptionBudget для StatefulSet Control Plane.

**Почему это плохо:**
- Kubernetes может убить все поды одновременно при drain.
- API-сервер становится недоступным.
- Невозможно проводить maintenance.

**Правильный подход:**
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: vcluster-pdb
  namespace: team-alpha
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: vcluster
```

### Антипаттерн 9: Ручные изменения в проде

**Описание:** Изменение конфигурации vCluster через `kubectl patch` вместо Git.

**Почему это плохо:**
- Configuration drift: реальное состояние не соответствует Git.
- Невозможно отследить, кто и что изменил.
- Невоспроизводимость: следующий vCluster будет настроен иначе.
- Невозможно откатить.

**Правильный подход:**
```
1. Изменить vcluster.yaml в Git
2. Создать PR/MR
3. После мержа ArgoCD/Flux применит изменения
4. Кластер соответствует Git (SSoT)
```

### Антипаттерн 10: Нет изоляции тенантов

**Описание:** Общий namespace для нескольких vCluster или общий RBAC.

**Почему это плохо:**
- Один тенант видит ресурсы другого.
- Конфликты имён (Secret, ServiceAccount).
- Невозможно установить quotas per-tenant.

**Правильный подход:**
```text
Неправильно:                          Правильно:
┌──────────────┐                      ┌──────────────┐
│  namespace   │                      │ team-alpha   │
│  (shared)    │                      │  vCluster A  │
│  vCluster A  │                      ├──────────────┤
│  vCluster B  │                      │ team-beta    │
└──────────────┘                      │  vCluster B  │
                                      └──────────────┘
```

## Практические сценарии

### Как не ломать изоляцию тенантов

```yaml
# 1. Отдельный namespace для каждого vCluster
apiVersion: v1
kind: Namespace
metadata:
  name: team-alpha
  labels:
    vcluster.loft.sh/name: team-alpha
    team: alpha
    environment: production

# 2. ResourceQuota per-tenant
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-alpha-quota
  namespace: team-alpha
spec:
  hard:
    requests.cpu: "8"
    requests.memory: 16Gi
    pods: "100"

# 3. NetworkPolicy для изоляции
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: team-alpha-isolation
  namespace: team-alpha
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector: {}
  egress:
    - to:
        - podSelector: {}
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
```

### Как проверить конфигурацию на антипаттерны

```bash
#!/usr/bin/env bash
# check-vcluster-antipatterns.sh

echo "=== vCluster Antipattern Checker ==="

# 1. Проверить cluster-admin для Syncer
echo ""
echo "--- Check 1: Syncer RBAC ---"
for ns in $(kubectl get ns -l vcluster.loft.sh/name -o jsonpath='{.items[*].metadata.name}'); do
  SA=$(kubectl -n $ns get sa -l app=vcluster -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [ -n "$SA" ]; then
    CLUSTERROLES=$(kubectl get clusterrolebinding -o json | \
      jq -r ".items[] | select(.subjects[]? | select(.name==\"$SA\" and .namespace==\"$ns\")) | .roleRef.name" 2>/dev/null)
    if echo "$CLUSTERROLES" | grep -q "cluster-admin"; then
      echo "  [CRITICAL] $ns: Syncer has cluster-admin"
    else
      echo "  [OK] $ns: Syncer RBAC is minimal"
    fi
  fi
done

# 2. Проверить selfHeal
echo ""
echo "--- Check 2: ArgoCD selfHeal ---"
if kubectl get application -A -o json 2>/dev/null | jq -r '.items[] | select(.spec.syncPolicy.automated.selfHeal==true)' | grep -q "vcluster"; then
  echo "  [WARNING] ArgoCD selfHeal enabled for vCluster applications"
else
  echo "  [OK] selfHeal disabled for vCluster"
fi

# 3. Проверить бэкап
echo ""
echo "--- Check 3: Backup CronJob ---"
for ns in $(kubectl get ns -l vcluster.loft.sh/name -o jsonpath='{.items[*].metadata.name}'); do
  if kubectl -n $ns get cronjob -l app=vcluster-backup > /dev/null 2>&1; then
    LAST_SCHEDULE=$(kubectl -n $ns get cronjob vcluster-backup -o jsonpath='{.status.lastScheduleTime}' 2>/dev/null)
    echo "  [OK] $ns: Backup CronJob exists (last: $LAST_SCHEDULE)"
  else
    echo "  [CRITICAL] $ns: No backup CronJob found"
  fi
done

# 4. Проверить PDB
echo ""
echo "--- Check 4: PodDisruptionBudget ---"
for ns in $(kubectl get ns -l vcluster.loft.sh/name -o jsonpath='{.items[*].metadata.name}'); do
  if kubectl -n $ns get pdb -l app=vcluster > /dev/null 2>&1; then
    echo "  [OK] $ns: PDB exists"
  else
    echo "  [WARNING] $ns: No PDB found"
  fi
done

# 5. Проверить NetworkPolicy
echo ""
echo "--- Check 5: NetworkPolicy ---"
for ns in $(kubectl get ns -l vcluster.loft.sh/name -o jsonpath='{.items[*].metadata.name}'); do
  if kubectl -n $ns get networkpolicy -l vcluster.loft.sh/auto-generated=true > /dev/null 2>&1; then
    echo "  [OK] $ns: Auto-generated NetworkPolicy exists"
  else
    echo "  [WARNING] $ns: No auto-generated NetworkPolicy"
  fi
done

echo ""
echo "=== Check Complete ==="
```

### Чек-лист код-ревью для vCluster

| Проверка | Что искать | Действие |
| :--- | :--- | :--- |
| RBAC Syncer | `cluster-admin` в ClusterRoleBinding | Заменить на Role в namespace |
| selfHeal | `selfHeal: true` в ArgoCD | Отключить, добавить ignoreDifferences |
| Backup | Отсутствие CronJob | Добавить CronJob с etcd snapshot |
| PDB | Отсутствие PodDisruptionBudget | Добавить `minAvailable: 2` |
| NetworkPolicy | Отсутствие networkPolicy | Включить `policies.networkPolicy.enabled` |
| PSA | `podSecurityStandard: privileged` или отсутствие | Установить `restricted` |
| Resources | Отсутствие `resources.limits` | Добавить limits для Control Plane |
| Audit | `auditLog.enabled: false` | Включить аудит |
| Config drift | Ручные kubectl patch | Перевести на GitOps |

### Лучшие практики

- **Каждый тенант = отдельный vCluster:** Не объединяйте тенантов в одном vCluster.
- **GitOps только:** Все изменения через Git. Никаких ручных patch в проде.
- **Бэкап обязательно:** Автоматический бэкап каждые 4 часа + тест восстановления.
- **PDB обязателен:** Без PDB Kubernetes может убить все поды одновременно.
- **Minimal RBAC:** Syncer = Role, не ClusterRole. Без pods/exec.
- **Audit log:** Включите для compliance и troubleshooting.
- **Регулярный аудит:** Запускайте checker-скрипт 1 раз в неделю.
- **Документация:** Опишите архитектуру, зависимости, procedures.

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — troubleshooting](./vcluster_troubleshooting.md)
- [vCluster — безопасность и синхронизация](./vcluster_security_and_sync.md)

### См. также

- [Kubernetes — Security Best Practices](../../Kubernetes/Security/)
- [RBAC — Overview](../../Security/rbac/rbac_overview.md)

### Внешние ссылки

- [vCluster Best Practices](https://www.vcluster.com/docs/other-topics/best-practices)
- [Kubernetes Antipatterns](https://kubernetes.io/docs/concepts/configuration/best-practices/)
- [CIS Kubernetes Benchmark](https://www.cisecurity.org/benchmark/kubernetes)
