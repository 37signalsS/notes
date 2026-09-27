# Let's Encrypt: Disaster Recovery и Backup

## Определения

**Disaster Recovery (DR)** — комплекс мероприятий по восстановлению работоспособности инфраструктуры после катастрофических сбоев: потеря данных, аппаратные сбои, компрометация ключей, уничтожение кластера. Для Let's Encrypt + cert-manager DR охватывает: восстановление ACME-аккаунтов, Issuer-ресурсов, Certificate-ресурсов и доступа к DNS API.

**RTO (Recovery Time Objective)** — максимальное допустимое время восстановления. Для Let's Encrypt: < 30 минут для сертификатов (автоматическое перевыпуск), < 2 часов для полного восстановления PKI-инфраструктуры.

**RPO (Recovery Point Objective)** — максимальная допустимая потеря данных. Для Let's Encrypt: 0 для приватных ключей (ACME-аккаунт), 0 для DNS API-токенов (ревокация не нужна — сертификаты перевыпускаются).

**Blast Radius** — зона поражения при инциденте. Потеря CA-ключа Let's Encrypt не влияет на сертификаты (ACME API генерирует новые ключи), но потеря DNS API-токена блокирует выпуск wildcard-сертификатов.

---

## Основные концепции

### Типы данных и стратегии восстановления

| Тип данных | Восстановление | Зависимость | RPO |
| :--- | :--- | :--- | :--- |
| **ACME Account Key** | Автоматическое (cert-manager перерегистрируется) | DNS API доступен | 0 |
| **Certificate ресурсы** | Автоматическое (cert-manager перевыпустит) | ACME API доступен | 0 |
| **Issuer/ClusterIssuer** | Ручное (восстановление из YAML/Git) | Нет | 0 |
| **DNS API Tokens** | Ручное (восстановление из хранилища секретов) | Хранилище доступно | 0 |
| **Certificate Secrets** | Автоматическое (cert-manager перевыпустит) | ACME API + DNS API | 0 |
| **trust-manager Bundle** | Автоматическое (после восстановления Secret) | Secret как источник | 0 |

**Ключевой принцип:** В отличие от Private CA, для Let's Encrypt **не нужно** хранить приватные ключи CA — они генерируются заново через ACME API. DR-стратегия фокусируется на восстановлении доступа к ACME API и DNS API.

### Источники бэкапа

| Что бэкапить | Где хранить | Частота | Формат |
| :--- | :--- | :--- | :--- |
| YAML-манифесты Issuer/Certificate | Git repository | При каждом изменении | Git commit |
| DNS API Tokens | HashiCorp Vault / Sealed Secrets | При каждом изменении | Encrypted Secret |
| RBAC Role/RoleBinding | Git repository | При каждом изменении | YAML |
| trust-manager Bundle | Git repository | При каждом изменении | YAML |
| Prometheus Rule | Git repository | При каждом изменении | YAML |
| cert-manager Helm values | Git repository | При каждом изменении | values.yaml |

---

## Практические сценарии

### Runbook 1: Потеря namespace cert-manager

**Триггер:** `kubectl delete namespace cert-manager` или потеря узла.

**Шаг 1: Восстановление cert-manager (10 мин)**
```bash
# Установка cert-manager через Helm
helm repo add jetstack https://charts.jetstack.io
helm repo update

helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.21.0 \
  --set installCRDs=true
```

**Шаг 2: Восстановление Issuer из Git (5 мин)**
```bash
# Клонируйте репозиторий с манифестами
git clone https://github.com/example/k8s-certificates.git
cd k8s-certificates

# Примените все Issuer и ClusterIssuer
kubectl apply -f issuers/
kubectl apply -f clusterissuers/
```

**Шаг 3: Верификация (10 мин)**
```bash
# Проверка статуса Issuer
kubectl describe clusterissuer letsencrypt-prod

# Проверка автоматического восстановления Certificate
kubectl get certificate -A -o custom-columns=\
  NAME:.metadata.name,\
  NAMESPACE:.metadata.namespace,\
  READY:.status.conditions[?(@.type=="Ready")].status

# Ожидание выпуска сертификатов (5–10 минут)
kubectl get order -A -w
```

### Runbook 2: Потеря DNS API Token

**Триггер:** Cloudflare API Token деактивирован, утерян или скомпрометирован.

**Шаг 1: Создание нового токена (5 мин)**
```bash
# Cloudflare: создайте новый API Token в Dashboard
# Permissions: Zone -> DNS -> Edit (для конкретной зоны)
# IP Restriction: ограничьте IP-адресами кластера

# Создайте новый Secret
kubectl create secret generic cloudflare-api-token-new \
  --from-literal=api-token=<NEW_TOKEN> \
  -n cert-manager \
  --dry-run=client -o yaml | kubectl apply -f -
```

**Шаг 2: Обновление ClusterIssuer (2 мин)**
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-dns01
spec:
  acme:
    email: admin@example.com
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-dns01-account-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token-new  # Новый Secret
            key: api-token
```

**Шаг 3: Принудительное продление (5 мин)**
```bash
# Принудительное продление wildcard-сертификатов
cmctl renew --all -A

# Мониторинг
kubectl get order -A -w
```

### Runbook 3: Потеря Kubernetes-кластера

**Триггер:** Полная потеря кластера (облачный провайдер, локальная инфраструктура).

**Шаг 1: Восстановление кластера (зависит от инфраструктуры)**
```bash
# Восстановление через Velero (если настроен)
velero restore create --from-backup <backup-name>

# Восстановление через ArgoCD (GitOps)
argocd app sync cert-manager
```

**Шаг 2: Восстановление cert-manager (10 мин)**
```bash
# Если GitOps не настроен — ручная установка
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.21.0 \
  --set installCRDs=true

# Применение всех ресурсов из Git
kubectl apply -f k8s-certificates/
```

**Шаг 3: Верификация (15 мин)**
```bash
# Проверка, что все сертификаты перевыпущены
kubectl get certificate -A -o custom-columns=\
  NAME:.metadata.name,\
  NAMESPACE:.metadata.namespace,\
  READY:.status.conditions[?(@.type=="Ready")].status

# Проверка rate limits (массовый перевыпуск может их превысить)
kubectl logs -n cert-manager -l app=cert-manager | grep -i "rate\|limit"

# При rate limit — переключение на Staging для тестирования
```

### Runbook 4: Компрометация ACME-аккаунта

**Триггер:** Утечка приватного ключа ACME-аккаунта.

**Шаг 1: Перерегистрация (5 мин)**
```bash
# Удаление старого Secret с ключом аккаунта
kubectl delete secret cert-manager-issuer-account-letsencrypt-prod -n cert-manager

# Применение Issuer заново (cert-manager зарегистрирует новый аккаунт)
kubectl delete clusterissuer letsencrypt-prod
kubectl apply -f clusterissuer-prod.yaml

# Верификация
kubectl describe clusterissuer letsencrypt-prod
# → Status should show "Ready: True"
```

**Шаг 2: Перевыпуск сертификатов (10 мин)**
```bash
# Принудительное продление всех сертификатов (с новым аккаунтом)
cmctl renew --all -A
```

---

## Дополнительная информация

### Автоматизация бэкапа через CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cert-manager-backup
  namespace: cert-manager
spec:
  schedule: "0 2 * * *"  # Ежедневно в 2:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              # Бэкап всех Issuer и ClusterIssuer
              kubectl get clusterissuer -o yaml > /backup/clusterissuers.yaml
              kubectl get issuer -A -o yaml > /backup/issuers.yaml

              # Бэкап всех Certificate
              kubectl get certificate -A -o yaml > /backup/certificates.yaml

              # Бэкап trust-manager Bundle
              kubectl get bundle -A -o yaml 2>/dev/null > /backup/bundles.yaml || true

              # Бэкап PrometheusRule
              kubectl get prometheusrule -n cert-manager -o yaml > /backup/prometheusrules.yaml 2>/dev/null || true

              echo "Backup completed: $(date)"
            volumeMounts:
            - name: backup
              mountPath: /backup
          restartPolicy: OnFailure
          volumes:
          - name: backup
            persistentVolumeClaim:
              claimName: cert-manager-backup-pvc
```

### Мониторинг целостности backups

```yaml
# PrometheusRule для алерта на отсутствие бэкапа
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cert-manager-backup-alerts
  namespace: cert-manager
spec:
  groups:
  - name: backup.rules
    rules:
    - alert: CertManagerBackupMissing
      expr: time() - cert_manager_backup_last_success_timestamp_seconds > 86400 * 2
      for: 1h
      labels:
        severity: warning
      annotations:
        summary: "Бэкап cert-manager не выполнялся более 2 дней"
```

### GitOps для cert-manager

Рекомендуемый подход к backup — GitOps: все ресурсы cert-manager хранятся в Git и автоматически применяются через ArgoCD/Flux.

```
├── cluster/
│   ├── cert-manager/
│   │   ├── helm-values.yaml
│   │   ├── clusterissuer-prod.yaml
│   │   ├── clusterissuer-staging.yaml
│   │   ├── certificates/
│   │   │   ├── app-tls.yaml
│   │   │   ├── wildcard-tls.yaml
│   │   │   └── api-tls.yaml
│   │   ├── network-policies/
│   │   │   └── cert-manager-egress.yaml
│   │   └── prometheus-rules/
│   │       └── letsencrypt-alerts.yaml
```

### Смотрите также

- **[Disaster Recovery: Private CA](../Private_CA/disaster_recovery_runbook.md)** — DR для внутренних CA (Vault PKI)
- **[Kubernetes Backup Strategies](../../../../Kubernetes/Operations/backup-strategies.md)** — общие стратегии бэкапа Kubernetes
- **[Let's Encrypt: Incident Response](./letsencrypt_incident_response.md)** — процедуры реагирования на инциденты
- **[Let's Encrypt: Обзор](./index.md)** — лимиты и мониторинг
- **[cert-manager: Администрирование](../Administration/index.md)** — HA и эксплуатация
