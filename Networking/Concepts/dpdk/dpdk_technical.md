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
