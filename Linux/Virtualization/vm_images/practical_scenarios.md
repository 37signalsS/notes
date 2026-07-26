# Образы ВМ — Практические сценарии

**Reliability Score: 10 (Verified Toolset 2026)**

В данном файле собраны инструкции по манипуляции образами виртуальных машин с использованием утилит `qemu-img` и пакета `libguestfs`. Теоретические основы описаны в [Определениях](./definitions.md) и [Основных концепциях](./basic_concepts.md).

## Базовые инструменты

*   **qemu-img** — швейцарский нож для работы с форматами, размерами и снапшотами.
*   **libguestfs (virt-*)** — набор высокоуровневых утилит для безопасной модификации содержимого дисков без запуска ВМ и без использования `mount`/`chroot`.
*   **qemu-nbd** — низкоуровневый инструмент для монтирования дисков через сетевое блочное устройство.

## Практические сценарии

### Сценарий 1: Базовые операции с qemu-img

#### Создание и анализ
```bash
# Создание qcow2 с предварительным выделением метаданных (ускоряет запись)
qemu-img create -f qcow2 -o preallocation=metadata web-server.qcow2 40G

# Проверка реального и виртуального размера
qemu-img info web-server.qcow2
# → image: web-server.qcow2
# → file format: qcow2
# → virtual size: 40 GiB
# → disk size: 2.1 MiB (тонкий диск)
```

#### Конвертация и сжатие
Конвертация в новый файл — лучший способ «схлопнуть» пустое место в `qcow2`.
```bash
# Конвертация из VMDK в QCOW2 с включенным сжатием
qemu-img convert -f vmdk -O qcow2 -c source.vmdk compressed_target.qcow2

# Оценка необходимого места перед конвертацией
qemu-img measure -f raw -O qcow2 raw_disk.img
# → required size: 10737418240 (размер результирующего файла)
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

### Сценарий 4: Работа с внешними снапшотами

Внешние снапшоты предпочтительнее для продакшена (лучшая производительность, чем у внутренних).

```bash
# Создание внешнего снапшота (оригинал становится backing file)
# Обязательно указывайте -F qcow2 для безопасности
qemu-img create -f qcow2 -F qcow2 -b base.qcow2 snapshot1.qcow2

# Слияние изменений (Commit) обратно в базовый образ
qemu-img commit snapshot1.qcow2
# → Image committed. (snapshot1 теперь можно удалять)

# Перепривязка к новому базовому образу (Rebase)
qemu-img rebase -b new_base.qcow2 -F qcow2 disk.qcow2
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
