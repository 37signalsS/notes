# Стратегии резервного копирования etcd

**Актуально для:** etcd 3.7.x

**etcd** — единственный источник истины для Kubernetes. Потеря данных без бэкапа означает потерю всего состояния кластера. Данный документ описывает стратегии, trade-offs и практические сценарии бэкапа.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Snapshot** | Полный снимок состояния BoltDB на конкретной ревизии. Онлайн-операция (`etcdctl snapshot save`) — consistent point-in-time: записи во время сохранения не влияют на целостность. |
| **Logical Backup** | Выгрузка ключей и значений через `etcdctl get --prefix -w json`. Замедляет кластер при больших объемах; не сохраняет leases, ревизии и метаданные. |
| **Incremental Backup** | В etcd core отсутствует: снапшот всегда полный. Инкрементальность реализуют внешние компоненты (gardener/etcd-backup-restore) или снапшоты хранилища (LVM/ZFS). |
| **Offline Backup** | Копирование `member/snap/db` при остановленном etcd. Гарантирует целостность, но требует даунтайма; данные из WAL, не сброшенные в db, теряются. |
| **Online Backup** | Резервное копирование работающего кластера. Даунтайм 0; снапшот — согласованное состояние на одной ревизии. |
| **Restore Drill** | Регулярное упражнение по восстановлению из снапшота в изолированной среде. |
| **RPO / RTO** | Максимальная допустимая потеря данных (Recovery Point Objective) и время восстановления (Recovery Time Objective). Частота снапшотов определяет RPO. |

---

## Основные концепции

### Snapshot vs Logical Backup

| Критерий | Snapshot | Logical Backup (`etcdctl get`) |
| :--- | :--- | :--- |
| **Скорость** | Быстро (поток через Snapshot API) | Медленно (вызывает gRPC Range запросы) |
| **Влияние на кластер** | Низкое (Snapshot API, один RPC-стрим) | Высокое (нагружает etcd и сеть) |
| **Целостность** | Полная (все данные, включая метаданные) | Частичная (только ключи/значения, нет внутренних метаданных) |
| **Размер** | Размер файла BoltDB | Обычно меньше (только user keys) |
| **Восстановление** | Быстрое (offline restore) | Медленное (bulk import через `etcdctl put`) |

**Рекомендация:** Используйте snapshot для production. Logical backup — только для миграции данных или аудита.

### Ограничения snapshot

- **Версионность:** Восстановить можно только на версию `>=` версии создания. Downgrade невозможен (см. [Совместимость версий](./version_compatibility.md)).
- **Архитектура:** Снапшот переносим между архитектурами с одинаковым порядком байт: amd64 ↔ arm64 ↔ ppc64le (все little-endian) — совместимы. Риск только при смене endianness (например, amd64 → s390x, big-endian): bbolt memory-maps файл. Для таких миграций используйте логический backup.
- **Cluster Token:** При восстановлении используйте уникальный `--initial-cluster-token`, иначе кластер может "слиться" с существующим.
- **Размер:** Размер снапшота = размер БД (ограничена `quota-backend-bytes`: по умолчанию 2 ГБ, максимум 8 ГБ). Большие снапшоты долго сохраняются и восстанавливаются (I/O-bound); для очень больших БД используйте снапшоты уровня хранилища (LVM) — см. [Maintenance API](./maintenance_api.md).

### Инкрементальные бэкапы

etcd core не поддерживает инкрементальные бэкапы: `etcdctl snapshot save` всегда пишет полный снапшот (флага `--delta-from` не существует). Инкрементальность реализуют:

- **gardener/etcd-backup-restore** — sidecar с full + incremental снапшотами и валидацией data directory (см. [etcd Operator](./etcd_operator.md));
- **Снапшоты хранилища (LVM/ZFS)** — на уровне диска; требуют согласованности (fsfreeze или пауза записи) и не заменяют логический бэкап.

**Trade-offs:**
- **Плюс:** Меньший размер, быстрее.
- **Минус:** Для восстановления нужна цепочка (базовый полный + инкременты). Сложнее управлять.

### Encryption at Rest для бэкапов

Снапшоты содержат ВСЕ данные (включая секреты) в открытом виде (если не включено encryption at Rest).
- **Политика:** Шифруйте снапшоты перед отправкой в object storage/offsite.
- **Инструменты:** `openssl enc -aes-256-cbc -pbkdf2 -in snapshot.db -out snapshot.db.enc` (без `-pbkdf2` перебор пароля тривиален — ключ выводится за один проход).

### Автоматические снапшоты — это НЕ бэкап

etcd создаёт внутренние снапшоты каждые `--snapshot-count` ревизий (по умолчанию 10 000 в v3.6+), но они лежат в `data-dir/member/snap` и погибают вместе с диском. Их задача — усечение Raft-лога, а не резервное копирование. Бэкап — это `etcdctl snapshot save` на отдельный носитель.

---

## Практические сценарии

### Стратегия бэкапа для production K8s

| Тип | Частота | Хранение | Срок |
| :--- | :--- | :--- | :--- |
| **Snapshot** | Каждые 15 минут | Локально + object storage (с версионированием) | 7 дней |
| **Logical Backup** | Раз в день | object storage (отдельный bucket) | 30 дней |
| **Offsite Copy** | Раз в день | Другой дата-центр / сайт | 90 дней |

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
            image: gcr.io/etcd-development/etcd:<VERSION>  # → замените <VERSION> на нужный тег (например, 3.7.2); пините версию
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
              etcdutl snapshot status /backup/etcd-snapshot-${DATE}.db -w table
              # Offsite-копия: rsync/scp на backup-сервер или в смонтированное сетевое хранилище
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
# Проверка статуса (колонки: HASH, REVISION, TOTAL KEYS, TOTAL SIZE)
etcdutl snapshot status /backup/etcd-snapshot.db -w table

# Проверка размера
ls -lh /backup/etcd-snapshot.db
# → 1.2G
```

Снапшот, созданный `etcdctl snapshot save`, содержит контрольную сумму SHA-256 — `etcdutl snapshot restore` проверяет её автоматически. Для снапшотов, скопированных напрямую из `member/snap/db`, хеша нет, и restore возможен только с `--skip-hash-check`.

### Восстановление из снапшота (Disaster Recovery)

Восстанавливать нужно КАЖДЫЙ узел из ОДНОГО и того же снапшота — restore создаёт новый data-dir с новым member ID и cluster ID.

```bash
# 1. Остановить etcd на всех узлах
systemctl stop etcd

# 2. Восстановить snapshot на каждом узле (один снапшот, разные --name и peer URL)
#    node1:
etcdutl snapshot restore /backup/etcd-snapshot.db \
  --name node1 \
  --initial-cluster node1=https://10.0.1.10:2380,node2=https://10.0.1.11:2380,node3=https://10.0.1.12:2380 \
  --initial-advertise-peer-urls https://10.0.1.10:2380 \
  --initial-cluster-token restored-cluster \
  --data-dir /var/lib/etcd-restored
#    node2, node3 — аналогично, с их --name и --initial-advertise-peer-urls

# 3. Заменить data-dir на каждом узле
mv /var/lib/etcd /var/lib/etcd-old
mv /var/lib/etcd-restored /var/lib/etcd

# 4. Запустить etcd на всех узлах
systemctl start etcd

# 5. Валидация
etcdctl endpoint health --cluster
etcdctl get --prefix --keys-only | wc -l
```

**Для Kubernetes:** добавьте `--bump-revision=<N> --mark-compacted` (etcd 3.6+) — поднимает ревизию и помечает её скомпактированной, чтобы watches контроллеров не ждали ревизии, которой больше не будет (инвалидация informer-кэшей). Восстановление одного узла через `--force-new-cluster` — аварийный путь, см. [Аварийное восстановление](./emergency_recovery.md).

### Logical backup для миграции данных

```bash
# Выгрузка всех ключей и значений в JSON (медленно!)
etcdctl get --prefix "" --write-out=json > etcd-logical-backup.json

# Восстановление (простой случай: значения без переносов строк и табов)
jq -r '.kvs[] | [.key, .value] | @tsv' etcd-logical-backup.json |
  while IFS=$'\t' read -r key value; do
    etcdctl put "$(printf '%s' "$key" | base64 -d)" "$(printf '%s' "$value" | base64 -d)"
  done
```

**Warning:** Logical backup не восстанавливает leases, alarms, ревизии и внутренние метаданные. Значения с переносами строк/табуляторами требуют бинарно-безопасного скрипта (Python/Go). Для миграции целого кластера предпочтительнее `etcdutl snapshot restore`.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `snapshot restore failed` | Файл поврежден (сетевая ошибка, диск) | Использовать предыдущий снапшот; проверить WAL через `etcd-dump-logs` |
| `data-dir %q not empty or could not be read` | Директория не пуста при `etcdutl snapshot restore` | Указать новую/пустую директорию для restore |
| `snapshot missing hash but --skip-hash-check=false` | Снапшот скопирован из `member/snap/db` (без хеша) | `--skip-hash-check` — только для копий из data-dir |
| Снапшот долго сохраняется/восстанавливается | Большая БД, операция I/O-bound | Снапшот уровня хранилища (LVM); см. [Maintenance API](./maintenance_api.md) |
| Restore на другую архитектуру | Разный порядок байт (little-endian → big-endian, например amd64 → s390x) | Логический backup через `etcdctl get` |
| Старый снапшот | Потеря данных с момента снапшота (RPO) | Сравнить REVISION в `etcdutl snapshot status` с текущей ревизией кластера; уменьшить интервал бэкапа |

---

## Best Practices

- **Restore Drill каждые квартал:** Бэкап без тестирования восстановления — не бэкап.
- **Хранилище с версионированием:** Защита от случайного удаления (ransomware) — object storage или файловый сервер с версиями.
- **Offsite copy:** Храните копию в другом дата-центре/сайте.
- **Шифруйте снапшоты:** Перед отправкой в хранилище шифруйте (AES-256 с `-pbkdf2` или HSM).
- **Не храните бэкапы на том же диске, что и data-dir:** При отказе диска вы потеряете и данные, и бэкап.
- **Валидируйте каждый снапшот:** `etcdutl snapshot status` сразу после `snapshot save` — в CronJob (см. [etcd Operator](./etcd_operator.md)).
- **RPO определяет частоту:** при снапшоте каждые 15 минут максимальная потеря — 15 минут записей. Согласуйте интервал с требованиями бизнеса.
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
*   **[etcd Operator](./etcd_operator.md)** — gardener/etcd-backup-restore (full + incremental).
