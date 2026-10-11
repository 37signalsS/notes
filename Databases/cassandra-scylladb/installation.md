# Установка и первоначальная настройка

**Актуально для:** Apache Cassandra 5.0.x (актуальный патч 5.0.9; образ `cassandra:5.0`, репозиторий `50x`) / ScyllaDB 2026.x (актуальный патч 2026.3.2; LTS — 2026.1)

## Определения

- **Seed-узел** — адрес первого контакта для gossip-протокола. Seed — не специальная роль: любой узел может быть seed, важно лишь, чтобы адреса в `seeds` были стабильными и доступными.
- **Gossip** — протокол обмена состоянием узлов кластера (доступность, нагрузка, версия, топология).
- **Snitch** — компонент, определяющий сетевую топологию (datacenter/rack) для маршрутизации реплик.
- **vNode (virtual node)** — диапазон токенов, назначенный узлу. Количество vNode задаётся параметром `num_tokens` (дефолт 16 с Cassandra 4.0).
- **THP (Transparent Huge Pages)** — механизм ядра Linux, деградирующий производительность Cassandra; должен быть отключён.
- **commitlog** — write-ahead log: каждая запись сначала фиксируется на диске, затем попадает в MemTable.
- **cqlsh / nodetool** — CLI-утилиты: интерактивная оболочка CQL и инструмент администрирования кластера.

## Выбор метода установки

| Метод | Когда использовать | Особенности |
| :--- | :--- | :--- |
| Docker Compose | dev, тест, POC | быстрый старт, изоляция; не подходит для production-нагрузок |
| Bare-metal (deb/rpm/tarball) | production on-prem | полный контроль тюнинга ОС (THP, sysctl, диски, лимиты) |
| Kubernetes | production с оркестрацией | cass-operator / ScyllaDB Operator / K8ssandra — см. [Развёртывание в Kubernetes](./kubernetes.md) |

**Что происходит при первом запуске:** узел связывается по gossip с seed-узлами из `seeds`, формирует ring, создаёт системный keyspace `system` и запускает native transport (порт 9042). При присоединении к существующему кластеру с данными узел выполняет bootstrap — стриминг своих диапазонов токенов с других узлов.

### Версии Cassandra

| Версия | Актуальный патч | Статус | Поддержка до |
| :--- | :--- | :--- | :--- |
| 5.0.x | 5.0.9 (2026-08-07) | Current | выхода 8.0 |
| 4.1.x | 4.1.12 | Previous stable | выхода 7.0 |
| 4.0.x | 4.0.21 | Older stable | выхода 6.0 |
| 3.11.x | — | EOL, unmaintained | — |

**Java:** Cassandra 5.0 работает на Java 11 (supported) и Java 17 (supported, рекомендуется). Java 21 в 5.0 **не поддерживается** — поддержка JDK 21 добавлена в ветке 6.0/trunk (CASSANDRA-18831). Бинарные релизы 5.0 собраны Java 11.

### Порты

| Порт | Назначение |
| :--- | :--- |
| 7000 | Межузловая связь (gossip, messaging) |
| 7001 | Межузловая связь с TLS |
| 7199 | JMX (мониторинг, nodetool) |
| 9042 | Native transport (CQL, клиенты) |

Порт 9160 (Thrift) удалён в Cassandra 4.0. В Cassandra 5.0 deprecated использование двух native-портов (`native_transport_port` + `native_transport_port_ssl`): шифрование клиентского трафика обслуживается одним портом (CASSANDRA-19392).

---

## Docker Compose: минимальный кластер Cassandra

```yaml
# docker-compose.yml
services:
  cassandra-1:
    image: cassandra:5.0
    container_name: cassandra-1
    ports:
      - "9042:9042"
    environment:
      CASSANDRA_SEEDS: cassandra-1,cassandra-2
      CASSANDRA_CLUSTER_NAME: "MyCluster"
      CASSANDRA_DC: DC1
      CASSANDRA_RACK: RACK1
      CASSANDRA_ENDPOINT_SNITCH: GossipingPropertyFileSnitch
    volumes:
      - cassandra-1-data:/var/lib/cassandra
    ulimits:
      memlock: -1
      nofile: 1048576
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "nodetool status | grep -q UN"]
      interval: 30s
      timeout: 10s
      retries: 12
      start_period: 90s

  cassandra-2:
    image: cassandra:5.0
    container_name: cassandra-2
    ports:
      - "9043:9042"
    environment:
      CASSANDRA_SEEDS: cassandra-1,cassandra-2
      CASSANDRA_CLUSTER_NAME: "MyCluster"
      CASSANDRA_DC: DC1
      CASSANDRA_RACK: RACK2
      CASSANDRA_ENDPOINT_SNITCH: GossipingPropertyFileSnitch
    volumes:
      - cassandra-2-data:/var/lib/cassandra
    ulimits:
      memlock: -1
      nofile: 1048576
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "nodetool status | grep -q UN"]
      interval: 30s
      timeout: 10s
      retries: 12
      start_period: 90s

volumes:
  cassandra-1-data:
  cassandra-2-data:
```

```bash
# Запуск кластера
docker compose up -d

# Ожидание готовности (полный старт ~60 секунд)
docker compose ps   # колонка Health: healthy

# Проверка состояния
docker exec -it cassandra-1 nodetool status
# → Datacenter: DC1
#   Status=Up/Down
#   /- State
#   UN  172.18.0.2  256 KB  256.0%  c4e5d6f1-...  cassandra-1
#   UN  172.18.0.3  128 KB  128.0%  a1b2c3d4-...  cassandra-2
```

**Переменные окружения образа `cassandra:5.0`:**

| Переменная | Назначение |
| :--- | :--- |
| `CASSANDRA_SEEDS` | Список seed-узлов (в Compose — имена сервисов) |
| `CASSANDRA_CLUSTER_NAME` | Имя кластера (должно совпадать на всех узлах) |
| `CASSANDRA_DC` / `CASSANDRA_RACK` | Datacenter / rack узла |
| `CASSANDRA_ENDPOINT_SNITCH` | Snitch (для multi-DC — `GossipingPropertyFileSnitch`) |
| `CASSANDRA_LISTEN_ADDRESS` / `CASSANDRA_BROADCAST_ADDRESS` | Адрес межузловой связи / адрес, анонсируемый другим узлам |
| `CASSANDRA_BROADCAST_RPC_ADDRESS` | Адрес, анонсируемый клиентам (обязателен при `rpc_address: 0.0.0.0`) |
| `CASSANDRA_USER` / `CASSANDRA_PASSWORD` | Суперпользователь при включённой аутентификации |

Примечания:
- Ключ `version` в compose-файле устарел в Compose v2 и выводит предупреждение — указывать его не нужно.
- Образ запускается от пользователя `cassandra` (UID 999); при bind-mount томов нужно заранее выдать права на каталог.
- Оба узла указаны как seeds — нормально для двухузлового dev-кластера; в production seeds выбирают иначе (см. Best Practices).

---

## Bare-metal: Apache Cassandra (Ubuntu 22.04/24.04, Debian 11/12)

### Предварительные требования

- **ОС:** Ubuntu 22.04/24.04, Debian 11/12 (для RPM — RHEL/CentOS 8+).
- **Java:** OpenJDK 11 или 17 (рекомендуется 17). Java 21 в Cassandra 5.0 не поддерживается.
- **RAM:** production — от 16 GB (heap + off-heap + page cache ОС).
- **Диск:** SSD; при HDD — отдельный диск для commitlog.
- **Отключённые Transparent Huge Pages** (обязательно, иначе деградация latency).
- **Отключённый swap** (или `vm.swappiness=1` как компромисс).
- **Лимит файловых дескрипторов** `nofile >= 32768` (production — 1048576).
- **Синхронизированные часы** (chrony/NTP) — рассинхрон на несколько секунд ломает gossip.

```bash
# 1. Java (17 рекомендуется для Cassandra 5.0)
sudo apt update && sudo apt install -y openjdk-17-jre-headless

# 2. Отключение THP (с сохранением после перезагрузки)
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/defrag
sudo tee /etc/systemd/system/disable-thp.service > /dev/null <<'EOF'
[Unit]
Description=Disable Transparent Huge Pages
[Service]
Type=oneshot
ExecStart=/bin/sh -c "echo never > /sys/kernel/mm/transparent_hugepage/enabled; echo never > /sys/kernel/mm/transparent_hugepage/defrag"
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now disable-thp

# 3. Лимиты и sysctl
echo "* soft nofile 1048576" | sudo tee -a /etc/security/limits.conf
echo "* hard nofile 1048576" | sudo tee -a /etc/security/limits.conf
sudo tee -a /etc/sysctl.conf > /dev/null <<'EOF'
vm.swappiness = 1
vm.max_map_count = 1048575   # рекомендация DataStax для mmap-индексов
EOF
sudo sysctl -p

# 4. Read-ahead: 4 KB для SSD (8 секторов по 512 байт), 64 KB (128) для HDD
sudo blockdev --setra 8 /dev/sda

# 5. Синхронизация времени
sudo apt install -y chrony
```

### Установка из репозитория (Debian/Ubuntu)

```bash
# 1. Ключи Apache Cassandra
sudo mkdir -p /etc/apt/keyrings
sudo curl -o /etc/apt/keyrings/apache-cassandra.asc https://downloads.apache.org/cassandra/KEYS

# 2. Репозиторий (50x = ветка 5.0; для 4.1 — 41x, для 4.0 — 40x)
echo "deb [signed-by=/etc/apt/keyrings/apache-cassandra.asc] https://debian.cassandra.apache.org 50x main" | sudo tee -a /etc/apt/sources.list.d/cassandra.sources.list

# 3. Установка
sudo apt-get update && sudo apt-get install -y cassandra
```

Пакет запускает сервис автоматически. **Перед правкой конфигурации остановите сервис:** `sudo systemctl stop cassandra`.

- Конфигурация: `/etc/cassandra/`
- Данные: `/var/lib/cassandra/`, логи: `/var/log/cassandra/`
- Параметры запуска (heap и др.): `/etc/default/cassandra`

### Установка из RPM (RHEL/CentOS)

```bash
sudo tee /etc/yum.repos.d/cassandra.repo > /dev/null <<'EOF'
[cassandra]
name=Apache Cassandra
baseurl=https://redhat.cassandra.apache.org/50x/
gpgcheck=1
repo_gpgcheck=1
gpgkey=https://downloads.apache.org/cassandra/KEYS
EOF
sudo yum install -y cassandra
sudo systemctl daemon-reload   # может потребоваться для регистрации сервиса
sudo systemctl start cassandra
```

### Установка из tarball (без root, для POC)

```bash
curl -O https://downloads.apache.org/cassandra/5.0.9/apache-cassandra-5.0.9-bin.tar.gz
tar -xzf apache-cassandra-5.0.9-bin.tar.gz
cd apache-cassandra-5.0.9
bin/cassandra -f        # запуск в foreground; конфигурация в conf/cassandra.yaml
```

---

## Установка ScyllaDB

ScyllaDB использует календарное версионирование. Поддерживаются две последние линейки: **2026.1 — LTS** (поддержка до 2028.1), 2026.3 — актуальный STS-релиз.

### Docker Compose

```yaml
# docker-compose.yml
services:
  scylla-1:
    image: scylladb/scylla:2026.3
    container_name: scylla-1
    command: --seeds=scylla-1
    ports:
      - "9042:9042"
    volumes:
      - scylla-1-data:/var/lib/scylla
    restart: unless-stopped

  scylla-2:
    image: scylladb/scylla:2026.3
    container_name: scylla-2
    command: --seeds=scylla-1
    ports:
      - "9043:9042"
    volumes:
      - scylla-2-data:/var/lib/scylla
    restart: unless-stopped

volumes:
  scylla-1-data:
  scylla-2-data:
```

```bash
docker compose up -d
docker exec -it scylla-1 nodetool status
```

На dev-машинах с малым объёмом RAM добавьте `command: --seeds=scylla-1 --smp 1 --developer-mode 1` (ограничение на одно ядро и developer mode — **только для dev**, в production не использовать).

### Bare-metal (Ubuntu/Debian)

Рекомендуемый способ — Web Installer (платформонезависимый скрипт):

```bash
# Установка последней поддерживаемой версии
curl -sSf get.scylladb.com/server | sudo bash

# Список активных линеек и установка конкретной
curl -sSf get.scylladb.com/server | sudo bash -s -- --list-active-releases
curl -sSf get.scylladb.com/server | sudo bash -s -- --scylla-version 2026.3
```

Или вручную через APT (замените `2026.3` на нужную линейку):

```bash
# 1. Ключ и репозиторий
sudo mkdir -p /etc/apt/keyrings
sudo gpg --homedir /tmp --no-default-keyring --keyring /tmp/temp.gpg \
  --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys c503c686b007f39e
sudo gpg --homedir /tmp --no-default-keyring --keyring /tmp/temp.gpg \
  --export --armor c503c686b007f39e | gpg --dearmor > /etc/apt/keyrings/scylladb.gpg
sudo wget -O /etc/apt/sources.list.d/scylla.list https://downloads.scylladb.com/deb/debian/scylla-2026.3.list

# 2. Установка (последний патч линейки)
sudo apt-get update && sudo apt-get install -y scylla

# Установка конкретного патча
apt-cache madison scylla
sudo apt-get install scylla{,-server,-kernel-conf,-node-exporter,-conf,-python3,-cqlsh}=<patch-version>
```

Для CentOS/RHEL: подключить EPEL, удалить ABRT (`sudo yum remove -y abrt` — конфликтует с конфигурацией coredump ScyllaDB), затем:

```bash
sudo curl -o /etc/yum.repos.d/scylla.repo -L https://downloads.scylladb.com/rpm/centos/scylla-2026.3.repo
sudo yum install -y scylla
```

### Запуск и тюнинг ОС

```bash
# 1. Настроить cluster_name, seeds, listen_address, rpc_address в /etc/scylla/scylla.yaml

# 2. Тюнинг ОС: RAID0/XFS, бенчмарк диска, генерация /etc/scylla.d/io.conf
sudo scylla_setup

# 3. Запуск сервиса
sudo systemctl start scylla-server
```

Важно:
- ScyllaDB **не запустится** без XFS на `/var/lib/scylla` или без сгенерированного `io.conf` (обход — developer mode, только для dev).
- Порты: 7000/7001 (межузловая связь), 9042 (CQL), 10000 (Admin REST API).

---

## Конфигурация Cassandra (`/etc/cassandra/cassandra.yaml`)

В Cassandra 5.0 поставляются два варианта файла: `cassandra.yaml` (совместимые дефолты, для апгрейдов) и `cassandra_latest.yaml` (дефолты с новыми возможностями, для новых кластеров).

```yaml
# Имя кластера (должно совпадать на всех узлах; изменить после запуска нельзя)
cluster_name: 'ProductionCluster'

# Адрес межузловой связи (IP узла или hostname)
listen_address: <LOCAL_IP>
# Адрес, анонсируемый другим узлам (по умолчанию = listen_address)
# broadcast_address: <PUBLIC_IP>

# Адрес для клиентских подключений
rpc_address: 0.0.0.0
# ОБЯЗАТЕЛЬНО при rpc_address: 0.0.0.0 — реальный адрес, анонсируемый клиентам
broadcast_rpc_address: <LOCAL_IP>

# Порты
storage_port: 7000           # Между узлами
ssl_storage_port: 7001       # TLS между узлами
native_transport_port: 9042  # Клиенты (CQL)

# Seeds — начальные узлы для Gossip (2-3 стабильных узла на DC)
seeds: "10.0.1.1,10.0.1.2"

# Snitch — определение топологии (для multi-DC)
endpoint_snitch: GossipingPropertyFileSnitch
# DC и rack для этого snitch задаются в /etc/cassandra/cassandra-rackdc.properties

# vNodes: диапазонов токенов на узел (дефолт 16 с 4.0)
num_tokens: 16
# Рекомендуется: RF локального DC — для равномерной аллокации токенов
allocate_tokens_for_local_replication_factor: 3
```

**Размер heap** задаётся в `/etc/cassandra/jvm.options` (`-Xms`/`-Xmx`), а не в `cassandra.yaml`. Рекомендация: heap не более 8–16 GB — остальная RAM нужна ОС для page cache.

---

## Валидация установки

```bash
# Состояние узлов: UN = Up/Normal, DN = Down, UL = Up/Leaving
nodetool status
# → Datacenter: DC1
#   Status=Up/Down
#   /- State
#   UN  172.18.0.2  256 KB  256.0%  c4e5d6f1-...  cassandra-1

# Метаданные кластера: имя, snitch, partitioner, версии схемы на узлах
nodetool describecluster

# Диапазоны токенов
nodetool ring

# Тестовое CQL-подключение
cqlsh <node_ip> 9042 -e "SELECT cluster_name, release_version FROM system.local;"

# Логи
journalctl -u cassandra -f          # bare-metal (systemd)
tail -f /var/log/cassandra/system.log
docker logs -f cassandra-1          # Docker
```

Для ScyllaDB дополнительно — Admin REST API:

```bash
curl -s http://localhost:10000/storage_service/scylla_release_version
# → "2026.3.2"
```

---

## Troubleshooting установки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Unable to gossip with any seeds` | seed недоступен: неверный IP/hostname, закрыт порт 7000 | проверить `seeds`, DNS, `ss -lntp \| grep 7000` на seed-узле |
| `cqlsh: Connection refused` | узел ещё стартует (~60 s) или native transport выключен | подождать; `nodetool status`; логи |
| Контейнер Cassandra перезапускается / OOM | мало RAM; heap по умолчанию велик | `docker compose ps`; `limits.memory`; уменьшить `-Xmx` в `jvm.options` |
| `Address already in use` / `Failed to bind` | порт 9042/7000 занят другим процессом | `ss -lntp \| grep -E '9042\|7000'` |
| Предупреждение о THP в логах | включён Transparent Huge Pages | отключить (см. «Предварительные требования») |
| Клиенты видят `0.0.0.0` в `system.peers` | `rpc_address: 0.0.0.0` без `broadcast_rpc_address` | задать `broadcast_rpc_address` |
| `apt-get install cassandra`: пакет не найден | репозиторий не добавлен или неверная серия | проверить `/etc/apt/sources.list.d/cassandra.sources.list` (должна быть `50x`), `apt-get update` |
| ScyllaDB не стартует: «io.conf not found» | не выполнен `scylla_setup` или `/var/lib/scylla` не на XFS | `sudo scylla_setup`; XFS на data-dir |
| ScyllaDB в Docker съедает всю RAM | Seastar резервирует память под все ядра | dev: `--smp 1 --developer-mode 1` |

---

## Best Practices

- **Seeds:** 2–3 стабильных узла на datacenter, не все узлы кластера; список seeds меняют редко и согласованно на всех узлах.
- **Keyspaces:** только `NetworkTopologyStrategy` в production (никогда `SimpleStrategy`).
- **Шифрование** (client-to-node и node-to-node) настраивайте сразу при развёртывании — перенос на работающем кластере сложен и рискован.
- **Read-ahead:** 64 KB для HDD, 4 KB для SSD (`blockdev --setra`).
- **Swap:** отключить; если нельзя — `vm.swappiness=1`.
- **Часы:** chrony/NTP на всех узлах.
- **Heap:** не более 8–16 GB; остальная RAM — page cache ОС.
- **commitlog:** при HDD — на отдельном диске от data.

### Очистка и удаление

```bash
# Docker Compose (флаг -v удаляет volumes с данными)
docker compose down -v

# Cassandra (Debian/Ubuntu)
sudo systemctl stop cassandra
sudo apt purge -y cassandra
sudo rm -rf /var/lib/cassandra /var/log/cassandra /etc/cassandra
sudo rm -f /etc/apt/sources.list.d/cassandra.sources.list /etc/apt/keyrings/apache-cassandra.asc

# ScyllaDB
sudo systemctl stop scylla-server
sudo apt purge -y 'scylla*'
sudo rm -rf /var/lib/scylla /etc/scylla /etc/apt/sources.list.d/scylla.list
# ВНИМАНИЕ: на Ubuntu после удаления ScyllaDB не запускайте `apt autoremove` —
# он удалит системные пакеты (известная проблема ScyllaDB)
```

---

## См. также

- **[Архитектура: Cassandra vs ScyllaDB](./architecture.md)** — Seastar, JVM, vNodes vs Tablets.
- **[Безопасность](./security.md)** — TLS, аутентификация, RBAC, firewall (порты выше).
- **[Тюнинг производительности](./performance.md)** — JVM Heap, I/O.
- **[Обслуживание и эксплуатация](./operations.md)** — добавление узлов, bootstrap, repair.
- **[Мониторинг](./monitoring.md)** — метрики, Prometheus, ScyllaDB Monitoring Stack.
- **[Развёртывание в Kubernetes](./kubernetes.md)** — ScyllaDB Operator, cass-operator, K8ssandra.
- **[Поиск и устранение неисправностей](./troubleshooting.md)** — типичные ошибки эксплуатации.
- Официальная документация: [Apache Cassandra](https://cassandra.apache.org/doc/latest/), [ScyllaDB](https://docs.scylladb.com/stable/).
