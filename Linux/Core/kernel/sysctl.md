# Настройка параметров ядра (sysctl)

## Определения

**`sysctl`** — утилита и механизм Linux для просмотра и изменения параметров ядра runtime, без перезагрузки. Параметры (tunables) управляют поведением подсистем: сети, виртуальной памяти, ФС, безопасности.

## Основные концепции

### Иерархическая структура

Параметры организованы иерархически и доступны через `/proc/sys/`. Например, `vm.swappiness` соответствует файлу `/proc/sys/vm/swappiness`.

### Тематическая группировка

| Префикс | Подсистема | Примеры |
| :--- | :--- | :--- |
| `vm.*` | Виртуальная память | `vm.swappiness`, `vm.overcommit_memory` |
| `net.*` | Сетевой стек | `net.ipv4.ip_forward`, `net.core.somaxconn` |
| `kernel.*` | Общие параметры ядра | `kernel.hostname`, `kernel.panic` |
| `fs.*` | Файловая система | `fs.file-max`, `fs.inotify.max_user_watches` |

### Безопасность

Критические параметры безопасности настраиваются через `sysctl`:

- `kernel.dmesg_restrict` — ограничение доступа к логам ядра
- `net.ipv4.tcp_syncookies` — защита от SYN-флуда
- `kernel.kptr_restrict` — скрытие указателей ядра из `/proc`

### Динамические параметры

Некоторые параметры появляются в `/proc/sys` только после загрузки соответствующих модулей ядра.

## Практические сценарии

### Просмотр параметров

```bash
# Все параметры
sudo sysctl -a

# Конкретный параметр
sysctl vm.swappiness

# Поиск по ключевому слову
sysctl -a | grep ip_forward
```

### Изменение параметров (временно)

Действуют до перезагрузки:

```bash
# Через утилиту sysctl
sudo sysctl -w vm.swappiness=10

# Напрямую в /proc
echo 10 | sudo tee /proc/sys/vm/swappiness
```

### Сохранение параметров (постоянно)

1. Создать файл `/etc/sysctl.d/99-custom.conf`:

    ```
    net.ipv4.ip_forward = 1
    net.core.somaxconn = 4096
    ```

2. Применить без перезагрузки:

    ```bash
    sudo sysctl --system
    # Или конкретный файл:
    sudo sysctl -p /etc/sysctl.d/99-custom.conf
    ```

## Дополнительная информация

### Связанные темы

- **Интерфейсы ядра:** [Kernel Interfaces](./kernel_interfaces.md) — `/proc/sys/` как часть procfs
- **Сетевые параметры:** [TCP Tuning](../../Networking/Concepts/tcp_tuning/tcp_congestion_algorithms.md) — оптимизация сетевого стека через `net.*`
- **Паника ядра:** [Kernel Panic](./kernel_panic.md) — настройка `kernel.panic` для автоперезагрузки
- **Зависания ядра:** [Lockups](./lockups.md) — параметры `kernel.watchdog_thresh`, `kernel.softlockup_panic`
- **Маршрутизация:** [Routing](../../SystemAdministration/routing.md) — включение `net.ipv4.ip_forward`
