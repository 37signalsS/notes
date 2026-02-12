# DPDK: Технические детали

## Hugepages

DPDK использует hugepages (2MB или 1GB) вместо стандартных 4KB страниц:
- Уменьшает размер TLB (Translation Lookaside Buffer)
- Снижает количество page faults
- Улучшает локальность данных

```bash
# Настройка hugepages
# /etc/sysctl.conf
vm.nr_hugepages = 1024

# Проверка
cat /proc/meminfo | grep Huge
```

## PMD (Poll Mode Drivers)

Вместо прерываний DPDK использует polling:

```c
// Пример polling loop в DPDK
while (1) {
    // Прием пакетов (не блокируется!)
    nb_rx = rte_eth_rx_burst(port_id, queue_id, rx_pkts, BURST_SIZE);
    
    if (nb_rx > 0) {
        // Обработка пакетов
        process_packets(rx_pkts, nb_rx);
    }
    
    // Отправка пакетов
    rte_eth_tx_burst(port_id, queue_id, tx_pkts, nb_tx);
}
```

**Преимущества polling:**
- Нет overhead от прерываний
- Предсказуемая задержка (latency)
- Максимальная пропускная способность

**Недостатки:**
- 100% загрузка CPU ядра
- Неэффективен при низкой нагрузке

## Производительность DPDK

| Метрика | Linux Kernel | DPDK | Улучшение |
|---------|--------------|------|-----------|
| **Throughput** | 1-2 Mpps | 100+ Mpps | 50-100x |
| **Latency** | 10-50 μs | 1-5 μs | 10x |
| **Jitter** | Высокий | Низкий | Стабильнее |
| **CPU per packet** | Высокое | Минимальное | Эффективнее |

## Использование DPDK

**Сценарии применения:**
- NFV (Network Function Virtualization)
- Виртуальные маршрутизаторы (vRouter)
- Load balancers
- 5G packet core
- IPS/IDS высокой производительности
- High-frequency trading

**Примеры продуктов на DPDK:**
- VPP (Vector Packet Processing) от Cisco
- OVS-DPDK (Open vSwitch with DPDK)
- DPDK-based NAT
- Telecom applications
