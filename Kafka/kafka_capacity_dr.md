# Capacity Planning и Disaster Recovery для Apache Kafka

**Capacity Planning** — это процесс определения необходимых ресурсов (CPU, RAM, диск, сеть) для обеспечения требуемой производительности и доступности Kafka-кластера. **Disaster Recovery (DR)** — это стратегия восстановления после катастрофических сбоев с минимальной потерей данных.

---

## Определения

- **Throughput:** Объём данных, обрабатываемый кластером (MB/s или GB/s).
- **Retention:** Период хранения данных в Kafka (время или размер).
- **RPO (Recovery Point Objective):** Максимально допустимая потеря данных (время).
- **RTO (Recovery Time Objective):** Максимально допустимое время простоя.
- **Headroom:** Запас ресурсов для обработки пиковых нагрузок (обычно 30-50%).
- **JBOD (Just a Bunch of Disks):** Конфигурация без RAID, где каждый диск используется отдельно.
- **Tiered Storage:** Хранение старых данных на дешёвом хранилище (S3, GCS).
- **MirrorMaker 2:** Инструмент для межкластерной репликации в Kafka.
- **Backup:** Резервная копия данных и метаданных для восстановления.

---

## Основные концепции

### Формулы планирования ёмкости

**1. Количество партиций на брокер:**
```
Partitions per broker ≤ 4000 (bare-metal) или ≤ 1000 (VM)
```

**2. Общее количество партиций:**
```
Total partitions = max(
    target_throughput_mbps / throughput_per_partition_mbps,
    number_of_consumers
)
```

**3. Размер диска:**
```
Disk per broker = (daily_data_GB × replication_factor × retention_days × headroom) / number_of_brokers
```

**4. Пропускная способность сети:**
```
Network = write_throughput_mbps × (replication_factor - 1) + consumer_read_throughput_mbps
```

**5. RAM:**
```
RAM = heap_gb + page_cache_gb + overhead_gb
page_cache_gb = (total_throughput_mbps × hot_data_window_seconds) / 1024
```

### Типичные параметры партиции

| Параметр | Значение |
|----------|----------|
| Throughput на партицию | 10-50 MB/s (зависит от сообщений) |
| Размер сегмента | 1 GB (по умолчанию) |
| Количество сегментов | Зависит от retention |
| Лимит размера сообщения | 1 MB (по умолчанию) |

### Стратегии Disaster Recovery

| Стратегия | RPO | RTO | Сложность | Стоимость |
|-----------|-----|-----|-----------|-----------|
| **Multi-AZ** | 0 сек | 1-5 мин | Низкая | Средняя |
| **Active-Passive** | 1-5 мин | 5-30 мин | Средняя | Средняя |
| **Active-Active** | 0 сек | 1-5 мин | Высокая | Высокая |
| **Backup & Restore** | 24 часа | 1-24 часа | Низкая | Низкая |

**Multi-AZ (в пределах одного региона):**
- Брокеры распределены по зонам доступности
- Реплики партиций распределены по зонам (rack awareness)
- Автоматическое переключение при выходе зоны

**Active-Passive (между регионами):**
- Два кластера: активный и пассивный
- MirrorMaker 2 для репликации
- Ручное или автоматическое переключение (failover)

**Active-Active (между регионами):**
- Два кластера одновременно обрабатывают трафик
- Двунаправленная репликация
- Сложность разрешения конфликтов

### Backup стратегии

**Что бэкапить:**
1. Данные топиков (сегменты логов)
2. Метаданные (конфигурации топиков, ACL, схемы)
3. Внутренние топики Kafka (`__consumer_offsets`, `__transaction_state`)

**Методы бэкапа:**
- **Снапшоты файловой системы:** LVM, ZFS, EBS snapshots
- **Kafka нативный:** MirrorMaker 2 в бэкап-кластер
- **Экспорт данных:** `kafka-console-consumer` + `kafka-console-producer`
- **В Kubernetes:** Velero, Velero + Restic

**Метаданные `__cluster_metadata`:**
```bash
# Экспорт метаданных (топики, конфигурации)
kafka-topics.sh --bootstrap-server kafka:9092 --list > topics.txt
kafka-configs.sh --bootstrap-server kafka:9092 --describe --all > configs.txt
kafka-acls.sh --bootstrap-server kafka:9092 --list > acls.txt
```

---

## Практические сценарии

### Сценарий 1: Расчёт ёмкости для нового кластера

**Требования:**
- Throughput: 100 MB/s write, 200 MB/s read
- Retention: 7 дней
- Replication factor: 3
- Headroom: 50%

**Расчёт:**
```bash
# 1. Дневной объём данных
daily_data_GB = 100 MB/s × 86400 s = 8640 GB ≈ 8.6 TB

# 2. Общий объём с репликацией и retention
total_storage_GB = 8.6 TB × 3 (RF) × 7 (days) × 1.5 (headroom) = 270 TB

# 3. Количество брокеров (при 4 TB на брокер)
number_of_brokers = 270 TB / 4 TB = 68 брокеров

# 4. Партиции
throughput_per_partition = 20 MB/s
number_of_partitions = 100 MB/s / 20 MB/s = 5 партиций на топик (минимально)

# 5. Сеть
network = 100 MB/s × 2 (репликация) + 200 MB/s (чтение) = 400 MB/s ≈ 3.2 Gbps
```

### Сценарий 2: Настройка MirrorMaker 2 для DR

Файл `mirror-maker.properties`:
```properties
# Кластеры
clusters=primary, backup
primary.bootstrap.servers=primary-kafka:9092
backup.bootstrap.servers=backup-kafka:9092

# Репликация топиков
primary->backup.enabled=true
primary->backup.topics=.*
primary->backup.topics.exclude=__.*,*-changelog

# Репликация групп консьюмеров
sync.group.offsets.enabled=true
emit.checkpoints.interval.seconds=60

# Конфигурация безопасности
primary.security.protocol=SASL_SSL
primary.sasl.mechanism=PLAIN
backup.security.protocol=SASL_SSL
backup.sasl.mechanism=PLAIN
```

### Сценарий 3: Автоматический Backup метаданных

Скрипт `/usr/local/bin/kafka-metadata-backup.sh`:
```bash
#!/bin/bash
BACKUP_DIR="/backup/kafka-metadata/$(date +%Y%m%d_%H%M%S)"
mkdir -p $BACKUP_DIR

BOOTSTRAP="kafka:9092"

# Экспорт топиков
kafka-topics.sh --bootstrap-server $BOOTSTRAP --list > $BACKUP_DIR/topics.txt

# Экспорт конфигураций
kafka-configs.sh --bootstrap-server $BOOTSTRAP --describe --all > $BACKUP_DIR/configs.txt

# Экспорт ACL
kafka-acls.sh --bootstrap-server $BOOTSTRAP --list > $BACKUP_DIR/acls.txt

# Экспорт групп консьюмеров
kafka-consumer-groups.sh --bootstrap-server $BOOTSTRAP --list > $BACKUP_DIR/consumer-groups.txt

# Сжатие и загрузка в S3
tar -czf $BACKUP_DIR.tar.gz $BACKUP_DIR
aws s3 cp $BACKUP_DIR.tar.gz s3://kafka-backups/metadata/
```

### Сценарий 4: Rack Awareness для Multi-ZA

```properties
# На каждом брокере server.properties
broker.rack=us-east-1a  # или автоматически из метаданных облака
```

**Проверка:**
```bash
kafka-topics.sh --bootstrap-server kafka:9092 \
  --topic my-topic --describe | grep -E "Replicas|Isr"
```

**Результат:** Реплики распределены по зонам доступности.

### Сценарий 5: Восстановление после катастрофы

```bash
# 1. Восстановление топиков из бэкапа
while read topic; do
  kafka-topics.sh --bootstrap-server new-kafka:9092 --create \
    --topic $topic --partitions 6 --replication-factor 3
done < topics.txt

# 2. Восстановление конфигураций
kafka-configs.sh --bootstrap-server new-kafka:9092 \
  --alter --all --from-file configs.txt

# 3. Восстановление ACL
kafka-acls.sh --bootstrap-server new-kafka:9092 \
  --add --allow-principal --from-file acls.txt

# 4. Восстановление данных (если есть снапшоты файловой системы)
# Скопировать данные из backup в /kafka-data

# 5. Переключение DNS/Load Balancer на новый кластер
```

### Сценарий 6: Тестирование DR

**Chaos Engineering сежемся:**
```bash
# Симуляция выхода брокера
docker stop kafka-broker-1

# Мониторинг
# - UnderReplicatedPartitions должен вернуться к 0
# - ActiveControllerCount должен быть 1
# - Consumer lag не должен расти

# Симуляция выхода зоны доступности
# (остановить все брокеры в одной зоне)
```

---

## Дополнительная информация

### Чек-лист Capacity Planning

- [ ] Определены требования к throughput (MB/s)
- [ ] Определены требования к retention (дни/размер)
- [ ] Рассчитано количество партиций
- [ ] Рассчитан объём дисков с учётом репликации и headroom
- [ ] Рассчитана пропускная способность сети
- [ ] Определено количество брокеров
- [ ] Запланирован rack awareness
- [ ] Настроен мониторинг загрузки ресурсов

### Чек-лист Disaster Recovery

- [ ] Определены RPO и RTO
- [ ] Выбрана стратегия DR (Multi-AZ, Active-Passive, Active-Active)
- [ ] Настроена репликация (MirrorMaker 2)
- [ ] Настроен backup метаданных
- [ ] Проведены тесты DR (failover)
- [ ] Документированы процедуры восстановления
- [ ] Настроен мониторинг репликации

### Мониторинг ресурсов

| Метрика | Алерт |
|---------|-------|
| Disk usage > 80% | Увеличить retention или добавить диски |
| Network > 70% | Добавить сетевые интерфейсы |
| CPU > 70% | Добавить брокеры |
| ISR shrink | Проблема с репликацией |
| Consumer lag > порога | Проблема с консьюмерами |

### Связь с другими настройками

- **[Партиционирование](./partitioning_and_balancing.md)** — количество партиций влияет на capacity
- **[ISR и репликация](./kafka_isr_replication.md)** — влияет на storage и DR
- **[OS тюнинг](./kafka_os_tuning.md)** — настройки файловой системы для хранения
- **[Мониторинг](./kafka_for_monitoring.md)** — метрики загрузки ресурсов

### См. также
- **[MirrorMaker 2](./strimzi_kafka_operator.md)** — межкластерная репликация
- **[Развертывание в Kubernetes](./strimzi_kafka_operator.md)** — ресурсы для брокеров
- **[Мониторинг Kafka](./kafka_for_monitoring.md)** — метрики загрузки
- **[Партиционирование](./partitioning_and_balancing.md)** — балансировка нагрузки
