# Disaster Recovery для Kyverno

## Определения

**Disaster Recovery (DR)** — процесс восстановления работоспособности систем после катастрофических сбоев (потеря кластера, повреждение etcd, сбой контроллеров). Для Kyverno включает восстановление политик, webhook-конфигураций и PolicyReport.

**RPO (Recovery Point Objective)** — максимальный допустимый объем потерянных данных. Для политик Kyverno RPO = время между последним бэкапом и моментом сбоя.

**RTO (Recovery Time Objective)** — максимальное допустимое время восстановления. Для Kyverno RTO = время от обнаружения сбоя до восстановления admission control.

---

## Сценарии сбоев

```text
┌─────────────────────────────────────────────────────────────────┐
│  Уровень 1: Локальный сбой (Pod Crash, OOM)                    │
│  ────────────────────────────────────────────────────────────  │
│  Восстановление: автоматическое (restart policy)               │
│  RTO: <1 минута                                                 │
│  RPO: 0 (данные в etcd)                                         │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Уровень 2: Потеря контроллера (Deployment Failure)            │
│  ────────────────────────────────────────────────────────────  │
│  Восстановление:ubectl rollout restart / Argo CD sync          │
│  RTO: 5-10 минут                                                │
│  RPO: 0 (политики в etcd)                                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Уровень 3: Потеря webhook-конфигурации                        │
│  ────────────────────────────────────────────────────────────  │
│  Восстановление:helm upgrade / kubectl apply манифестов        │
│  RTO: 10-30 минут                                               │
│  RPO: 0 (конфигурация в Kubernetes)                             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Уровень 4: Потеря кластера (Total Loss)                       │
│  ────────────────────────────────────────────────────────────  │
│  Восстановление:helm install + kubectl apply политик           │
│  RTO: 30-60 минут                                               │
│  RPO: зависит от частоты бэкапов etcd                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Практические сценарии

### Сценарий 1: Бэкап политик Kyverno

**Цель:** Сохранить все политики, webhook-конфигурации и PolicyReport перед обновлением.

**Автоматический бэкап:**

```bash
#!/bin/bash
# kyverno-backup.sh
BACKUP_DIR="./kyverno-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p $BACKUP_DIR

# Бэкап политик
kubectl get clusterpolicy -o yaml > $BACKUP_DIR/clusterpolicies.yaml
kubectl get validatingpolicy -o yaml > $BACKUP_DIR/validatingpolicies.yaml
kubectl get mutatingpolicy -o yaml > $BACKUP_DIR/mutatingpolicies.yaml
kubectl get generatingpolicy -o yaml > $BACKUP_DIR/generatingpolicies.yaml

# Бэкап webhook-конфигураций
kubectl get validatingwebhookconfigurations -l app.kubernetes.io/instance=kyverno -o yaml \
  > $BACKUP_DIR/validating-webhooks.yaml
kubectl get mutatingwebhookconfigurations -l app.kubernetes.io/instance=kyverno -o yaml \
  > $BACKUP_DIR/mutating-webhooks.yaml

# Бэкап PolicyReport
kubectl get polr -A -o yaml > $BACKUP_DIR/policyreports.yaml

# Бэкап UpdateRequest
kubectl get updaterequests -n kyverno -o yaml > $BACKUP_DIR/updaterequests.yaml

# Бэкап конфигурации Helm
helm get values kyverno -n kyverno > $BACKUP_DIR/helm-values.yaml
helm get manifest kyverno -n kyverno > $BACKUP_DIR/helm-manifest.yaml

echo "Backup completed: $BACKUP_DIR"
ls -la $BACKUP_DIR
```

**CronJob для регулярного бэкапа:**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: kyverno-backup
  namespace: kube-system
spec:
  schedule: "0 */6 * * *"  # Каждые 6 часов
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: bitnami/kubectl:latest
              command: ["/bin/bash", "/scripts/backup.sh"]
              volumeMounts:
                - name: scripts
                  mountPath: /scripts
                - name: backup-storage
                  mountPath: /backup
          volumes:
            - name: scripts
              configMap:
                name: kyverno-backup-script
                defaultMode: 0755
            - name: backup-storage
              persistentVolumeClaim:
                claimName: kyverno-backup-pvc
          restartPolicy: OnFailure
```

### Сценарий 2: Восстановление после сбоя Pod

**Симптомы:** Pod Kyverno в CrashLoopBackOff.

**Диагностика:**

```bash
# Проверка логов
kubectl logs -n kyverno -l app.kubernetes.io/component=admission-controller --tail=100

# Проверка resource usage
kubectl top pods -n kyverno

# Проверка событий
kubectl get events -n kyverno --sort-by='.lastTimestamp'
```

**Восстановление:**

```bash
# Вариант 1: Restart deployment
kubectl rollout restart deployment kyverno-admission-controller -n kyverno
kubectl rollout status deployment kyverno-admission-controller -n kyverno

# Вариант 2: Если OOM - увеличить лимиты
kubectl patch deployment kyverno-admission-controller -n kyverno --type merge \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"kyverno","resources":{"limits":{"memory":"2Gi"}}}]}}}}'

# Вариант 3: Если конфигурация повреждена - переустановить
helm upgrade kyverno kyverno/kyverno -n kyverno --reuse-values
```

### Сценарий 3: Восстановление webhook-конфигурации

**Симптомы:** Webhook-конфигурация удалена или повреждена.

**Экстренное восстановление:**

```bash
# Шаг 1: Проверить наличие конфигураций
kubectl get validatingwebhookconfigurations | grep kyverno
kubectl get mutatingwebhookconfigurations | grep kyverno

# Шаг 2: Если конфигурации отсутствуют - восстановить из Helm
helm get manifest kyverno -n kyverno | kubectl apply -f -

# Шаг 3: Альтернатива - применить из бэкапа
kubectl apply -f ./kyverno-backup-*/validating-webhooks.yaml
kubectl apply -f ./kyverno-backup-*/mutating-webhooks.yaml

# Шаг 4: Проверить работоспособность
kubectl create deployment test --image=nginx --dry-run=server -o yaml | kubectl apply -f -
kubectl delete deployment test
```

**Временное отключение (если webhook блокирует все):**

```bash
# ВНИМАНИЕ: Использовать только в экстренных случаях!
kubectl delete validatingwebhookconfigurations -l app.kubernetes.io/instance=kyverno
kubectl delete mutatingwebhookconfigurations -l app.kubernetes.io/instance=kyverno

# После восстановления доступа - вернуть конфигурации
helm upgrade kyverno kyverno/kyverno -n kyverno --reuse-values
```

### Сценарий 4: Полное восстановление кластера

**Цель:** Восстановить Kyverno после потери кластера.

**Пошаговый процесс:**

```bash
# Шаг 1: Установка Kyverno на новый кластер
helm repo add kyverno https://kyverno.github.io/kyverno/
helm install kyverno kyverno/kyverno -n kyverno --create-namespace \
  --set validationFailureAction=Audit \
  --set replicaCount=3

# Шаг 2: Восстановление политик из Git
git clone https://github.com/myorg/gitops-policies.git
kubectl apply -f gitops-policies/base/

# Шаг 3: Восстановление webhook-конфигураций
kubectl apply -f ./kyverno-backup-*/validating-webhooks.yaml
kubectl apply -f ./kyverno-backup-*/mutating-webhooks.yaml

# Шаг 4: Восстановление PolicyReport (если необходимо)
kubectl apply -f ./kyverno-backup-*/policyreports.yaml

# Шаг 5: Верификация
kubectl get pods -n kyverno
kubectl get clusterpolicy
kubectl get polr -A

# Шаг 6: Активация политик
kubectl patch clusterpolicy <policy-name> --type merge \
  -p '{"spec":{"validationFailureAction":"Enforce"}}'
```

### Сценарий 5: Восстановление UpdateRequests

**Симптомы:** UpdateRequests в состоянии Failed или Pending.

**Диагностика и восстановление:**

```bash
# Шаг 1: Найти проблемные UpdateRequests
kubectl get updaterequests -n kyverno -o json | \
  jq -r '.items[] | select(.status.state != "Completed") | .metadata.name'

# Шаг 2: Удалить зависшие UpdateRequests
kubectl delete updaterequests -n kyverno -l state=Failed
kubectl delete updaterequests -n kyverno -l state=Pending

# Шаг 3: Принудительное сканирование для восстановления
kubectl annotate clusterpolicy <policy-name> kyverno.io/force-scan=$(date +%s) --overwrite
kubectl annotate clusterpolicy <policy-name> kyverno.io/force-scan-  # Удалить аннотацию

# Шаг 4: Проверить новые UpdateRequests
kubectl get updaterequests -n kyverno -w
```

---

## Дополнительная информация

### RTO/RPO для разных компонентов

| Компонент | RTO | RPO | Метод восстановления |
| :--- | :--- | :--- | :--- |
| Admission Controller | <1 мин | 0 | Автоматический restart |
| Background Controller | <1 мин | 0 | Автоматический restart |
| Webhook Configuration | <5 мин | 0 | helm upgrade / kubectl apply |
| ClusterPolicy | <10 мин | 0 | GitOps sync / kubectl apply |
| ValidatingPolicy | <10 мин | 0 | GitOps sync / kubectl apply |
| PolicyReport | <30 мин | <6ч | Восстановление из бэкапа |
| UpdateRequest | <5 мин | 0 | Принудительное сканирование |

### Prometheus метрики для мониторинга

```yaml
# Алерты для DR
groups:
  - name: kyverno-dr
    rules:
      - alert: KyvernoAdmissionControllerDown
        expr: up{job="kyverno"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Kyverno Admission Controller недоступен"

      - alert: KyvernoHighErrorRate
        expr: |
          sum(rate(kyverno_admission_requests_total{resource_state="error"}[5m]))
          / sum(rate(kyverno_admission_requests_total[5m])) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень ошибок webhook"

      - alert: KyvernoUpdateRequestsFailed
        expr: sum(kyverno_update_requests_total{status_type="error"}) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Большое количество Failed UpdateRequests"
```

### См. также
- [Диагностика проблем](./troubleshooting.md) — методология поиска причин
- [Установка](./install.md) — первоначальная настройка Kyverno
- [GitOps-интеграция](./argo-cd.md) — восстановление через Argo CD
- [Мультикластер](./multi-cluster.md) — восстановление в мультикластере
