# CephFS: Дополнительные темы

## Определения

**Kernel driver** — встроенный в ядро Linux клиент CephFS (`mount -t ceph`), обеспечивает максимальную производительность за счёт прямого доступа к сетевому стеку и VFS.

**FUSE (Filesystem in Userspace)** — пользовательский клиент CephFS (`ceph-fuse`), работает в пространстве пользователя, обеспечивает лучшую совместимость, но с накладными расходами на переключение контекста.

**MDSCache** — кэш метаданных на клиенте, хранит информацию об иерархии каталогов и атрибутах файлов для ускорения операций.

**Congestion window** — параметр управления потоком данных, определяющий максимальный объём данных в полёте до подтверждения получения.

---

## Базовые концепции

### Архитектура клиентов CephFS

```
┌─────────────────────────────────────────┐
│           Kernel Driver                 │
│  (высокая производительность, Linux)    │
└─────────────────────────────────────────┘
                    ↓ VFS
┌─────────────────────────────────────────┐
│           FUSE Client                   │
│  (портативность, накладные расходы)     │
└─────────────────────────────────────────┘
                    ↓ libcephfs
┌─────────────────────────────────────────┐
│         Ceph Monitor + OSD              │
└─────────────────────────────────────────┘
```

### Сравнение Kernel vs FUSE

| Критерий | Kernel driver | FUSE |
|----------|---------------|------|
| **Производительность** | Высокая (прямой доступ к VFS) | Средняя (переключение контекста) |
| **Совместимость** | Требуется модуль ядра (5.4+) | Любое ядро с FUSE |
| **Отладка** | Сложнее (dmesg, ceph-debugfs) | Проще (логи в userspace) |
| **Обновление** | С ядром системы | Отдельный пакет (ceph-fuse) |
| **Рекомендация** | Production, Linux | Тестирование, нестандартные ядра |

### Влияние опций монтирования на производительность

| Опция | Влияние | Сценарий |
|-------|---------|----------|
| `noatime` | Снижает запись метаданных | ✅ Production (чтение интенсивное) |
| `relatime` | Обновляет atime периодически | ✅ Компромисс POSIX |
| `rw` | Полная запись | По умолчанию |
| `ro` | Только чтение | Резервные узлы, аудит |
| `norecover` | Отключает восстановление сессии | Отладка (⚠️ риск потери данных) |
| `recover_session=clean` | Очищает зависшие сессии | Восстановление после сбоев |

---

## Практические сценарии

### Настройка производительности

#### 1. Оптимизация кэша метаданных

```bash
# Проверка текущего размера кэша
cat /sys/module/ceph/parameters/mds_max_dentries_per_dir

# Увеличение кэша (для рабочих нагрузок с интенсивной работой с метаданными)
echo 1048576 | sudo tee /sys/module/ceph/parameters/mds_max_dentries_per_dir

# Сохранение в sysctl
echo 'module.ceph.mds_max_dentries_per_dir=1048576' | sudo tee /etc/sysctl.d/99-cephfs.conf
sudo sysctl -p /etc/sysctl.d/99-cephfs.conf
```

> **Примечание**: Параметр `mds_cache` устарел в новых версиях ядра. Используйте `mds_max_dentries_per_dir`.

#### 2. Настройка congestion window

```bash
# Увеличение congestion window (8 ГБ)
sudo mount -t ceph 172.21.0.10:6789:/data_pes /mnt/shared_fs \
  -o name=fs_user,secret=$USER_SECRET,congestion_kb=8388608

# Проверка параметра
mount | grep ceph
```

> **Рекомендация**: Значение `congestion_kb` зависит от объёма RAM и сетевой пропускной способности. Начните с 4–8 ГБ для 10GbE сети.

#### 3. Выбор клиента под задачу

```bash
# Kernel driver (рекомендуется для production)
sudo mount -t ceph 172.21.0.10:6789:/data_pes /mnt/shared_fs \
  -o name=fs_user,secret=$USER_SECRET,noatime

# FUSE (для тестирования или нестандартных ядер)
sudo ceph-fuse -m 172.21.0.10:6789 /mnt/shared_fs \
  -r /data_pes -n client.fs_user \
  -k /etc/ceph/ceph.client.fs_user.keyring
```

### Настройка безопасности

#### 1. Изоляция пользователей

```bash
# Создание пользователя с ограниченным доступом
ceph auth get-or-create client.app_reader \
  mon 'allow r' \
  mds 'allow r path=/data_pes' \
  osd 'allow rw pool=cephfs_data'

# Пользователь только для конкретного пути
ceph auth get-or-create client.app_writer \
  mon 'allow r' \
  mds 'allow rw path=/data_pes/app1' \
  osd 'allow rw pool=cephfs_data'
```

#### 2. Шифрование трафика

```bash
# Включение шифрования на стороне монитора
ceph config set mon ms_mode secure

# Проверка режима
ceph config get mon ms_mode

# Монтирование с принудительным шифрованием
sudo mount -t ceph 172.21.0.10:6789:/data_pes /mnt/shared_fs \
  -o name=fs_user,secret=$USER_SECRET,ms_mode=secure
```

> **Важно**: `ms_mode=secure` требует настроенного TLS на кластере Ceph. Без настройки кластера монтирование завершится ошибкой.

#### 3. Ротация ключей

```bash
# Генерация нового ключа
ceph auth get client.fs_user -o /etc/ceph/ceph.client.fs_user.keyring.new

# Замена keyring
sudo mv /etc/ceph/ceph.client.fs_user.keyring{,.old}
sudo mv /etc/ceph/ceph.client.fs_user.keyring{.new,}

# Перемонтирование с новым ключом
sudo mount -o remount /mnt/shared_fs

# Удаление старого ключа
sudo rm /etc/ceph/ceph.client.fs_user.keyring.old
```

> **Рекомендация**: Ротация ключей — каждые 90 дней. Старый ключ храните до подтверждения работоспособности нового.

---

## Дополнительная информация

### Диагностика производительности

```bash
# Статистика клиентских сессий MDS
ceph fs session ls

# Проверка congestion на клиенте
cat /sys/module/ceph/parameters/congestion_kb

# Мониторинг операций в реальном времени
sudo ceph-debugfs start
dmesg | grep ceph
```

### Известные ограничения

- **Kernel driver < 5.15**: проблемы с большими каталогами (>1M файлов)
- **FUSE**: не поддерживает все опции монтирования ядра
- **Quota enforcement**: применяется на уровне MDS, возможна задержка до 30 сек
- **Snapshot**: не поддерживает атомарное восстановление, только копирование

### Связанные файлы

- [Определения и концепции](./definitions_and_concepts.md)
- [Практические сценарии](./practical_scenarios.md)
- [Обзор Ceph](../ceph_overview.md)
- [Расчёт placement groups](../ceph_placement_groups.md)
- [Официальная документация CephFS](https://docs.ceph.com/en/latest/cephfs/)
