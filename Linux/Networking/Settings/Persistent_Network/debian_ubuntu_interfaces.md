# Debian/Ubuntu: настройка сети через /etc/network/interfaces

## Классический способ

В системах, где не используется `NetworkManager` или `netplan`, сеть настраивается через файл `/etc/network/interfaces`.

### Пример статической конфигурации

```ini
# /etc/network/interfaces
auto lo
iface lo inet loopback

# Основной сетевой интерфейс
auto eth0
iface eth0 inet static
    address 10.10.10.10/24    # IP-адрес и маска
    gateway 10.10.10.1        # Шлюз по умолчанию
    dns-nameservers 8.8.8.8 1.1.1.1
```

### Пример DHCP-конфигурации

```ini
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
```

### Директивы

| Директива | Описание |
| :--- | :--- |
| `iface` | Описание интерфейса, `inet` означает IPv4 |
| `auto` | Автоматическое включение интерфейса при загрузке |
| `loopback` | Виртуальный интерфейс 127.0.0.1 |

---

## Hook-скрипты (pre-up/post-up и т.д.)

Возможно выполнение команд или скриптов до/после включения-выключения интерфейса:

```ini
iface eth0 inet static
    address 10.10.10.10/24
    gateway 10.10.10.1

    pre-up /usr/local/bin/before-up.sh
    post-up /usr/local/bin/after-up.sh
    pre-down /usr/local/bin/before-down.sh
    post-down /usr/local/bin/after-down.sh
```

### Порядок выполнения

| Хук | Описание |
| :--- | :--- |
| `pre-up` | Перед включением интерфейса |
| `post-up` | После включения интерфейса |
| `pre-down` | Перед выключением интерфейса |
| `post-down` | После выключения интерфейса |

---

## Применение изменений

```bash
# Перезапуск службы networking
sudo systemctl restart networking

# Или переконфигурирование конкретного интерфейса
sudo ifdown eth0 && sudo ifup eth0
```
