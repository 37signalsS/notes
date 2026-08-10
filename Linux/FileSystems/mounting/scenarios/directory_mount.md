# Определения

**Сценарий переноса каталога (Directory migration scenario)** — комплексная процедура перемещения содержимого существующей системной директории (например, `/var/log`, `/var/lib/docker`, `/home`) на выделенный физический диск, раздел или логический том.

Основная цель операции — предотвращение переполнения корневого раздела (`/`), изоляция данных для повышения отказоустойчивости, оптимизация производительности или упрощение процедур резервного копирования.

# Основные концепции

Для успешной миграции без потери данных и нарушения работы системы необходимо соблюдать следующие принципы:

1.  **Консистентность (Consistency)**: Остановка всех процессов, пишущих в целевой каталог. Использование `lsof` или `fuser` для поиска открытых дескрипторов.
2.  **Сохранение метаданных**: Использование инструментов (преимущественно `rsync -aAX`), поддерживающих сохранение прав доступа, расширенных атрибутов (xattr), ACL и контекстов SELinux.
3.  **Атомарность переключения**: Подготовка нового раздела во временной точке монтирования и быстрая подмена оригинального каталога.
4.  **Безопасный откат (Rollback)**: Переименование оригинального каталога вместо его немедленного удаления.

# Практические сценарии

## Сценарий 1: Перенос /var/log на новый диск

Типовая задача при переполнении корневого раздела системными журналами.

### 1. Подготовка и проверка
Определите процессы, использующие каталог:
```bash
sudo lsof +D /var/log
# → Команда покажет список открытых файлов и PID процессов
```

Остановите основные службы логирования:
```bash
sudo systemctl stop rsyslog.service systemd-journald.service
```

### 2. Копирование данных
Смонтируйте новый раздел (например, `/dev/sdb1`) во временную директорию:
```bash
sudo mount /dev/sdb1 /mnt
sudo rsync -aAXv /var/log/ /mnt/
```
*Примечание: Слэш в конце `/var/log/` инструктирует rsync копировать содержимое каталога, а не сам каталог.*

### 3. Переключение и настройка fstab
```bash
# Резервирование старых данных
sudo mv /var/log /var/log.old
sudo mkdir /var/log

# Получение UUID нового диска
UUID=$(lsblk -dno UUID /dev/sdb1)

# Добавление в /etc/fstab (опция noatime рекомендуется для SSD)
echo "UUID=$UUID /var/log ext4 defaults,noatime 0 2" | sudo tee -a /etc/fstab

sudo systemctl daemon-reload
sudo mount /var/log
```

### 4. Верификация и восстановление контекста
Если в системе включен SELinux, необходимо восстановить контексты безопасности:
```bash
sudo restorecon -Rv /var/log
```

Запустите службы и проверьте их статус:
```bash
sudo systemctl start systemd-journald.service rsyslog.service
sudo systemctl status rsyslog.service
```

---

## Сценарий 2: Перенос /var/lib/docker на LVM-том

LVM позволяет гибко расширять пространство в будущем, что критично для хранения образов и контейнеров.

### 1. Создание логического тома
Предположим, у вас есть группа томов `vg_data`.
```bash
sudo lvcreate -L 50G -n lv_docker vg_data
sudo mkfs.xfs /dev/mapper/vg_data-lv_docker
```

### 2. Миграция данных Docker
```bash
# Полная остановка Docker и связанных компонентов
sudo systemctl stop docker.socket docker.service

# Монтирование и копирование
sudo mount /dev/mapper/vg_data-lv_docker /mnt
sudo rsync -aAXv /var/lib/docker/ /mnt/

# Переименование и создание точки монтирования
sudo mv /var/lib/docker /var/lib/docker.old
sudo mkdir /var/lib/docker

# Настройка fstab
echo "/dev/mapper/vg_data-lv_docker /var/lib/docker xfs defaults 0 0" | sudo tee -a /etc/fstab
sudo systemctl daemon-reload
sudo mount /var/lib/docker

# Запуск
sudo systemctl start docker
```

---

## Сценарий 3: Использование Bind Mount для переназначения путей

Bind mount позволяет смонтировать одну директорию в другую, что удобно для быстрого "переброса" данных без изменения конфигурации приложений.

### 1. Перенос данных
Например, перенесем данные сайта из `/var/www/html` в `/data/www`:
```bash
sudo mkdir -p /data/www
sudo rsync -aAXv /var/www/html/ /data/www/
```

### 2. Настройка монтирования
Временное решение:
```bash
sudo mount --bind /data/www /var/www/html
```

Постоянное решение через `/etc/fstab`:
```bash
# Формат: [Источник] [Точка монтирования] none bind 0 0
echo "/data/www /var/www/html none bind 0 0" | sudo tee -a /etc/fstab
```

# Дополнительная информация

*   **[Конфигурация fstab](../fstab.md)** — описание опций монтирования и параметров проверки.
*   **[Сценарий базовой разметки](./basic_partition.md)** — подготовка физического диска (GPT, MBR).
*   **[Управление LVM](../LVM/overview_concepts.md)** — создание и расширение логических томов.
*   **[SELinux: Механизмы и настройка](../../Security/Mechanisms/SELinux.md)** — работа с контекстами безопасности при переносе данных.
*   **[Диагностика дискового пространства](../../Diagnostics/Filesystem/filesystem_and_disk_space_diagnostics.md)** — поиск "тяжелых" каталогов через `du` и `ncdu`.
