# Backup и восстановление стека LGTM

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**
> - **[Backup и восстановление](./lgtm_backup_disaster_recovery.md)** (текущий)

---

## Определения

**RPO (Recovery Point Objective)** — максимально допустимая потеря данных. Определяет, насколько свежими должны быть данные после восстановления. Например, RPO = 1 час означает, что при восстановлении данные могут быть потеряны за последний час.

**RTO (Recovery Time Objective)** — максимально допустимое время восстановления сервиса. Определяет, сколько времени система может быть недоступна после сбоя.

**Backup (резервное копирование)** — создание копии данных для восстановления в случае повреждения или потери.

**Disaster Recovery (восстановление после сбоев)** — набор процедур и инструментов для восстановления работоспособности системы после катастрофических сбоев.

**Snapshot (снимок)** — мгновенная копия состояния системы или данных в определенный момент времени.

---

## Основные концепции

### Стратегия backup для стека LGTM

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                        Backup Strategy for LGTM                         │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Prometheus                                      │  │
│  │  • TSDB snapshots (встроенный механизм)                           │  │
│  │  • Remote Write в.external storage (S3, Thanos)                   │  │
│  │  • Backup правил и конфигурации                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Loki                                            │  │
│  │  • Объектное хранилище (S3/GCS) - естественная избыточность       │  │
│  │  • Backup индексов (TSDB)                                         │  │
│  │  • Репликация через replication_factor                            │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Tempo                                           │  │
│  │  • Объектное хранилище (S3/GCS) - естественная избыточность       │  │
│  │  • Backup блоков (Parquet)                                        │  │
│  │  • Репликация через replication_factor                            │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Grafana                                         │  │
│  │  • Backup базы данных (PostgreSQL/MySQL)                          │  │
│  │  • Экспорт дашбордов и алертов                                    │  │
│  │  • Backup конфигурации (grafana.ini)                              │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Конфигурация                                    │  │
│  │  • Helm values.yaml в Git                                         │  │
│  │  • ConfigMaps и Secrets                                           │  │
│  │  • Kubernetes манифесты                                           │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Ключевые принципы

| Принцип | Описание | Рекомендация |
| :--- | :--- | :--- |
| **3-2-1 правило** | 3 копии данных, 2 разных типа носителей, 1 вне сайта | S3 + локальный диск + архив |
| **Регулярность** | Частота backup зависит от RPO | Ежедневные для критичных данных |
| **Тестирование** | Проверка восстановления из backup | Ежеквартальные тесты |
| **Шифрование** | Защита backup от несанкционированного доступа | Шифрование в покое и при передаче |
| **Документация** | Пошаговые инструкции по восстановлению | Runbooks для каждого компонента |

---

## Практические сценарии

### Сценарий 1: Backup Prometheus

**Цель:** Создание резервных копий метрик и конфигурации Prometheus.

#### Шаг 1: Настройка TSDB snapshots

```bash
# Создание снимка TSDB
kubectl exec -n monitoring prometheus-prometheus-kube-prometheus-prometheus-0 -- \
  wget -qO- http://localhost:9090/api/v1/admin/tsdb/snapshot
# → Expected: {"status":"success","data":{"name":"20260909T120000Z"}}

# Проверка создания снимка
kubectl exec -n monitoring prometheus-prometheus-kube-prometheus-prometheus-0 -- \
  ls -la /prometheus/snapshots/
# → Expected: директория с именем снимка
```

#### Шаг 2: Копирование снимка в внешнее хранилище

```bash
# Создание Job для копирования снимка в S3
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: prometheus-backup
  namespace: monitoring
spec:
  template:
    spec:
      containers:
        - name: backup
          image: amazon/aws-cli:latest
          command:
            - /bin/sh
            - -c
            - |
              # Копирование снимка в S3
              aws s3 cp /prometheus/snapshots/ s3://lgmt-backups/prometheus/snapshots/ --recursive
              # Очистка старых снимков (оставляем последние 7)
              aws s3 ls s3://lgmt-backups/prometheus/snapshots/ | sort | head -n -7 | awk '{print $NF}' | xargs -I {} aws s3 rm s3://lgmt-backups/prometheus/snapshots/{}
          volumeMounts:
            - name: prometheus-data
              mountPath: /prometheus
              readOnly: true
            - name: aws-credentials
              mountPath: /root/.aws
              readOnly: true
      volumes:
        - name: prometheus-data
          persistentVolumeClaim:
            claimName: prometheus-prometheus-kube-prometheus-prometheus-db-prometheus-prometheus-kube-prometheus-prometheus-0
        - name: aws-credentials
          secret:
            secretName: aws-credentials
      restartPolicy: Never
EOF
```

#### Шаг 3: Backup конфигурации

```bash
# Экспорт правил алертинга
kubectl get prometheusrule -A -o yaml > prometheusrules-backup.yaml

# Экспорт ServiceMonitor
kubectl get servicemonitor -A -o yaml > servicemonitors-backup.yaml

# Экспорт ConfigMap с конфигурацией Prometheus
kubectl get configmap -n monitoring prometheus-prometheus-kube-prometheus-prometheus -o yaml > prometheus-config-backup.yaml
```

---

### Сценарий 2: Backup Loki

**Цель:** Создание резервных копий логов и индексов Loki.

#### Шаг 1: Понимание архитектуры хранения Loki

Loki хранит данные в объектном хранилище (S3/GCS) в двух типах:
- **Chunks:** Сжатые блоки логов
- **Index:** Индекс TSDB для поиска по меткам

> **Примечание:** При использовании объектного хранилища (S3/GCS) данные автоматически реплицируются. Backup должен фокусироваться на индексах и конфигурации.

#### Шаг 2: Backup индексов Loki

```bash
# Создание Job для backup индексов
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: loki-index-backup
  namespace: loki
spec:
  template:
    spec:
      containers:
        - name: backup
          image: amazon/aws-cli:latest
          command:
            - /bin/sh
            - -c
            - |
              # Backup индексов Loki из S3
              aws s3 sync s3://loki-bucket/index/ s3://lgmt-backups/loki/index/
              # Backup чанков (опционально, если нужно полное восстановление)
              aws s3 sync s3://loki-bucket/chunks/ s3://lgmt-backups/loki/chunks/
          env:
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: aws-credentials
                  key: access-key-id
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: aws-credentials
                  key: secret-access-key
      restartPolicy: Never
EOF
```

#### Шаг 3: Backup конфигурации Loki

```bash
# Экспорт ConfigMap с конфигурацией Loki
kubectl get configmap -n loki loki -o yaml > loki-config-backup.yaml

# Экспорт Secret с credentials
kubectl get secret -n loki -o yaml > loki-secrets-backup.yaml

# Экспорт Helm values
helm get values loki -n loki -o yaml > loki-values-backup.yaml
```

---

### Сценарий 3: Backup Tempo

**Цель:** Создание резервных копий трассировок и конфигурации Tempo.

#### Шаг 1: Backup трассировок Tempo

```bash
# Создание Job для backup трассировок
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: tempo-backup
  namespace: tempo
spec:
  template:
    spec:
      containers:
        - name: backup
          image: amazon/aws-cli:latest
          command:
            - /bin/sh
            - -c
            - |
              # Backup блоков Tempo из S3
              aws s3 sync s3://tempo-bucket/blocks/ s3://lgmt-backups/tempo/blocks/
              # Backup индексов
              aws s3 sync s3://tempo-bucket/index/ s3://lgmt-backups/tempo/index/
          env:
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: aws-credentials
                  key: access-key-id
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: aws-credentials
                  key: secret-access-key
      restartPolicy: Never
EOF
```

#### Шаг 2: Backup конфигурации Tempo

```bash
# Экспорт ConfigMap с конфигурацией Tempo
kubectl get configmap -n tempo tempo -o yaml > tempo-config-backup.yaml

# Экспорт Helm values
helm get values tempo -n tempo -o yaml > tempo-values-backup.yaml
```

---

### Сценарий 4: Backup Grafana

**Цель:** Создание резервных копий дашбордов, алертов и конфигурации Grafana.

#### Шаг 1: Экспорт дашбордов через API

```bash
#!/bin/bash
# Экспорт всех дашбордов
GRAFANA_URL="https://grafana.example.internal"
API_KEY="<your-api-key>"

# Получение списка дашбордов
DASHBOARDS=$(curl -s -H "Authorization: Bearer $API_KEY" \
  "$GRAFANA_URL/api/search?type=dash-db" | jq -r '.[].uid')

# Экспорт каждого дашборда
for DASHBOARD_UID in $DASHBOARDS; do
  curl -s -H "Authorization: Bearer $API_KEY" \
    "$GRAFANA_URL/api/dashboards/uid/$DASHBOARD_UID" | \
    jq -r '.dashboard' > "dashboard-$DASHBOARD_UID.json"
done
```

#### Шаг 2: Экспорт алертов

```bash
# Экспорт правил алертинга
curl -s -H "Authorization: Bearer $API_KEY" \
  "$GRAFANA_URL/api/v1/provisioning/alert-rules" > grafana-alert-rules-backup.yaml

# Экспорт contact points
curl -s -H "Authorization: Bearer $API_KEY" \
  "$GRAFANA_URL/api/v1/provisioning/contact-points" > grafana-contact-points-backup.yaml

# Экспорт notification policies
curl -s -H "Authorization: Bearer $API_KEY" \
  "$GRAFANA_URL/api/v1/provisioning/policies" > grafana-notification-policies-backup.yaml
```

#### Шаг 3: Backup базы данных Grafana

```bash
# Для PostgreSQL
kubectl exec -n monitoring grafana-postgresql-0 -- \
  pg_dump -U grafana grafana > grafana-db-backup.sql

# Для MySQL
kubectl exec -n monitoring grafana-mysql-0 -- \
  mysqldump -u grafana -p grafana > grafana-db-backup.sql
```

#### Шаг 4: Backup конфигурации

```bash
# Экспорт grafana.ini
kubectl get configmap -n monitoring grafana -o yaml > grafana-config-backup.yaml

# Экспорт Helm values
helm get values grafana -n monitoring -o yaml > grafana-values-backup.yaml
```

---

### Сценарий 5: Автоматизация backup

**Цель:** Настройка регулярных автоматических backup.

#### Шаг 1: Создание CronJob для Prometheus

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: prometheus-backup
  namespace: monitoring
spec:
  schedule: "0 2 * * *"  # Ежедневно в 2:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: prom/prometheus:latest
              command:
                - /bin/sh
                - -c
                - |
                  # Создание снимка
                  wget -qO- http://prometheus-operated:9090/api/v1/admin/tsdb/snapshot
                  # Копирование в S3
                  aws s3 sync /prometheus/snapshots/ s3://lgmt-backups/prometheus/snapshots/
          volumes:
            - name: prometheus-data
              persistentVolumeClaim:
                claimName: prometheus-prometheus-kube-prometheus-prometheus-db-prometheus-prometheus-kube-prometheus-prometheus-0
          restartPolicy: OnFailure
```

#### Шаг 2: Создание CronJob для Loki

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: loki-backup
  namespace: loki
spec:
  schedule: "0 3 * * *"  # Ежедневно в 3:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: amazon/aws-cli:latest
              command:
                - /bin/sh
                - -c
                - |
                  aws s3 sync s3://loki-bucket/index/ s3://lgmt-backups/loki/index/
          restartPolicy: OnFailure
```

#### Шаг 3: Создание CronJob для Grafana

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: grafana-backup
  namespace: monitoring
spec:
  schedule: "0 4 * * *"  # Ежедневно в 4:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: postgres:15
              command:
                - /bin/sh
                - -c
                - |
                  PGPASSWORD=$POSTGRES_PASSWORD pg_dump -U grafana grafana > /backup/grafana-$(date +%Y%m%d).sql
                  aws s3 cp /backup/grafana-$(date +%Y%m%d).sql s3://lgmt-backups/grafana/
              env:
                - name: POSTGRES_PASSWORD
                  valueFrom:
                    secretKeyRef:
                      name: grafana-postgresql
                      key: postgres-password
          volumes:
            - name: backup
              emptyDir: {}
          restartPolicy: OnFailure
```

---

### Сценарий 6: Восстановление Prometheus

**Цель:** Восстановление метрик из снимка TSDB.

#### Шаг 1: Восстановление из снимка

```bash
# Копирование снимка из S3
kubectl exec -n monitoring prometheus-prometheus-kube-prometheus-prometheus-0 -- \
  aws s3 sync s3://lgmt-backups/prometheus/snapshots/ /prometheus/snapshots/

# Восстановление снимка через API
kubectl exec -n monitoring prometheus-prometheus-kube-prometheus-prometheus-0 -- \
  wget -qO- --post-data='{"dir": "/prometheus/snapshots/20260909T120000Z"}' \
  http://localhost:9090/api/v1/admin/tsdb/snapshot
```

#### Шаг 2: Проверка восстановления

```bash
# Проверка доступных метрик
curl -s 'http://localhost:9090/api/v1/label/__name__/values' | jq '.data | length'
# → Expected: количество метрик > 0
```

---

### Сценарий 7: Восстановление Grafana

**Цель:** Восстановление дашбордов и конфигурации Grafana.

#### Шаг 1: Восстановление базы данных

```bash
# Восстановление PostgreSQL
kubectl exec -n monitoring grafana-postgresql-0 -- \
  psql -U grafana grafana < grafana-db-backup.sql
```

#### Шаг 2: Восстановление дашбордов

```bash
#!/bin/bash
# Импорт дашбордов
for file in dashboard-*.json; do
  curl -s -X POST -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d @"$file" \
    "$GRAFANA_URL/api/dashboards/db"
done
```

---

## Дополнительная информация

### Чек-лист backup

| Компонент | Что бэкапить | Частота | Хранение |
| :--- | :--- | :--- | :--- |
| **Prometheus** | TSDB snapshots, правила, конфигурация | Ежедневно | 30 дней |
| **Loki** | Индексы, конфигурация | Ежедневно | 30 дней |
| **Tempo** | Блоки, индексы, конфигурация | Ежедневно | 30 дней |
| **Grafana** | База данных, дашборды, алерты | Ежедневно | 30 дней |
| **Конфигурация** | Helm values, манифесты | При изменениях | Бессрочно |

### Связанные материалы

- **[Grafana: Backup и восстановление](../../../Grafana/grafana_backup_restore.md)** — детальные инструкции для Grafana
- **[Prometheus: Конфигурация](../../../Prometheus/configuration.md)** — настройка retention и storage
- **[Loki: Архитектура](../../../Loki/loki_overview.md)** — детали хранения данных

---

**Навигация по руководству:**

- **[Production Hardening](./lgtm_production_hardening.md)** (назад)
- **[CI/CD интеграция](./lgtm_cicd_gitops_integration.md)** (вперед)
