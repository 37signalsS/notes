# Docker Network Connectivity Troubleshooting

## Определения

**Проблемы сетевой связности** — сбои, при которых контейнеры не могут взаимодействовать с хостом, другими контейнерами или внешними сетями. Причины чаще всего на уровне хостовой ОС (файрвол, маршрутизация), а не в Docker.

## Основные концепции

### Ключевые компоненты хоста

| Компонент | Назначение | Типичная проблема |
| :--- | :--- | :--- |
| **`iptables` / `nftables`** | Фильтрация и NAT трафика | Конфликт правил с `firewalld`/`ufw` |
| **`NetworkManager`** | Управление интерфейсами | Управление `docker0`, сброс маршрутов |
| **`net.ipv4.ip_forward`** | Пересылка пакетов между интерфейсами | Отключена маршрутизация наружу |
| **DNS-резолвер** | Разрешение имён | Рассинхронизация с хостом |

### Быстрая диагностика по симптомам

| Симптом | Вероятная причина | Проверка |
| :--- | :--- | :--- |
| **Нет доступа в интернет** | `ip_forward=0` | `sysctl net.ipv4.ip_forward` |
| **Доступен IP, но не домен** | DNS | `ping 8.8.8.8` vs `ping google.com` |
| **Доступ с хоста, но не извне** | Файрвол (`FORWARD DROP`) | `iptables -L FORWARD -n` |
| **Пропадает связь после перезагрузки** | `NetworkManager` | `nmcli dev show \| grep docker` |
| **Контейнеры не видят друг друга** | Docker DNS | `docker exec nslookup <container>` |

## Практические сценарии

### Сценарий 1: Конфликт файрвола (`iptables` / `nftables`)

**Симптомы:**
- Контейнер доступен по `localhost`, но не из сети
- Правила Docker перезаписываются после перезагрузки

**Диагностика:**

```bash
# Проверка бэкенда Docker
docker info | grep -i iptables

# Проверка правил FORWARD
iptables -L FORWARD -v -n | grep docker
```

**Решение:** Подробно в **[Интеграция с iptables](../Docker_network/troubleshooting/iptables_integration.md)**:
- Используйте цепочку `DOCKER-USER` для пользовательских правил
- При конфликте с `firewalld` переключите Docker на `iptables-legacy`

### Сценарий 2: NetworkManager управляет `docker0`

**Симптомы:**
- Сеть работает до перезагрузки хоста
- После перезагрузки контейнеры изолированы

**Диагностика:**

```bash
# Проверка управления docker0
nmcli dev show | grep docker0

# Если вывод есть — интерфейс под управлением NetworkManager
```

**Решение:**

```ini
# /etc/NetworkManager/conf.d/docker.conf
[keyfile]
unmanaged-devices=interface-name:docker0
```

```bash
# Перезапуск NetworkManager
sudo systemctl restart NetworkManager

# Проверка
nmcli dev status | grep docker0
```

### Сценарий 3: Отключена пересылка пакетов

**Симптомы:**
- Контейнеры пингуют хост, но не интернет
- `ping 8.8.8.8` не работает из контейнера

**Диагностика:**

```bash
sysctl net.ipv4.ip_forward
# 0 — отключено, 1 — включено
```

**Решение:**

```bash
# Включить немедленно
sudo sysctl -w net.ipv4.ip_forward=1

# Сохранить после перезагрузки
echo 'net.ipv4.ip_forward=1' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

Подробно о `sysctl` в **[Kernel Sysctl](../../Linux/Core/kernel/sysctl.md)**.

### Сценарий 4: Проблемы с DNS

**Симптомы:**
- `ping 8.8.8.8` работает, `ping google.com` — нет
- Ошибки `SERVFAIL` или таймауты

**Диагностика:**

```bash
# Проверка resolv.conf в контейнере
docker exec <container> cat /etc/resolv.conf
# nameserver 127.0.0.11 — встроенный DNS Docker

# Проверка разрешения
docker exec <container> dig ya.ru
```

**Решение:** Подробно в **[DNS Troubleshooting](../Docker_network/troubleshooting/dns_resolution_issues.md)**:

```json
# /etc/docker/daemon.json
{
  "dns": ["1.1.1.1", "8.8.8.8"]
}
```

```bash
sudo systemctl restart docker
```

### Сценарий 5: Изоляция между контейнерами

**Симптомы:**
- Контейнеры в одной сети не пингуют друг друга
- DNS-разрешение имён не работает

**Диагностика:**

```bash
# Проверка сети контейнера
docker network inspect bridge

# Проверка DNS
docker exec container1 ping container2
```

**Решение:**

```bash
# Убедитесь, что контейнеры в одной сети
docker network connect bridge container2

# Перезапуск контейнера
docker restart container1
```

### Сценарий 6: Проброс портов не работает

**Симптомы:**
- `docker run -p 8080:80` — порт недоступен извне
- С хоста доступен, из сети — нет

**Диагностика:**

```bash
# Проверка правил NAT
iptables -t nat -L PREROUTING -n -v | grep 8080

# Проверка FORWARD
iptables -L FORWARD -n | grep docker
```

**Решение:**

```bash
# Разрешить FORWARD для Docker
sudo iptables -I DOCKER-USER -i eth0 -o docker0 -j ACCEPT
sudo iptables-save | sudo tee /etc/iptables/rules.v4
```

## Дополнительная информация

### Чеклист быстрой диагностики

```bash
# 1. Проверка пересылки пакетов
sysctl net.ipv4.ip_forward

# 2. Проверка файрвола
iptables -L FORWARD -n | head -10

# 3. Проверка NetworkManager
nmcli dev status | grep docker

# 4. Проверка DNS
docker run --rm alpine ping -c 1 google.com

# 5. Проверка маршрутов
ip route show | grep docker
```

### Связанные темы

- **[iptables Integration](../Docker_network/troubleshooting/iptables_integration.md)** — настройка файрвола
- **[DNS Troubleshooting](../Docker_network/troubleshooting/dns_resolution_issues.md)** — разрешение имён
- **[Docker Network Overview](../Docker_network/docker_network.md)** — обзор сетей
- **[sysctl](../../Linux/Core/kernel/sysctl.md)** — параметры ядра

### Примечания

- При изменении `/etc/docker/daemon.json` требуется перезапуск Docker
- Правила `iptables` не сохраняются после перезагрузки — используйте `iptables-save`
- Для production настройте мониторинг сетевых метрик Docker
