# Аварийное восстановление etcd

**Аварийное восстановление** — это процедура, используемая, когда стандартные методы (restore из снапшота, добавление узлов) невозможны. Включает `--force-new-cluster`, восстановление после потери кворума и migration между кластерами.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Force New Cluster** | Режим запуска etcd, при котором узел создаёт новый кластер, игнорируя существующие данные. Флаг `--force-new-cluster`. |
| **Cluster Fencing** | Изоляция старых узлов (выключение или блокировка сети) для предотвращения вмешательства в новый кворум. |
| **Logical Migration** | Перенос данных между кластерами через `etcdctl get --prefix` / `etcdctl put`. |
| **Disaster Recovery (DR)** | Полное восстановление кластера после потери большинства узлов. |
| **RTO** | Recovery Time Objective — максимальное допустимое время восстановления. |
| **RPO** | Recovery Point Objective — максимально допустимая потеря данных (в ревизиях или времени). |

---

## Основные концепции

### Когда использовать `--force-new-cluster`

`--force-new-cluster` — это крайняя мера, используемая только когда:

1. **Потерян весь кластер** (все узлы недоступны).
2. **Нет валидного снапшота** для restore.
3. **Нет возможности восстановить WAL** (поврежден или отсутствует).

**Что делает флаг:**
- Игнорирует существующие данные в `--data-dir`.
- Создаёт новый кластер из одного узла.
- Сбрасывает `cluster-token` и `member-id`.

**Что теряется:**
- **ВСЕ данные** в старом кластере.
- История ревизий, leases, alarms.
- RBAC пользователи и роли.

```bash
# Аварийный запуск одного узла
etcd --force-new-cluster \
  --name node1 \
  --listen-client-urls https://127.0.0.1:2379 \
  --advertise-client-urls https://127.0.0.1:2379 \
  --listen-peer-urls https://127.0.0.1:2380 \
  --initial-advertise-peer-urls https://127.0.0.1:2380 \
  --data-dir /var/lib/etcd
```

**Валидация:**
```bash
etcdctl endpoint health
# → healthy

etcdctl get --prefix --keys-only | wc -l
# → 0 (новый пустой кластер)
```

### Cluster Fencing при восстановлении

Если старые узлы еще живы и находятся в сети, новый кластер может "слиться" со старым через gossip:

1. **Выключите старые узлы** (physically or network-level).
2. **Запустите новый кластер** из снапшота или `--force-new-cluster`.
3. **Убедитесь**, что старые узлы не могут подключиться (проверьте firewall, выключите сервисы).

### Logical Migration между кластерами

Если нужно перенести данные из старого кластера в новый (не restore, а именно migration):

```bash
# На старом кластере (если он еще жив)
etcdctl --endpoints=https://old-etcd:2379 get --prefix --keys-only / > keys.txt

# На новом кластере
while read key; do
  value=$(etcdctl --endpoints=https://old-etcd:2379 get "$key" --print-value-only)
  etcdctl put "$key" "$value"
done < keys.txt
```

**Ограничения:**
- Не переносит leases, alarms, внутренние метаданные.
- Не переносит RBAC (пользователи, роли).
- Медленно для > 100 000 ключей.
- Требует, чтобы старый кластер был доступен.

### Потеря кворума: алгоритм восстановления

```
1. Изоляция старых узлов (fencing)
   ↓
2. Проверка снапшота (etcdutl snapshot status)
   ↓
3. Restore на новый кластер (etcdutl snapshot restore)
   ↓
4. Запуск нового кластера
   ↓
5. Валидация (health, keys count, alarms)
   ↓
6. Обновление clients (kube-apiserver, etcdctl endpoints)
```

**RTO minimization:**
- Подготовьте скрипт восстановления заранее ( Infrastructure as Code).
- Храните снапшоты на быстром доступе (не только в S3, но и локально).
- Используйте `etcdutl` вместо `etcdctl` для faster restore.

---

## Практические сценарии

### Сценарий 1: Потеря 2 из 3 узлов, снапшот есть

```bash
# 1. Fencing: убедиться, что старый узел выключен
ssh old-node "systemctl stop etcd"

# 2. Restore на новом узле
etcdutl snapshot restore /backup/last-good.db \
  --name node1 \
  --initial-cluster node1=https://10.0.1.10:2380,node2=https://10.0.1.11:2380 \
  --initial-cluster-token new-cluster-1 \
  --data-dir /var/lib/etcd-restored

# 3. Запустить
etcd --data-dir /var/lib/etcd-restored \
  --listen-client-urls https://10.0.1.10:2379 \
  --advertise-client-urls https://10.0.1.10:2379 \
  --listen-peer-urls https://10.0.1.10:2380 \
  --initial-advertise-peer-urls https://10.0.1.10:2380

# 4. Валидация
etcdctl endpoint health --cluster
etcdctl get --prefix --keys-only | wc -l
```

### Сценарий 2: Потеря всех узлов, снапшота нет

```bash
# Если есть хотя бы один узел с данными:
# 1. Запустить с --force-new-cluster (теряем данные)
etcd --force-new-cluster ...

# 2. Или попробовать восстановить WAL:
etcdutl wal verify /var/lib/etcd/wal/
# Если WAL целый — можно попробовать восстановить данные

# 3. Логическая миграция (если есть доступ к старому кластеру):
etcdctl get --prefix --keys-only / > all_keys.txt
# → восстановить на новом кластере
```

### Сценарий 3: Коррупция данных на части узлов, кворум жив

```bash
# 1. Не использовать --force-new-cluster! Кворум есть.
# 2. Логический бэкап с живого узла:
etcdctl --endpoints=https://healthy-node:2379 get --prefix --keys-only / > all_keys.json

# 3. Удалить проблемный узел:
etcdctl member remove <CORRUPT_MEMBER_ID>

# 4. Восстановить кластер из снапшота (опционально):
etcdutl snapshot restore /backup/good.db ...

# 5. Импортировать данные (если restore из снапшота):
cat all_keys.json | while read key; do
  value=$(etcdctl get "$key" --print-value-only)
  etcdctl put "$key" "$value"
done
```

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `--force-new-cluster` не работает | `--data-dir` не пустой или неверные флаги | Очистите директорию или используйте новую |
| Новый кластер не набирает кворум | Старые узлы в сети (fencing failed) | Выключите старые узлы, проверьте firewall |
| `mvcc: required revision has been compacted` после restore | Снапшот устарел, ревизии удалены | Используйте более свежий снапшот |
| `data-dir already exists` | Директория не пуста | Используйте новую директорию или очистите |
| Миграция занимает вечно | Слишком много ключей (> 1M) | Используйте параллельные `put` или промежуточный etcd |

---

## Best Practices

- **`--force-new-cluster` — последний resort:** Всегда пытайтесь restore из снапшота сначала.
- **Fencing перед restore:** Выключайте старые узлы ДО запуска нового кластера.
- **RTO < 15 минут:** Подготовьте скрипт восстановления и протестируйте его.
- **RPO = 0:** Частые снапшоты (каждые 15 минут) + transactional replication = минимальная потеря данных.
- **Документируйте процедуру:** Каждый шаг восстановления должен быть в runbook.

---

## Edge Cases

- **Force-new-cluster с существующим data-dir:** etcd откажется запускаться. Используйте новую директорию или удалите старую.
- **Восстановление на другую архитектуру:** Снапшоты несовместимы (amd64 → arm64). Используйте логическую миграцию.
- **Cluster ID mismatch:** При restore используйте уникальный `--initial-cluster-token`, иначе новый кластер может "слиться" со старым через gossip.
- **Split-brain при DR:** Если старый кластер частично жив, новый кластер может получить устаревшие данные. Fencing критически важен.

---

## См. также

* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — DR процедуры.
* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — snapshot и restore команды.
* **[Стратегии резервного копирования](./backup_strategies.md)** — snapshot vs logical backup.
* **[Систематический troubleshooting](./troubleshooting.md)** — playbook для production.
