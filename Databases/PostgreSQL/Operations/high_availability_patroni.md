# Отказоустойчивый кластер PostgreSQL (Patroni, etcd, HAProxy)

## Определения

**Patroni** — высокодоступный шаблон (Python-приложение) для управления кластерами PostgreSQL. Обеспечивает автоматический Failover, управление конфигурацией и мониторинг состояния инстансов. Он «оборачивает» процесс БД, превращая его в управляемый компонент HA-стека.

**etcd** — распределенное отказоустойчивое хранилище типа «ключ-значение». Используется Patroni как **DCS (Distributed Configuration Store)** для хранения состояния кластера, конфигурации и реализации механизма распределенных блокировок (Leader Election) на базе алгоритма консенсуса **Raft**. Детали защиты от двух лидеров — в **[Обзоре Raft в etcd](../../../etcd/raft_consensus.md#механизм-против-двух-лидеров-anti-split-brain)**.

**Watchdog** — механизм защиты («сторожевой таймер»), принудительно перезагружающий ОС в случае зависания Patroni или потери связи с DCS. Это гарантирует, что узел не останется мастером в изолированном состоянии, исключая возникновение **Split Brain**.

**Failover** — автоматический процесс переключения ролей в кластере при выходе из строя мастера.

**Switchover** — плановый и контролируемый перенос роли мастера на один из резервных узлов (например, для обслуживания железа или обновления ядра ОС).

**Fencing (Изоляция)** — метод принудительного отсечения старого мастера от ресурсов, чтобы предотвратить одновременную запись с двух узлов.

## Архитектура стека

Типовая схема включает 3 узла базы данных для обеспечения кворума в DCS.

```text
      [ Клиент / Приложение ]
               |
        [ VIP / DNS Name ]
               |
      [ HAProxy + Keepalived ] (2-3 ноды)
               |
    -----------------------
    |          |          |
[ Узел 1 ] [ Узел 2 ] [ Узел 3 ]
| Patroni| | Patroni| | Patroni|
| Postgre| | Postgre| | Postgre|
|Watchdog| |Watchdog| |Watchdog|
    \          |          /
     \--- [ etcd кластер ] ---/
```

### Роли компонентов

1.  **PostgreSQL:** Непосредственно хранение и обработка данных. Работает в режиме `Primary` (чтение/запись) или `Replica` (только чтение, асинхронная или синхронная репликация).
2.  **Patroni:**
    -   Запускает и управляет процессом PostgreSQL.
    -   Удерживает **Leader Lock** в etcd через периодические Heartbeats (обычно каждые 10 секунд, настраивается через `loop_wait`).
    -   Взаимодействует с ядром через `/dev/watchdog` для обеспечения безопасности на уровне ОС.
    -   Предоставляет REST API для проверок состояния (порты 8008 по умолчанию: `/master`, `/replica`, `/primary`).
3.  **etcd:**
    -   Хранит конфигурацию кластера и текущую позицию WAL (LSN) каждого узла.
    -   Служит механизмом блокировок (Locks) для предотвращения ситуации "Split Brain".
    -   Обеспечивает консистентность состояния кластера.
4.  **HAProxy:**
    -   Опрашивает REST API Patroni на каждом узле.
    -   Узел, вернувший HTTP 200 на эндпоинт `/master` (или `/primary`), помечается как `UP` в пуле для записи.
    -   Узлы, вернувшие 200 на `/replica`, могут использоваться для балансировки запросов на чтение (Read Scaling).

## Механизмы защиты: Watchdog и Fencing

Критически важно предотвратить ситуацию, когда два узла одновременно считают себя мастерами (Split Brain).

### Split Brain в Patroni: детальный разбор

**Split Brain** — состояние, при котором в кластере одновременно существует два или более активных Primary (мастера), принимающих запись. В PostgreSQL это приводит к необратимой порче данных, так как репликационная связь между двумя Primary невозможна (PostgreSQL не поддерживает Multi-Primary).

#### Сценарии возникновения

1.  **Партиция сети DCS:** Узел-мастер продолжает работать, но теряет связь с etcd/Consul. Patroni на этом узле не может обновить Leader Key (TTL истекает), но сам процесс PostgreSQL остается доступным для записи. В этот момент другая часть кластера, имеющая кворум DCS, выбирает нового мастера. Теперь два узла пишут данные параллельно.
2.  **Ошибка Fencing:** Patroni определяет, что связь с DCS потеряна, но по какой-то причине не останавливает PostgreSQL (например, сбой в скрипте fencing, ошибка прав доступа, зависание процесса). Узел продолжает принимать запись, в то время как DCS уже выбрала нового лидера.
3.  **Потеря кворума etcd:** При падении 2 узлов etcd из 3-х оставшийся узел не может получить кворум. Patroni на каждом узле PostgreSQL не может определить, является ли он лидером, и в зависимости от конфигурации может либо остановить БД, либо продолжить работу в `read-only`, либо перейти в состояние `promoted` без подтверждения DCS.
4.  **Грязный перезапуск ( unclean restart ):** После потери питания узел перезагружается быстрее, чем DCS фиксирует его состояние. Patroni запускается, видит отсутствие лидера в DCS и promotes себя, хотя старый мастер тоже уже жив и считает себя Primary.

#### Последствия

- **Необратимая рассинхронизация данных:** два Primary имеют разные наборы транзакций, которые невозможно автоматически слить.
- **Клиенты видят разные данные:** часть запросов идет на старый мастер, часть — на новый. Транзакционная согласованность нарушается.
- **Сложность восстановления:** требуется ручной анализ WAL, выбор "истории победителя" и принудительный сброс старого мастера.

#### Детекция

**Через логи Patroni:**
```bash
# Признак: узел потерял лидерство, но БД остается running
grep -i "cluster is not running in standalone mode" /var/log/patroni/patroni.log
grep -i "failed to acquire leader lock" /var/log/patroni/patroni.log
grep -i "running as a standalone" /var/log/patroni/patroni.log  # опасный сигнал
```

**Через REST API Patroni:**
```bash
# На каждом узле
curl -s http://localhost:8008/patroni | jq .role
# Должно быть: "leader" только на одном узле. Если "leader" на двух и более — split-brain.

curl -s http://localhost:8008/patroni | jq .state
# "running" + "role": "leader" = потенциальная проблема, если других лидеров нет
```

**Через PostgreSQL:**
```sql
-- На каждом узле
SELECT pg_is_in_recovery();
-- false = Primary. Если false на двух узлах одновременно — критично.

SELECT pg_current_wal_lsn();
-- Сравните LSN между узлами. Если оба Primary имеют разные LSN и оба не в recovery — проблема.
```

**Через HAProxy:**
```bash
echo "show stat" | socat /var/run/haproxy.sock stdio | grep -i postgres
# В колонке status может быть "UP" для нескольких мастеров одновременно
```

#### Восстановление после Split Brain

Алгоритм зависит от того, обнаружена ли проблема сразу или найдена постфактум:

**Сценарий A: Обнаружено сразу (два узла в состоянии Primary)**
1.  **Остановить один из узлов** через IPMI/iDRAC/iLO/VMware console (аппаратное fencing). Нельзя просто выключить PostgreSQL, так как это может не сработать.
2.  **На выжившем узле проверить данные:**
    ```bash
    sudo -u postgres psql -c "SELECT count(*) FROM critical_table;"
    ```
3.  **На stopped узле очистить data_dir** и перезапустить Patroni — он автоматически сделает `basebackup` от нового мастера.
4.  **Аудит:** проверьте, какие транзакции на stopped узле могли быть потеряны. Сравните `pg_wal` на обоих узлах.

**Сценарий B: Обнаружено постфактум (уже есть расхождение данных)**
1.  **Выбрать победителя:** узел с более актуальными данными (больше WAL LSN или более полный набор таблиц).
2.  **На проигравшем узле:**
    ```bash
    sudo systemctl stop patroni
    sudo -u postgres rm -rf /var/lib/postgresql/data/*
    sudo systemctl start patroni
    ```
3.  **Проверка консистентности:** после восстановления убедитесь, что `pg_stat_replication` показывает здоровое состояние.

**Важно:** Не пытайтесь автоматизировать recovery из split-brain. Каждый случай требует ручного анализа.

1.  **Watchdog (Software/Hardware):** Patroni периодически "кормит" собаку (сбрасывает таймер `/dev/watchdog`). Если Patroni зависнет (например, из-за 100% CPU или OOM), таймер истечет, и Watchdog вызовет немедленную перезагрузку (Kernel Panic / Reboot), гарантированно освобождая лидерский ключ.
2.  **Fencing:** Если узел теряет связь с etcd, Patroni немедленно переводит PostgreSQL в режим `read-only` или выключает его. Это регулируется параметром `master_start_timeout`. Если Patroni не может подтвердить лидерство в течение заданного времени, он обязан остановить БД.
3.  **DCS Quorum (Raft):** etcd обеспечивает, что только одна часть кластера может выбрать лидера. При partition только majority-сторона сохраняет кворум и может принимать решения. Minority сторона блокирует все операции записи.
4.  **STONITH (Shoot The Other Node In The Head):** Аппаратный или hypervisor-level fencing. В облачных средах (AWS, GCP, Azure) Patroni может интегрироваться с cloud API для принудительного отключения узла (например, `ec2-stop-instances`).
5.  **`maximum_lag_on_failover`:** Параметр Patroni, предотвращающий повышение реплики, если отставание от мастера превышает порог. Это защищает от promotion реплики с устаревшими данными в момент partition.

## Механизм Failover

Процесс переключения ролей происходит по следующему алгоритму:

1.  **Сбой мастера:** Мастер (Узел 1) падает или теряет сетевую связность с DCS.
2.  **Истечение TTL:** Leader Key в etcd имеет время жизни (TTL, обычно 30с). Поскольку Patroni на Узле 1 не может его обновить, ключ удаляется автоматически.
3.  **Выборы:** Patroni на репликах (Узел 2 и 3) замечают отсутствие мастера и начинают процесс выбора. Узел с наиболее актуальными данными (максимальным LSN) захватывает новый Leader Key.
4.  **Смена роли:** Выбранная реплика (например, Узел 2) переходит в режим `Master`.
5.  **Переключение трафика:** HAProxy при очередной проверке (раз в 2-3 секунды) видит, что Узел 1 недоступен, а Узел 2 теперь отвечает на запрос `/master`. Трафик мгновенно перенаправляется на Узел 2.

## Обеспечение отказоустойчивости балансировщика

Сам HAProxy может стать единой точкой отказа. Методы защиты:

-   **Keepalived (VRRP):** Несколько нод HAProxy разделяют один **Virtual IP (VIP)**. При падении активной ноды VIP переезжает на резервную за миллисекунды.
-   **DNS Round Robin:** За одним DNS-именем закреплено несколько IP-адресов балансировщиков. Клиент пробует их по очереди (менее надежно, зависит от TTL DNS).
-   **Headless Service (в Kubernetes):** Если приложение в K8s, оно может обращаться к Patroni напрямую через сервис, который обновляет свои Endpoints на основе проверок Patroni API.

---

## Практическая реализация

### 1. Подготовка окружения (Prerequisites)

- **ОС:** Рекомендуется Ubuntu 22.04+ или RHEL 8+.
- **Watchdog:** Убедитесь, что модуль `softdog` загружен (`modprobe softdog`) и доступен файл `/dev/watchdog`.
- **Сеть:** Открытые порты 5432 (DB), 8008 (API), 2379 (etcd).

### 2. Установка (на примере Ubuntu)

```bash
# PostgreSQL и Patroni
sudo apt install postgresql-16 python3-patroni python3-etcd3
# Или через pip для свежих версий
pip install patroni[etcd3]

# etcd (на 3-х узлах для кворума)
sudo apt install etcd
```

### 3. Пример конфигурации `patroni.yml`

```yaml
scope: pg_cluster
name: pg_node_1
namespace: /db/

etcd3:
  hosts: ["10.0.0.1:2379", "10.0.0.2:2379", "10.0.0.3:2379"]

restapi:
  listen: 0.0.0.0:8008
  connect_address: 10.0.0.1:8008

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576 # 1MB
    postgresql:
      use_pg_rewind: true
      parameters:
        wal_level: logical
        max_connections: 100
  initdb:
  - encoding: UTF8
  - data-checksums

postgresql:
  listen: 0.0.0.0:5432
  connect_address: 10.0.0.1:5432
  data_dir: /var/lib/postgresql/16/main
  bin_dir: /usr/lib/postgresql/16/bin
  authentication:
    replication: {username: replicator, password: rep_pass}
    superuser: {username: postgres, password: super_pass}

watchdog:
  mode: required
  device: /dev/watchdog
```

### 4. Настройка Health Check в HAProxy

```haproxy
listen postgres_master
    bind *:5432
    option httpchk GET /master
    http-check expect status 200
    default-server inter 2s fall 3 rise 2
    server pg_node_1 10.0.0.1:5432 check port 8008
    server pg_node_2 10.0.0.2:5432 check port 8008
    server pg_node_3 10.0.0.3:5432 check port 8008
```

### 5. Сценарий: Синхронная репликация (Zero Data Loss)

Если бизнес-требования запрещают потерю даже одной транзакции (RPO=0):

```yaml
# Через patronictl edit-config
postgresql:
  parameters:
    synchronous_commit: "on"
  use_pg_rewind: true
  synchronous_mode: true
  synchronous_node_count: 1 # Минимум одна реплика должна подтвердить запись
```
*Внимание: Если ни одна реплика не доступна, мастер перестанет принимать запись (заблокирует транзакции) до восстановления связности.*

### 6. Сценарий: Обслуживание кластера (Maintenance Mode)

Для проведения технических работ без срабатывания failover:

```bash
# Пауза автоматики
patronictl -c /etc/patroni.yml pause pg_cluster

# Теперь можно безопасно останавливать сервисы
sudo systemctl stop patroni

# Снятие паузы
patronictl -c /etc/patroni.yml resume pg_cluster
```

### 7. Интеграция Patroni с S3 (WAL-архивирование и бэкапы)

Patroni нативно поддерживает интеграцию с S3-совместимыми хранилищами для WAL-архивирования и создания бэкапов через **pgBackRest** или **WAL-G**.

**Конфигурация WAL-G с S3 в Patroni (DCS):**

```yaml
# patronictl edit-config
postgresql:
  parameters:
    archive_mode: "on"
    archive_command: "wal-g wal-push %p"
    restore_command: "wal-g wal-fetch %f %p"
  
  # Настройки pgBackRest (альтернатива WAL-G)
  pgbackrest:
    command: /usr/bin/pgbackrest --stanza=main archive-push %p
    keep_data: true
    no_params: true
  
  # Или использование pgBackRest для полных бэкапов
  recovery_conf:
    restore_command: "pgbackrest --stanza=main archive-get %f %p"
```

**Переменные окружения для доступа к S3:**

```bash
# Должны быть доступны процессу PostgreSQL
export WALG_S3_PREFIX=s3://bucket-name/path/to/wal
export AWS_ACCESS_KEY_ID=<key>
export AWS_SECRET_ACCESS_KEY=<secret>
export AWS_ENDPOINT_URL=https://s3.yandexcloud.net  # Для Yandex Cloud
export AWS_S3_FORCE_PATH_STYLE=true  # Важно для MinIO и Yandex Cloud
```

**Принцип работы:**
1.  Каждый WAL-файл при завершении (16 МБ) автоматически загружается в S3.
2.  При failover/switchover новая реплика может восстановить недостающие WAL-сегменты из S3.
3.  Полные бэкапы (через `pgbackrest backup` или `wal-g backup-push`) также загружаются в S3.
4.  **Point-in-Time Recovery (PITR):** Позволяет восстановить базу на любой момент времени, используя полный бэкап + WAL-архив из S3.

**Patroni + S3 внутри Kubernetes:**
При развертывании Patroni в Kubernetes (через Zalando Operator или чарты), доступ к S3 осуществляется через:
- **Kubernetes Secret** с ключами доступа, монтируемый как volume или переменные окружения.
- **IAM-роли для Service Account (IRSA в AWS, Workload Identity в GCP)** — более безопасный подход без хранения статических ключей.

---

## Устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Cluster has no leader** | etcd недоступен или потерян кворум. | Проверьте доступность `etcd` на порту 2379. Проверьте кворум: `etcdctl endpoint health`. |
| **Watchdog reboot loop** | Patroni не успевает сбросить таймер из-за нагрузки. | Увеличьте приоритет процесса Patroni (`nice -n -20`). Проверьте `loop_wait` и `ttl`. |
| **Node won't start (data_dir)** | Остались файлы от старого кластера. | Очистите `data_dir` (только для реплик!) и дайте Patroni сделать `basebackup`. |
| **Multiple Primaries** | Отсутствие Watchdog или ошибка Fencing. | 1) Аппаратно отключить проигравший узел. 2) Очистить его `data_dir`. 3) Проверить `watchdog: mode: required`. |
| **Split-brain после network partition** | Часть узлов изолирована, но DCS кворум сохранен в другой части. | Patroni автоматически завершит устаревшего лидера при восстановлении связи, если настроен Watchdog. |
| **Patroni не останавливает PostgreSQL при потере DCS** | Некорректный скрипт fencing или `master_start_timeout` слишком большой. | Уменьшите `master_start_timeout` до 30-60 сек. Проверьте права на выполнение fencing-скрипта. |
| **etcd: lost leader, but PostgreSQL still running** | Patroni завис на обновлении DCS, но не завершил БД. | Настройте `loop_wait` и `ttl` соответствующими друг другу (`ttl` должно быть больше `loop_wait` минимум в 2 раза). |

---

## Мониторинг и предотвращение Split-Brain

### Ключевые метрики и проверки

| Метрика / Проверка | Инструмент | Порог | Значение |
| :--- | :--- | :--- | :--- |
| `patroni_must_up` | Prometheus / curl | 1 | Patroni жив на всех узлах. |
| `etcd_health` | `etcdctl endpoint health` | healthy | Все узлы etcd доступны. |
| `pg_is_in_recovery` | SQL-запрос | false только на одном узле | Если `false` на двух и более — split-brain. |
| `patroni_role` | REST API `/patroni` | `leader` только на одном | Два `leader` = катастрофа. |
| `replication_lag` | `patronictl list` | < `maximum_lag_on_failover` | Большой лаг при падении мастера = риск потери данных при failover. |
| `watchdog_status` | `cat /proc/watchdog` или `wd_keepalive` | 1 | 0 = Watchdog не активен. |

### Автоматические проверки (Cron/Systemd)

```bash
#!/bin/bash
# /usr/local/bin/patroni_splitbrain_check.sh
LEADERS=$(for node in 10.0.0.1 10.0.0.2 10.0.0.3; do
    curl -sf http://$node:8008/patroni | jq -r .role
done | grep -c leader)

if [ "$LEADERS" -gt 1 ]; then
    echo "CRITICAL: Multiple leaders detected ($LEADERS)" | mail -s "PATRONI SPLIT-BRAIN" ops@example.com
    exit 2
elif [ "$LEADERS" -eq 0 ]; then
    echo "WARNING: No leader detected" | mail -s "PATRONI NO LEADER" ops@example.com
    exit 1
fi
echo "OK: Single leader"
```

### Рекомендации по конфигурации

1.  **`watchdog: mode: required`** — обязателен в production. Никогда не используйте `off` или `automatic` на production-базах.
2.  **`ttl` и `loop_wait`:** `ttl` должен быть минимум в 2-3 раза больше `loop_wait`. Рекомендуется `ttl: 30`, `loop_wait: 10`.
3.  **`master_start_timeout`:** Установите 30-60 секунд. Если узел не может подтвердить лидерство за это время — он должен остановить БД, а не ждать вечно.
4.  **Четное число узлов PostgreSQL:** Используйте 3 или 5 узлов. 2 узла дают риск split-brain при network partition (кворум etcd из 2 узлов невозможен).
5.  **Сетевая изоляция:** Убедитесь, что между узлами PostgreSQL и etcd есть стабильная связь с латентностью < 10 мс и packet loss < 0.1%.
6.  **Аппаратный Watchdog:** На физических серверах используйте IPMI/iDRAC/iLO Watchdog Timer. Программный (`softdog`) работает, но менее надежен при kernel panic.

---

## Вопросы на собеседованиях

1.  **Что такое Split Brain в контексте Patroni?**
    - Состояние, при котором два узла одновременно считают себя мастерами. Приводит к порче данных, так как PostgreSQL не поддерживает multi-primary.

2.  **Как Patroni предотвращает Split Brain?**
    - DCS (etcd) с алгоритмом Raft обеспечивает, что только один узел может владеть Leader Lock.
    - Watchdog: при зависании Patroni ядро перезагружает узел.
    - Fencing: при потере связи с DCS узел переводит БД в read-only или останавливает.
    - STONITH: аппаратное отключение проигравшего узла.

3.  **Что такое Fencing и зачем он нужен?**
    - Метод принудительного отсечения старого мастера от ресурсов (остановка PostgreSQL, перезагрузка узла). Гарантирует, что старый мастер не может продолжать запись после того как новый мастер уже выбран.

4.  **Чем отличается software Watchdog от hardware Watchdog?**
    - Software (`softdog`): работает на уровне kernel module, сбрасывается из userspace. Не защищает при kernel panic или OOM.
    - Hardware: интегрирован в BMC (iDRAC/iLO/IPMI). Срабатывает даже при kernel panic. Более надежен, но требует поддержки железа.

5.  **Что такое `master_start_timeout` и как он помогает?**
    - Максимальное время, которое Patroni ждет перед тем как остановить PostgreSQL, если не может подтвердить лидерство в DCS. Защищает от "мертвого мастера", который продолжает писать, но не может обновить TTL.

6.  **Что такое `maximum_lag_on_failover`?**
    - Порог отставания реплики (в байтах), при превышении которого реплика не может быть повышена до мастера. Защищает от потери данных при failover, если реплика не дождалась всех WAL-сегментов.

7.  **Как обнаружить, что в кластере два мастера?**
    - `SELECT pg_is_in_recovery()` — должен возвращать `false` только на одном узле.
    - `curl http://<node>:8008/patroni | jq .role` — `leader` должен быть только на одном узле.
    - `patronictl list` — показывает статус каждого узла.

8.  **Что делать, если вы обнаружили Split Brain?**
    - Немедленно остановить один из мастеров (аппаратно или через hypervisor).
    - На выжившем узле проверить целостность данных.
    - На stopped узле очистить `data_dir` и позволить Patroni сделать `basebackup`.
    - Провести аудит потерь данных.

9.  **Почему 2 узла для PostgreSQL + Patroni — плохая идея?**
    - При 2 узлах etcd + 2 узлах PostgreSQL потеря одного узла приводит к потере кворума. Patroni не может выбрать лидера. Используйте минимум 3 узла.

10. **В чем разница между Failover и Switchover?**
    - Failover: автоматическое или ручное переключение при аварии старого мастера. Может привести к потере данных (uncommitted transactions).
    - Switchover: плановый перенос роли. Синхронная репликация гарантирует RPO=0.

| Фактор | PostgreSQL в Kubernetes | PostgreSQL на ВМ |
| :--- | :--- | :--- |
| **Управление** | Через операторы (Zalando, CloudNativePG). | Ручное или через Ansible (Patroni). |
| **Автоматизация** | Встроена в оператор (самоисцеление, бэкапы). | Требует настройки внешних инструментов (Barman, WAL-G). |
| **Команда** | Подходит для продуктовых команд (DevOps-style). | Предпочтительно при наличии выделенного отдела DBA. |
| **Сложность** | Высокая (требует глубокого знания K8s Networking/Storage). | Средняя (классический стек). |
| **Fencing** | Lease API Kubernetes (облачный). | Аппаратный/Программный Watchdog. |

---

## Дополнительная информация

**См. также:**

- [Отказоустойчивость PostgreSQL](../Concepts/high_availability.md) — теория RPO/RTO и механизмы DCS.
- [Репликация в PostgreSQL](../Concepts/replication.md) — SSoT по типам репликации.
- [Обзор etcd](../../../etcd/architecture-and-concepts.md) — архитектура хранилища конфигураций.
- [Zalando Postgres Operator](./zalando_postgres_operator.md) — эксплуатация стека в Kubernetes.
- [Безопасная установка СУБД](../../installation_security.md) — общие принципы защиты баз данных.

**Инструменты:** `Patroni`, `etcd`, `HAProxy`, `Keepalived`, `Watchdog`, `patronictl`.
