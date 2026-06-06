# Алгоритмы управления перегрузкой TCP в Linux

> **SSoT:** Полная документация по алгоритмам (CUBIC, BBR, Reno, формулы, сравнение) — в [Алгоритмы управления перегрузкой TCP](../../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md).

## Основные концепции

### Взаимодействие с qdisc

В Linux алгоритм управления перегрузкой тесно связан с дисциплиной очереди (qdisc). Выбор qdisc может существенно влиять на эффективность алгоритма:

- **BBR:** настоятельно рекомендуется использовать совместно с `fq` (Fair Queueing) для корректной работы механизма pacing.
- **CUBIC:** хорошо сочетается с `fq_codel` или `cake` для борьбы с bufferbloat на домашних роутерах.

---

## Практические сценарии

### Просмотр состояния в системе

```bash
# Список доступных алгоритмов (загруженных в ядро)
sysctl net.ipv4.tcp_available_congestion_control
# Пример: net.ipv4.tcp_available_congestion_control = cubic reno bbr

# Текущий алгоритм по умолчанию
sysctl net.ipv4.tcp_congestion_control

# Просмотр алгоритма для конкретных соединений
ss -ti
```

### Включение BBR

**Требования:** ядро Linux 4.9+.

1. **Настройка параметров ядра:**

   ```bash
   # /etc/sysctl.d/99-bbr.conf
   net.core.default_qdisc = fq
   net.ipv4.tcp_congestion_control = bbr
   ```

2. **Применение настроек:**

   ```bash
   sudo sysctl -p /etc/sysctl.d/99-bbr.conf
   ```

### BBRv3 (экспериментально)

На 2026 год BBRv3 доступен в некоторых современных дистрибутивах (например, Fedora, последние версии Ubuntu HWE) или через сторонние репозитории.

- Для BBRv3 также рекомендуется qdisc `fq`.
- Проверить версию BBR напрямую через sysctl нельзя, но можно косвенно через `modinfo tcp_bbr` (если загружен как модуль).

### Возврат к CUBIC

Если BBR вызывает проблемы с несправедливым распределением полосы (fairness) в старых сетях:

```bash
# /etc/sysctl.d/99-network.conf
net.core.default_qdisc = fq_codel
net.ipv4.tcp_congestion_control = cubic
```

---

## Дополнительная информация

### Связанные темы

- [Алгоритмы управления перегрузкой TCP (SSoT)](../../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md) — теория и описание.
- [Дисциплины очередей TCP](./tcp_queueing_disciplines.md) — подробнее о fq, fq_codel и др.
- [Диагностика перегрузок](../../../../Networking/Protocols/TCP/congestion/tcp_congestion_diagnostics.md) — анализ через `ss` и `ip route`.
- [Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md) — общие настройки стека.
