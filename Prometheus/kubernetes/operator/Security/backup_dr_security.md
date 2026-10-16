# Безопасность бэкапа и disaster recovery в Prometheus Operator

## Определения

**Backup Security Prometheus Operator** — комплекс мер по обеспечению конфиденциальности, целостности и доступности резервных копий данных мониторинга: TSDB данные Prometheus, конфигурация (ServiceMonitor, PrometheusRule, AlertmanagerConfig), секреты (Bearer tokens, TLS сертификаты, SMTP пароли).

**Disaster Recovery (DR)** — процесс восстановления стека мониторинга после катастрофы: потеря кластера, компрометация данных, ransomware, случайное удаление критичных CRD.

**TSDB (Time Series Database)** — хранилище временных рядов Prometheus. Данные хранятся в локальном каталоге и при потере требуют полного пересбора метрик (re-scraping), что может занять часы.

**Immutable Backups (WORM)** — неизменяемые резервные копии, которые невозможно удалить или модифицировать. Защита от ransomware и insider threats.

**RPO (Recovery Point Objective)** — максимальная допустимая потеря данных. Для мониторинга: 1-4 часа.

**RTO (Recovery Time Objective)** — максимальное допустимое время восстановления. Для критичного мониторинга: 15-30 минут.

> **Навигация:** [Главная Security](./index.md) | [Секреты](./secrets_best_practices.md) | [Runtime](./runtime_security.md)

---

## Основные концепции

### Специфика бэкапов Prometheus Operator

В отличие от типичых приложений, стек Prometheus Operator имеет уникальные особенности:

| Компонент | Особенности бэкапа | Приоритет | RPO |
|:---|:---|:---|:---|
| **Prometheus TSDB** | Локальный каталог /prometheus, PVC; при потере — re-scraping (часы) | Средний | 1-4 ч |
| **CRD (ServiceMonitor, PrometheusRule)** | Хранятся в etcd; GitOps = SSoT, но CRD в etcd должны быть синхронизированы | Критический | 0 (GitOps) |
| **Alertmanager TSDB** | Тишина алертов, group_wait; при потере — повторная отправка алертов | Низкий | 1 ч |
| **Секреты Operator** | TLS сертификаты, Basic Auth, OAuth2 токены, SMTP пароли | Критический | 0 (Immutable) |
| **Grafana dashboards** | Конфигурация datasource, panels; GitOps = SSoT | Высокий | 0 (GitOps) |

### Архитектура бэкапа (5 уровней)

**Level 1: etcd Snapshot** — Все Secrets, ConfigMaps, CRD (ServiceMonitor, PrometheusRule, AlertmanagerConfig). Шифрование: EncryptionConfiguration. Частота: 1-4 часа.

**Level 2: Velero + Kopia** — PVC с TSDB данными Prometheus. Шифрование: клиентское (AES-256). Частота: 4-8 часов.

**Level 3: GitOps State (SSoT)** — ServiceMonitor, PrometheusRule, AlertmanagerConfig в Git. Инкрементально при каждом коммите.

**Level 4: Object Storage (Thanos/S3)** — Historical метрики. Шифрование: SSE-KMS. Иммутабельность: Object Lock (WORM).

**Level 5: Offsite / Air-gapped** — Копия etcd snapshot на отдельном хранилище. Регулярная верификация. Частота: ежедневно.

### Шифрование бэкапов

**1. EncryptionConfiguration (etcd at rest):**

```yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources: [secrets]
    providers:
      - aescbc:
          keys:
            - name: key1
              secret: <base64-32-byte-key>
      - identity: {}
```

**2. Шифрование etcd snapshot перед загрузкой:**

```bash
# Снимок
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-snapshot.db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# Шифрование (AES-256-GCM)
openssl enc -aes-256-gcm -salt -pbkdf2 \
  -in /backup/etcd-snapshot.db \
  -out /backup/etcd-snapshot.db.enc \
  -pass file:/etc/backup/encryption-key

# Загрузка в S3 с Object Lock (WORM)
aws s3 cp /backup/etcd-snapshot.db.enc s3://monitoring-backups/etcd/ \
  --object-lock-mode COMPLIANCE \
  --sse aws:kms
```

**3. Velero BSL с Object Lock:**

```yaml
apiVersion: velero.io/v1
kind: BackupStorageLocation
metadata:
  name: default
  namespace: velero
spec:
  provider: aws
  objectStorage:
    bucket: monitoring-backups
    prefix: velero
  config:
    region: us-east-1
    serverSideEncryption: aws:kms
    kmsKeyId: <KMS-KEY-ID>
```

### Безопасность Secrets в бэкапах

**Проблема:** Secrets в etcd зашифрованы через EncryptionConfiguration, но при восстановлении ключ шифрования должен совпадать.

**Решения:**

1. **Хранение ключей шифрования отдельно от кластера:**

```bash
# Генерация ключа
dd if=/dev/urandom bs=32 count=1 | base64 > /secure/etcd-encryption-key

# Ключ НЕ хранится в кластере — только в offline vault/HSM
```

2. **Immutable Secrets для критичных токенов:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: prometheus-scrape-secrets
  namespace: monitoring
immutable: true
type: Opaque
data:
  bearer-token: <base64>
```

3. **External Secrets Operator для синхронизации:**

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: alertmanager-slack
  namespace: monitoring
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: alertmanager-slack-secret
    creationPolicy: Owner
  data:
    - secretKey: webhook-url
      remoteRef:
        key: monitoring/alertmanager
        property: slack-webhook
```

---

## Практические сценарии

### CronJob для автоматического бэкапа etcd

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-backup
  namespace: kube-system
spec:
  schedule: "0 */4 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          hostPID: true
          nodeSelector:
            node-role.kubernetes.io/control-plane: ""
          containers:
            - name: etcd-backup
              image: registry.k8s.io/etcd:3.5.12-0
              command:
                - /bin/sh
                - -c
                - |
                  set -euo pipefail
                  TIMESTAMP=$(date +%Y%m%d-%H%M)
                  SNAPSHOT="/tmp/etcd-snapshot-${TIMESTAMP}.db"
                  ENCRYPTED="/backup/etcd-snapshot-${TIMESTAMP}.db.enc"
                  etcdctl snapshot save ${SNAPSHOT} \
                    --endpoints=https://127.0.0.1:2379 \
                    --cacert=/etc/kubernetes/pki/etcd/ca.crt \
                    --cert=/etc/kubernetes/pki/etcd/server.crt \
                    --key=/etc/kubernetes/pki/etcd/server.key
                  etcdctl snapshot status ${SNAPSHOT} --write-out=table
                  openssl enc -aes-256-gcm -salt -pbkdf2 \
                    -in ${SNAPSHOT} -out ${ENCRYPTED} \
                    -pass file:/etc/backup/etcd-key
                  aws s3 cp ${ENCRYPTED} s3://monitoring-backups/etcd/ --sse aws:kms
                  rm -f ${SNAPSHOT} ${ENCRYPTED}
              volumeMounts:
                - name: pki
                  mountPath: /etc/kubernetes/pki
                  readOnly: true
                - name: backup
                  mountPath: /backup
          volumes:
            - name: pki
              hostPath:
                path: /etc/kubernetes/pki
            - name: backup
              persistentVolumeClaim:
                claimName: etcd-backup-pvc
          restartPolicy: OnFailure
```

### Восстановление Prometheus после потери данных

```bash
# 1. Остановить scraping (scale down)
kubectl scale deployment prometheus -n monitoring --replicas=0

# 2. Удалить PVC с повреждёнными данными
kubectl delete pvc data-prometheus-0 -n monitoring

# 3. Восстановить PVC из Velero backup
velero restore create prometheus-restore \
  --from-backup prometheus-backup-latest \
  --include-namespaces monitoring \
  --selector app.kubernetes.io/name=prometheus

# 4. Дождаться восстановления PVC
kubectl get pvc -n monitoring -w

# 5. Запустить Prometheus
kubectl scale deployment prometheus -n monitoring --replicas=2

# 6. Верификация
kubectl port-forward -n monitoring svc/prometheus 9090:9090
# Открыть http://localhost:9090/targets
```

### Восстановление после компрометации кластера

```bash
# 1. Верификация целостности бэкапа
ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-latest.db --write-out=table

# 2. Восстановление etcd на новом кластере
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-latest.db \
  --data-dir=/var/lib/etcd-restored \
  --name=new-master

# 3. Восстановление EncryptionConfiguration
kubectl apply -f /backup/encryption-config.yaml

# 4. Восстановление CRD Prometheus Operator
kubectl apply -f /backup/crds/

# 5. Восстановление мониторинга
kubectl apply -f /backup/monitoring-namespace/
kubectl apply -f /backup/prometheus-operator/

# 6. Восстановление скрейпинг-конфигурации
kubectl apply -f /backup/servicemonitors/
kubectl apply -f /backup/prometheusrules/

# 7. Восстановление секретов
velero restore create secrets-restore \
  --from-backup secrets-backup-latest \
  --include-resources secrets

# 8. Верификация
kubectl get pods -n monitoring
kubectl get servicemonitors -A
kubectl get prometheusrules -A
```

### Ротация ключей шифрования

```bash
# 1. Сгенерировать новый ключ
NEW_KEY=$(dd if=/dev/urandom bs=32 count=1 | base64)

# 2. Обновить EncryptionConfiguration
kubectl get encryption-config -o yaml > encryption-config-new.yaml
# Заменить secret в aescbc на новый ключ

# 3. Применить новую конфигурацию
kubectl apply -f encryption-config-new.yaml

# 4. Перезаписать все secrets (re-encryption)
kubectl get secrets --all-namespaces -o json | kubectl replace -f -

# 5. Сохранить новый ключ в offline vault
echo "$NEW_KEY" > /secure/etcd-key-$(date +%Y%m%d)
```

---

## Дополнительная информация

### Связанные файлы

| Файл | Содержание |
|:---|:---|
| [secrets_best_practices.md](./secrets_best_practices.md) | Управление секретами в Operator |
| [index.md](./index.md) | Обзор безопасности Prometheus Operator |
| [access_control.md](./access_control.md) | RBAC и NetworkPolicy |
| [Kubernetes/Operations/backup-strategies.md](../../../../Kubernetes/Operations/backup-strategies.md) | Общий гайд по бэкапам Kubernetes |
| [etcd/backup_strategies.md](../../../../etcd/backup_strategies.md) | Стратегии бэкапа etcd |
| [Databases/Concepts/backup_security.md](../../../../Databases/Concepts/backup_security.md) | Безопасность бэкапов (шифрование, WORM) |

### Мониторинг бэкапов

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: backup-alerts
spec:
  groups:
    - name: backup
      rules:
        - alert: VeleroBackupFailed
          expr: |
            increase(velero_backup_failure_total[1h]) > 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Velero backup завершился ошибкой"

        - alert: BackupStorageLocationUnavailable
          expr: |
            velero_backup_storage_location_last_validation_result == 0
          for: 10m
          labels:
            severity: critical
          annotations:
            summary: "Backup Storage Location недоступна"
```

### Частые ошибки на собеседованиях

1. **"etcd backup достаточно для полного восстановления"** — Нет. etcd содержит только Kubernetes объекты. TSDB данные Prometheus хранятся в PVC, которые нужно бэкапить отдельно (Velero).
2. **"EncryptionConfiguration ключ хранится в etcd"** — Нет. Ключ должен храниться OFFLINE (vault, HSM).
3. **"GitOps заменяет backup"** — GitOps хранит конфигурацию, но НЕ данные (TSDB, silences). Оба нужны.
4. **"RPO мониторинга = 0"** — Невозможно. Prometheus не реплицирует TSDB в реальном времени.
