# Настройка сервисов для работы с IPv6

## Обзор

Большинство демонов требуют явной настройки для поддержки IPv6.

## chrony (NTP)

### Настройка сервера

```bash
# В /etc/chrony.conf
# Разрешить доступ по IPv6
allow fc00::/64

# Прослушивать все интерфейсы
bindaddress ::
```

### Перезапуск и проверка

```bash
# Перезапуск сервиса
systemctl restart chronyd

# Проверка прослушивания
ss -6 -unap | grep chronyd
```

## nginx

### Конфигурация server

```nginx
# Прослушивать IPv4 и IPv6
listen 80;
listen [::]:80;

# Или только IPv6
listen [::]:80;

# С SSL
listen [::]:443 ssl http2;
```

### Пример полной конфигурации

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name example.com;
    
    location / {
        root /var/www/html;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name example.com;
    
    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;
    
    location / {
        root /var/www/html;
    }
}
```

### Проверка

```bash
# Проверка конфигурации
nginx -t

# Перезапуск
systemctl restart nginx

# Проверка прослушивания
ss -6 -tlnp | grep nginx
```

## SSH (sshd)

### Конфигурация

```bash
# В /etc/ssh/sshd_config

# Прослушивать все интерфейсы (IPv4 + IPv6)
ListenAddress ::
ListenAddress 0.0.0.0

# Или только IPv6
# ListenAddress ::

# Или только IPv4
# ListenAddress 0.0.0.0
```

### Перезапуск и проверка

```bash
# Проверка конфигурации
sshd -t

# Перезапуск
systemctl restart sshd

# Проверка прослушивания
ss -6 -tlnp | grep sshd
```

## Apache HTTP Server

### Конфигурация

```apache
# В /etc/apache2/ports.conf или httpd.conf

# Прослушивать все интерфейсы
Listen 80
Listen [::]:80

# С SSL
Listen 443
Listen [::]:443
```

### Виртуальные хосты

```apache
<VirtualHost *:80>
    ServerName example.com
    DocumentRoot /var/www/html
</VirtualHost>

<VirtualHost [::]:80>
    ServerName example.com
    DocumentRoot /var/www/html
</VirtualHost>
```

## PostgreSQL

### Конфигурация

```bash
# В /etc/postgresql/*/main/postgresql.conf
listen_addresses = '*'  # Все интерфейсы

# В /etc/postgresql/*/main/pg_hba.conf
# Разрешить IPv6 подключения
host    all             all             ::0/0                 md5
host    all             all             fc00::/7              md5
```

### Перезапуск и проверка

```bash
# Перезапуск
systemctl restart postgresql

# Проверка прослушивания
ss -6 -tlnp | grep postgres
```

## MySQL/MariaDB

### Конфигурация

```bash
# В /etc/mysql/my.cnf или /etc/my.cnf
[mysqld]
bind-address = ::  # Все интерфейсы
# bind-address = 0.0.0.0  # Только IPv4
```

### Перезапуск и проверка

```bash
# Перезапуск
systemctl restart mysql

# Проверка прослушивания
ss -6 -tlnp | grep mysql
```

## Redis

### Конфигурация

```bash
# В /etc/redis/redis.conf
bind ::1  # Только IPv6 loopback
# bind 0.0.0.0 ::  # Все интерфейсы
```

### Перезапуск и проверка

```bash
# Перезапуск
systemctl restart redis

# Проверка прослушивания
ss -6 -tlnp | grep redis
```

## Docker

### Настройка daemon.json

```json
{
  "ipv6": true,
  "fixed-cidr-v6": "fd00::/80"
}
```

### Проверка

```bash
# Перезапуск
systemctl restart docker

# Проверка сети
docker network inspect bridge | grep -A10 "IPv6"
```

## Проверка прослушивания сервисов

```bash
# Все IPv6 сокеты
ss -6 -tlnp

# Только TCP
ss -6 -tln

# Только UDP
ss -6 -uln

# С процессами
ss -6 -tlnp | grep <сервис>
```

## Связанные темы

* **[Настройка адресов](./address_configuration.md)** — конфигурация IPv6
* **[Firewall](./firewall.md)** — настройка файрвола
* **[Диагностика](./diagnostics.md)** — решение проблем
