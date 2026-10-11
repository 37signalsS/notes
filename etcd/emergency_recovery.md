# Аварийное восстановление etcd

**Актуально для:** etcd 3.7.x (офлайн restore через `etcdutl` — 3.6+; в 3.5 `snapshot restore` ещё доступен через `etcdctl`)

**Аварийное восстановление** — это процедура, используемая, когда стандартные методы (restore из снапшота, добавление узлов) невозможны. Включает `--force-new-cluster`, восстановление после потери кворума и migration между кластерами.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Force New Cluster** | Режим запуска etcd из существующего `data-dir`: сохраняет данные приложений, перестраивает membership в одноузловой кластер. Флаг `--force-new-cluster`. Строго не рекомендуется документацией etcd. |
| **Cluster Fencing** | Изоляция старых узлов (выключение или блокировка сети) для предотвращения вмешательства в новый кворум. |
| **Logical Migration** | Перенос данных между кластерами через `etcdctl get --prefix` / `etcdctl put`. |
| **Disaster Recovery (DR)** | Полное восстановление кластера после потери большинства узлов. |
| **RTO** | Recovery Time Objective — максимальное допустимое время восстановления. |
| **RPO** | Recovery Point Objective — максимально допустимая потеря данных (в ревизиях или времени). |

---

## Основные концепции

### Когда использовать `--force-new-cluster`

`--force-new-cluster` — крайняя мера, только когда **одновременно**:

1. **Кворум потерян безвозвратно** (например, 2 из 3 узлов безвозвратно недоступны).
2. **Нет валидного снапшота** для restore (рекомендуемый путь — restore из снапшота, см. [Кластеризация и восстановление](./clustering_and_recovery.md)).
3. **Сохранился `data-dir` хотя бы одного члена** с целыми WAL и БД.

**Что делает флаг (по исходникам etcd, `etcdserver/bootstrap.go`):**
- Читает **существующие** данные из `--data-dir` — keyspace сохраняется целиком, включая RBAC (пользователи и роли хранятся в самом etcd, см. [Security](./security.md)).
- Отбрасывает незакоммиченные записи WAL и принудительно коммитит config-change записи, удаляя всех остальных членов: кластер стартует как **одноузловой**.
- **Member ID и cluster ID сохраняются** (берутся из WAL meta) — identity члена не сбрасывается.

**Строго не рекомендуется** (официальная документация etcd): флаг **panic'нет при старте, если узлы старого кластера ещё живы** — они должны быть изолированы (fencing) ДО запуска. Не работает для члена, удалённого через `etcdctl member remove` (panic `removed all voters`, issue etcd-io/etcd#13848).

**Что теряется:**
- Записи, которые не успели попасть в WAL выжившего члена (данные остальных узлов).
- Конфигурация membership (остальные члены исключены).

**Что сохраняется:** keyspace выжившего члена (ключи, значения, leases, RBAC, ревизии до момента последнего снапшота/WAL).

```bash
# Аварийный запуск одного узла (TLS-флаги при включённом TLS обязательны)
etcd --force-new-cluster \
  --name node1 \
  --listen-client-urls https://10.0.1.10:2379 \
  --advertise-client-urls https://10.0.1.10:2379 \
  --listen-peer-urls https://10.0.1.10:2380 \
  --initial-advertise-peer-urls https://10.0.1.10:2380 \
  --initial-cluster node1=https://10.0.1.10:2380 \
  --data-dir /var/lib/etcd
```

**Валидация:**
```bash
etcdctl endpoint health
# → healthy

etcdctl get "" --prefix --keys-only | wc -l
# → число ключей из data-dir выжившего члена (НЕ 0 — данные сохранены)

etcdctl member list
# → 1 член (остальные исключены)
```

### Cluster Fencing при восстановлении

Если старые узлы ещё живы и находятся в сети, новый кластер может "слиться" со старым через gossip, а старый — продолжить принимать записи, если восстановит кворум:

1. **Выключите старые узлы** (physically or network-level). Обязательно: `--force-new-cluster` panic'нет, если узлы старого кластера живы.
2. **Запустите новый кластер** из снапшота или `--force-new-cluster`.
3. **Убедитесь**, что старые узлы не могут подключиться (проверьте firewall, выключите сервисы).

### Logical Migration между кластерами

Если нужно перенести данные из старого кластера в новый (не restore, а именно migration):

```bash
# На старом кластере (если он еще жив) — пустой prefix "" выбирает ВСЕ ключи
etcdctl --endpoints=https://old-etcd:2379 get "" --prefix --keys-only > keys.txt

# На новом кластере (один RPC на ключ; значения с бинарными данными или newlines
# таким циклом не перенести — для них используйте snapshot restore)
while read key; do
  value=$(etcdctl --endpoints=https://old-etcd:2379 get "$key" --print-value-only)
  etcdctl --endpoints=https://new-etcd:2379 put "$key" "$value"
done < keys.txt
```

**Ограничения:**
- Не переносит leases, alarms, внутренние метаданные и историю ревизий.
- Не переносит RBAC (пользователи, роли) — воссоздаются отдельно (см. [Security](./security.md)).
- Медленно для > 100 000 ключей (один `get` + один `put` на ключ). Для больших keyspace используйте `etcdutl snapshot restore` — он быстрее и сохраняет метаданные.
- Требует, чтобы старый кластер был доступен.

### Потеря кворума: алгоритм восстановления

```
1. Изоляция старых узлов (fencing)
   ↓
2. Проверка снапшота (etcdutl snapshot status — hash, revision, total key, size)
   ↓
3. Restore на новый кластер (etcdutl snapshot restore; ВСЕ члены восстанавливают ОДИН и тот же снапшот)
   ↓
4. Запуск нового кластера
   ↓
5. Валидация (health, keys count, alarms)
   ↓
6. Обновление clients (kube-apiserver, etcdctl endpoints)
```

**RTO minimization:**
- Подготовьте скрипт восстановления заранее (Infrastructure as Code) и регулярно отрабатывайте его в изолированной среде (Restore Drills — см. [Кластеризация и восстановление](./clustering_and_recovery.md)).
- Храните снапшоты на быстром локальном диске и на удалённом хранилище (сетевой том, репликация в другой ЦОК).
- С etcd 3.6+ restore выполняется только через `etcdutl` (команда удалена из `etcdctl`) — это разделение инструментов, а не ускорение.

---

## Практические сценарии

### Сценарий 1: Потеря 2 из 3 узлов, снапшот есть

```bash
# 1. Fencing: остановить ВСЕ старые узлы (включая выживший — он член старого кластера)
ssh node1 "systemctl stop etcd"; ssh node2 "systemctl stop etcd"; ssh node3 "systemctl stop etcd"

# 2. Проверить снапшот
etcdutl snapshot status /backup/last-good.db
# → hash: ..., revision: 48291, total key: 12500, size: 12.5 MB

# 3. Restore на новом узле (snapshot restore перезаписывает member ID и cluster ID —
#    член теряет прежнюю identity, поэтому это новый логический кластер)
etcdutl snapshot restore /backup/last-good.db \
  --name node1 \
  --initial-cluster node1=https://10.0.1.10:2380,node2=https://10.0.1.11:2380,node3=https://10.0.1.12:2380 \
  --initial-cluster-token new-cluster-1 \
  --initial-advertise-peer-urls https://10.0.1.10:2380 \
  --data-dir /var/lib/etcd-restored

# 4. Запустить
etcd --data-dir /var/lib/etcd-restored \
  --listen-client-urls https://10.0.1.10:2379 \
  --advertise-client-urls https://10.0.1.10:2379 \
  --listen-peer-urls https://10.0.1.10:2380 \
  --initial-advertise-peer-urls https://10.0.1.10:2380

# 5. Вернуть топологию 3 узлов: добавить node2 и node3 (learner → promote)
etcdctl member add node2 --peer-urls=https://10.0.1.11:2380
etcdctl member add node3 --peer-urls=https://10.0.1.12:2380

# 6. Валидация
etcdctl endpoint health --cluster -w table
etcdctl get "" --prefix --keys-only | wc -l
etcdctl alarm list
# → пустой вывод
```

### Сценарий 2: Потеря всех узлов, снапшота нет

```bash
# Если сохранился data-dir хотя бы одного узла:
# 1. Проверить WAL (целостность проверяется при старте etcd;
#    ручная диагностика — через etcd-dump-logs)
etcd-dump-logs /var/lib/etcd

# 2. Запустить с --force-new-cluster — ДАННЫЕ СОХРАНЯЮТСЯ из data-dir
#    (строго не рекомендуется; panic, если узлы старого кластера живы)
etcd --force-new-cluster ...

# 3. Логическая миграция (если есть доступ к старому кластеру):
etcdctl get "" --prefix --keys-only > all_keys.txt
# → восстановить на новом кластере
```

Если ни снапшота, ни целого data-dir нет — данные потеряны безвозвратно; остаётся запустить пустой кластер и заново завести ресурсы (в Kubernetes — kube-apiserver воссоздаёт состояние из manifests и controller-реконсиляции).

### Сценарий 3: Коррупция данных на части узлов, кворум жив

```bash
# 1. Не использовать --force-new-cluster и snapshot restore! Кворум есть —
#    кластер работает, новый член синхронизируется с лидера автоматически.

# 2. (Опционально) Логический бэкап с живого узла как страховка:
etcdctl --endpoints=https://healthy-node:2379 get "" --prefix --keys-only > all_keys.txt

# 3. Удалить проблемный узел:
etcdctl member remove <CORRUPT_MEMBER_ID>

# 4. Добавить новый узел (learner → promote):
etcdctl member add <NEW_MEMBER_NAME> --peer-urls=https://10.0.1.12:2380
# на новом узле: etcd ... --initial-cluster-state existing
# promote: etcdctl member promote <NEW_MEMBER_ID>
```

Restore из снапшота в этом сценарии не нужен: он создаёт новый кластер и теряет записи после снапшота. Логический бэкап пригодился бы только при потере кворума.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `--force-new-cluster` panic при старте | Узлы старого кластера ещё живы, или член удалён через `member remove` (`removed all voters`, issue etcd-io/etcd#13848) | Изолируйте (fencing) все узлы старого кластера; для удалённого члена — только restore из снапшота |
| `--force-new-cluster` не работает | `--data-dir` пустой или отсутствует (нечего восстанавливать) | Используйте data-dir выжившего члена или restore из снапшота |
| Новый кластер не набирает кворум | Старые узлы в сети (fencing failed) | Выключите старые узлы, проверьте firewall |
| `mvcc: required revision has been compacted` после restore | Снапшот устарел, ревизии удалены | Используйте более свежий снапшот |
| `data-dir %q not empty or could not be read` | Директория не пуста при `etcdutl snapshot restore` | Укажите новую/пустую директорию для restore |
| `snapshot restore` отказывается восстанавливать | Снапшот скопирован из `data-dir/member/snap/db` — у него нет integrity hash | `--skip-hash-check` (только для копий из data-dir; снапшоты от `etcdctl snapshot save` проверяются автоматически) |
| `etcdutl: command not found` | etcd ≤ 3.5 | Используйте `etcdctl snapshot restore` (в 3.6+ команда перенесена в `etcdutl`) |
| Миграция занимает вечно | Слишком много ключей (> 1M) | Пакетные `etcdctl txn` (до 128 операций) или, лучше, `etcdutl snapshot restore` |

---

## Best Practices

- **`--force-new-cluster` — последний resort:** Всегда пытайтесь restore из снапшота сначала (документация etcd: force-new-cluster «strongly discouraged»).
- **Fencing перед restore:** Выключайте старые узлы ДО запуска нового кластера.
- **RTO — целевая оценка (например, < 15 минут):** достигается подготовленным и протестированным скриптом восстановления.
- **RPO = интервал снапшотов:** при снапшотах каждые 15 минут RPO = 15 минут; RPO = 0 недостижимо при периодических снапшотах (etcd не имеет «transactional replication» во внешние системы).
- **После восстановления:** немедленно настройте регулярные снапшоты и проверьте `etcdctl alarm list`.
- **Документируйте процедуру:** Каждый шаг восстановления должен быть в runbook.

---

## Edge Cases

- **Force-new-cluster с существующим data-dir:** это штатный режим работы флага — он читает данные из существующего `data-dir`. Откажется запускаться, если `data-dir` пустой или отсутствует (нечего восстанавливать), либо если член был удалён через `member remove` (panic `removed all voters`).
- **Восстановление на другую архитектуру:** amd64 ↔ arm64 совместимы (оба little-endian). Риск только при смене endianness (например, amd64 → s390x, big-endian) — используйте логическую миграцию.
- **Cluster ID mismatch:** При restore используйте уникальный `--initial-cluster-token` — защита от непреднамеренного взаимодействия кластеров. Сам restore перезаписывает member ID и cluster ID, поэтому восстановленный член не сможет присоединиться к старому кластеру.
- **Два независимых кластера при DR:** если старый кластер частично жив и не изолирован, он может восстановить кворум и продолжить принимать записи — клиенты окажутся перед двумя источниками истины. Fencing критически важен.

---

## См. также

* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — DR процедуры и restore из снапшота.
* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — snapshot и restore команды.
* **[Стратегии резервного копирования](./backup_strategies.md)** — snapshot vs logical backup.
* **[Совместимость версий](./version_compatibility.md)** — снапшот нельзя восстановить на младшей версии.
* **[Raft-консенсус](./raft_consensus.md)** — кворум и потеря большинства.
* **[Систематический troubleshooting](./troubleshooting.md)** — playbook для production.
