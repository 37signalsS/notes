# Управление очередями соединений TCP

## Определения

**SYN backlog** — очередь полуоткрытых соединений в состоянии `SYN_RECV`, контролируется параметром `net.ipv4.tcp_max_syn_backlog`.

**Accept backlog** — очередь установленных соединений в состоянии `ESTABLISHED`, ожидающих вызова `accept()` приложением, размер определяется `net.core.somaxconn`.

## Настройка параметров

### Увеличение очередей соединений

```bash
# Увеличить accept backlog (максимум ожидающих соединений)
sudo sysctl -w net.core.somaxconn=65535

# Увеличить SYN backlog (полуоткрытые соединения). Это помогает предотвратить отбрасывание SYN-пакетов (SYN drop).
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=4096

# Увеличить очередь пакетов от NIC (сетевой карты). Помогает не терять пакеты при кратковременных всплесках трафика, когда ядро не успевает их обработать.
sudo sysctl -w net.core.netdev_max_backlog=30000
```

### Последствия переполнения

* Переполнение `SYN backlog` → отбрасывание SYN-пакетов (SYN drop) → задержки установления соединения
* Переполнение `Accept backlog` → сброс соединений с отправкой `RST` → отказы в обслуживании

## Защита от SYN-флуд

```bash
# Включение SYN cookies (обычно включено по умолчанию)
sudo sysctl -w net.ipv4.tcp_syncookies=1
```

SYN cookies активируются автоматически при риске переполнения SYN backlog.

> Детальная диагностика: [`ss`](../../Diagnostics/Networking/ss.md)

## Связанные темы

* **[`sysctl`](../../Core/kernel/sysctl.md)** — управление параметрами ядра
* **Обзор оптимизации TCP:** [Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md)
* **[SYN-флуд](../../../Networking/Concepts/dos_ddos_overview.md#syn-флуд)** — информация об атаке
