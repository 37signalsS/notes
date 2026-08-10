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

## Дополнительная информация

### Безопасность и проверка
*   **Проверка на ошибки:** `qemu-img check disk.qcow2` — исправляет незначительные повреждения метаданных.
*   **Очистка перед публикацией:** Всегда используйте `virt-sysprep -a image.qcow2` перед тем, как делиться образом. Это удалит SSH-хост-ключи, логи и machine-id.

### См. также
- [Образы ВМ — Определения](./definitions.md)
- [Образы ВМ — Основные концепции](./basic_concepts.md)
- [KVM — Управление через virsh](../kvm/management.md)
- [Диагностика дисковой подсистемы](../../Diagnostics/Filesystem/iostat.md)
