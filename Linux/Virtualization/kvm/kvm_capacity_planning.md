# Планирование ресурсов и оптимизация ВМ (Capacity Planning)

Данный файл описывает методологию расчёта ресурсов для KVM-хостов и виртуальных машин: определение ratio CPU/RAM, right-sizing, прогнозирование нагрузки и предотвращение перерасхода. Overcommit и планирование описаны в [Overcommit и планирование ресурсов](./kvm_overcommit_and_capacity.md).

## Определения

**Capacity Planning** — процесс расчёта требуемых вычислительных ресурсов (CPU, RAM, Disk I/O, Network) для удовлетворения текущей и прогнозируемой нагрузки с учётом SLA и запаса.

**Right-Sizing** — процесс оптимизации конфигурации ВМ (vCPU, RAM) на основе реального потребления, устранение over-provisioning и under-provisioning.

**Over-Provisioning** — выделение ВМ ресурсов, превышающих реальное потребление. Ведёт к浪费 места и снижению плотности размещения.

**Under-Provisioning** — выделение ВМ ресурсов, недостаточных для реальной нагрузки. Ведёт к деградации производительности и простоям.

**Consolidation Ratio** — отношение количества ВМ к количеству физических хостов. Чем выше ratio, тем эффективнее использование ресурсов, но выше риск Noisy Neighbor.

**Steal Time** — время, в течение которого vCPU ВМ ожидал физический CPU из-за перегрузки хоста. Признак необходимости масштабирования.

**PSI (Pressure Stall Information)** — механизм ядра Linux для измерения давления на CPU, память и I/O. Позволяет прогнозировать деградацию до OOM или throttling.

## Базовые концепции

### Методология расчёта ресурсов

**Формула расчёта количества ВМ на хосте:**

```
CPU ratio = сумма vCPU всех ВМ / количество физических ядер
RAM ratio = сумма RAM всех ВМ / физическая RAM

Рекомендуемые ratios:
- CPU: 2:1 — 4:1 (depending on workload)
- RAM: 1.2:1 — 1.5:1 (max, с учётом balloon)
```

**Матрица рекомендуемых ratios по типу нагрузки:**

| Тип нагрузки | CPU ratio | RAM ratio | Пример |
| :--- | :--- | :--- | :--- |
| **Web-серверы (stateless)** | 3:1 — 4:1 | 1.2:1 | Nginx, Apache |
| **Application server** | 2:1 — 3:1 | 1.3:1 | Node.js, Java |
| **Базы данных** | 1:1 — 2:1 | 1:1 | PostgreSQL, MySQL |
| **Cache-серверы** | 2:1 | 1:1 | Redis, Memcached |
| **Batch processing** | 4:1 — 8:1 | 1.5:1 | CI/CD runners |

### Методы сбора данных для right-sizing

**1. Мониторинг через Prometheus:**
```yaml
# PromQL для анализа потребления CPU ВМ
# Среднее потребление CPU за 7 дней
avg_over_time(
  rate(libvirt_vcpu_cpu_time_seconds_total[5m])[7d:5m]
) by (domain)

# Максимальное потребление RAM за 7 дней
max_over_time(libvirt_domain_memory_usage_bytes[7d]) by (domain)

# Steal time (признак перегрузки хоста)
rate(libvirt_domain_vcpu_steal_time_seconds_total[5m]) > 0.05
```

**2. Мониторинг через virsh:**
```bash
# Текущее потребление CPU/RAM
virsh domstats web-server-01
# → cpu.user: 123456789
# → cpu.system: 987654321
# → balloon.current: 2048

# Исторические данные (через libvirt API)
virsh domstats --cpu-total --block-total --net-total web-server-01
```

**3. PSI (Pressure Stall Information):**
```bash
# Давление на CPU
cat /proc/pressure/cpu
# → some avg10=2.50 avg60=1.20 avg300=0.80 total=12345678
# → full avg10=0.00 avg60=0.00 avg300=0.00 total=0

# Давление на память
cat /proc/pressure/memory
# → some avg10=0.00 avg60=0.00 avg300=0.00 total=0
# → full avg10=0.00 avg60=0.00 avg300=0.00 total=0

# Давление на I/O
cat /proc/pressure/io
# → some avg10=5.20 avg60=3.10 avg300=2.00 total=98765432
# → full avg10=1.00 avg60=0.50 avg300=0.30 total=12345678
```

### Правила thumb для sizing

**CPU:**
- 1 vCPU = 1 core (не thread) для production БД
- Для web-серверов: 1 vCPU на 1000-2000 RPS (depends on app)
- Мониторить `steal time`: если > 5% — хост перегружен

**RAM:**
- Не используйте swap для latency-sensitive workloads
- Для БД: RAM = 25-50% от размера рабочего набора (working set)
- Для web/app: RAM = 2-4x от потребления при пиковой нагрузке
- Всегда оставляйте 20-30% RAM хоста свободной для буфера

**Disk I/O:**
- NVMe: 100k+ IOPS, 3-5 GB/s throughput
- SATA SSD: 10k IOPS, 500 MB/s
- HDD: 100-200 IOPS, 100-200 MB/s

**Network:**
- 1 Gbps = ~125 MB/s = ~100k пакетов/сек (small packets)
- 10 Gbps = ~1.25 GB/s
- Для ВМ с высокой сетевой нагрузкой: SR-IOV или macvtap

## Практические сценарии

### Сценарий 1: Right-sizing web-серверов

Анализ потребления 10 веб-серверов и оптимизация:

```bash
#!/bin/bash
# right-sizing-web.sh — анализ потребления ВМ
set -euo pipefail

echo "=== VM Resource Usage ==="
for vm in $(virsh list --name); do
  CPU=$(virsh domstats "$vm" 2>/dev/null | grep cpu.user | awk '{print $2}' || echo "0")
  MEM=$(virsh domstats "$vm" 2>/dev/null | grep balloon.current | awk '{print $2}' || echo "0")
  VCPU=$(virsh dominfo "$vm" 2>/dev/null | grep "CPU(s):" | awk '{print $2}' || echo "1")
  MAXMEM=$(virsh dominfo "$vm" 2>/dev/null | grep "Max memory" | awk '{print $3}' || echo "0")
  
  printf "%-20s vCPU=%-4s RAM=%-8s MaxRAM=%-8s\n" "$vm" "$VCPU" "${MEM}MB" "${MAXMEM}kB"
done

echo ""
echo "=== Recommendations ==="
# Правило: если реальное потребление < 50% от выделенного — уменьшить
# Если steal time > 5% — увеличить или перенести на другой хост
```

### Сценарий 2: Расчёт количества ВМ на хосте

```python
#!/usr/bin/env python3
"""capacity_calculator.py — расчёт capacity для KVM-хоста"""

# Физические ресурсы хоста
HOST_CPU_CORES = 32
HOST_RAM_GB = 128
CPU_RATIO = 3  # 3 vCPU на 1 core
RAM_RATIO = 1.3  # 1.3x oversubscription

# Доступные ресурсы
AVAIL_VCPU = HOST_CPU_CORES * CPU_RATIO  # 96 vCPU
AVAIL_RAM_GB = HOST_RAM_GB / RAM_RATIO   # ~98 GB

# Конфигурации ВМ
VM_CONFIGS = {
    "web-small": {"vcpu": 2, "ram_gb": 4},
    "web-medium": {"vcpu": 4, "ram_gb": 8},
    "app-medium": {"vcpu": 4, "ram_gb": 16},
    "db-large": {"vcpu": 8, "ram_gb": 32},
}

# Расчёт
for name, config in VM_CONFIGS.items():
    max_vms_by_cpu = AVAIL_VCPU // config["vcpu"]
    max_vms_by_ram = int(AVAIL_RAM_GB // config["ram_gb"])
    max_vms = min(max_vms_by_cpu, max_vms_by_ram)
    print(f"{name}: max {max_vms} VMs (CPU limit: {max_vms_by_cpu}, RAM limit: {max_vms_by_ram})")
```

### Сценарий 3: Мониторинг steal time и алертинг

```yaml
# Prometheus alert rule
groups:
  - name: vm_capacity
    rules:
      - alert: VMHighStealTime
        expr: rate(libvirt_domain_vcpu_steal_time_seconds_total[5m]) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High steal time on {{ $labels.domain }}"
          description: "Steal time > 5% for 10 minutes. Host may be overloaded."

      - alert: VMHighMemoryUsage
        expr: (libvirt_domain_memory_usage_bytes / libvirt_domain_memory_stats_available_bytes) > 0.9
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Memory usage > 90% on {{ $labels.domain }}"

      - alert: HostCPUSaturated
        expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 90
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "Host CPU > 90% for 15 minutes"
```

### Сценарий 4: Автоматический right-sizing через Ansible

```yaml
---
- name: VM Right-Sizing
  hosts: kvm-hosts
  vars:
    vm_overcommit_threshold: 0.5  # если < 50% использование — уменьшить
  tasks:
    - name: Получение статистики ВМ
      shell: virsh domstats {{ item }} --cpu-total --block-total
      register: vm_stats
      loop: "{{ groups['vms'] }}"

    - name: Анализ и рекомендации
      debug:
        msg: |
          VM: {{ item.item }}
          CPU usage: {{ item.stdout_lines | select('match', 'cpu.user') | first }}
      loop: "{{ vm_stats.results }}"
      when: vm_stats is not failed
```

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **OOM Killer срабатывает** | Недостаточно RAM, swap отключен | Увеличить RAM или включить swap |
| **Steal time > 5%** | Хост перегружен CPU | Уменьшить количество ВМ или увеличить хост |
| **CPU throttling** | cgroup quota exceeded | Увеличить quota или vCPU |
| **Дисковое место заканчивается** | Нет мониторинга | Настроить алерты на disk usage > 80% |
| **Высокая latency** | Noisy Neighbor | CPU pinning, I/O throttling |

## Дополнительная информация

- [Overcommit и планирование ресурсов](./kvm_overcommit_and_capacity.md) — CPU/RAM overcommit, расчёт ratio.
- [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md) — NUMA, pinning, io_uring.
- [Мониторинг KVM](./kvm_monitoring.md) — Prometheus, Grafana, kvm_stat.
- [Резервное копирование и DR](./vm_backup_dr.md) — RPO/RTO, стратегии бэкапа.
- [Capacity Planning: общие принципы](../../Concepts/capacity-planning.md) — методология, формулы.
- [Kubernetes Right-Sizing](../../Kubernetes/Autoscaling/hpa_cost_rightsizing.md) — VPA, HPA, методология.
