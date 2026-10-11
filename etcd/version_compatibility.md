# Совместимость версий и обновление etcd

**Актуально для:** etcd 3.5.x / 3.6.x / 3.7.x

**etcd** имеет строгую политику версионирования. Обновление и откат в production — регламентные операции, требующие планирования и валидации. Понимание совместимости версий критично для безопасности и стабильности кластера.

## Определения

| Термин | Описание |
| :--- | :--- |
| **v2 API** | Устаревший HTTP/JSON API. Флаг `--enable-v2` удалён в 3.6 (включить нельзя); v2store полностью удалён в 3.7. |
| **v3 API** | gRPC/Protobuf API. Стабилен с etcd 3.0: ответы API не меняются, добавляются только новые возможности. |
| **Rolling upgrade** | Поэтапное обновление узлов кластера по одному без остановки работы. |
| **Downgrade** | Откат на предыдущую minor-версию. Штатная процедура с etcd 3.6 через `etcdctl downgrade enable`; только по одной minor-версии за раз. |
| **Mixed-version state** | Состояние кластера, в котором узлы работают на разных версиях во время rolling upgrade/downgrade. |
| **Cluster version** | Версия протокола кластера. Определяется наименьшей версией участника; автоматически повышается после обновления всех узлов. |
| **Storage version** | Версия схемы хранения данных. Мигрируется автоматически при включении downgrade; видна в `etcdctl endpoint status`. |
| **Feature gate** | Именованный переключатель функциональности (`--feature-gates=<name>=true\|false`). Фреймворк введён в 3.6. |
| **etcdutl** | Утилита для офлайн-операций со снапшотами и data-dir. Доступна с 3.6. |

---

## Основные концепции

### Версионирование etcd

- Версии следуют SemVer: `major.minor.patch` (например, 3.6.15).
- Поддерживаются текущая и предыдущая release-ветки: с выходом 3.6 ветка 3.4 вышла из поддержки.
- **Patch-обновление** внутри одной minor-версии — регламентная операция, выполняется в любом порядке по узлам.
- **Minor-обновление** — строго по одной версии за раз (3.5 → 3.6 → 3.7). Пропуск версий не поддерживается и, вероятно, завершится ошибкой.
- Перед minor-обновлением все узлы должны быть на последнем patch-релизе своей ветки (требования — в сценариях ниже).

### v2 API и v3 API

| Аспект | v2 | v3 |
| :--- | :--- | :--- |
| **Протокол** | HTTP/JSON | gRPC/Protobuf |
| **Endpoint** | `/v2/keys/...` | gRPC-сервисы (`etcdserver.KV`, `etcdserver.Watch` и др.) |
| **Atomic CAS** | Compare-and-swap через условия `prevValue`/`prevIndex`/`prevExist` | Только через Txn (`cmp` + success/failure) |
| **TTL** | Устанавливается на запись | Через Lease (отдельный механизм) |
| **Watch** | Long-polling HTTP | gRPC stream |
| **Transactions** | Ограниченные (compare-and-swap) | Полноценные (cmp + success/failure) |
| **Storage** | Отдельный store | Единый MVCC-стор |

**Хронология удаления v2:**
- **3.5:** v2 API доступен через `--enable-v2` (выключен по умолчанию); дефолт `--v2-deprecation=not-yet`.
- **3.6:** флаг `--enable-v2` удалён — включить v2store нельзя. etcd не стартует, если data-dir содержит v2-данные (кроме membership-данных). Дефолт `--v2-deprecation` изменён на `write-only`. Проверить наличие v2-данных заранее: `etcdutl check v2store` (утилита с 3.5.18; в 3.5.32+ проверяет также WAL-записи).
- **3.7:** v2store удалён полностью — v2 HTTP API, `--experimental-enable-v2v3`, v2 discovery, клиентская библиотека `client/v2` и загрузка v2-снапшотов.

**Миграция с v2 на v3:**
```bash
# Проверить наличие v2-данных перед апгрейдом на 3.6+
etcdutl check v2store

# Прочитать v2-данные через API (для выгрузки в v3)
curl -s http://127.0.0.1:2379/v2/keys/?recursive=true | jq .
```
Миграция приложений с v2 на v3 описана в официальной странице «Migrate applications from using API v2 to API v3».

### Совместимость участников кластера

- **Mixed-version state:** кластер поддерживает узлы разных версий и работает на протоколе наименьшей версии. Кластер считается обновлённым только когда все узлы обновлены; cluster version повышается автоматически.
- **Снапшоты:** снапшот восстанавливается на etcd той же major.minor-версии (любой patch). Снапшот 3.6 нельзя восстановить на 3.5 — для cross-minor восстановления используйте логический backup или штатный downgrade.
- **Откат:** формальный механизм `etcdctl downgrade enable` появился в 3.6 (см. сценарий «Rolling downgrade»).

### Совместимость клиента и сервера

etcd не публикует официальную матрицу совместимости клиент↔сервер. Верифицировано:
- v3 API стабилен с etcd 3.0 — ответы не меняются, добавляются только новые возможности.
- Новые возможности API требуют соответствующего сервера: например, RangeStream API в etcd 3.7 (используется kube-apiserver в K8s 1.37 через feature gate `EtcdRangeStream`).

**Рекомендация:** держать версии клиентских SDK и сервера в одной minor-линии; перед апгрейдом сервера проверять совместимость клиентских библиотек с новой minor-версией.

### Совместимость с Kubernetes

| Kubernetes | Поддерживаемый etcd | Примечание |
| :--- | :--- | :--- |
| 1.28 | 3.5.9+ | минимальный patch |
| 1.29 | 3.5.10+ | минимальный patch |
| 1.30 | 3.5.13+ | минимальный patch |
| 1.31–1.33 | 3.5.14+ (в поздних сборках 3.5.23/3.5.24) | только линия 3.5.x |
| 1.34 | 3.6.x (3.5.x также поддерживается) | переход по умолчанию на 3.6 |
| 1.35–1.36 | 3.6.x | «1.34 и выше» по гайду etcd |
| 1.37 | 3.6.x; опционально 3.7.x | feature gate `EtcdRangeStream` (Beta, включён по умолчанию) |

**Важно:**
- Минимальные рекомендуемые версии etcd для production по документации Kubernetes: **3.4.29+ и 3.5.11+**.
- Kubernetes использует официальные etcd-образы (`registry.k8s.io/etcd`); версия фиксируется в `build/dependencies.yaml` и константах kubeadm (`DefaultEtcdVersion`, `SupportedEtcdVersion`).
- При апгрейде Kubernetes проверяйте release notes: минимальная поддерживаемая версия etcd может потребовать обновления etcd до обновления control plane.
- **EtcdRangeStream (K8s 1.37):** при включённом gate и etcd 3.7+ kube-apiserver читает большие коллекции из etcd потоком вместо постраничного чтения, снижая пиковое потребление памяти. Если бэкенд не реализует RangeStream RPC, API server детектирует gRPC `Unimplemented` и откатывается на постраничные чтения. Для не-etcd бэкендов/proxy без чистого fallback отключите gate: `--feature-gates=EtcdRangeStream=false`. Потоковые чтения записываются как `operation="listStream"` в метрике `etcd_request_duration_seconds` — обновите дашборды и алерты, фильтрующие `operation="list"`.

### Feature Gates (v3.6+)

Фреймворк feature gates введён в etcd 3.6 (в 3.5 экспериментальные функции включаются флагами `--experimental-*`). Некоторые функции требуют явного включения:

| Feature Gate | Версия | Назначение |
| :--- | :--- | :--- |
| `LeaseCheckpoint` | v3.6+ (в 3.4/3.5 — флаг `--experimental-enable-lease-checkpoint`) | Checkpoint lease TTL: remaining TTL реплицируется через Raft каждые 5 мин (Alpha, default false) |
| `LeaseCheckpointPersist` | v3.6+ | Persist remainingTTL в локальный backend при cluster version < 3.6 (Alpha, default false; при cluster version ≥ 3.6 persist выполняется автоматически при включённом LeaseCheckpoint) |
| `FastLeaseKeepAlive` | v3.7 | Ускорение продления leases: пропуск ожидания applied index (Beta, default true) |

```bash
# Включение feature gate
etcd --feature-gates=LeaseCheckpoint=true ...
```

---

## Практические сценарии

### Проверка версий кластера

```bash
# Версия установленных бинарей
etcd --version
# → etcd Version: 3.7.2
etcdctl version
# → etcdctl version: 3.7.2

# Версия сервера и кластера через API
curl -s http://localhost:2379/version
# → {"etcdserver":"3.7.2","etcdcluster":"3.7.0","storage":"3.7.0"}
# В 3.6+ возвращается также поле storage; в 3.5 его нет:
# → {"etcdserver":"3.5.34","etcdcluster":"3.5.0"}

# Версия и storage version каждого узла
etcdctl --endpoints=https://127.0.0.1:2379 endpoint status -w table
# → столбцы VERSION и STORAGE VERSION для каждого узла

# Метрика версии (Prometheus)
curl -s http://localhost:2379/metrics | grep '^etcd_server_version'
# → etcd_server_version{server_version="3.7.2"} 1
```

### Rolling upgrade: etcd 3.5 → 3.6

**Требования:**
- Все узлы на **3.5.32+** (последний patch линии 3.5).
- Отсутствие v2-данных: `etcdutl check v2store` (в 3.5.32+ проверяет также WAL-записи). Если v2store содержит данные — мигрировать на v3 до апгрейда.
- Удалить из конфига флаги, удалённые в 3.6: `--enable-v2`, `--experimental-enable-v2v3`, `--proxy`, `--proxy-failure-wait`, `--proxy-refresh-interval`, `--proxy-dial-timeout`, `--proxy-write-timeout`, `--proxy-read-timeout`.
- Заменить experimental-флаги на feature gates (таблица ниже); остальные `--experimental-*` флаги 3.5 переименованы в стабильные (без префикса): `--experimental-max-learners` → `--max-learners`, `--experimental-snapshot-catchup-entries` → `--snapshot-catchup-entries`, `--experimental-compaction-batch-limit` → `--compaction-batch-limit` и т.д. Полный список: `diff <(etcd-3.5/bin/etcd -h | grep -- '--') <(etcd-3.6/bin/etcd -h | grep -- '--')`.
- Учесть новые дефолты 3.6: `--snapshot-count=10000` (было 100000), `--v2-deprecation=write-only` (было `not-yet`), `--discovery-fallback=exit` (было `proxy`). Флаги discovery (`--discovery-*`) стали стабильными.

| 3.5 (`--experimental-*`) | 3.6 |
| :--- | :--- |
| `--experimental-compact-hash-check-enabled=true` | `--feature-gates=CompactHashCheck=true` |
| `--experimental-initial-corrupt-check=true` | `--feature-gates=InitialCorruptCheck=true` |
| `--experimental-enable-lease-checkpoint=true` | `--feature-gates=LeaseCheckpoint=true` |
| `--experimental-enable-lease-checkpoint-persist=true` | `--feature-gates=LeaseCheckpointPersist=true` |
| `--experimental-stop-grpc-service-on-defrag=true` | `--feature-gates=StopGRPCServiceOnDefrag=true` |
| `--experimental-txn-mode-write-with-shared-buffer=false` | `--feature-gates=TxnModeWriteWithSharedBuffer=false` |

**Процедура (официальный гайд):**

1. Проверить здоровье кластера:
   ```bash
   etcdctl --endpoints=https://10.0.0.1:2379,https://10.0.0.2:2379,https://10.0.0.3:2379 endpoint health
   # → https://10.0.0.1:2379 is healthy: successfully committed proposal: took = 1.05ms
   ```
2. Сделать снапшот **с лидера** (лидер гарантированно содержит последние данные):
   ```bash
   etcdctl --endpoints=https://10.0.0.1:2379 snapshot save /backup/pre-upgrade-35.db
   # → Snapshot saved at /backup/pre-upgrade-35.db
   etcdutl --write-out=table snapshot status /backup/pre-upgrade-35.db
   ```
3. Остановить один узел. Graceful stop передаёт лидерство автоматически — специальный порядок узлов не регламентирован:
   ```bash
   systemctl stop etcd
   ```
4. Установить etcd 3.6.x и запустить узел с прежним конфигом (с учётом маппинга флагов выше).
5. Проверить здоровье узла и кластера, повторить шаги 3–4 для остальных узлов.
6. Валидация: все узлы показывают VERSION 3.6.x; cluster version автоматически переключится на 3.6 после обновления последнего узла.

**Новые метрики в 3.6:** `etcd_network_known_peers`, `etcd_server_feature_enabled`.

### Rolling upgrade: etcd 3.6 → 3.7

**Требования:**
- Все узлы на **3.6.11+** (последний patch линии 3.6).
- Все `--experimental-*` флаги удалены в 3.7 — процесс **не стартует**, если они остались в конфиге. Используйте стабильные эквиваленты или `--feature-gates`.
- Новых флагов и изменений дефолтов в 3.7 нет.

**Процедура:** аналогична 3.5 → 3.6 (снапшот с лидера → остановка одного узла → запуск с новым бинарём и тем же конфигом → проверка health → повтор).

**Изменения 3.7 (для сборок и embedding):** Go-рефакторинг — gogo/protobuf → google.golang.org/protobuf, go-grpc-middleware v1 → v2, otelgrpc v0.61.0. На операции кластера не влияет.

### Rolling downgrade: etcd 3.7 → 3.6 (и 3.6 → 3.5)

Штатный механизм downgrade появился в 3.6. Downgrade возможен только на **одну minor-версию** (3.7 → 3.5 нельзя).

**Процедура (официальный гайд):**

1. Проверить здоровье: `etcdctl endpoint health`.
2. Сделать снапшот **с лидера** — страховка на случай проблем.
3. Валидация целевой версии:
   ```bash
   etcdctl downgrade validate 3.6
   # → Downgrade validate success, cluster version 3.7
   ```
4. Включить downgrade — кластер переключается на протокол целевой версии и автоматически мигрирует схему хранения (storage version), даже пока все узлы ещё работают на старом бинаре:
   ```bash
   etcdctl downgrade enable 3.6
   # → Downgrade enable success, cluster version 3.7

   etcdctl endpoint status -w table
   # → STORAGE VERSION: 3.6.0, DOWNGRADE ENABLED: true на всех узлах
   ```
5. Останавливать узлы по одному, **лидера — последним**. Перед остановкой лидера передайте лидерство, чтобы избежать даунтайма:
   ```bash
   etcdctl move-leader <ID_ДРУГОГО_УЗЛА>
   # → Leadership transferred from 7339c4e5e833c029 to 729934363faa4a24
   ```
6. Запустить остановленный узел на бинаре 3.6 с тем же конфигом. Для 3.6 → 3.5 дополнительно убрать/переименовать флаги, появившиеся в 3.6 (см. ниже).
7. Повторить для остальных узлов. Когда все узлы понижены, downgrade завершается автоматически (`DOWNGRADE ENABLED` сбрасывается в false).

**Отмена downgrade в mixed-version state:** `etcdctl downgrade cancel` и перезапуск пониженных узлов на исходном бинаре. После полного downgrade возврат возможен только через повторный апгрейд по официальному гайду.

**Особенности 3.6 → 3.5:**
- Флаги, недоступные в 3.5 (появились в 3.6): `--discovery-*`, `--feature-gates`, `--log-format`.
- Переименовать стабильные флаги обратно в `--experimental-*`: `--max-learners` → `--experimental-max-learners`, `--snapshot-catchup-entries` → `--experimental-snapshot-catchup-entries`, `--compaction-batch-limit` → `--experimental-compaction-batch-limit` и т.д.
- Дефолты возвращаются к прежним: `--snapshot-count=100000`, `--v2-deprecation=not-yet`, `--discovery-fallback=proxy`.
- Метрики, появившиеся в 3.6 (`etcd_network_known_peers`, `etcd_server_feature_enabled`) и 3.7 (`etcd_server_request_duration_seconds`, `etcd_debugging_server_watch_send_loop_*`), в старых версиях недоступны.
- Статус-эндпоинт 3.5 не показывает информацию о downgrade: на пониженных до 3.5 узлах `DOWNGRADE ENABLED` не отображается, хотя для кластера downgrade всё ещё включён.

### Откат после обновления (rollback)

- **Mixed-version state** (не все узлы обновлены): заменить бинари/образы на предыдущую версию и перезапустить узлы. Для формального downgrade — `etcdctl downgrade cancel` и перезапуск на исходном бинаре.
- **Все узлы обновлены:** восстановление из снапшота, сделанного до обновления (восстанавливается на той же major.minor), или штатный downgrade по гайду.
- Снапшот более новой minor-версии на старую версию не восстанавливается — используйте логический backup (`etcdctl get --prefix --keys-only` + повторная запись) или промежуточный кластер.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| etcd не стартует после апгрейда на 3.6 | в data-dir остались v2-данные (кроме membership-данных) | мигрировать данные на v3; проверять `etcdutl check v2store` до апгрейда |
| etcd не стартует после апгрейда на 3.7 | в конфиге остались `--experimental-*` флаги | удалить их; использовать стабильные эквиваленты или `--feature-gates` |
| `remotes server has mismatching etcd version` в логах | mixed-version state во время rolling upgrade/downgrade | нормально; исчезает после обновления всех узлов |
| `etcdserver: request is too large` после обновления | клиент использует старый max-request-bytes | проверить флаг `--max-request-bytes` на новом сервере |
| `mvcc: required revision has been compacted` | watcher отстал от compaction | обновить клиентский код; увеличить `--auto-compaction-retention` |
| Снапшот не восстанавливается | снапшот другой major.minor-версии | восстанавливать на исходной версии; для cross-minor — логический backup |
| Лидер flapping после обновления | clock skew или disk latency на новом узле | проверить NTP, latency `fdatasync` |

---

## Best Practices

- **Перед minor-апгрейдом** — последний patch-релиз ветки (3.5.32+ / 3.6.11+).
- **Снапшот — с лидера** перед обновлением и downgrade: лидер гарантированно содержит последние данные. Проверять снапшот: `etcdutl snapshot status`.
- **Обновлять по одному узлу**, после каждого — проверять `etcdctl endpoint health`.
- **При downgrade — лидера последним**, с предварительным `move-leader` для избежания даунтайма.
- **Не пропускать minor-версии** (3.5 → 3.7 напрямую не поддерживается).
- **Тестировать в staging** перед production (официальная рекомендация).
- **Feature gates:** не включать экспериментальные gates в production без тестирования.
- **Для Kubernetes:** проверять release notes на минимальные поддерживаемые версии etcd перед апгрейдом control plane.

---

## Edge Cases

- **Cluster ID mismatch:** при восстановлении из снапшота с другим `cluster-token` etcd отклонит подключение. Используйте `--initial-cluster-token` при `snapshot restore`.
- **Downgrade через 2 версии:** невозможен (например, 3.7 → 3.5). Требуется промежуточный кластер или логическая миграция.
- **v2-данные:** в 3.6 нельзя включить v2store (`--enable-v2` удалён); etcd не стартует, если data-dir содержит v2-данные. В 3.7 v2store удалён полностью — загрузка v2-снапшотов невозможна.
- **K8s 1.37 + etcd < 3.7:** gate `EtcdRangeStream` включён, но API server автоматически откатывается на постраничные чтения (gRPC `Unimplemented`). Для не-etcd бэкендов без чистого fallback — отключить gate.
- **etcd 3.5 в статусе:** статус-эндпоинт 3.5 не показывает столбцы DOWNGRADE — информацию о downgrade смотрите на узлах 3.6+.

---

## См. также

* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — rolling upgrade и замену узлов.
* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — feature gates.
* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — snapshot save/restore.
* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики версий и feature gates.
* [Upgrading etcd clusters and applications](https://etcd.io/docs/v3.7/upgrades/) — официальные гайды апгрейда.
* [Downgrading etcd clusters and applications](https://etcd.io/docs/v3.7/downgrades/) — официальные гайды downgrade.
* [Operating etcd clusters for Kubernetes](https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/) — etcd в Kubernetes.
