# Настройка параметров ядра (sysctl) — тюнинг и оптимизация

## Определения

**`sysctl`** — утилита и механизм ядра Linux, предназначенные для чтения и изменения параметров ядра в режиме реального времени (runtime) без необходимости перезагрузки системы.

**`/proc/sys/`** — виртуальная файловая система, через которую ядро экспортирует свои внутренние переменные в пространство пользователя. Утилита `sysctl` служит высокоуровневым интерфейсом к этой ФС, позволяя работать с параметрами в формате иерархических имен (например, `net.ipv4.ip_forward` вместо прямого обращения к пути `/proc/sys/net/ipv4/ip_forward`).

Тюнинг параметров ядра критически важен для адаптации ОС под специфические нагрузки: высокопроизводительные базы данных, узлы Kubernetes, сетевые шлюзы и системы с повышенными требованиями к безопасности (hardened).

## Основные концепции

### Иерархия параметров

Параметры сгруппированы по функциональным разделам, что отражается в их именовании:

- **`net.*`** — Сетевой стек. Управление TCP/IP, ARP, маршрутизацией, фильтрацией пакетов и дисциплинами очередей (qdisc).
- **`vm.*`** — Виртуальная память. Настройка агрессивности Swap, лимитов на маппинг памяти (`max_map_count`) и алгоритмов очистки кэша.
- **`kernel.*`** — Общие свойства ядра. Лимиты на PID, безопасность eBPF, параметры планировщика и поведение при сбоях (Panic).
- **`fs.*`** — Файловые системы. Лимиты на количество открытых дескрипторов (`file-max`), квоты и подписки `inotify`.
- **`user.*`** — Лимиты ресурсов для пространств имён пользователей (user namespaces).

### Ключевые параметры для современных систем (2024-2025)

| Параметр | Описание | Рекомендуемое значение (High Load) |
| :--- | :--- | :--- |
| `net.ipv4.tcp_congestion_control` | Алгоритм управления перегрузкой. | `bbr` (BBRv3 в ядрах 6.x) |
| `net.core.default_qdisc` | Дисциплина очередей по умолчанию. | `fq` (необходимо для BBR) |
| `net.core.somaxconn` | Максимальный размер очереди сокетов. | `65535` |
| `vm.swappiness` | Агрессивность использования Swap. | `10` (для SSD/NVMe) |
| `kernel.randomize_va_space` | Рандомизация адресного пространства (ASLR). | `2` (Full ASLR) |
| `net.ipv4.tcp_syncookies` | Защита от SYN-флуда. | `1` (Enabled) |
| `kernel.pid_max` | Максимальный PID в системе. | `4194304` (для плотных K8s узлов) |

## Практические сценарии

### Основные команды управления

```bash
# Вывести все текущие параметры системы
sysctl -a

# Получить значение конкретного параметра
sysctl net.ipv4.ip_forward

# Временное изменение параметра (до перезагрузки)
sudo sysctl -w net.ipv4.ip_forward=1
```

### Постоянное сохранение настроек

Для обеспечения персистентности настроек используются файлы конфигурации.

- **`/etc/sysctl.conf`** — классический файл (устаревает, не рекомендуется для новых настроек).
- **`/etc/sysctl.d/*.conf`** — современный модульный стандарт. Файлы загружаются в лексикографическом порядке (например, `99-performance.conf` перекроет `10-defaults.conf`).

**Эталонная конфигурация `/etc/sysctl.d/99-performance.conf`:**
```conf
# --- Сетевая производительность ---
# Включение BBRv3 (требует ядро 6.x и fq)
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# Оптимизация буферов для 10Gbps+ сетей
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_rmem = 4096 87380 134217728
net.ipv4.tcp_wmem = 4096 65536 134217728

# Масштабируемость соединений
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535

# --- Виртуальная память и MGLRU ---
# Swappiness для быстрых накопителей
vm.swappiness = 10
vm.vfs_cache_pressure = 50
# Лимит для Elasticsearch/Lucene
vm.max_map_count = 262144

# --- Безопасность (Hardening) ---
# Для комплексного харденинга см. SSoT: [Харденинг ядра Linux](../../Security/Mechanisms/Kernel/hardening.md)
# Защита от SYN атак и спуфинга
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
# Отключение редиректов (защита от MITM)
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
# Ограничение доступа к dmesg и JIT
kernel.dmesg_restrict = 1
net.core.bpf_jit_harden = 2
```

### Применение конфигурации

```bash
# Применить изменения из всех файлов (/etc/sysctl.d/, /run/sysctl.d/ и т.д.)
sudo sysctl --system

# Применить изменения из конкретного файла вручную
sudo sysctl -p /etc/sysctl.d/99-performance.conf
```

### Тюнинг MGLRU (Multi-Gen LRU)

В новых ядрах (6.1+) механизм MGLRU значительно повышает производительность при нехватке памяти. Его настройка производится через `/sys/kernel/mm/`, но часто дублируется в скриптах тюнинга.

```bash
# Включение всех компонентов MGLRU (Aging, Eviction, Tiering)
echo 7 > /sys/kernel/mm/lru_gen/enabled
```

## Тюнинг в Kubernetes

В Kubernetes параметры `sysctl` делятся на:
- **Безопасные (Safe):** Можно настраивать в `PodSpec` через `securityContext.sysctls` (например, `net.ipv4.tcp_keepalive_time`).
- **Небезопасные (Unsafe):** Требуют явного разрешения в конфиге `kubelet` узла (параметр `--allowed-unsafe-sysctls`).

**Пример манифеста Pod:**
```yaml
securityContext:
  sysctls:
  - name: net.core.somaxconn
    value: "16384"
```

## Дополнительная информация

### Связанные темы

- **Интерфейсы ядра:** [Интерфейсы ядра Linux](./kernel_interfaces.md) — роль Syscalls и виртуальных ФС.
- **Сетевая оптимизация:** [Алгоритмы TCP](../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md) — подробнее о логике BBR.
- **Тюнинг памяти:** [Performance Tuning](../memory/performance_tuning.md) — глубокая настройка подсистемы виртуальной памяти.
- **Диагностика:** [Анализ Kernel Panic](./kernel_panic.md) — использование `kernel.panic` для автоматической перезагрузки.

### Полезные ссылки
- [Документация ядра: sysctl/net](https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt)
- [Документация ядра: sysctl/vm](https://www.kernel.org/doc/Documentation/sysctl/vm.txt)
