# Образы ВМ — Практические сценарии

В данном файле собраны инструкции по манипуляции образами виртуальных машин с использованием утилит `qemu-img` и пакета `libguestfs`. Теоретические основы описаны в [Определениях](./definitions.md) и [Основных концепциях](./basic_concepts.md).

## Базовые инструменты

*   **qemu-img** — универсальный инструмент для работы с форматами, размерами и снапшотами.
*   **libguestfs (virt-*)** — набор высокоуровневых утилит для безопасной модификации содержимого дисков без запуска ВМ.
*   **virt-sparsify** — инструмент для освобождения неиспользуемого места в файле образа («зануление» пустых блоков).
*   **virt-builder** — утилита для быстрой генерации готовых образов ОС из облачных репозиториев.
*   **qemu-nbd** — низкоуровневый инструмент для монтирования дисков через сетевое блочное устройство.

## Практические сценарии

### Сценарий 1: Базовые операции с qemu-img

#### Создание и анализ
```bash
# Создание qcow2 с предварительным выделением метаданных (ускоряет запись)
qemu-img create -f qcow2 -o preallocation=metadata web-server.qcow2 40G

# Получение детальной информации в формате JSON для автоматизации
qemu-img info --output=json web-server.qcow2
# → virtual-size: 42949672960 (40 GiB)
# → actual-size: 2203648 (тонкий диск)
```

#### Конвертация и сжатие
Конвертация в новый файл — лучший способ минимизировать размер `qcow2`. В современных системах (QEMU 5.1+) рекомендуется использовать `zstd`.
```bash
# Конвертация из VMDK в QCOW2 с использованием сжатия ZSTD (уровень по умолчанию)
qemu-img convert -f vmdk -O qcow2 -c -o compression_type=zstd source.vmdk compressed_target.qcow2

# Оценка необходимого места перед конвертацией
qemu-img measure -f raw -O qcow2 raw_disk.img
# → required size: 10737418240 (размер результирующего файла)
```

#### Работа с шифрованием
```bash
# Создание зашифрованного образа (LUKS)
qemu-img create -f qcow2 --object secret,id=sec0,data=MyPassword123 \
  -o encrypt.format=luks,encrypt.key-secret=sec0 encrypted.qcow2 10G

# Проверка информации о зашифрованном образе
qemu-img info --object secret,id=sec0,data=MyPassword123 encrypted.qcow2
```

### Сценарий 2: Расширение диска (Автоматизированный метод)

Вместо ручного манипулирования `qemu-nbd` и `fdisk` внутри гостя, рекомендуется использовать `virt-resize`.

```bash
# 1. Увеличиваем физический файл (создаем целевой нужного размера)
qemu-img create -f qcow2 new_disk.qcow2 100G

# 2. Переносим данные с расширением раздела и ФС в один шаг
virt-resize --expand /dev/sda1 old_disk.qcow2 new_disk.qcow2
# → Copying /dev/sda1 ...
# → Expanding /dev/sda1 to fill the extra space ...

# 3. Заменяем старый диск новым
mv new_disk.qcow2 live_disk.qcow2
```

### Сценарий 3: Редактирование «холодных» образов (libguestfs)

Использование `virt-edit` и `virt-customize` исключает риск повреждения ФС хоста при неправильном монтировании.

#### Сброс пароля или добавление SSH-ключа
```bash
# Установка пароля root и добавление ключа
virt-customize -a disk.qcow2 \
  --root-password password:MySecret123 \
  --ssh-inject root:file:/home/user/.ssh/id_rsa.pub
# → [   0.0] Examining the guest...
# → [   4.0] Setting passwords...
# → [   5.0] Injecting ssh-inject...
```

#### Быстрое извлечение или правка конфига
```bash
# Просмотр сетевых настроек внутри образа
virt-cat -a disk.qcow2 /etc/netplan/01-netcfg.yaml

# Редактирование файла в текстовом редакторе хоста
virt-edit -a disk.qcow2 /etc/ssh/sshd_config
```

### Сценарий 4: Оптимизация и очистка места

Если внутри ВМ было удалено много файлов, физический размер `.qcow2` на хосте не уменьшится сам по себе. `virt-sparsify` позволяет пересоздать файл, исключив пустые блоки.

```bash
# Очистка места во временный файл (in-place не рекомендуется)
virt-sparsify --compress old_disk.qcow2 optimized_disk.qcow2
# → [   0.0] Examining the guest...
# → [  10.0] Filling free space in /dev/sda1 with zero ...
# → [  25.0] Copying to optimized_disk.qcow2 ...
# → Succeeded. Очищает неиспользуемые блоки данных.
```

### Сценарий 5: Инспекция и анализ состава образа

Утилиты для аудита содержимого диска без его монтирования.

```bash
# Проверка используемого места разделами внутри образа
virt-df -h -a disk.qcow2

# Полный технический отчет об ОС (версия ядра, пакеты, ФС) в формате JSON
virt-inspector -a disk.qcow2 --format=json

# Интерактивная оболочка для работы с ФС образа (guestfish)
guestfish -a disk.qcow2 -i
# ><fs> ls /var/log
# ><fs> download /etc/fstab /tmp/fstab
```

### Сценарий 6: Автоматизированная сборка образов (virt-builder)

Позволяет собрать настроенный образ за одну команду, используя официальные шаблоны репозитория libguestfs.

```bash
# Список доступных ОС для сборки
virt-builder --list

# Сборка Ubuntu 24.04 с установленным nginx и настроенным пользователем
virt-builder ubuntu-24.04 \
  --size 20G \
  --format qcow2 \
  --install nginx \
  --root-password password:admin \
  --output my-web-server.qcow2
```

### Сценарий 7: Работа с внешними снапшотами

Внешние снапшоты предпочтительнее для высоконагруженных систем (лучшая производительность, чем у внутренних).

```bash
# Создание внешнего снапшота (оригинал становится backing file)
# Обязательно указывайте -F qcow2 для безопасности (защита от backing file проброса)
qemu-img create -f qcow2 -F qcow2 -b base.qcow2 snapshot1.qcow2

# Слияние изменений (Commit) обратно в базовый образ
qemu-img commit snapshot1.qcow2
# → Image committed. (snapshot1 теперь можно удалять)

# Перепривязка к новому базовому образу (Rebase)
qemu-img rebase -b new_base.qcow2 -F qcow2 disk.qcow2
```

### Сценарий 8: Прямое монтирование через qemu-nbd

Метод для низкоуровневой работы, если инструменты libguestfs недоступны или специфичны. **ВНИМАНИЕ:** Не монтируйте работающие ВМ!

```bash
# 1. Загрузка модуля ядра (на хосте)
sudo modprobe nbd max_part=8

# 2. Подключение образа к сетевому блочному устройству
sudo qemu-nbd --connect=/dev/nbd0 disk.qcow2

# 3. Обнаружение разделов и монтирование
sudo partprobe /dev/nbd0
sudo mount /dev/nbd0p1 /mnt

# 4. Отключение после работы
sudo umount /mnt
sudo qemu-nbd --disconnect /dev/nbd0
```

### Сценарий 9: Управление снапшотами через qemu-img

Помимо внешних снапшотов через `qemu-img create -b`, `qcow2` поддерживает встроенные (внутренние) снапшоты, управляемые напрямую через `qemu-img`.

#### Создание, список и удаление снапшотов

```bash
# Создание внутреннего снапшота (сохраняет текущее состояние диска)
qemu-img snapshot -c pre-update web-server.qcow2

# Просмотр всех снапшотов
qemu-img snapshot -l web-server.qcow2
# → snapshot list:
# → ID        TAG               VM SIZE                DATE       VM CLOCK
# → 1         pre-update        0                      2026-09-11  00:00:00.000

# Откат к снапшоту (ТРЕБУЕТ ВЫКЛЮЧЕННОЙ ВМ)
qemu-img snapshot -a pre-update web-server.qcow2

# Удаление снапшота
qemu-img snapshot -d pre-update web-server.qcow2
```

#### Безопасный rebase с сохранением формата

При перепривязке снапшота к новому базовому образу обязательно указывайте `-F` для защиты от атак через backing file проброс.

```bash
# 1. Создайте новый базовый образ
qemu-img create -f qcow2 -o preallocation=metadata new-base.qcow2 20G

# 2. Перепривязка с указанием формата базового файла
qemu-img rebase -b new-base.qcow2 -F qcow2 web-server.qcow2
# → rebasing finished

# 3. Проверка цепочки
qemu-img info --backing-chain web-server.qcow2
```

#### Откат к снапшоту без базового файла

Если базовый файл недоступен, можно создать независимый образ из текущего слоя:

```bash
# qemu-img snapshot -a не сработает без backing file.
# Создайте полную копию текущего состояния:
qemu-img convert -f qcow2 -O qcow2 web-server.qcow2 web-server-independent.qcow2
```

### Сценарий 10: Глубокое сравнение и аудит образов

Инструменты `libguestfs` позволяют сравнивать содержимое образов и проводить аудит без монтирования.

#### Сравнение двух образов (virt-diff)

```bash
# Поиск отличий в файловых системах
virt-diff -a old-disk.qcow2 -b new-disk.qcow2
# → -/etc/ssh/sshd_config
# → +/etc/hostname
# → ~/var/log/syslog (size changed)
```

#### Быстрый инвентарь файловых систем (virt-list-filesystems)

```bash
# Список всех разделов и ФС
virt-list-filesystems -a disk.qcow2
# → /dev/sda1: ext4
# → /dev/sdb1: xfs
```

#### Обход файлов (virt-ls)

```bash
# Рекурсивный список файлов с размерами
virt-ls -l -R -a disk.qcow2 /var/log
# → -rw-r--r-- root root 4096  /var/log/journal
# → -rw-r--r-- root root 1234  /var/log/syslog
```

#### Извлечение файлов как архива (virt-tar)

```bash
# Создание tar-архива из contents диска
virt-tar -a disk.qcow2 -z /backup.tar.gz /var/www
# → tarring /var/www ...
```

#### Парсинг отчета virt-inspector

```bash
# JSON-отчет для автоматизации
virt-inspector --format=json -a disk.qcow2 | jq '{
  os: .operating_system.product_name,
  version: .operating_system.version,
  arch: .operating_system.arch,
  packages: [.filesystems[].mountpoint]
}'
```

### Сценарий 11: Продвинутая оптимизация размера образа

#### virt-sparsify: in-place vs copy

```bash
# Безопасный режим (copy в новый файл)
virt-sparsify --compress old-disk.qcow2 optimized-disk.qcow2

# In-place режим (опасен, требуются 2x свободного места)
virt-sparsify --inplace --compress disk.qcow2

# С указанием временной директории (если /tmp мало)
virt-sparsify --tmpdir /var/tmp --compress disk.qcow2 optimized.qcow2

# Проверка свободного места перед запуском
AVAILABLE=$(df --output=avail /var/lib/libvirt/images | tail -1)
SIZE=$(qemu-img info --output=json disk.qcow2 | jq -r '.virtual-size')
# Достаточно минимум 2x $SIZE для режима copy
```

#### Zeroing свободного пространства перед sparsify

`virt-sparsify` сам заполняет нулями, но для максимального сжатия можно сделать это заранее внутри гостя:

```bash
# Внутри гостя (Linux):
sudo fstrim -v /
# или для полного zeroing (медленнее, но лучше сжатие):
sudo dd if=/dev/zero of=/zero.tmp bs=1M status=progress || true
sudo rm -f /zero.tmp
```

#### Выбор уровня сжатия ZSTD

```bash
# Бенчмарк скорости сжатия vs коэффициент
for level in 1 3 6 10 15 20; do
  echo "Testing zstd level $level..."
  time qemu-img convert -f qcow2 -O qcow2 \
    -c -o compression_type=zstd,compression_level=$level \
    source.qcow2 "compressed-l$level.qcow2"
done

# Обычно sweet spot: level 3-6 для баланса скорость/размер
# Level 15+ оправдано только для archival
```

### Сценарий 12: Массовые операции с образами

#### Параллельная конвертация директории

```bash
#!/bin/bash
# batch-convert.sh — массовая конвертация raw → qcow2
set -euo pipefail

SRC_DIR="/backup/raw-images"
DST_DIR="/var/lib/libvirt/images"
POOL="default"

convert_one() {
  local src="$1"
  local name=$(basename "$src" .raw)
  local dst="$DST_DIR/${name}.qcow2"
  
  echo "Converting $src → $dst"
  qemu-img convert -p -O qcow2 \
    -o preallocation=metadata,compression_type=zstd \
    "$src" "$dst"
  
  # Импорт в пул libvirt
  virsh vol-create-as "$POOL" "${name}.qcow2" \
    "$(qemu-img info --output=json "$dst" | jq -r '.virtual-size')" \
    --format qcow2 --pool "$POOL"
  
  # Проверка
  qemu-img check --output=json "$dst" | jq -r '.["format-specific"]["data"]["dirty-flag"]' | \
    grep -q false && echo "[OK] $name" || echo "[FAIL] $name"
}

export -f convert_one

find "$SRC_DIR" -name "*.raw" -print0 | \
  xargs -0 -P 4 -I {} bash -c 'convert_one "$@"' _ {}
```

#### Массовая проверка на ошибки

```bash
#!/bin/bash
# validate-images.sh — проверка всех образов в пуле
set -euo pipefail

POOL="default"
ERRORS=0

for vol in $(virsh vol-list "$POOL" | awk 'NR>2 {print $1}'); do
  path=$(virsh vol-path "$vol" --pool "$POOL")
  result=$(qemu-img check --output=json "$path" 2>/dev/null || echo '{"check-errors": true}')
  
  if echo "$result" | jq -e '.["check-errors"] // false' > /dev/null; then
    echo "[FAIL] $vol"
    ERRORS=$((ERRORS + 1))
  else
    echo "[OK]   $vol"
  fi
done

exit $ERRORS
```

#### Очистка orphaned образов

```bash
#!/bin/bash
# cleanup-orphans.sh — удаление файлов без соответствующих ВМ
set -euo pipefail

IMAGES_DIR="/var/lib/libvirt/images"

for img in "$IMAGES_DIR"/*.qcow2; do
  vm_name=$(basename "$img" .qcow2)
  
  # Проверка существования ВМ (defined или running)
  if ! virsh list --all --name | grep -qx "$vm_name"; then
    size=$(du -h "$img" | cut -f1)
    echo "Orphan: $vm_name ($size)"
    
    # Архивировать перед удалением
    mv "$img" "/backup/orphans/${vm_name}.qcow2"
    echo "  → moved to /backup/orphans/"
  fi
done
```

### Сценарий 13: Восстановление после сбоев

#### Стратегии восстановления поврежденного qcow2

```bash
# 1. Анализ повреждений
qemu-img check disk.qcow2
# → ERROR cluster 1234: refcount=0, should be 1
# → ERROR cluster 5678: L2 table offset mismatch

# 2. Попытка автоматического восстановления
qemu-img check -r all disk.qcow2
# → Repairing broken clusters...
# → 2 clusters repaired, 0 leaked

# 3. Если refcount не восстановился — конвертация с пропуском битых блоков
qemu-img convert -f qcow2 -O qcow2 \
  -r skipped \
  disk.qcow2 repaired.qcow2
# → 0.0/100.0 MB written (skipped 2 leaked clusters)

# 4. Проверка результата
qemu-img check repaired.qcow2
```

#### Извлечение данных через qemu-nbd в режиме только для чтения

```bash
# 1. Подключение в режиме только для чтения (безопасно для поврежденных образов)
sudo modprobe nbd max_part=8
sudo qemu-nbd --connect=/dev/nbd0 --read-only disk.qcow2

# 2. Попытка монтирования с опцией ro
sudo mount -o ro /dev/nbd0p1 /mnt/recovery

# 3. Копирование критичных данных
sudo cp -a /mnt/recovery/etc /backup/recovery/
sudo cp -a /mnt/recovery/home /backup/recovery/

# 4. Отключение
sudo umount /mnt/recovery
sudo qemu-nbd --disconnect /dev/nbd0
```

#### Работа с guestfish в безопасном режиме

```bash
# Оболочка с доступом только для чтения
guestfish --ro -a disk.qcow2 -i
# ><fs> ls /home
# ><fs> download /etc/passwd /tmp/passwd

# Или прямое извлечение файла без оболочки
guestfish --ro -a disk.qcow2 -i \
  --copy-out /var/www /backup/www
```

### Сценарий 14: Гостевая интеграция и bulk-операции

#### Первый запуск и кастомизация (virt-customize)

```bash
# Установка пакетов и SSH-ключа
virt-customize -a disk.qcow2 \
  --root-password password:Admin123! \
  --ssh-inject root:file:/home/sysadmin/.ssh/id_rsa.pub \
  --install nginx,curl,vim \
  --run-command 'systemctl enable nginx' \
  --firstboot /usr/local/bin/firstboot.sh \
  --hostname web-server-01

# Содержимое firstboot.sh выполнится при первом запуске ВМ
# > #!/bin/bash
# > systemctl start nginx
# > logger "First boot completed"
```

#### Неинтерактивное редактирование файлов (virt-edit --edit)

```bash
# Замена строки в sshd_config через sed
virt-edit -a disk.qcow2 /etc/ssh/sshd_config \
  --edit 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/'

# Множественные замены
virt-edit -a disk.qcow2 /etc/ssh/sshd_config \
  --edit 's/^#\?PermitRootLogin.*/PermitRootLogin no/' \
  --edit 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/'
```

#### Bulk-операции с файлами (virt-copy-in/out)

```bash
# Копирование директории внутрь образа
virt-copy-in -a disk.qcow2 ./nginx-conf/ /etc/nginx/

# Извлечение директории из образа
virt-copy-out -a disk.qcow2 /var/log /backup/vm-logs/

# Проверка существования файла
virt-cat -a disk.qcow2 /etc/hostname
```

#### Диагностика загрузки (virt-log, virt-tail)

```bash
# Просмотр загрузочного лога без запуска ВМ
virt-log -a disk.qcow2
# → [    0.000000] Linux version 6.5.0-35-generic ...
# → [    0.000000] Command line: BOOT_IMAGE=/vmlinuz-6.5.0-35-generic

# Просмотр последних строк лога (как tail -f)
virt-tail -a disk.qcow2 /var/log/syslog
# → 2026-09-11T10:00:00.000001+00:00 web-server systemd[1]: Started ...
```

### Сценарий 15: Миграция между платформами (virt-v2v)

Преобразование образов из VMware ESXi, Hyper-V или физических серверов в формат KVM.

```bash
# Установка (Debian/Ubuntu)
sudo apt-get install -y virt-v2v

# Миграция из VMware (VMDK + VMX)
virt-v2v -i vmx /path/to/vm.vmx \
  -o libvirt -os /var/lib/libvirt/images/
# → libvirt XML создается автоматически

# Миграция из Hyper-V (VHDX)
virt-v2v -i disk /path/to/disk.vhdx \
  -o libvirt -os /var/lib/libvirt/images/

# Миграция в OVA (для переноса на другой гипервизор)
virt-v2v -i ova /path/to/image.ova \
  -o local -os /var/lib/libvirt/images/
```

### Сценарий 16: Тестирование производительности хранилища

#### Бенчмарк disk image как гостевой ОС (fio)

```bash
# Типичный workload ВМ: смешанный чтение/запись 4K, 16 очередей
fio --name=vm-workload \
  --rw=randrw \
  --bs=4k \
  --iodepth=16 \
  --size=1G \
  --filename=/var/lib/libvirt/images/test.qcow2 \
  --output-format=json \
  --runtime=60 \
  --time_based

# Оценка latency (p99, p999)
fio --name=latency-test \
  --rw=randread \
  --bs=4k \
  --iodepth=1 \
  --size=1G \
  --filename=/var/lib/libvirt/images/test.qcow2 \
  --output-format=json | \
  jq '.jobs[0].latency'
```

#### Сравнение cache modes

```bash
# Тест с cache=none (рекомендуется для БД)
fio --name=cache-none --rw=randrw --bs=4k --iodepth=16 \
  --filename=/var/lib/libvirt/images/test-cache-none.qcow2

# После изменения cache mode в XML libvirt перезапустите ВМ
virsh dumpxml vm-name | grep -E 'cache|io='
```

### Теоретические дополнения

#### Расчет безопасного overcommit для тонкого выделения

```text
Безопасный overcommit (%) = (Физический объем / Сумма виртуальных томов) * 100

Рекомендуемый порог: 150–200% с активным мониторингом.
При превышении 200% без мониторинга риск потери данных критичен.
```

#### Влияние alignment диска

```bash
# Проверка alignment раздела (должен быть 1 MiB для современных дисков)
sudo fdisk -l /dev/nbd0p1
# → sector size 512, start 2048 → alignment 1 MiB (correct)

# Оптимальная геометрия для virtio-blk в libvirt XML:
# <disk type='file' device='disk'>
#   <driver name='qemu' type='qcow2' cache='none' io='io_uring' queues='4'/>
#   <source file='/var/lib/libvirt/images/vm.qcow2'/>
#   <target bus='virtio' dev='vda'/>
# </disk>
```

#### Стек TRIM/Discard: от гостя до хоста

```text
Гостевая ОС (fstrim)
    ↓
Виртуальный диск (virtio-scsi, discard=unmap)
    ↓
QEMU (UNMAP command)
    ↓
Файловая система хоста (hole punching)
    ↓
Физическое освобождение блоков
```

Для работоспособности требуется:
1. Гостевая ОС с поддержкой TRIM (Linux ≥ 2.6.38, Windows ≥ 8/2012)
2. Контроллер `virtio-scsi` (не virtio-blk для UNMAP)
3. Опция `discard='unmap'` в конфигурации диска libvirt
4. Файловая система хоста с поддержкой sparse-файлов (ext4, XFS, ZFS)

#### Оптимальный размер кластера qcow2

| Сценарий | Размер кластера | Обоснование |
| :--- | :--- | :--- |
| Общие нагрузки, шаблоны | 64 КБ (по умолчанию) | Оптимальный баланс метаданных/данных |
| Базы данных, последовательный I/O | 128 КБ – 2 МБ | Уменьшение числа L2-запросов |
| Большие файлы (>1 ТБ) | 2 МБ | Минимизация оверхеда таблиц |
| Много маленьких файлов | 32 КБ – 64 КБ | Уменьшение внутренней фрагментации |

Изменение размера кластера для существующего образа невозможно без пересоздания.

## Дополнительная информация

### Безопасность и проверка
*   **Проверка на ошибки:** `qemu-img check disk.qcow2` — исправляет незначительные повреждения метаданных.
*   **Очистка перед публикацией:** Всегда используйте `virt-sysprep -a image.qcow2` перед тем, как делиться образом. Это удалит SSH-хост-ключи, логи и machine-id.

### См. также
- [Образы ВМ — Определения](./definitions.md)
- [Образы ВМ — Основные концепции](./basic_concepts.md)
- [Автоматизация сборки образов](./image_automation.md) — Packer, CI/CD пайплайн, тестирование.
- [Развёртывание в продакшен](./production_deployment.md) — сеть, CPU/память, HA, мониторинг.
- [Резервное копирование и восстановление ВМ](../kvm/vm_backup_dr.md) — стратегии бэкапа, DR.
- [KVM — Управление ВМ](../kvm/management.md)
- [Диагностика дисковой подсистемы](../../Diagnostics/Filesystem/iostat.md)
