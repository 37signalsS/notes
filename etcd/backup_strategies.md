# Стратегии резервного копирования etcd

**etcd** — единственный источник истины для Kubernetes. Потеря данных без бэкапа означает потерю всего состояния кластера. Данный документ описывает стратегии, trade-offs и практические сценарии бэкапа.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Snapshot** | Полный снимок состояния BoltDB на конкретной ревизии. Онлайн-операция (`etcdctl snapshot save`). |
| **Logical Backup** | Выгрузка всех ключей через `etcdctl get --prefix --keys-only`. Замедляет кластер при больших объемах. |
| **Incremental Backup** | Резервное копирование только изменений с момента последнего снапшота (через WAL). |
| **Offline Backup** | Резервное копирование при остановленном etcd. Гарантирует целостность, но требует даунтайма. |
| **Online Backup** | Резервное копирование работающего кластера. Минимальный даунтайм (0), но возможна неконсистентность при active writes. |
| **Restore Drill** | Регулярное упражнение по восстановлению из снапшота в изолированной среде. |

---

## Основные концепции

### Snapshot vs Logical Backup

| Критерий | Snapshot | Logical Backup (`etcdctl get`) |
| :--- | :--- | :--- |
| **Скорость** | Быстро (копирует файл) | Медленно (вызывает gRPC Range запрос) |
| **Влияние на кластер** | Минимальное (чтение на уровне ОС) | Высокое (нагружает etcd и сеть) |
| **Целостность** | Полная (все данные, включая метаданные) | Частичная (только ключи/значения, нет внутренних метаданных) |
| **Размер** | Размер файла BoltDB | Обычно меньше (только user keys) |
| **Восстановление** | Быстрое (offline restore) | Медленное (bulk import через `etcdctl put`) |

**Рекомендация:** Используйте snapshot для production. Logical backup — только для миграции данных или аудита.

### Ограничения snapshot

- **Версионность:** Восстановить можно только на версию `>=` версии создания. Downgrade невозможен.
- **Архитектура:** Снапшот несовместим между архитектурами (amd64 → arm64).
- **Cluster Token:** При восстановлении используйте уникальный `--initial-cluster-token`, иначе кластер может "слиться" с существующим.
- **Размер:** При > 8 ГБ snapshot становится нестабильным. В этом случае используйте external etcd или разделите кластер.

### Incremental Backup (v3.5+)

etcd 3.5+ поддерживает инкрементальное резервное копирование через WAL:

```bash
# Сохранить текущий снапшот (база для incremental)
etcdctl snapshot save base.db

# Сохранить изменения (incremental)
etcdctl snapshot save incremental.db --delta-from=base.db
```

**Trade-offs:**
- **Плюс:** Меньший размер, быстрее.
- **Минус:** Для восстановления нужна цепочка снапшотов. Сложнее управлять.

### Encryption at Rest для бэкапов

Снапшоты содержат ВСЕ данные (включая секреты) в открытом виде (если не включено encryption at Rest).
- **Политика:** Шифруйте снапшоты перед отправкой в S3/offsite.
- **Инструменты:** `openssl enc -aes-256-cbc -in snapshot.db -out snapshot.db.enc`.

---

## Практические сценарии

### Стратегия бэкапа для production K8s (2026)

| Тип | Частота | Хранение | Срок |
| :--- | :--- | :--- | :--- |
| **Snapshot** | Каждые 15 минут | Локально + S3 (с версионированием) | 7 дней |
| **Logical Backup** | Раз в день | S3 (отдельный bucket) | 30 дней |
| **Offsite Copy** | Раз в день | Другой регион / облако | 90 дней |

**Автоматизация (Kubernetes CronJob):**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-backup
  namespace: kube-system
spec:
  schedule: "*/15 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          hostNetwork: true
          containers:
          - name: etcd-backup
            image: bitnami/etcd:3.7.1
            command:
            - /bin/sh
            - -c
            - |
              DATE=$(date +%Y%m%d%H%M%S)
              etcdctl --endpoints=https://127.0.0.1:2379 \
                --cacert=/etc/kubernetes/pki/etcd/ca.crt \
                --cert=/etc/kubernetes/pki/etcd/server.crt \
                --key=/etc/kubernetes/pki/etcd/server.key \
                snapshot save /backup/etcd-snapshot-${DATE}.db
              aws s3 cp /backup/etcd-snapshot-${DATE}.db s3://my-backups/etcd/
            volumeMounts:
            - name: etcd-pki
              mountPath: /etc/kubernetes/pki/etcd
              readOnly: true
            - name: backup-storage
              mountPath: /backup
          volumes:
          - name: etcd-pki
            hostPath:
              path: /etc/kubernetes/pki/etcd
          - name: backup-storage
            hostPath:
              path: /var/lib/etcd-backup
          restartPolicy: OnFailure
```

### Валидация снапшота

```bash
# Проверка статуса
etcdutl snapshot status /backup/etcd-snapshot.db -w table
# → Hash: 1a2b3c4d, Revision: 512340, Total key count: 1254300

# Верификация
etcdutl snapshot verify /backup/etcd-snapshot.db
# → snapshot verify passed, revision: 512340

# Проверка размера
ls -lh /backup/etcd-snapshot.db
# → 1.2G
```

### Восстановление из снапшота (Disaster Recovery)

```bash
# 1. Остановить etcd на всех узлах
systemctl stop etcd

# 2. Восстановить snapshot
etcdutl snapshot restore /backup/etcd-snapshot.db \
  --name node1 \
  --initial-cluster node1=https://10.0.1.10:2380,node2=...,node3=... \
  --initial-cluster-token restored-cluster \
  --data-dir /var/lib/etcd-restored

# 3. Заменить data-dir
mv /var/lib/etcd /var/lib/etcd-old
mv /var/lib/etcd-restored /var/lib/etcd

# 4. Запустить etcd
systemctl start etcd

# 5. Валидация
etcdctl endpoint health --cluster
etcdctl get --prefix --keys-only | wc -l
```

### Logical backup для миграции данных

```bash
# Выгрузка всех ключей (медленно!)
etcdctl get --prefix --keys-only / > all_keys.txt

# Восстановление
cat all_keys.txt | while read key; do
  value=$(etcdctl get "$key" --print-value-only)
  etcdctl put "$key" "$value"
done
```

**Warning:** Logical backup не восстанавливает leases, alarms, внутренние метаданные. Используйте только для user data.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `snapshot verify failed` | Файл поврежден (сетевая ошибка, диск) | Использовать предыдущий снапшот; проверить `etcdutl wal verify` |
| `data-dir already exists` | Директория не пуста при restore | Удалить или использовать новую директорию |
| Snapshot > 8 ГБ | БД превысила стабильный лимит bbolt | Использовать external etcd или разделить кластер |
| Restore на другую архитектуру | Снапшот amd64, целевой arm64 | Логический backup через `etcdctl get` |
| Snapshot старше compaction | Снапшот содержит старые ревизии, но это нормально | Проверить `revision` в снапшоте; убедиться, что он >= compacted revision |

---

## Best Practices

- **Restore Drill каждые квартал:** Бэкап без тестирования восстановления — не бэкап.
- **S3 с версионированием:** Защита от случайного удаления (ransomware).
- **Offsite copy:** Храните копию в другом регионе/облаке.
- **Шифруйте снапшоты:** Перед отправкой в S3 шифруйте (AES-256 или KMS).
- **Не храните бэкапы на том же диске, что и data-dir:** При отказе диска вы потеряете и данные, и бэкап.
- **Логический бэкап для критичных ключей:** `/k8s` prefix можно выгружать отдельно для быстрого восстановления.

---

## Edge Cases

- **Снапшот во время compaction:** Snapshot стабилен (copy-on-write в bbolt). Compaction не влияет на уже созданный снапшот.
- **Снапшот во время massive write:** Snapshot создается быстро (копирование файла). Write нагрузка продолжается.
- **Restore на уже существующий кластер:** Всегда используйте новый `cluster-token`, иначе новый кластер "сливается" со старым через gossip.
- **WAL-only backup:** Можно копировать только WAL, но для восстановления нужен хотя бы один снапшот.

---

## См. также

*   **[Кластеризация и восстановление](./clustering_and_recovery.md)** — DR процедуры.
*   **[Аварийное восстановление](./emergency_recovery.md)** — `--force-new-cluster` и логическая миграция.
*   **[Лимиты и ограничения](./limits_and_constraints.md)** — size limits и capacity planning.
*   **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — snapshot save/restore.
*   **[Мониторинг etcd](./etcd_monitoring.md)** — мониторинг бэкапов.
