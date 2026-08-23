# Maintenance API etcd

**etcd Maintenance API** — это набор gRPC-методов для операций обслуживания кластера, выполняемых в фоновом режиме без остановки etcd. Включает дефрагментацию, проверку хешей, управление WAL и диагностику.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Maintenance Service** | gRPC-сервис (`etcdserverpb.Maintenance`) с методами обслуживания. |
| **HashKV** | RPC для проверки целостности данных на всех узлах (сравнение хешей). |
| **Defragment** | RPC для онлайн-дефрагментации BoltDB на конкретном узле. |
| **Snapshot** | RPC для получения снапшота через gRPC (не через файловую систему). |
| **WAL Operations** | RPC для работы с WAL: `WALCheckpoint`, `WALRepair`, `WALList`. |
| **Alarm** | RPC для управления алармами (`AlarmActivate`, `AlarmDeactivate`). |
| **Downgrade** | RPC для подготовки кластера к downgrade на определённую версию. |

---

## Основные концепции

### Endpoint и доступ

Maintenance API доступен на том же порту, что и основной API (2379), но требует отдельного gRPC-метода.

```bash
# Вызов maintenance RPC через etcdctl
etcdctl defrag --endpoints=https://10.0.1.10:2379

# Или напрямую через grpcurl
grpcurl -d '{"key":"/config/app"}' \
  -H "authorization: Bearer $(cat /var/lib/etcd/token)" \
  --cacert /etc/etcd/ca.crt \
  --cert /etc/etcd/server.crt \
  --key /etc/etcd/server.key \
  10.0.1.10:2379 \
  etcdserverpb.Maintenance/HashKV
```

### HashKV: проверка целостности данных

`HashKV` вычисляет хеш всех ключей на конкретном узле и возвращает его. Сравнение хешей между узлами позволяет обнаружить рассинхронизацию.

```bash
# Хеш всех ключей на конкретном узле
etcdctl endpoint hashkv --cluster -w table
# → +----------------+------------------+----------+---------+
# → |    ENDPOINT    |        ID        |   HASH   | ROLE    |
# → +----------------+------------------+----------+---------+
# → | 10.0.1.10:2379 | 8e9e05f54f240d12 | 12345678 | Leader  |
# → | 10.0.1.11:2379 | 9f1a06g632g85g1e | 12345678 | Follower|
# → +----------------+------------------+----------+---------+
```

**Валидация:** Все узлы должны иметь одинаковый `HASH`. Различия указывают на рассинхронизацию или коррупцию данных.

### Defragment через Maintenance API

Онлайн-дефрагментация через gRPC (блокирует узел на время выполнения):

```bash
# Дефрагментация конкретного узла
etcdctl defrag --endpoints=https://10.0.1.10:2379

# Дефрагментация всего кластера (поочередно)
etcdctl defrag --cluster
```

**Что происходит внутри:**
1. Сервер получает gRPC-запрос `Defragment`.
2. Блокируются новые write-запросы на этом узле.
3. Создается новый BoltDB файл, копируются только "живые" страницы.
4. Старый файл заменяется новым.
5. Узел возобновляет обработку запросов.

### Snapshot через Maintenance API

Создание снапшота через gRPC (полезно, если нет доступа к файловой системе):

```bash
# Через etcdctl (использует maintenance API под капотом)
etcdctl snapshot save /backup/etcd.db

# Прямой вызов через grpcurl (псевдокод)
grpcurl -d '{"keys":["/"]}' \
  -H "authorization: Bearer $(cat token)" \
  --cacert ca.crt --cert server.crt --key server.key \
  10.0.1.10:2379 \
  etcdserverpb.Maintenance/Snapshot
```

### WAL Maintenance

```bash
# Показать WAL записи (offline)
etcdutl wal show /var/lib/etcd/wal/

# Проверить целостность WAL (offline)
etcdutl wal verify /var/lib/etcd/wal/
```

**Online WAL операции (Maintenance API):**
- `WALCheckpoint` — создаёт checkpoint в WAL (ускоряет восстановление).
- `WALRepair` — пытается восстановить повреждённый WAL.
- `WALList` — возвращает список сегментов WAL.

```bash
# Пример: принудительный checkpoint WAL
grpcurl -d '{}' \
  -H "authorization: Bearer $(cat token)" \
  --cacert ca.crt --cert server.crt --key server.key \
  10.0.1.10:2379 \
  etcdserverpb.Maintenance/WALCheckpoint
```

### Alarm Management

```bash
# Список алармов
etcdctl alarm list

# Сброс аларма
etcdctl alarm disarm --member=8e9e05f54f240d12
```

**Внутри Maintenance API:**
- `AlarmActivate` — поднимает аларм (например, `NOSPACE`).
- `AlarmDeactivate` — сбрасывает аларм.
- `AlarmGet` — получает список активных алармов.

---

## Практические сценарии

### Плановое обслуживание без остановки

```bash
# 1. Передать лидерство на follower
etcdctl move-leader <FOLLOWER_ID>

# 2. Дефрагментация текущего узла (он больше не лидер)
etcdctl defrag --endpoints=https://10.0.1.10:2379

# 3. Проверить, что кластер стабилен
etcdctl endpoint health --cluster
```

### Проверка согласованности данных после обновления

```bash
# Сравнить хеши на всех узлах
etcdctl endpoint hashkv --cluster -w table

# Если хеши разные — проверить логи
journalctl -u etcd -n 100 | grep -i "error\|corrupt\|inconsistent"
```

### Диагностика проблем с WAL

```bash
# Проверить WAL на проблемном узле
etcdutl wal verify /var/lib/etcd/wal/

# Если WAL поврежден — repair через maintenance API или восстановление из снапшота
etcdctl --endpoints=https://10.0.1.10:2379 alarm list
# → CORRUPT alarm

# Repair
etcdutl wal repair /var/lib/etcd/wal/
```

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `defrag` блокирует узел надолго | БД > 20 ГБ или медленный диск | Выполнять в часы минимальной нагрузки; поочередно на узлах |
| `hashkv` возвращает разные хеши | Рассинхронизация или коррупция | Проверить логи; восстановить из снапшота |
| `maintenance: method not found` | Версия клиента старше сервера | Обновить etcdctl до версии >= сервера |
| `WAL repair` не помогает | Сильное повреждение | Восстановление из снапшота |
| Snapshot через API медленный | Большая БД (> 8 ГБ) | Использовать файловый snapshot (`etcdctl snapshot save`) |

---

## Best Practices

- **Используйте Maintenance API вместо прямого доступа к файлам:** gRPC-методы безопаснее, чем работа с файлами напрямую.
- **HashKV после каждого изменения:** Сравнивайте хеши после rolling upgrade, замены узлов, restore.
- **Defrag по очереди:** Никогда не дефрагментируйте все узлы одновременно — потеря кворума.
- **WAL checkpoint регулярно:** Ускоряет восстановление после сбоя. В etcd 3.7+ выполняется автоматически.
- **Не злоупотребляйте Snapshot API:** Для больших кластеров (> 8 ГБ) используйте файловый snapshot, он быстрее.

---

## См. также

* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — команды maintenance.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — restore и DR.
* **[Внутреннее устройство хранения](./storage_internals.md)** — BoltDB и defrag internals.
