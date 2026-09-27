# Chaos Engineering для не-Kubernetes сред

## Определения

**Non-Kubernetes Chaos** — направление Chaos Engineering, ориентированное на среды, не использующие Kubernetes: виртуальные машины (VM), bare-metal серверы, Docker-контейнеры без оркестрации, гипервизоры.

**VM Termination Chaos** — симуляция внезапного отключения виртуальной машины для проверки resilience инфраструктуры и приложений.

**Bare-Metal Chaos** — хаос-тестирование на физических серверах: отключение питания, дисковая ошибка, сетевой partition.

**Hypervisor Chaos** — инъекция сбоев на уровне гипервизора: pause/resume VM, memory ballooning, CPU limit.

**Docker Standalone Chaos** — хаос-тестирование для Docker-контейнеров без Kubernetes: Pumba, Toxiproxy, docker-compose.

**Docker Swarm Chaos** — хаос-тестирование для Docker Swarm: service task kill, network partition, Pumba.

**Nomad Chaos** — хаос-тестирование для Nomad: allocation stop, node drain, PowerfulSeal.

## Основные концепции

### Среды и соответствующие инструменты

| Среда | Инструменты | Типичные сценарии |
|:---|:---|:---|
| **Virtual Machines** | AWS Fault Injection Simulator, Azure Chaos Studio, GCP Chaos Engineering, Pumba | VM termination, disk latency, network partition |
| **Bare-Metal** | PowerfulSeal, custom scripts (ipmitool, tc, iptables) | Power off, NIC failure, disk error |
| **Docker Standalone** | Pumba, Toxiproxy, docker-compose | Container kill, network delay, pause |
| **Docker Swarm** | Pumba, custom scripts | Service task kill, network partition |
| **Hypervisor** | QEMU/KVM scripts, VMware PowerCLI | VM pause, memory ballooning, CPU cap |
| **Nomad** | Nomad built-in, PowerfulSeal | Allocation stop, node drain |

### Подходы к chaos для не-K8s сред

**Infrastructure-level:**
- VM/instance termination
- Disk I/O throttling
- Network latency/loss
- CPU/memory starvation

**Application-level:**
- Process kill
- Port blocking
- File descriptor exhaustion
- Disk full

**Dependency-level:**
- Database connection failure
- External API timeout
- DNS resolution failure

## Практические сценарии

### Сценарий 1: Docker Standalone chaos (Pumba)

**Цель:** Проверить resilience Docker-контейнеров без оркестратора.

**Инструмент:** Pumba.

**Инжектируем сбои:**

```bash
# Пауза контейнера на 30 секунд
pumba pause --duration 30s <container_id>

# Удаление контейнера (SIGKILL)
pumba kill --signal SIGKILL <container_id>

# Сетевая задержка 500мс
pumba netem --duration 60s --delay 500ms <container_id>

# Потеря пакетов 10%
pumba netem --duration 60s --loss 10% <container_id>

# Остановка всех контейнеров образа
pumba stop --duration 60s <image_name>
```

**Пример: chaos для docker-compose:**

```bash
#!/bin/bash
# docker-compose-chaos.sh

# Запускаем стек
docker-compose up -d

# Ждем готовности
sleep 30

# Инжектируем паузу в frontend
FRONTEND_ID=$(docker ps -qf "name=frontend")
pumba pause --duration 30s $FRONTEND_ID

# Проверяем, что backend продолжает работать
curl -s http://localhost:8080/health
# → 200 OK

# Инжектируем network delay между frontend и backend
BACKEND_ID=$(docker ps -qf "name=backend")
pumba netem --duration 60s --delay 500ms --target $BACKEND_ID $FRONTEND_ID

# Проверяем timeout handling
curl -s -w "\n%{time_total}\n" http://localhost:8080/api/data
# → timeout или degraded response

# Очистка
docker-compose down
```

### Сценарий 2: VM termination chaos

**Цель:** Проверить, что приложение переживает внезапное отключение VM.

**Инструмент:** AWS Fault Injection Simulator (FIS) или manual termination.

**AWS FIS:**

```json
{
  "Targets": [
    {
      "ResourceType": "aws:ec2:instance",
      "ResourceArns": ["arn:aws:ec2:us-east-1:123456789012:instance/i-1234567890abcdef0"],
      "Filters": [
        {
          "Path": "Tags.Name",
          "Values": ["production-api-server"]
        }
      ]
    }
  ],
  "Actions": [
    {
      "ActionId": "aws:ec2:terminate-instances",
      "Parameters": {
        "InstanceWaitTime": 300
      }
    }
  ],
  "StopConditions": [
    {
      "Source": "none"
    }
  ],
  "RoleArn": "arn:aws:iam::123456789012:role/FISRole"
}
```

**Azure Chaos Studio:**

```bash
# Создание chaos target
az chaos-target create \
  --resource-group my-rg \
  --resource-id /subscriptions/.../resourceGroups/my-rg/providers/Microsoft.Compute/virtualMachines/api-server \
  --chaos-target-name vm-target

# Запуск эксперимента
az chaos-experiment start \
  --resource-group my-rg \
  --experiment-name vm-termination-test
```

**Manual termination (any cloud):**

```bash
# Находим VM
VM_ID=$(openstack server list -f value -c ID -c Name | grep api-server | awk '{print $1}')

# Терминируем VM
openstack server delete $VM_ID

# Или через virsh (KVM)
virsh destroy production-vm

# Проверяем resilience
# Приложение должно переключиться на другой инстанс
curl -s http://load-balancer/api/health
# → 200 OK (другой VM отвечает)
```

### Сценарий 3: Bare-metal chaos

**Цель:** Проверить resilience на физических серверах.

**Инструмент:** PowerfulSeal, ipmitool, tc, iptables.

**Сценарий 3.1: Disk I/O error**

```bash
# Имитируем ошибку диска через scsi_debug
modprobe scsi_debug add_host=1 sector_size=512 dev_size_mb=1000 error="abort:10"

# Или через dd с throttling
dd if=/dev/zero of=/mnt/data/testfile bs=1M count=1000 oflag=direct &
# В другом терминале: ограничиваем I/O
echo "0 10485760" | sudo tee /sys/block/sda/block/../queue/iops
```

**Сценарий 3.2: Network partition (bare-metal)**

```bash
# Разделяем сеть между двумя серверами
sudo iptables -A FORWARD -s 192.168.1.10 -d 192.168.1.20 -j DROP
sudo iptables -A FORWARD -s 192.168.1.20 -d 192.168.1.10 -j DROP

# Или через tc
sudo tc qdisc add dev eth0 root netem delay 500ms 100ms
sudo tc qdisc add dev eth1 root netem loss 20%

# Проверяем connectivity
ping -c 3 192.168.1.20
# → 20% packet loss

# Очистка
sudo iptables -F
sudo tc qdisc del dev eth0 root
```

**Сценарий 3.3: Power off (ipmitool)**

```bash
# Отключаем питание сервера (требует IPMI)
ipmitool -I lanplus -H ipmi-host -U admin -P password power off

# Или черезilo/DRAC
ipmitool -I lanplus -H ilo-host -U admin -P password power cycle

# Проверяем failover
# Приложение должно переключиться на standby
```

### Сценарий 4: Hypervisor chaos

**Цель:** Проверить resilience VM при сбоях на уровне гипервизора.

**QEMU/KVM:**

```bash
# Пауза VM
virsh suspend production-vm

# Возобновление
virsh resume production-vm

# Ограничение CPU
virsh schedinfo production-vm --set cpu_shares=256

# Ограничение памяти (balloon)
virsh setmem production-vm 1G --live

# Проверяем, что приложение деградирует gracefully
```

**VMware PowerCLI:**

```powershell
# Пауза VM
Suspend-VM -Name "production-vm" -Confirm:$false

# Ограничение CPU
Set-VM -Name "production-vm" -NumCpu 1 -Confirm:$false

# Ограничение памяти
Set-VM -Name "production-vm" -MemoryGB 2 -Confirm:$false
```

### Сценарий 5: Docker Swarm chaos

**Цель:** Проверить resilience Docker Swarm service при отказе задачи.

**Инструмент:** Pumba + docker service.

```bash
# Убиваем задачу сервиса
SERVICE_NAME=api-service
TASK_ID=$(docker service ps $SERVICE_NAME -f "desired-state=running" -q | head -1)
docker stop $TASK_ID

# Или через Pumba
pumba kill --signal SIGKILL $(docker ps -qf "name=${SERVICE_NAME}")

# Swarm автоматически перезапускает задачу
docker service ps $SERVICE_NAME
# → Новый task запущен

# Проверяем доступность
curl -s http://localhost:8080/health
# → 200 OK
```

### Сценарий 6: Nomad chaos

**Цель:** Проверить resilience Nomad allocations.

**Инструмент:** Nomad CLI + PowerfulSeal.

```bash
# Останавливаем аллокацию
ALLOC_ID=$(nomad job allocations api-service -json | jq -r '.[0].ID')
nomad alloc stop $ALLOC_ID

# Drain узла
nomad node drain -enable <node-id>

# Проверяем, что аллокации переехали
nomad job status api-service
# → Все аллокации на других узлах
```

## Операции и команды

### Pumba

```bash
# Пауза контейнера
pumba pause --duration 30s <container_id>

# Удаление контейнера
pumba kill --signal SIGKILL <container_id>

# Сетевая задержка
pumba netem --duration 60s --delay 500ms <container_id>

# Потеря пакетов
pumba netem --duration 60s --loss 10% <container_id>

# Остановка всех контейнеров образа
pumba stop --duration 60s <image_name>

# Просмотр списка
pumba ls
```

### Toxiproxy

```bash
# Создание прокси
curl -X POST http://localhost:8474/proxies -d '{
  "name":"app",
  "listen":"0.0.0.0:8080",
  "upstream":"app:8080",
  "enabled":true
}'

# Добавление задержки
curl -X POST http://localhost:8474/proxies/app/toxics -d '{
  "name":"latency",
  "type":"latency",
  "attributes":{"latency":5000}
}'

# Потеря пакетов
curl -X POST http://localhost:8474/proxies/app/toxics -d '{
  "name":"loss",
  "type":"loss",
  "attributes":{"percentage":10}
}'

# Удаление toxic
curl -X DELETE http://localhost:8474/proxies/app/toxics/latency

# Список прокси
curl http://localhost:8474/proxies
```

### tc (traffic control)

```bash
# Добавление задержки
sudo tc qdisc add dev eth0 root netem delay 200ms 50ms

# Потеря пакетов
sudo tc qdisc add dev eth0 root netem loss 10% 25%

# Дублирование пакетов
sudo tc qdisc add dev eth0 root netem duplicate 1%

# Очистка
sudo tc qdisc del dev eth0 root

# Просмотр правил
sudo tc qdisc show dev eth0
```

### iptables

```bash
# Блокировка трафика
sudo iptables -A INPUT -s 192.168.1.10 -j DROP
sudo iptables -A OUTPUT -d 192.168.1.10 -j DROP

# Очистка
sudo iptables -F

# Просмотр
sudo iptables -L -v -n
```

### ipmitool

```bash
# Статус питания
ipmitool -I lanplus -H ipmi-host -U admin -P password power status

# Выключение
ipmitool -I lanplus -H ipmi-host -U admin -P password power off

# Включение
ipmitool -I lanplus -H ipmi-host -U admin -P password power on

# Перезагрузка
ipmitool -I lanplus -H ipmi-host -U admin -P password power cycle
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **Pumba не находит контейнер** | Неверный ID или имя | Используйте `pumba ls` для списка контейнеров |
| **tc не применяет задержку** | Нет прав CAP_NET_ADMIN | Запустите с `sudo` или добавьте capabilities |
| **iptables правила не работают** | Правила перезаписаны или conflict | Проверьте `iptables-save`, используйте `-I` вместо `-A` |
| **VM не перезапускается** | Нет прав IPMI или гипервизор недоступен | Проверьте connectivity, credentials IPMI |
| **Docker Swarm не перезапускает задачу** | Нет доступных узлов или constraints | Проверьте `docker node ls`, `docker service ps` |
| **Toxiproxy не создает прокси** | Порт занят или upstream недоступен | Проверьте `curl http://localhost:8474/proxies`, убедитесь, что upstream работает |
| **Network partition не работает** | Маршрутизация bypass iptables | Используйте `tc` вместо `iptables` для network partition |
| **Bare-metal chaos требует reboot** | Сбой на уровне ядра или железа | Восстановите из backup, используйте IPMI remote console |

## Лучшие практики

### Безопасность

1. **Тестируйте в staging** — первый эксперимент только в тестовой среде.
2. **Ограничивайте duration** — максимум 5-10 минут для большинства сценариев.
3. **Имейте emergency stop** — manual kill, IPMI power on.
4. **Уведомляйте команду** — все должны знать о bare-metal/VM chaos.
5. **Не тестируйте во время production нагрузки** — выбирайте окно обслуживания.

### Инструменты

6. **Используйте Pumba для Docker** — простой CLI, покрывает большинство сценариев.
7. **Используйте Toxiproxy для TCP** — точная инъекция на уровне соединения.
8. **Используйте tc/iptables для network** — гибкая конфигурация задержек и потерь.
9. **Используйте ipmitool для bare-metal** — удаленное управление питанием.
10. **Используйте cloud-native tools** — AWS FIS, Azure Chaos Studio, GCP Chaos Engineering.

### Мониторинг

11. **Настройте алерты на все сценарии** — VM down, container killed, network partition.
12. **Используйте distributed tracing** — Jaeger для корреляции запросов.
13. **Фиксируйте timeline** — время отключения, время failover, время восстановления.
14. **Ведите audit trail** — все эксперименты документируются.

### Автоматизация

15. **Интегрируйте в CI/CD** — chaos tests в pipeline для Docker и VM.
16. **Используйте Infrastructure as Code** — Terraform/CloudFormation для воссоздания среды.
17. **Автоматизируйте cleanup** — восстановление VM, удаление iptables правил.
18. **Планируйте по расписанию** — еженедельные/ежеквартальные Game Days.

## Дополнительная информация

### Связанные технологии

- **Pumba** — chaos для Docker-контейнеров.
- **Toxiproxy** — TCP proxy для инъекции аномалий.
- **PowerfulSeal** — autonomous chaos для K8s и VM.
- **AWS Fault Injection Simulator** — managed chaos для AWS.
- **Azure Chaos Studio** — managed chaos для Azure.
- **GCP Chaos Engineering** — managed chaos для GCP.

### См. также

- [Chaos Engineering — инструменты](chaos_engineering_tools.md) — Pumba, Toxiproxy, PowerfulSeal.
- [Chaos Engineering — практическое руководство](chaos_engineering_practical.md) — Game Days для VM/bare-metal.
- [Nomad — Chaos Engineering](../../Nomad/nomad_chaos_engineering.md) — хаос для Nomad.
