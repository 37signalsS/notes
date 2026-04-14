# DNS и Service Discovery в Docker

## Определения

- **Встроенный DNS-сервер**: DNS-сервер Docker по адресу `127.0.0.11` в пользовательских `bridge`-сетях. Разрешает имена контейнеров в их внутренние IP-адреса.
- **Service Discovery**: Механизм автоматического обнаружения контейнеров по именам без необходимости знать их IP-адреса.
- **Network Alias**: Дополнительное DNS-имя контейнера, задаваемое флагом `--network-alias`. Позволяет обращаться к контейнеру по нескольким именам.
- **DNS Round-Robin**: Механизм балансировки, при котором DNS возвращает все IP-адреса контейнеров с одинаковым alias в порядке ротации.
- **Veth-интерфейс**: Виртуальный сетевой интерфейс (патч-корд), соединяющий network namespace контейнера с мостом на хосте.

**Важно:** Встроенный DNS-сервер **не работает в сети `bridge` по умолчанию**. Требуется создание пользовательской сети.

## Основные концепции

### Принцип работы DNS в Docker

При подключении контейнера к пользовательской `bridge`-сети:

1. **Настройка DNS**: Docker прописывает `127.0.0.11` в `/etc/resolv.conf` контейнера.
2. **DNS-запрос**: При обращении к контейнеру по имени (например, `db`) запрос отправляется на `127.0.0.11`.
3. **Разрешение имени**: Встроенный DNS находит IP целевого контейнера в данной сети.
4. **Соединение**: Контейнер устанавливает прямое соединение через [сетевой мост](./drivers/bridge.md).

### Network Alias и балансировка

Несколько контейнеров могут иметь одинаковый alias для балансировки нагрузки:

```bash
# Запуск контейнеров с общим alias
docker run -d --name web1 --network-alias web --network my-app-net nginx
docker run -d --name web2 --network-alias web --network my-app-net nginx
```

**DNS Round-Robin:**

- При запросе `web` DNS возвращает оба IP в порядке ротации
- Клиент использует первый адрес из списка
- Простейшая балансировка без внешних инструментов

**Динамическое обновление (для nginx):**

```nginx
resolver 127.0.0.11 valid=10s;
server {
    location / {
        proxy_pass http://web:80;
    }
}
```

Опция `valid=10s` заставляет nginx обновлять DNS-кэш каждые 10 секунд.

### Настройка DNS

Переопределение DNS для контейнеров:

| Опция | Назначение | Пример |
| :--- | :--- | :--- |
| `--dns <IP>` | Кастомный DNS-сервер | `--dns 8.8.8.8` |
| `--dns-search <домен>` | Домен поиска для коротких имен | `--dns-search corp.local` |
| `--dns-opt <опция>` | Опции resolv.conf | `--dns-opt ndots:5` |

```bash
# Контейнер с кастомным DNS
docker run --dns 8.8.8.8 --dns-search corp.local --network my-app-net alpine nslookup google.com
```

Встроенный DNS обрабатывает внутренние имена, внешние запросы пересылает на указанный `--dns` сервер.

## Практические сценарии

### Базовое взаимодействие контейнеров

1. **Создание пользовательской сети:**

   ```bash
   docker network create my-app-net
   ```

2. **Запуск сервера:**

   ```bash
   docker run -d --name server --network my-app-net nginx
   ```

3. **Проверка разрешения имени:**

   ```bash
   docker run --rm --network my-app-net alpine ping -c 4 server
   # PING server (172.20.0.2): 56 data bytes
   # 64 bytes from 172.20.0.2: seq=0 ttl=64 time=0.082 ms
   ```

### Диагностика DNS

**Проверка `/etc/resolv.conf`:**

```bash
docker exec my-container cat /etc/resolv.conf
# nameserver 127.0.0.11
```

**Проверка разрешения имени:**

```bash
docker run --rm --network my-app-net alpine nslookup server
# Name:      server
# Address 1: 172.20.0.2
```

**Тестирование connectivity:**

```bash
docker run --rm --network my-app-net alpine wget -qO- http://server
```

### Сравнение: пользовательская сеть vs bridge по умолчанию

**Bridge по умолчанию (DNS не работает):**

```bash
docker run -d --name nginx1 nginx:alpine
docker run --rm alpine ping -c 2 nginx1
# ping: bad address 'nginx1'
```

**Пользовательская сеть (DNS работает):**

```bash
docker network create test-net
docker run -d --name nginx2 --network test-net nginx:alpine
docker run --rm --network test-net alpine ping -c 2 nginx2
# PING nginx2 (172.19.0.2): 56 data bytes
# 64 bytes from 172.19.0.2: seq=0 ttl=64 time=0.082 ms
```

См. подробное сравнение в [Обзоре сетевых моделей Docker](./docker_network.md).

## Дополнительная информация

**Ограничения:**

- DNS не работает в `bridge` по умолчанию — только в пользовательских сетях
- Для внешних запросов требуется корректная настройка DNS на хосте
- При изменении DNS на хосте может потребоваться перезапуск контейнеров

См. также: [Обзор сетевых моделей Docker](./docker_network.md), [Управление сетями (CLI)](./cli.md), [Решение проблем: DNS](./troubleshooting/dns_resolution_issues.md).
