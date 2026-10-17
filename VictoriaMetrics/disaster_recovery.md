# Аварийное восстановление VictoriaMetrics (Disaster Recovery)

**Актуально для:** VictoriaMetrics v1.154.x (vmbackup/vmrestore, cluster, single-node)

## Определения

**DR (Disaster Recovery)** — совокупность процедур возвращения системы в рабочее состояние после частичной или полной потери данных/сервиса.

**RPO (Recovery Point Objective)** — допустимый объём потерянных данных (время от последнего бэкапа до момента сбоя). **RTO (Recovery Time Objective)** — целевое время восстановления сервиса. Для VictoriaMetrics определяющими являются: тип сборки (single vs cluster), репликация (`-replicationFactor`), периодичность бэкапов [vmbackup](./vmbackup_restore.md) и возможность быстрого переразвёртывания инфраструктуры (Helm/metal).

**Snapshot** — консистентная точка данных, создаётся по `/snapshot/create`; базовый механизм бэкапа VM (детали — в [http_api_reference.md](./http_api_reference.md)).

## Базовые концепции

### Что именно теряем

| Уровень | Что обновляется при потере | Чем восстанавливаем |
| :--- | :--- | :--- |
| Данные (`-storageDataPath`) | Все серии/партиции | vmrestore из бэкапа |
| Дата-центр / вся виртуалка | Всё | Новые ноды + vmrestore + перепривязка DNS/vmauth |
| Случайное удаление/регресс (`delete_series`, `POST /api/v1/admin/tsdb/delete_series`) | Целевые серии | Откат на бэкап или снапшот |
| Логи (VictoriaLogs) | Бэкап через vmbackup | vmrestore в каталог VictoriaLogs |

### Типичные RPO/RTO для конфигураций

| Конфигурация | Сценарий | Типичный RPO | Типичный RTO |
| :--- | :--- | :--- | :--- |
| Single-node + daily бэкап | Полная потеря | ≤ 24 ч | часы (переразвёртывание + restore) |
| Cluster, RF=2 + hourly бэкап | Потеря 1 ноды | ≈ 1 ч (если часть данных не в бэкапе ещё) | минуты-часы (перераспределения ноды) |
| Cluster, RF=2, NO бэкап | Потеря 1 ноды | 0 (данные с живой копии) | минуты (см. [cluster_operations](./cluster_operations.md)) |
| Cluster, RF=1 + hourly бэкап | Потеря всех нод | ≈ 1 ч | часы (полный restore) |

> RF защищает от потери *одного* экземпляра хранения, но не от полной потери кластера — бэкап обязателен всегда. RPO/RTO задаются продуктом/командой, а не «по умолчанию»: зафиксируйте целевые значения в DR-документации и проверяйте их тестами.

### Механика восстановления (обзор)

#### Предварительные требования

Перед любой DR-операцией:

1. **VM остановлен** — `vmrestore` требует, чтобы сервис не писал в `-storageDataPath` (иначе риск коррупции партиций).
2. **Бэкап существует и проверен** — минимум один full backup в `-src`; инкременты применяются автоматически vmrestore.
3. **Порты API известны:** single-node — `:8428`, vmstorage — `:8482` (`/snapshot/create`), vmselect — `:8481`.
4. **Credentials доступны** — через `-credsFilePath` или env vars; не передавайте ключи в `ps`.
5. **Диск на `-storageDataPath` имеет** достаточно места — vmrestore синхронизирует содержимое, удаляя файлы, которых нет в бэкапе (как `rsync --delete`), поэтому путь должен вместить **полный объём восстанавливаемого датасета**. Перед restore проверьте:
   ```bash
   df -h /var/lib/vmstorage
   # свободного места должно быть ≥ размеру бэкапа в -src
   du -sh /var/lib/vmstorage  # после restore
   ```
   Оценить требуемый объём можно по формуле из [overview.md](./overview.md#планирование-мощностей-capacity-planning): `BytesPerSample × IngestionRate × ReplicationFactor × RetentionSeconds × 1.25` + ~20% на индекс.

#### Ключевые флаги vmrestore для DR

| Флаг | Назначение | Примечание |
| :--- | :--- | :--- |
| `-src` | Источник бэкапа (`s3://`, `gs://`, `azblob://`, `fs://`) | Тот же формат, что `-dst` для vmbackup |
| `-storageDataPath` | Куда восстанавливать | Должен быть пуст или синхронизироваться |
| `-skipBackupCompleteCheck` | Пропустить проверку `backup complete` в `-src` | Полезно для восстановления из старых бэкапов (v1.139.0+) |
| `-concurrency` | Число параллельных воркеров | По умолчанию 10; увеличить для больших кластеров |
| `-maxBytesPerSecond` | Ограничение скорости загрузки | 0 = без ограничения |

Полный справочник флагов — в [vmbackup_restore](./vmbackup_restore.md#восстановление-vmrestore).

#### Как это работает

- Бэкап делается **поузлового** (каждый `vmstorage` отдельной копией) — см. [vmbackup_restore](./vmbackup_restore.md);
- Восстановление — **поузловое**: vmrestore на каждый `-storageDataPath`, затем запуск всех компонентов в прежнем составе;
- Для отката к конкретному моменту — восстановить из бэкапа нужного времени (работа TTL/ротации бэкапов — у vmbackupmanager (Enterprise) или по cron);
- **Перерыв и возобновление:** vmrestore можно прервать в любой момент — при повторном запуске с теми же аргументами восстановление продолжится с места прерывания (до включения preallocation — с начала файла, после — с последнего завершённого файла). Это важно для DR: длительный restore можно безопасно паузить и возобновлять, не теряя прогресса.

## Практические сценарии

### 1. Потеря одного `vmstorage` (RF=2) — восстановление ноды

**Предпосылки:** RF≥2 на записи (`-replicationFactor=2` на `vminsert`), бэкап существует (на случай, если требуется восстановить данные, а не полагаться на реплику).

Цель: вернуть кластер в полный состав без потери реплик.

1. **Диагностика**: `vm_dropped_rows_total` в vminsert растёт, health `vmstorage-N:8482/health` — нет ответа.
2. **Новая нода**: развернуть новый `vmstorage` с тем же форматом `-storageNode` (пустой диск — перераспределение подтянет серии с живых реплик, см. runbook в [cluster_operations](./cluster_operations.md#4-изменение-состава-vmstorage-узлов-runbook)).
3. **Валидация**: `vmselect` снова даёт полные ответы (`"isPartial": false`), replicas сходятся, `vm_dropped_rows_total` не растёт.
4. Если RF=1 и данные ноды важны — восстановить её из бэкапа **в пустой каталог** (`vmrestore -storageDataPath=... -skipBackupCompleteCheck`, если бэкап старый) и подключить на место удалённой ноды.

### 2. Полная потеря кластера (все vmstorage), бэкап свежий

**Предпосылки:** IaC (Helm/Terraform) готов к разворачиванию, `-src` в объектном хранилище содержит full + инкременты, credentials доступны.

```bash
# 0. Восстановить инфраструктуру (Helm/Terraform), но с ПУСТЫМИ путями данных
# 1. Остановить все vmstorage (не запускать VM с пустым каталогом!)

# 2. Поочерёдно восстановить каждый узел в том же составе (0..N)
#    диапазон 0..N и пути -src/N должны совпадать с topology кластера
for i in 0 1 2; do           # ← подгоните под число vmstorage в вашем кластере
  vmrestore \
    -storageDataPath=/var/lib/vmstorage-$i \
    -src=s3://backups/victoria-cluster/$i
done

# 3. Запустить кластер в прежнем составе (vminsert/vmselect/vmstorage)
# 4. Валидация:
curl -sf 'http://vmselect:8481/select/0/prometheus/api/v1/query?query=up' | jq .
curl -sf http://vmstorage-0:8482/health
# → 200 OK
curl -sf 'http://vmselect:8481/select/0/prometheus/api/v1/query?query=label_replace(count(up),"","count",,)' \
  | jq -e '.data.result[0].value[1] | tonumber > 0' || exit 1
```

> Критично: не давайте VM стартовать с пустым каталогом до vmrestore — потеряете реплики и можете повредить индексную структуру. Если бэкап старый (без `backup complete`), добавьте `-skipBackupCompleteCheck`.

### 3. Откат на метку времени (административный инцидент)

**Предпосылки:** нужный бэкап/снапшот доступен в объектном хранилище, есть резервный хост/порт для «теневой» VM.

1. Найти в объектном хранилище бэкап на нужный момент (или снапшот);
2. Развернуть «теневую» VM: `victoria-metrics -storageDataPath=/data -httpListenAddr=:8499` после `vmrestore -src=<backup> -storageDataPath=/data` (добавьте `-skipBackupCompleteCheck` для старых бэкапов);
3. Выгрузить нужный кусок серий через `/api/v1/export` и загрузить в прод через `/api/v1/import` (или переключить роль теневой на прод);
4. Свернуть теневую (`kill` + `rm -rf /data`).

Это безопаснее, чем чистить продовые данные вручную (`delete_series`) на живом кластере.

### 4. Полная потеря single-node инстанса (vmsingle)

**Предпосылки:** IaC (systemd unit / Docker-compose) воспроизводится, `-src` в объектном хранилище содержит full + инкременты, credentials доступны, порт `8428`.

Цель: вернуть vmsingle на новом хосте с данными из последнего бэкапа.

1. **Развернуть хост:** развернуть ОС, создать пользователя `victoriametrics`, создать `-storageDataPath` (пустой каталог, права пользователя) — IaC из Git;
2. **vmrestore из последнего бэкапа:**
   ```bash
   vmrestore \
     -storageDataPath=/var/lib/victoria-metrics \
     -src=s3://backups/victoria-metrics/prod/latest \
     -credsFilePath=/etc/victoriametrics/s3-creds
   # → инкремент + базовый full применяются автоматически
   ```
3. **Запустить vmsingle** с тем же `-storageDataPath` и `-retentionPeriod`, не меняя его:
   ```bash
   systemctl enable --now victoria-metrics
   ```
4. **Валидация:** данные на месте, health отвечает, запросы отдают серии:
   ```bash
   curl -sf http://localhost:8428/health        # → 200 OK / {}
   curl -sf 'http://localhost:8428/api/v1/query?query=up' | jq -e '.data.result | length > 0' || exit 1
   curl -sf 'http://localhost:8428/api/v1/status/tsdb' | jq -r '.data.totalSeries'  # > 0
   ```
5. **Перепривязка:** обновить запись в DNS/Load Balancer и вернуть в прод.

> Для Enterprise-хранилищ используйте vmbackupmanager с restore mark: `vmbackupmanager restore create` создаёт метку, затем vmrestore читает её. Сценарий идентичен, но без ручного выбора `-src` — см. [vmbackup_restore](./vmbackup_restore.md#восстановление-vmrestore).

## Валидация установки (тест восстановления)

Регулярный (не реже 1 раза в месяц) прогон в CI/по cron:

```bash
#!/usr/bin/env bash
set -euo pipefail
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

vmrestore -storageDataPath="$TMP" -src=s3://backups/victoria-metrics/latest

victoria-metrics -storageDataPath="$TMP" -httpListenAddr=:8499 &
sleep 10

# Проверка: данные на месте надёжно
curl -sf 'http://localhost:8499/health' || exit 1
curl -sf 'http://localhost:8499/api/v1/query?query=up' \
  | jq -e '.data.result | length > 0' || exit 1
curl -sf 'http://localhost:8499/snapshot/list' \
  | jq -e '.status == "ok"'
kill %1; wait %1 2>/dev/null || true
echo "OK: восстановилось"
```

Рекомендуется: рассылать результат (OK/FAIL) в чат/оповещение; при FAIL — вызов on-call инженера.

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| После restore нет части данных | Восстановлен не тот бэкап (инкремент без базового) | vmrestore собирает инкремент сам; не удаляйте старые бэкапы из `-src` |
| VM «мёртв» после восстановления | Vmrestore выполнялся не на пустой каталог | Развернуть новую VM и повторить на пустой `-storageDataPath` |
| `snapshot not found` при live-бэкапе | Снапшот удалён до копии | Disaster-процедура: не удалять снапшоты, пока vmbackup не ответил успехом |
| Перезапуск после восстановления медленный (WAL replay) | Большой WAL | Нормально; следить `-inmemoryDataFlushInterval`, не гасить `kill -9` |
| Потери последних минут данных | RPO > 0 (бэкап раз в N ч), RF=1 | Поднять периодичность бэкапа / включить RF≥2 для критичных серий |
| `backup complete` error при restore | Старый бэкап без маркера завершения | Добавить флаг `-skipBackupCompleteCheck` |
| Бэкап VictoriaLogs не создаётся | Порт `9428` вместо `8428` для snapshot.createURL | Использовать `-snapshot.createURL=http://localhost:9428/snapshot/create` |
| Restore завис на загрузке | Мало воркеров / медленное хранилище | Увеличить `-concurrency`, ограничить `-maxBytesPerSecond` |

## Рекомендации по эксплуатации

- **Бэкап в отдельной зоне/дата-центре** от продовых нод и отдельный тестовый кластер для restore;
- Республицируйте **runbook тестового restore** (см. «Валидация установки») — он должен проходить без ручных действий;
- Поднимайте RF для критичных метрик, а не всё: RF вдвое умножает затраты на хранение (емкость ×RF);
- Настроить retention бэкапов (vmbackupmanager Enterprise или cron) — иначе старые копии займут весь объектный стор;
- Документируйте RPO/RTO и согласуйте с продуктом/командой — это критерий «готовности» инфраструктуры.

## Ограничения и особые случаи

- vmrestore требует **остановленного** сервиса; при необходимости RTO<часа — держите «горячий» standby (теневой инстанс, обновляемый бэкапом), а не cold-restore;
- Бэкап кластера поузлово: восстановление тоже поузлово — все ноды должны вернуться в одном составе, иначе шарды не совпадут;
- Shared-Nothing: нельзя восстановить один `vmstorage` на другой с другими данными — только в исходный состав;
- Удаление серий (`delete_series`) не откатывается точечно без бэкапа: для безопасного «отката» используйте теневой инстанс из бэкапа (сценарий 3).

## Очистка окружения после DR

После успешного восстановления и возврата в прод обязательно уберите временные артефакты, чтобы не платить за хранение и не создавать путаницу в следующем инциденте:

```bash
# 1. Остановить и удалить теневые/shadow-инстансы, поднятые для DR
systemctl stop victoria-metrics-shadow || true
rm -f /etc/systemd/system/victoria-metrics-shadow.service

# 2. Очистить временные каталоги восстановления (если восстанавливали в /tmp)
rm -rf "$TMP_RESTORE_DIR"

# 3. Удалить резервные снапшоты, созданные только для DR-восстановления
for snap in $(curl -s http://vmstorage-0:8482/snapshot/list | jq -r '.snapshots[].name'); do
  curl -s -XDELETE "http://vmstorage-0:8482/snapshot/$snap" | jq .
done

# 4. Проверить, что -storageDataPath НЕ переполнен временными файлами
df -h /var/lib/vmstorage
ls /var/lib/vmstorage/snapshots/  # должно быть пусто после vmbackup
```

- **Теневые инстансы:** выключайте (а не просто `kill`) — чтобы корректно закрыть WAL и партиции;
- **Бэкапы в `-src`:** не удаляйте из хранилища сразу — оставьте на период `retention` (обычно 2 недели+), пока не убедитесь, что восстановление работает стабильно;
- **Старые снапшоты в `-storageDataPath/snapshots/`:** удаляйте вручную, если `vmbackup` был прерван и не успел удалить снапшот автоматически — иначе они заполнят диск.

## Дополнительная информация

### См. также

- [vmbackup / vmrestore](./vmbackup_restore.md) — механика инкрементного бэкапа и восстановления;
- [Операции с кластером](./cluster_operations.md) — состав vmstorage, RF, диагностика частичных ответов;
- [HTTP API: снапшоты](./http_api_reference.md) — `/snapshot/create`, `/snapshot/list`;
- [VictoriaMetrics: обзор](./overview.md) — capacity-планирование, флаги retention;
- [Общее: стратегии DR](./../Concepts/disaster_recovery.md) — методология, Tier, матрица паттернов.
