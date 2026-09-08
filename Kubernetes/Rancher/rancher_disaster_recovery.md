# Disaster Recovery в Rancher

## Определения

**Disaster Recovery (DR)** — комплекс мер по восстановлению инфраструктуры Rancher после катастрофических сбоев (потеря Management-кластера, повреждение etcd, потеря всех узлов control plane).

**RTO (Recovery Time Objective)** — максимально допустимое время восстановления Rancher Server до рабочего состояния. Для Rancher рекомендуется RTO ≤ 1 часа.

**RPO (Recovery Point Objective)** — максимально допустимый объем потери данных. Для Rancher RPO определяется интервалом создания снимков etcd и rancher-backup.

**rancher-backup** — официальный пакет для резервного копирования Management-кластера (на базе Velero). Создает снимок etcd + ресурсы Rancher в совместимое хранилище (S3, локальная папка).

**etcd Snapshot** — снимок базы данных etcd, содержащий все объекты Kubernetes (Deployments, Services, Secrets, CRD Rancher). Основной механизм восстановления состояния кластера.

## Базовые концепции

### Два уровня резервного копирования

| Уровень | Что сохраняется | Инструмент | Интервал |
| :--- | :--- | :--- | :--- |
| **Management Cluster (Rancher Server)** | etcd + ресурсы Rancher (GitRepo, ClusterGroup, RoleTemplates) | `rancher-backup` (Velero) | Ежедневно |
| **Downstream Clusters** | etcd + прикладные ресурсы | Встроенные снимки etcd RKE2 | Ежедневно/по расписанию |

**Ключевой принцип:** Rancher Server — это Management Plane. Его потеря означает потерю UI, API, аутентификации и управления всеми downstream-кластерами. Самые downstream-кластеры продолжают работать автономно, но управлять ими становится невозможно.

### Механизм rancher-backup

`rancher-backup` работает на основе Velero и создает три типа артефактов:

1. **Снимок etcd Management-кластера** — полная копия базы данных.
2. **Ресурсы Rancher** — CRD и их экземпляры (clusters, projects, roletemplates, fleet gitrepos).
3. **PV (Persistent Volumes)** — если Rancher Server хранит данные в PV (например, для integrated authentication).

### Типичные сценарии DR

| Сценарий | RTO | RPO | Сложность |
| :--- | :--- | :--- | :--- |
| Потеря одного Master-узла | Автоматическое восстановление (etcd quorum) | 0 | Низкая |
| Потеря двух Master-узлов ( quorum loss) | 30–60 мин (восстановление из снимка) | Интервал снимка | Средняя |
| Потеря всех Master-узлов | 1–2 ч (восстановление из S3) | Интервал снимка | Высокая |
| Потеря Management-кластера целиком | 2–4 ч (пересоздание + восстановление) | Интервал rancher-backup | Очень высокая |

## Практические сценарии

### Шаг 1: Настройка rancher-backup

```bash
# Установка rancher-backup через Apps & Marketplace
# Или через Helm:
helm repo add rancher-charts https://releases.rancher.com/server-charts/latest
helm install rancher-backup rancher-charts/rancher-backup \
  --namespace cattle-resources-system \
  --create-namespace \
  --set persistence.enabled=true \
  --set persistence.size=10Gi \
  --set persistence.storageClassName=standard
```

### Шаг 2: Создание Backup CR

```yaml
apiVersion: resources.cattle.io/v1
kind: Backup
metadata:
  name: daily-rancher-backup
  namespace: cattle-resources-system
spec:
  resourceSetName: rancher-resource-set
  storageLocationName: s3-backup
  schedule: "0 2 * * *"       # ежедневно в 02:00
  retentionCount: 7            # хранить 7 последних копий
---
apiVersion: resources.cattle.io/v1
kind: Backup
metadata:
  name: weekly-rancher-backup
  namespace: cattle-resources-system
spec:
  resourceSetName: rancher-resource-set
  storageLocationName: s3-backup
  schedule: "0 3 * * 0"       # еженедельно в воскресенье в 03:00
  retentionCount: 4            # хранить 4 недельных копии
```

### Шаг 3: Настройка S3-хранилища

```yaml
apiVersion: resources.cattle.io/v1
kind: BackupStorageLocation
metadata:
  name: s3-backup
  namespace: cattle-resources-system
spec:
  s3:
    credentialSecretName: s3-creds
    region: eu-west-1
    bucket: rancher-backups
    endpoint: s3.amazonaws.com    # или MinIO/compatible
  backupStorageLocationConfig:
    resourceSet: rancher-resource-set
---
apiVersion: v1
kind: Secret
metadata:
  name: s3-creds
  namespace: cattle-resources-system
type: Opaque
stringData:
  access-key: "AKIAIOSFODNN7EXAMPLE"
  secret-key: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
```

### Шаг 4: Проверка бэкапов

```bash
# Просмотр созданых бэкапов
kubectl get backups -n cattle-resources-system
# → daily-rancher-backup      Completed
# → weekly-rancher-backup     Completed

# Просмотр деталей
kubectl describe backup daily-rancher-backup -n cattle-resources-system

# Проверка в UI: Cluster Management → Backups
```

### Шаг 5: Восстановление из бэкапа (Restore)

**Сценарий: Management-кластер работает, но Rancher Server в坏状态:**

```yaml
apiVersion: resources.cattle.io/v1
kind: Restore
metadata:
  name: rancher-restore
  namespace: cattle-resources-system
spec:
  backupFilename: daily-rancher-backup-xxxxx   # имя файла из Backup
  storageLocationName: s3-backup
```

```bash
# Применение Restore
kubectl apply -f restore.yaml

# Мониторинг
kubectl get restore -n cattle-resources-system
# → rancher-restore    Completed

# Проверка Rancher Server
kubectl -n cattle-system get pods
# → rancher-...   3/3   Running
```

**Сценарий: Полная потеря Management-кластера:**

1. Разверните новый Management-кластер (RKE2, 3 Master-узла + LB).
2. Установите Rancher Server (helm install rancher).
3. Установите rancher-backup.
4. Настройте BackupStorageLocation (S3).
5. Создайте Restore CR, указав `backupFilename` нужного снимка.

### Шаг 6: Восстановление downstream-кластера

Для downstream-кластеров используется встроенный механизм RKE2:

```bash
# На узле etcd downstream-кластера
sudo rke2 etcd-snapshot list        # просмотр доступных снимков

# Восстановление
sudo rke2 etcd-snapshot restore --name backup-2026-08-29
sudo systemctl restart rke2-server
```

### Шаг 7: Тестирование DR (Drill)

Регулярно выполняйте проверку восстановимости:

```bash
# 1. Создайте тестовый Backup
kubectl apply -f - <<EOF
apiVersion: resources.cattle.io/v1
kind: Backup
metadata:
  name: dr-test-backup
  namespace: cattle-resources-system
spec:
  resourceSetName: rancher-resource-set
  storageLocationName: s3-backup
EOF

# 2. Дождитесь завершения
kubectl get backup dr-test-backup -n cattle-resources-system -w

# 3. Восстановите в изолированном кластере
kubectl apply -f - <<EOF
apiVersion: resources.cattle.io/v1
kind: Restore
metadata:
  name: dr-test-restore
  namespace: cattle-resources-system
spec:
  backupFilename: dr-test-backup-xxxxx
  storageLocationName: s3-backup
EOF

# 4. Проверьте работоспособность Rancher
kubectl -n cattle-system get pods
curl -k https://rancher-test.example.com/v3
```

### Шаг 8: План действий при DR

| Шаг | Действие | Время |
| :--- | :--- | :--- |
| 1 | Оценка ущерба (что потеряно: Management, downstream, оба?) | 5 мин |
| 2 | Если downstream работает — переключиться на прямой доступ (ACE) | 5 мин |
| 3 | Если Management потерян — развернуть новый Management-кластер | 30–60 мин |
| 4 | Установить Rancher + rancher-backup | 15 мин |
| 5 | Восстановить из S3-backup | 15–30 мин |
| 6 | Проверить подключение downstream-кластеров | 10 мин |
| 7 | Проверить работоспособность UI и API | 5 мин |
| **Итого** | | **1.5–2.5 ч** |

## Диагностика и устранение неполадок

### Backup не создается

```bash
# Проверка подов rancher-backup
kubectl -n cattle-resources-system get pods
# → rancher-backup-...   Running

# Логи оператора
kubectl -n cattle-resources-system logs -l app=rancher-backup --tail=100

# Проверка BackupStorageLocation
kubectl get backupstoragelocation -n cattle-resources-system
# → s3-backup    Available
```

**Типичные причины:**
- Неверные credentials для S3 (проверьте Secret `s3-creds`).
- Bucket недоступен (проверьте сетевую доступность).
- Нехватка прав IAM (требуется `s3:PutObject`, `s3:GetObject`, `s3:ListBucket`).

### Restore завершается ошибкой

```bash
# Детали ошибки
kubectl describe restore <name> -n cattle-resources-system

# Проверка backup-файла
kubectl get backup <name> -n cattle-resources-system -o yaml
```

**Типичные причины:**
- Backup-файл поврежден (проверьте целостность в S3).
- Версия Rancher несовместима с версией backup (.restore только с той же minor-версии).
- Нехватка дискового пространства для восстановления.

### Downstream-кластер не подключается после восстановления

```bash
# Проверка cattle-cluster-agent
kubectl -n cattle-system get pods -l app=cattle-cluster-agent
# → если CrashLoopBackOff — проверьте логи

# Проверка туннеля
kubectl -n cattle-system logs -l app=cattle-cluster-agent -c cluster-register --tail=50
```

**Решение:** возможно, токен кластера изменился. Переустановите cattle-cluster-agent в downstream-кластере.

## Дополнительная информация

### Рекомендации по DR

1. **Автоматизация:** настройте ежедневные Backup CR с расписанием и retentionCount.
2. **S3-хранилище:** всегда используйте S3 (или compatible) вместо локальных снимков — локальные снимки не защищают от потери узла.
3. **Регулярные drill:** выполняйте тестовое восстановление не реже 1 раза в квартал.
4. **Документация:** храните инструкцию по восстановлению в safely accessible месте (вне Rancher).
5. **Мониторинг:** настройте алертинг на `BackupReady=False` и `RestoreReady=False`.

### Связанные темы

- [Установка Rancher Server](./rancher_installation.md) — HA-установка и backup.
- [RKE: Снимки etcd](./rancher_rke.md) — управление снимками downstream-кластеров.
- [Backup-стратегии Kubernetes](../Operations/backup-strategies.md) — общие принципы.
- [Обслуживание узлов](../Operations/node_maintenance.md) — drain/cordon.

**Внешние ресурсы:**

- [Rancher Backup Documentation](https://ranchermanager.docs.rancher.com/how-to-guides/new-user-guides/backup-restore-and-disaster-recovery)
- [Velero Documentation](https://velero.io/docs/)
