# Docker Swarm: Networking

## Определения

**Overlay Network** — виртуальная сеть (Layer 2), созданная поверх физической инфраструктуры (Layer 3) с использованием технологии инкапсуляции **[VXLAN](../Networking/Tunnels/vxlan.md)**. Позволяет контейнерам на разных узлах кластера общаться, как если бы они находились в одной локальной сети.

**Ingress Network** — специальная системная `overlay`-сеть для управления входящим трафиком сервисов Swarm. Основа механизма **[Routing Mesh](./swarm_core_concepts.md)**.

**docker_gwbridge** — сеть типа `bridge` на каждом узле Swarm, соединяющая `overlay`-сети с физической сетью хоста для доступа во внешние сети.

## Базовые концепции

### Архитектура overlay-сетей

Overlay-сети используют **[VXLAN](../Networking/Tunnels/vxlan.md)** для инкапсуляции Ethernet-кадров в UDP-пакеты (порт 4789). Процесс прозрачен для контейнеров:

```
[Container A @ Host-1] → [VXLAN encapsulation] → [UDP 4789] → [VXLAN decapsulation] → [Container B @ Host-2]
```

**Требования к сети:**
- **TCP 2377** — коммуникация между узлами кластера
- **TCP/UDP 7946** — обнаружение узлов
- **UDP 4789** — трафик VXLAN (data plane)

### Сетевые компоненты Swarm

| Компонент | Тип | Назначение |
|---|---|---|
| `ingress` | overlay | Входящий трафик (Routing Mesh) |
| `docker_gwbridge` | bridge | Шлюз для исходящего трафика |
| `bridge` (default) | bridge | Локальная сеть на узле |
| Пользовательские сети | overlay | Изоляция сервисов по доменам |

### Service Discovery

Swarm обеспечивает автоматическое обнаружение сервисов через встроенный DNS. Когда контейнер запрашивает сервис по имени, DNS возвращает IP-адрес одной из реплик. Подробнее в **[Docker: DNS и Service Discovery](../Docker/Docker_network/dns_and_service_discovery.md)**.

### Изоляция трафика

Каждая `overlay`-сеть — изолированный L2-сегмент. Сервисы в разных сетях не могут общаться напрямую без подключения к общей сети или использования шлюза.

## Практические сценарии

### Создание overlay-сети

#### Базовая сеть

```sh
docker network create \
  --driver overlay \
  my-overlay-network
```

#### Сеть с шифрованием

```sh
docker network create \
  --driver overlay \
  --opt encrypted \
  my-secure-network
```

Параметр `--opt encrypted` включает **IPsec-шифрование** (ESP) для всего трафика внутри сети. Подробнее об IPsec — в **[руководстве по IPsec](../Networking/Tunnels/ipsec/ipsec.md)**.

#### Attachable-сеть (для standalone-контейнеров)

```sh
docker network create \
  --driver overlay \
  --attachable \
  my-attachable-network
```

Параметр `--attachable` позволяет подключать автономные контейнеры (`docker run`) к сети:

```sh
docker run --rm -it --network my-attachable-network alpine ping service-name
```

### Подключение сервиса к нескольким сетям

```sh
# Создание сетей
docker network create --driver overlay frontend-net
docker network create --driver overlay backend-net

# Развертывание сервиса
docker service create \
  --name my-app \
  --network frontend-net \
  --network backend-net \
  --replicas 3 \
  my-image
```

Сервис будет иметь интерфейсы в обеих сетях, что позволяет разделить фронтенд- и бэкенд-трафик.

### Диагностика сети

#### Проверка состояния сетей

```sh
# Список сетей
docker network ls

# Детальная информация о сети
docker network inspect my-overlay-network

# Подключенные контейнеры
docker network inspect --format='{{range .Containers}}{{.Name}}{{end}}' my-overlay-network
```

#### Проверка связности

```sh
# DNS-разрешение из контейнера
docker run --rm --network my-overlay-network alpine nslookup service-name

# Проверка связности
docker run --rm --network my-overlay-network alpine ping service-name

# Трассировка пути
docker run --rm --network my-overlay-network alpine traceroute service-name
```

#### Анализ VXLAN-трафика

```sh
# Прослушивание VXLAN-порта на хосте
tcpdump -ni any udp port 4789

# Проверка MTU
ip link show | grep mtu
```

**Важно:** VXLAN добавляет ~50 байт оверхеда. При MTU 1500 эффективный MTU для контейнеров — ~1450.

### Troubleshooting

#### Проблема: Контейнеры не видят друг друга

**Проверка:**
```sh
# Убедиться, что сервисы в одной сети
docker service inspect --format='{{range .Spec.Networks.Attachments}}{{.Network.Name}}{{end}}' service-name

# Проверить DNS
docker exec <container> nslookup <service-name>
```

**Возможные причины:**
- Сервисы в разных overlay-сетях
- Firewall блокирует UDP 4789
- Неправильный MTU

#### Проблема: Медленная связь между узлами

**Проверка:**
```sh
# Тест скорости
docker run --rm --network my-overlay-network nicolaka/netshoot iperf3 -c <target-ip>

# Проверка задержки
docker run --rm --network my-overlay-network alpine ping -c 10 <service-ip>
```

**Решение:**
- Включить шифрование только для чувствительных данных (оверхед CPU)
- Проверить физическую сеть на предмет узких мест
- Настроить MTU для избежания фрагментации

#### Проблема: Routing Mesh не работает

**Симптомы:** Запрос на опубликованный порт не достигает сервиса.

**Проверка:**
```sh
# Проверка ingress-сети
docker network inspect ingress

# Проверка правил iptables
iptables -t nat -L DOCKER-INGRESS -n
```

**Решение:** Для сложной маршрутизации (L7) используйте **[Traefik в качестве Ingress-контроллера](./swarm_ingress_traefik.md)** вместо стандартного Routing Mesh.

## Дополнительная информация

### Сравнение с альтернативами

| Решение | Изоляция | Производительность | Масштабируемость |
|---|---|---|---|
| **overlay** | L2 (сеть) | Средняя (VXLAN оверхед) | до 1000 узлов |
| **host** | Нет | Максимальная | Один хост |
| **macvlan** | L2 (MAC) | Высокая | Зависит от сети |
| **Kubernetes CNI** | L3 (IP) | Зависит от плагина | до 5000 узлов |

Для максимальной производительности на одном хосте рассмотрите **[host-сеть](../Docker/Docker_network/drivers/host.md)**. Для продвинутой диагностики overlay-сетей см. **[драйвер overlay](../Docker/Docker_network/drivers/overlay.md#диагностика)**.

### Безопасность

**Рекомендации:**
- Включайте шифрование (`--opt encrypted`) для чувствительных данных
- Используйте отдельные сети для разных уровней приложения (frontend/backend)
- Ограничивайте доступ к портам VXLAN (UDP 4789) на фаерволе
- Мониторьте сетевой трафик на аномалии

### Основы туннелирования

Общие концепции оверлейных сетей описаны в **[обзоре туннелирования](../Networking/Tunnels/tunneling_overview.md)**.

### Связанные документы

- **Routing Mesh и Service Discovery** — **[swarm_core_concepts.md](./swarm_core_concepts.md)**
- **Ingress с Traefik** — **[swarm_ingress_traefik.md](./swarm_ingress_traefik.md)**
- **Драйвер overlay** — **[../Docker/Docker_network/drivers/overlay.md](../Docker/Docker_network/drivers/overlay.md)**
- **DNS и Service Discovery** — **[../Docker/Docker_network/dns_and_service_discovery.md](../Docker/Docker_network/dns_and_service_discovery.md)**
