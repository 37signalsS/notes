# Argo CD: Disaster Recovery — бэкап, восстановление и отказоустойчивость

> **Актуальность (2026):** Argo CD v3.x поддерживает экспорт/импорт состояния через `argocd admin export/import`, бэкап etcd с восстановлением контроллера, HA-режим с шардированием контроллера и multi-cluster failover. Ключевые компоненты для DR: Redis (кэш), etcd (состояние K8s), ConfigMaps/Secrets (конфигурация Argo CD), Applications/AppProjects (GitOps-состояние).

## Предварительные требования

1. **Argo CD установлен** (см. [Установка и настройка](./argocd_installation_and_setup.md)).
2. **kubectl** с доступом к кластеру.
3. **etcdctl** для работы с etcd (для полного бэкапа).
4. **argocd CLI** настроен.
5. **Доступ к Git-репозиториям** для верификации состояния.

## Определения

**Disaster Recovery (Восстановление после сбоев)** — процесс восстановления Argo CD после потери данных, сбоев инфраструктуры или катастрофических событий. Включает бэкап состояния, восстановление контроллера и проверку целостности.

**State Export (Экспорт состояния)** — команды `argocd admin export` и ручной экспорт ConfigMaps/Secrets/Applications для сохранения текущего состояния Argo CD.

**State Import (Импорт состояния)** — команды `argocd admin import` и ручной импорт сохраненных ресурсов для восстановления Argo CD.

**etcd Backup (Бэкап etcd)** —.snapshot базы данных Kubernetes etcd, содержащей все объекты кластера (включая Argo CD Resources).

**HA (High Availability)** — режим работы Argo CD с реплицированными компонентами: multiple replicas controller, repo-server, Redis Sentinel/Cluster.

**Geo-Recovery (Географическое восстановление)** — восстановление Argo CD на кластере в другом географическом регионе.

## Базовые концепции

### Что хранит Argo CD

```text
Состояние Argo CD (в Kubernetes):
├── Applications          ← GitOps-определения приложений
├── AppProjects           ← Проекты и ограничения
├── ConfigMaps            ← argocd-cm, argocd-rbac-cm, argocd-params-cm
├── Secrets               ← argocd-secret, cluster secrets, repo secrets
├── CronJobs             ← Кэширование, health checks
└── ServiceAccounts      ← Токены и учетные данные

Вне Kubernetes (вне etcd):
├── Git-репозитории       ← Источник манифестов (备份 не требуется)
├── Helm-репозитории      ← Чарты
└── Docker-образы         ← Контейнеры
```

### Стратегии бэкапа

| Стратегия | Что бэкапится | RPO* | RTO** | Сложность |
| :--- | :--- | :--- | :--- | :--- |
| **Export ConfigMaps** | argocd-cm, rbac-cm | ~0 | ~5 мин | Низкая |
| **Export Applications** | Все Application объекты | ~0 | ~5 мин | Низкая |
| **Export All** | ConfigMaps + Secrets + Apps + Projects | ~0 | ~10 мин | Средняя |
| **etcd Snapshot** | Все объекты K8s | ~1 мин | ~30 мин | Высокая |
| **HA + Geo** | Полная репликация | ~0 | ~0 | Очень высокая |

*RPO = Recovery Point Objective (потерянные данные)
**RTO = Recovery Time Objective (время восстановления)

### Архитектура DR

```text
Нормальный режим:
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  argocd     │────▶│  repo-      │────▶│  controller │
│  -server    │     │  server     │     │  (shard N)  │
└─────────────┘     └─────────────┘     └─────────────┘
       │                                      │
       ▼                                      ▼
┌─────────────┐                       ┌─────────────┐
│  Redis      │                       │  etcd       │
│  (cache)    │                       │  (state)    │
└─────────────┘                       └─────────────┘

Backup (каждые 15 минут):
┌─────────────┐     ┌─────────────┐
│  argocd     │────▶│  S3/MinIO   │
│  admin      │     │  (backup)   │
│  export     │     └─────────────┘
└─────────────┘

Disaster Recovery:
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Restore    │────▶│  argocd     │────▶│  Verify     │
│  from S3    │     │  admin      │     │  apps       │
│             │     │  import     │     │  healthy    │
└─────────────┘     └─────────────┘     └─────────────┘
```

## Практические сценарии

### Сценарий 1: Бэкап через argocd admin export

Экспорт всех Argo CD ресурсов в YAML-файлы.

**1. Экспорт Applications:**
```bash
argocd admin export applications > argocd-apps-backup.yaml
# → Файл содержит все Application объекты
```

**2. Экспорт AppProjects:**
```bash
argocd admin export appprojects > argocd-projects-backup.yaml
```

**3. Экспорт ConfigMaps:**
```bash
kubectl get configmap argocd-cm -n argocd -o yaml > argocd-cm-backup.yaml
kubectl get configmap argocd-rbac-cm -n argocd -o yaml > argocd-rbac-cm-backup.yaml
```

**4. Экспорт Secrets:**
```bash
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type -o yaml > argocd-secrets-backup.yaml
```

**5. Полный бэкап (одна команда):**
```bash
#!/bin/bash
BACKUP_DIR="/backup/argocd/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

argocd admin export applications > "$BACKUP_DIR/applications.yaml"
argocd admin export appprojects > "$BACKUP_DIR/appprojects.yaml"
kubectl get configmap argocd-cm -n argocd -o yaml > "$BACKUP_DIR/configmap-cm.yaml"
kubectl get configmap argocd-rbac-cm -n argocd -o yaml > "$BACKUP_DIR/configmap-rbac.yaml"
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type -o yaml > "$BACKUP_DIR/secrets.yaml"

echo "Backup saved to $BACKUP_DIR"
# Проверка целостности
wc -l "$BACKUP_DIR"/*.yaml
```

### Сценарий 2: Восстановление из argocd admin import

Импорт сохраненных ресурсов в Argo CD.

**1. Восстановление ConfigMaps:**
```bash
kubectl apply -f argocd-cm-backup.yaml
kubectl apply -f argocd-rbac-cm-backup.yaml
# Restart controller для применения
kubectl rollout restart deployment argocd-application-controller -n argocd
```

**2. Восстановление Secrets:**
```bash
kubectl apply -f argocd-secrets-backup.yaml
```

**3. Восстановление AppProjects (до Applications):**
```bash
argocd admin import argocd-projects-backup.yaml
# Или через kubectl
kubectl apply -f argocd-projects-backup.yaml
```

**4. Восстановление Applications:**
```bash
argocd admin import argocd-apps-backup.yaml
# Или через kubectl
kubectl apply -f argocd-apps-backup.yaml
```

**5. Валидация:**
```bash
# Проверка всех приложений
argocd app list

# Проверка здоровья
argocd app list -o json | jq '.items[] | {name: .metadata.name, health: .status.health.status, sync: .status.sync.status}'

# Проверка проектов
argocd proj list
```

### Сценарий 3: Бэкап etcd (полное кластерное восстановление)

Для полного восстановления Kubernetes кластера.

**1. Бэкап etcd:**
```bash
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-snapshot-$(date +%Y%m%d).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# Проверка
ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-snapshot-$(date +%Y%m%d).db --write-out=table
```

**2. Восстановление etcd:**
```bash
# Остановка etcd
systemctl stop etcd

# Восстановление
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-snapshot.db \
  --data-dir=/var/lib/etcd-restored \
  --name=<etcd-member-name> \
  --initial-cluster=<etcd-cluster> \
  --initial-advertise-peer-urls=<peer-urls>

# Запуск с новым data-dir
# Обновите systemd unit: --data-dir=/var/lib/etcd-restored
systemctl start etcd
```

### Сценарий 4: HA-режим и отказоустойчивость

Настройка High Availability для Argo CD.

**1. HA через Helm (рекомендуется):**
```yaml
# values.yaml
controller:
  replicas: 2
  env:
    - name: ARGOCD_CONTROLLER_SHARDING_ENABLED
      value: "true"

server:
  replicas: 2

redis:
  exporter:
    enabled: true
  # Или внешний Redis
 -ha:
    enabled: true

repoServer:
  replicas: 2
```

**2. Шардирование контроллера:**
```yaml
# argocd-cm
data:
  controller.sharding.algorithm: "round-robin"
```

**3. Внешний Redis (для HA):**
```bash
# Установка Redis Sentinel
helm install redis-sentinel bitnami/redis-sentinel \
  --set sentinel.enabled=true \
  --set architecture=replication
```

### Сценарий 5: Geo-Recovery (восстановление в другом регионе)

Восстановление Argo CD на кластере в другом регионе.

**1. Подготовка:**
```bash
# На основном кластере — экспорт
argocd admin export applications > apps-backup.yaml
argocd admin export appprojects > projects-backup.yaml

# Копирование в S3/MinIO
aws s3 cp apps-backup.yaml s3://dr-backup/argocd/
aws s3 cp projects-backup.yaml s3://dr-backup/argocd/
```

**2. Восстановление на DR-кластере:**
```bash
# Установка Argo CD на DR-кластере
helm install argocd argo/argo-cd -n argocd --create-namespace

# Ожидание готовности
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-application-controller -n argocd --timeout=300s

# Скачивание бэкапа
aws s3 cp s3://dr-backup/argocd/apps-backup.yaml .
aws s3 cp s3://dr-backup/argocd/projects-backup.yaml .

# Импорт
argocd admin import projects-backup.yaml
argocd admin import apps-backup.yaml
```

**3. Валидация:**
```bash
# Проверка connectivity к кластерам
argocd cluster list

# Проверка здоровья приложений
argocd app list -o json | jq '.[] | select(.status.health.status != "Healthy") | .metadata.name'
```

### Сценарий 6: Автоматический бэкап через CronJob

Автоматический бэкап каждые 15 минут.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: argocd-backup
  namespace: argocd
spec:
  schedule: "*/15 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: argocd-backup
          containers:
            - name: backup
              image: bitnami/kubectl:latest
              command:
                - /bin/bash
                - -c
                - |
                  BACKUP_DIR="/backup/$(date +%Y%m%d-%H%M%S)"
                  mkdir -p "$BACKUP_DIR"
                  argocd admin export applications > "$BACKUP_DIR/apps.yaml"
                  argocd admin export appprojects > "$BACKUP_DIR/projects.yaml"
                  kubectl get configmap argocd-cm argocd-rbac-cm -n argocd -o yaml > "$BACKUP_DIR/configmaps.yaml"
                  kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type -o yaml > "$BACKUP_DIR/secrets.yaml"
                  
                  # Удаление бэкапов старше 7 дней
                  find /backup -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;
              volumeMounts:
                - name: backup
                  mountPath: /backup
          volumes:
            - name: backup
              persistentVolumeClaim:
                claimName: argocd-backup-pvc
          restartPolicy: OnFailure
```

## Диагностика

### Базовые команды

```bash
# Проверка версии Argo CD
argocd version

# Просмотр состояния компонентов
kubectl get pods -n argocd

# Проверка etcd (на control plane нодах)
ETCDCTL_API=3 etcdctl endpoint health --endpoints=https://127.0.0.1:2379

# Просмотр log'ов controller
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=50

# Проверка Redis
kubectl exec -it -n argocd deployment/argocd-redis -- redis-cli ping
```

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `applications not restored` | Applications не были экспортированы | Проверьте бэкап перед удалением |
| `project not found` | AppProject не импортирован перед Application | Импортируйте проекты сначала |
| `cluster secret missing` | Secret кластера не восстановлен | Восстановите все Secrets |
| `RBAC denied` | argocd-rbac-cm не восстановлен | Восстановите RBAC конфигурацию |

## Лучшие практики

- **Автоматический бэкап:** Настройте CronJob для бэкапа каждые 15 минут.
- **Хранение бэкапов:** Используйте S3/MinIO с versioning и lifecycle policies.
- **Тестирование восстановления:** Регулярно проверяйте восстановление на test-кластере.
- **AppProjects перед Applications:** Всегда импортируйте проекты до приложений.
- **Версионирование Git:** Храните argocd-cm, argocd-rbac-cm в Git (Dogfooding).
- **Мониторинг etcd:** Отслеживайте размер etcd и производите compaction.

## Ограничения и edge cases

### Ограничения

- **argocd admin export не экспортирует Secrets по умолчанию:** Используйте kubectl для Secrets.
- **etcd snapshot требует доступа к control plane:** Не доступен в managed Kubernetes (EKS, GKE, AKS).
- **Нет встроенного incremental backup:** Каждый бэкап полный.

### Edge Cases

- **Восстановление после удаления namespace:** Если namespace `argocd` удален — восстановите через etcd или переустановите.
- **Версионная несовместимость:** Не импортируйте бэкапы из более новой версии Argo CD.
- **HA + Sharding:** При шардировании контроллера каждый shard бэкапируется отдельно.
- **Внешний Redis:** При потере Redis — Argo CD восстанавливает кэш из Git (занимает время).

## Дополнительная информация

### См. также

- [Установка и настройка HA](./argocd_installation_and_setup.md#сценарий-7-шардирование-контроллера)
- [RBAC](./argocd_rbac_deep.md)
- [AppProject](./argocd_appproject_deep.md)
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Мультитенантность](./argocd_multi_tenancy.md) — Паттерны мультитенантности, tenant isolation, project-per-team.
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — Multiple Sources, sourceHydrator, Helm+Git, CI-рендеринг vs Multi-Source.

### Ссылки

- [Disaster Recovery Guide](https://argo-cd.readthedocs.io/en/stable/operator-manual/disaster_recovery/)
- [Backup and Restore](https://argo-cd.readthedocs.io/en/stable/operator-manual/backup-restore/)
- [HA Architecture](https://argo-cd.readthedocs.io/en/stable/operator-manual/ha/)
