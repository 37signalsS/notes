# Конфигурация сети в Vagrant

## Определения

**Сетевые интерфейсы Vagrant** — механизмы подключения ВМ к сетям различных типов для обеспечения доступа к сервисам и взаимодействия между машинами.

## Базовые концепции

### Типы сетей

| Тип | Альтернативное название | Доступность |
| --- | --- | --- |
| **Forwarded Port** | Проброс портов | С хоста через `localhost:<port>` |
| **Private Network** | Host-only | Только хост и ВМ одного окружения |
| **Public Network** | Bridged | Все устройства локальной сети |

### 1. Проброс портов (Forwarded Port)

Пробрасывает порт с хост-машины на порт гостевой ВМ. Сервис в ВМ доступен через `localhost` на хосте.

### 2. Приватная сеть (Private Network)

Создаёт изолированный сетевой интерфейс между хостом и ВМ. Другие устройства физической сети не видят ВМ.

**Варианты:**

- **Статический IP:** `config.vm.network "private_network", ip: "192.168.50.4"`
- **DHCP:** `config.vm.network "private_network", type: "dhcp"`

### 3. Публичная сеть (Public Network)

Подключает ВМ напрямую к физической локальной сети через мост (bridge). ВМ получает собственный IP от DHCP-сервера.

## Практические сценарии

### Сценарий 1: Доступ к веб-серверу через проброс портов

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  
  # Проброс порта 8080 хоста → порт 80 ВМ
  config.vm.network "forwarded_port", guest: 80, host: 8080
  
  # Проброс нескольких портов
  config.vm.network "forwarded_port", guest: 443, host: 8443
  config.vm.network "forwarded_port", guest: 3306, host: 3306
end
```

**Доступ:** `http://localhost:8080`

### Сценарий 2: Изолированная сеть для кластера

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  
  # Статический IP для первой машины
  config.vm.network "private_network", ip: "192.168.50.4"
end
```

**Для нескольких ВМ:**

```ruby
(1..3).each do |i|
  config.vm.define "node#{i}" do |node|
    node.vm.network "private_network", ip: "192.168.50.#{10 + i}"
  end
end
```

**Результат:**

- `node1` → `192.168.50.10`
- `node2` → `192.168.50.11`
- `node3` → `192.168.50.12`

ВМ могут общаться между собой по этим IP.

### Сценарий 3: Публичная сеть (Bridged)

```ruby
Vagrant.configure("2") do |config|
  # Автоматический выбор интерфейса (DHCP)
  config.vm.network "public_network"
end
```

**С указанием интерфейса:**

```ruby
config.vm.network "public_network", bridge: "enp0s3"
```

**ВМ получит:**

- Собственный IP из диапазона локальной сети
- Доступность для других устройств сети
- Возможность работы как отдельный сервер

### Сценарий 4: Комбинированная конфигурация

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  
  # Проброс портов для доступа к сервисам
  config.vm.network "forwarded_port", guest: 80, host: 8080
  config.vm.network "forwarded_port", guest: 22, host: 2222
  
  # Приватная сеть для внутреннего общения
  config.vm.network "private_network", ip: "192.168.50.10"
  
  # Публичная сеть для внешнего доступа (опционально)
  # config.vm.network "public_network"
end
```

## Дополнительная информация

### Сравнительная таблица

| Тип сети | Доступность | Безопасность | Сценарий |
| --- | --- | --- | --- |
| **Forwarded Port** | `localhost:<port>` на хосте | Высокая | Доступ к отдельным сервисам |
| **Private Network** | Хост + ВМ окружения | Очень высокая | Кластеры, тестовые стенды |
| **Public Network** | Вся локальная сеть | Средняя | Демонстрация, продакшен-тесты |

### Диагностика сети

```bash
# Проверить IP внутри ВМ
vagrant ssh -c "ip addr show"

# Проверить маршруты
vagrant ssh -c "ip route"

# Тестировать доступность
ping 192.168.50.10

# Проверить проброшенные порты
netstat -tlnp | grep :8080
```

### Проблемы и решения

| Проблема | Решение |
| --- | --- |
| Порт занят на хосте | Изменить `host` в `forwarded_port` |
| Неправильный bridge | Указать `bridge: "interface_name"` |
| Нет доступа к private network | Проверить firewall на хосте |

### См. также

- [Vagrantfile Reference](./vagrantfile.md) — конфигурация сети в Vagrantfile
- [Vagrant Advanced Usage](./vagrant_advanced_usage.md) — мульти-машинные сети
- [Linux Networking](../Linux/Networking/Tools/tc_netem.md) — основы сетевого взаимодействия
