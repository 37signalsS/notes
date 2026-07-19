# Устранение проблем сетевой связности Docker (Troubleshooting)

## Определения

**Проблемы сетевой связности** — сбои, при которых контейнеры не могут взаимодействовать с хостом, другими контейнерами или внешними сетями. Причины чаще всего лежат на уровне хостовой ОС (файрвол, маршрутизация, MTU), а не во внутреннем коде Docker.

## Основные концепции

### Ключевые компоненты системы

| Компонент | Назначение | Типичная проблема |
| :--- | :--- | :--- |
| **`iptables` / `nftables`** | Фильтрация и NAT трафика | Правила `DOCKER` перекрываются `ufw` или `firewalld` |
| **`net.ipv4.ip_forward`** | Маршрутизация пакетов | Значение `0` (отключено) блокирует выход в интернет |
| **`MTU` (Maximum Transmission Unit)** | Макс. размер пакета | Пакеты отбрасываются в VPN или облачных сетях |
| **`NetworkManager`** | Управление интерфейсами | Интерфейс `docker0` помечается как `unmanaged` или сбрасывается |
| **Docker Embedded DNS** | Резолвер на `127.0.0.11` | Не может проксировать запросы к DNS-серверам хоста |

---

## Быстрая диагностика по симптомам

| Симптом | Вероятная причина | Команда для проверки |
| :--- | :--- | :--- |
| **Нет доступа в интернет** | `ip_forward=0` | `sysctl net.ipv4.ip_forward` # → 0 |
| **Пинг по IP работает, по домену — нет** | DNS резолвер | `ping 1.1.1.1` (OK) vs `ping google.com` (Fail) |
| **Доступ с хоста есть, извне — нет** | Firewall (`FORWARD DROP`) | `iptables -L FORWARD -n -v` |
| **Связь пропадает при большой нагрузке** | Лимит `conntrack` | `dmesg | grep conntrack` # → table full |
| **Медленная работа или "зависание" TCP** | Несоответствие `MTU` | `ping -s 1472 -M do 8.8.8.8` |

---

## Практические сценарии

### Сценарий 1: Отключена маршрутизация пакетов (IP Forwarding)

**Симптомы:** Контейнеры пингуют шлюз `docker0` (обычно `172.17.0.1`), но не могут выйти за пределы хоста.

**Диагностика:**
```bash
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 0
```

**Решение:**
```bash
# Включить временно
sudo sysctl -w net.ipv4.ip_forward=1

# Включить постоянно
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
# → net.ipv4.ip_forward = 1
```

### Сценарий 2: Конфликт MTU в VPN или Облаке

**Симптомы:** Небольшие пакеты (ping) проходят, но HTTP-запросы или SSH-сессии "зависают". Часто встречается при использовании Docker внутри туннелей (WireGuard, OpenVPN).

**Диагностика:**
```bash
# Пинг с запретом фрагментации (стандартный MTU 1500)
docker exec my_container ping -s 1472 -M do google.com
# → ping: local error: message too long, mtu=1450
```

**Решение:** Установите корректный MTU в `daemon.json` или для конкретной сети.
```json
# /etc/docker/daemon.json
{
  "mtu": 1450
}
```
```bash
sudo systemctl restart docker
```

### Сценарий 3: Перехват интерфейса NetworkManager

**Симптомы:** После перезагрузки хоста мост `docker0` пропадает или получает некорректный IP.

**Решение:** Исключите интерфейсы Docker из-под управления NetworkManager.
```ini
# /etc/NetworkManager/conf.d/docker.conf
[keyfile]
unmanaged-devices=interface-name:docker0;interface-name:br-*;interface-name:veth*
```
```bash
sudo systemctl reload NetworkManager
```

### Сценарий 4: Проблемы с резолвом имен (DNS)

**Симптомы:** Ошибки `Temporary failure in name resolution` внутри контейнера.

**Диагностика:**
```bash
# Проверка DNS-серверов в контейнере
docker exec my_container cat /etc/resolv.conf
# → nameserver 127.0.0.11

# Тест внешнего резолва
docker exec my_container nslookup google.com
# → ;; connection timed out; no servers could be reached
```

**Решение:** Принудительно укажите DNS-серверы, если резолвер хоста (например, `systemd-resolved`) недоступен для Docker.
```json
# /etc/docker/daemon.json
{
  "dns": ["8.8.8.8", "1.1.1.1"]
}
```
Подробно: **[Решение проблем с DNS](./dns_resolution_issues.md)**.

### Сценарий 5: Блокировка в цепочке FORWARD (iptables)

**Симптомы:** Порт проброшен (`-p 80:80`), но из внешней сети сервис недоступен.

**Диагностика:**
```bash
sudo iptables -L FORWARD -n -v
# → Chain FORWARD (policy DROP 150 packets, 9000 bytes)
```

**Решение:** Добавьте разрешающее правило в цепочку `DOCKER-USER`.
```bash
sudo iptables -I DOCKER-USER -i eth0 -o docker0 -j ACCEPT
```
Подробно: **[Интеграция с iptables](./iptables_integration.md)**.

### Сценарий 6: Конфликты IPv6

**Симптомы:** Задержки при старте соединений (до 5-10 секунд), так как приложение пытается сначала использовать IPv6, который не настроен в Docker.

**Решение:** Если IPv6 не используется, отключите его в контейнере или настройте корректно.
```json
# /etc/docker/daemon.json (для включения)
{
  "ipv6": true,
  "fixed-cidr-v6": "2001:db8:1::/64"
}
```

---

## Инструменты диагностики (Toolbox)

Для глубокого анализа сетевого трафика используйте эфемерные контейнеры:

```bash
# Использование netshoot (содержит tcpdump, tshark, nmap, mtr)
docker run --rm -it --net container:<target_container_id> nicolaka/netshoot

# Просмотр сетевых соединений внутри неймспейса
docker exec -it my_container ss -tunlp
```

### Мониторинг событий сети
```bash
# Отслеживание сетевых событий Docker в реальном времени
docker events --filter 'type=network'
```

---

## Дополнительная информация

### Чеклист быстрой проверки
1. `sysctl net.ipv4.ip_forward` должен быть `1`.
2. `iptables -L FORWARD` не должен дропать пакеты Docker.
3. Мост `docker0` должен иметь IP (обычно `172.17.0.1`).
4. В `/etc/resolv.conf` контейнера должен быть `127.0.0.11`.

### Связанные темы
- **[Интеграция с iptables](./iptables_integration.md)** — настройка файрвола.
- **[Решение проблем с DNS](./dns_resolution_issues.md)** — глубокая диагностика резолва.
- **[Обзор сетевых моделей Docker](../Docker_network/docker_network.md)** — архитектура сетей.
- **[Kernel Sysctl](../../Linux/Core/kernel/sysctl.md)** — параметры ядра.
