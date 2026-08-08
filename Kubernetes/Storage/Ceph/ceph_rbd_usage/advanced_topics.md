# RBD: Расширенные темы и оптимизация

Документ содержит углубленную информацию по настройке производительности, обеспечению катастрофоустойчивости и безопасности блочных устройств (RBD) в кластере Ceph.

## Определения

**RBD Mirroring** — механизм асинхронной репликации образов между территориально распределенными кластерами Ceph для обеспечения катастрофоустойчивости (Disaster Recovery).

**QoS (Quality of Service)** — набор параметров для гранулярного ограничения пропускной способности (BPS) и количества операций ввода-вывода (IOPS), включая поддержку всплесков (Bursting).

**Persistent Cache** — технология кэширования на стороне клиента с использованием быстрых локальных накопителей (NVMe/SSD/PMEM), позволяющая радикально снизить задержки на запись.

**Живая миграция (Live Migration)** — процесс перемещения данных образа между пулами (например, с HDD на SSD) или форматами без остановки работы клиента.

---

## Базовые концепции

### Оптимизация производительности

#### 1. Клиентское кэширование (librbd cache)
Работает в оперативной памяти клиента (KVM/QEMU, CSI-узел).
*   **Write-back**: Данные считаются записанными после попадания в кэш клиента. Максимальная скорость, риск потери данных при сбое узла.
*   **Write-through**: Запись подтверждается только после фиксации в кластере. Безопасно, но медленно.
*   **Safe mode**: `rbd_cache_writethrough_until_flush` — начинает в режиме write-through и переходит в write-back только после получения первой команды flush от приложения (сигнал о том, что ОС умеет управлять целостностью).

#### 2. Persistent Write Log (PWL)
Современная альтернатива обычному кэшу. Использует SSD или PMEM на узле клиента для хранения журнала транзакций. Обеспечивает производительность write-back с надежностью, близкой к локальному диску.

#### 3. Стрипинг (Striping v2)
Разделение данных образа на части для параллельной записи на разные OSD.
*   `stripe_unit`: Размер минимального блока данных.
*   `stripe_count`: Количество объектов, по которым распределяются данные перед переходом к следующей итерации. Оптимально для Big Data и потокового I/O.

### Отказоустойчивость: RBD Mirroring

Демон `rbd-mirror` обеспечивает репликацию на уровне отдельных образов или целых пулов:
*   **Journal-based (Журналирование)**: Каждый запрос на запись фиксируется в журнале и воспроизводится на удаленном кластере. Гарантирует строгую последовательность (Consistency), но создает дополнительную нагрузку на I/O.
*   **Snapshot-based (На базе снапшотов)**: Репликация происходит по расписанию через дифференциальную передачу снимков. Менее ресурсозатратно, рекомендуется для большинства современных инсталляций (доступно с версии Pacific).

### Безопасность и шифрование

Шифрование RBD выполняется **исключительно на стороне клиента** (End-to-End Encryption). Кластер Ceph видит только зашифрованные блоки.
*   **Стандарты**: LUKS1, LUKS2.
*   **Реализация**: Через Ceph CSI (автоматически при создании PVC) или вручную через `rbd encryption format`.

---

## Практические сценарии

### 1. Тонкая настройка QoS (Лимиты и Bursting)

Параметры QoS можно изменять "на лету" без перезагрузки приложений.

```bash
# Ограничение IOPS (800) и установка Burst (до 2000 IOPS на 60 секунд)
rbd config image set kube/my-image rbd_qos_iops_limit 800
rbd config image set kube/my-image rbd_qos_iops_burst 2000
rbd config image set kube/my-image rbd_qos_iops_burst_seconds 60

# Ограничение скорости записи (50 MiB/s)
rbd config image set kube/my-image rbd_qos_write_bps_limit 52428800
```

### 2. Настройка Persistent Cache (SSD)

Для включения кэширования на локальном SSD узла (например, в Kubernetes):

```bash
# Включение модуля в конфиге образа
rbd config image set kube/my-image rbd_persistent_cache_mode ssd
rbd config image set kube/my-image rbd_persistent_cache_path /var/lib/ceph/cache/
rbd config image set kube/my-image rbd_persistent_cache_size 10Gi
```

### 3. Живая миграция между пулами (HDD -> SSD)

```bash
# Начало миграции (подготовка)
rbd migration prepare kube/my-image ssd-pool/my-image

# Выполнение копирования (клиент продолжает работу)
rbd migration execute ssd-pool/my-image

# Фиксация миграции (удаление исходного образа)
rbd migration commit ssd-pool/my-image
```

### 4. Настройка RBD Mirroring (Snapshot-based)

```bash
# Включение режима зеркалирования для пула
rbd mirror pool enable kube image

# Включение зеркалирования для конкретного образа (на базе снапшотов)
rbd mirror image enable kube/my-image snapshot

# Добавление расписания (каждые 10 минут)
rbd mirror snapshot schedule add 10m --pool kube --image my-image
```

### 5. Шифрование образа через CLI

```bash
# Форматирование образа под LUKS2
rbd encryption format kube/my-image luks2 passphrase.txt

# Открытие зашифрованного устройства для маппинга
rbd device map -o encryption-format=luks2,encryption-passphrase-file=passphrase.txt kube/my-image
```

---

## Дополнительная информация

### Связанные темы
- [Обзор Ceph и RADOS](../ceph_overview.md) — архитектурная база.
- [RBD: Определения и концепции](./definitions_and_concepts.md) — основы технологии.
- [Бенчмаркинг через fio](../../../../Linux/Diagnostics/Filesystem/fio.md#тестирование-ceph-rbd) — методика проверки оптимизаций.

### Ресурсы
- [Official Ceph Docs: RBD Mirroring](https://docs.ceph.com/en/latest/rbd/rbd-mirroring/)
- [Official Ceph Docs: Client-side Encryption](https://docs.ceph.com/en/latest/rbd/rbd-encryption/)
- [Ceph CSI: Encryption Guide](https://github.com/ceph/ceph-csi/blob/devel/docs/encryption.md)
