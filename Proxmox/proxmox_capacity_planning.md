# Планирование ресурсов (Capacity Planning) в Proxmox VE

## Определения

**Capacity Planning** -- процесс расчёта требуемых вычислительных ресурсов (CPU, RAM, Disk I/O, Network) для удовлетворения текущей и прогнозируемой нагрузки с учётом SLA и запаса.

**Right-Sizing** -- процесс оптимизации конфигурации VM (vCPU, RAM) на основе реального потребления, устранение over-provisioning и under-provisioning.

**Over-Provisioning** -- выделение VM ресурсов, превышающих реальное потребление. Ведёт к浪费 места и снижению плотности размещения.

**Under-Provisioning** -- выделение VM ресурсов, недостаточных для реальной нагрузки. Ведёт к деградации производительности и простоям.

**Consolidation Ratio** -- отношение количества VM к количеству физических хостов. Чем выше ratio, тем эффективнее использование ресурсов, но выше риск Noisy Neighbor.

**Steal Time** -- время, в течение которого vCPU VM ожидал физический CPU из-за перегрузки хоста. Признак необходимости масштабирования.

**PSI (Pressure Stall Information)** -- механизм ядра Linux для измерения давления на CPU, память и I/O. Позволяет прогнозировать деградацию до OOM или throttling.

**Overcommit** -- выделение VM ресурсов сверх физически доступных. CPU overcommit безопасен (contention), RAM overcommit опасен (OOM).

## Теоретический блок

### Методология расчёта ресурсов

**Формула расчёта количества VM на хосте:**

```
CPU ratio = сумма vCPU всех VM / количество физических ядер
RAM ratio = сумма RAM всех VM / физическая RAM

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
| **Desktop/GUI** | 1:1 — 2:1 | 1.2:1 | Windows, Linux desktop |

### Методы сбора данных

**1. Proxmox API:**

```bash
# Статус узла
curl -k -H "Authorization: PVEAPIToken=$TOKEN" \
  "https://pve1:8006/api2/json/nodes/node1/status" | jq '.data'

# Список VM с ресурсами
curl -k -H "Authorization: PVEAPIToken=$TOKEN" \
  "https://pve1:8006/api2/json/nodes/node1/qemu" | jq '.data[] | {vmid, name, status, cpu, maxmem, maxdisk}'
```

**2. Prometheus + pve-exporter:**

```yaml
# PromQL для анализа потребления CPU VM
# Среднее потребление CPU за 7 дней
avg_over_time(
  rate(pve_cpu_seconds_total[5m])[7d:5m]
) by (vmid)

# Максимальное потребление RAM за 7 дней
max_over_time(pve_memory_used_bytes[7d]) by (vmid)

# Steal time (признак перегрузки хоста)
rate(pve_cpu_steal_seconds_total[5m]) > 0.05
```

**3. CLI-команды:**

```bash
# Статус всех VM
qm list

# Детальная информация о VM
qm status <vmid> --verbose

# Использование CPU на узле
mpstat -P ALL 1

# Использование RAM
free -h
cat /proc/meminfo | grep -E "MemTotal|MemFree|Buffers|Cached"

# IO delay
iostat -xmt 1

# NUMA статистика
numastat -p $(pgrep qemu)
```

## Практические сценарии

### 1. Анализ текущего использования

```bash
# Скрипт для анализа всех VM
#!/bin/bash
echo "VMID | Name | Status | CPU% | RAM Used | RAM Total | Disk Used"
echo "-----|------|--------|------|----------|-----------|---------"

for vmid in $(qm list | awk 'NR>1 {print $1}'); do
  status=$(qm status $vmid 2>/dev/null | awk '{print $2}')
  if [ "$status" = "running" ]; then
    config=$(qm config $vmid 2>/dev/null)
    name=$(echo "$config" | grep "^name:" | awk '{print $2}')
    cpu=$(echo "$config" | grep "^cores:" | awk '{print $2}')
    mem=$(echo "$config" | grep "^memory:" | awk '{print $2}')
    echo "$vmid | $name | $status | $cpu cores | $mem MB"
  fi
done
```

### 2. Правила алертинга Prometheus

```yaml
# groups:
# - name: proxmox_capacity
#   rules:
# High CPU usage
- alert: HighVmCpuUsage
  expr: |
    100 - (avg by(vmid) (rate(pve_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
  for: 30m
  labels:
    severity: warning
  annotations:
    summary: "High CPU usage on VM {{ $labels.vmid }}"

# High Memory usage
- alert: HighVmMemoryUsage
  expr: |
    (pve_memory_used_bytes / pve_memory_total_bytes) * 100 > 85
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "High memory usage on VM {{ $labels.vmid }}"

# Steal time (host overload)
- alert: HighStealTime
  expr: |
    rate(pve_cpu_steal_seconds_total[5m]) > 0.1
  for: 15m
  labels:
    severity: critical
  annotations:
    summary: "High steal time on node {{ $labels.node }}"

# Low disk space
- alert: LowDiskSpace
  expr: |
    (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 < 20
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Low disk space on node {{ $labels.node }}"
```

### 3. Автоматический right-sizing

```yaml
# Ansible playbook для автоматического right-sizing
---
- name: VM Right-Sizing
  hosts: proxmox
  vars:
    cpu_threshold: 20      # если < 20% использование — уменьшить
    memory_threshold: 30   # если < 30% использование — уменьшить
    scale_up_cpu: 80       # если > 80% использование — увеличить
    scale_up_memory: 85    # если > 85% использование — увеличить

  tasks:
    - name: Get VM stats
      uri:
        url: "https://pve1:8006/api2/json/nodes/{{ inventory_hostname }}/qemu"
        headers:
          Authorization: "PVEAPIToken={{ pve_token }}"
        validate_certs: false
      register: vm_list

    - name: Analyze and resize
      shell: |
        # Анализ и рекомендации
        echo "VM Analysis Report"
        echo "=================="
        for vmid in $(qm list | awk 'NR>1 {print $1}'); do
          # Получение статистики и рекомендаций
          echo "VM $vmid: $(qm config $vmid | grep -E 'cores|memory')"
        done
```

### 4. Прогнозирование нагрузки

```bash
# Прогнозирование роста на основе тренда
#!/bin/bash
# Сбор данных за 30 дней
CURRENT_VMS=$(qm list | wc -l)
CURRENT_RAM=$(free -g | awk '/^Mem:/{print $2}')
USED_RAM=$(free -g | awk '/^Mem:/{print $3}')

# Прогноз на 6 месяцев (10% роста в месяц)
MONTHS=6
GROWTH_RATE=0.10

PROJECTED_VMS=$(echo "$CURRENT_VMS * (1 + $GROWTH_RATE)^$MONTHS" | bc -l)
PROJECTED_RAM=$(echo "$CURRENT_RAM * (1 + $GROWTH_RATE)^$MONTHS" | bc -l)

echo "Current: $CURRENT_VMS VMs, ${CURRENT_RAM}GB RAM"
echo "Projected (6 months): $PROJECTED_VMS VMs, ${PROJECTED_RAM}GB RAM"
echo "Additional RAM needed: $(echo "$PROJECTED_RAM - $CURRENT_RAM" | bc -l) GB"
```

### 5. Правила размещения VM

```bash
# Размещение критичных VM на выделенных узлах
qm set 101 --affinity 0-3  # CPU pinning для DB

# Размещение по NUMA
qm set 101 --numa 1 --memory 16384

# Изоляция от Noisy Neighbor
qm set 101 --cpu host,limit=2  # Ограничение CPU

# Приоритеты
qm set 101 --shares 2048  # Высокий приоритет
qm set 102 --shares 512   # Низкий приоритет
```

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| High steal time | Перегрузка хоста CPU | Добавьте ядра илиVM на другой узел |
| OOM kill в VM | Нехватка RAM | Увеличьте лимит или добавьте swap |
| High I/O delay | Перегрузка хранилища | Миграция на SSD/NVMe или добавление OSD |
| CPU throttling | Overcommit CPU | Уменьшите количество VM или увеличьте ядра |
| Low consolidation ratio | Under-provisioning | Оптимизируйте конфигурации VM |

## Лучшие практики

1. **Мониторинг**: Настройте Prometheus + Grafana для отслеживания ресурсов.
2. **Headroom**: Всегда резервируйте 20-30% запаса ресурсов.
3. **Регулярная оценка**: Проверяйте использование ресурсов ежемесячно.
4. **Прогнозирование**: Учитывайте рост числа VM и пользователей.
5. **Автоматизация**: Используйте Ansible/Terraform для автоматического right-sizing.
6. **Алерты**: Настройте уведомления на превышение пороговых значений.
7. **Documentation**: Ведите реестр VM с описанием назначения и ожидаемой нагрузки.

## Граничные случаи

- **Seasonal spikes**: Учитывайте сезонные пики нагрузки (Black Friday, النهاية года).
- **Development vs Production**: Dev-среды могут иметь более высокий overcommit ratio.
- **Database workloads**: Требуют выделенных ресурсов; избегайте overcommit CPU/RAM.
- **Batch processing**: Может безопасно использовать высокий CPU overcommit.

## Дополнительная информация

### Связанные темы

- [Планирование ресурсов и оптимизация ВМ (Capacity Planning) -- SSoT](../Linux/Virtualization/kvm/kvm_capacity_planning.md)
- [Overcommit и планирование ресурсов KVM -- SSoT](../Linux/Virtualization/kvm/kvm_overcommit_and_capacity.md)
- [Оптимизация производительности KVM/LXC](./proxmox_performance.md)
- [Мониторинг Proxmox через Prometheus](./proxmox_monitoring.md)
- [Хранилища и Ceph](./proxmox_storage.md)
