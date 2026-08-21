# Установка и первоначальная настройка

## Docker Compose: минимальный кластер

```yaml
# docker-compose.yml
version: '3.8'

services:
  cassandra-1:
    image: cassandra:4.1
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

  cassandra-2:
    image: cassandra:4.1
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

volumes:
  cassandra-1-data:
  cassandra-2-data:
```

```bash
# Запуск кластера
docker compose up -d

# Проверка состояния (ожидайте ~60 секунд для полного старта)
docker exec -it cassandra-1 nodetool status
# → Datacenter: DC1
#   Status=Up/Down
#   /- State
#   UN  172.18.0.2  256 KB   256.0%   c4e5d6f1-...  cassandra-1
#   UN  172.18.0.3  128 KB   128.0%   a1b2c3d4-...  cassandra-2
```

---

##裸-metal установка (Ubuntu 22.04/24.04)

**Предварительные требования:**
- Java 11 или 17 (OpenJDK).
- Отключенный Transparent Huge Pages (THP).
- Увеличенный лимит файловых дескрипторов (`nofile` >= 32768).
- Синхронизированные часы (NTP/chrony).

```bash
# 1. Установка Java
sudo apt update && sudo apt install -y openjdk-17-jre-headless

# 2. Отключение THP (обязательно для Cassandra)
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/defrag

# 3. Увеличение лимитов
echo "* soft nofile 32768" | sudo tee -a /etc/security/limits.conf
echo "* hard nofile 32768" | sudo tee -a /etc/security/limits.conf
echo "vm.max_map_count = 1048575" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# 4. Добавление репозитория Apache Cassandra
curl https://downloads.apache.org/cassandra/KEYS | sudo gpg --dearmor -o /usr/share/keyrings/cassandra.gpg
echo "deb [signed-by=/usr/share/keyrings/cassandra.gpg] https://debian.cassandra.apache.org 41x main" | sudo tee /etc/apt/sources.list.d/cassandra.list
sudo apt update && sudo apt install -y cassandra
```

---

## Базовая конфигурация (`/etc/cassandra/cassandra.yaml`)

```yaml
# Имя кластера (должно совпадать на всех узлах)
cluster_name: 'ProductionCluster'

# Адрес для связи с другими узлами
listen_address: <LOCAL_IP>

# Адрес для клиентских подключений
rpc_address: 0.0.0.0

# Порты
storage_port: 7000       # Между узлами
ssl_storage_port: 7001   # SSL между узлами
native_transport_port: 9042  # Клиенты

# Seeds — начальные узлы для Gossip (укажите 2-3 стабильных узла)
seeds: "10.0.1.1,10.0.1.2"

# Snitch — определение топологии
endpoint_snitch: GossipingPropertyFileSnitch

# Размер heap (для Cassandra)
heap_size: 8G
new_heap_size: 8G
```

**Валидация после запуска:**
```bash
# Проверка подключения
cqlsh <node_ip> 9042

# Проверка состояния кластера
nodetool status
# → UN = Up/Normal, DN = Down, UL = Up/Leaving
```

---

## См. также
- **[Архитектура: Cassandra vs ScyllaDB](./architecture.md)** — Seastar, JVM, vNodes vs Tablets.
- **[Безопасность](./security.md)** — TLS, аутентификация, RBAC.
- **[Тюнинг производительности](./performance.md)** — JVM Heap, I/O.
