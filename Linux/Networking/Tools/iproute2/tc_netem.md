# tc netem: эмуляция сетевых проблем

**`tc netem` (Network Emulator)** — модуль `tc` для эмуляции сетевых условий: задержки, потери, повреждения, дублирование, изменение порядка пакетов.

## Навигация

### Основы

- **[Архитектура и концепции](./tc_netem_basics.md)** — параметры эмуляции, jitter, распределения задержки
- **[Практические сценарии](./tc_netem_scenarios.md)** — задержка, потери, reorder, тестовые кейсы

### Продвинутые темы

- **[Эмуляция таймаутов через iptables](./tc_netem_iptables_timeout.md)** — connection/request timeout

---

## Быстрый старт

```bash
# Добавить задержку 100ms
sudo tc qdisc add dev eth0 root netem delay 100ms

# Добавить потерю 5%
sudo tc qdisc add dev eth0 root netem loss 5%

# Удалить конфигурацию
sudo tc qdisc del dev eth0 root netem
```

---

## Связанные темы

- **[tc](./tc.md)** — полное руководство по управлению трафиком
- **[Оптимизация TCP](../../Concepts/tcp_tuning.md)** — настройка TCP-стека
- **[QoS](../../../../Networking/Concepts/qos.md)** — концепции качества обслуживания
- **[iptables](../Settings/tools/iptables_basics.md)** — эмуляция таймаутов
- **[tcpdump](../tcpdump.md)** — диагностика сетевых проблем
