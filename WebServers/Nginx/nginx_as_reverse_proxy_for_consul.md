# Настройка Nginx в качестве обратного прокси для Consul с SSL

Для обеспечения безопасного доступа к UI Consul и сокрытия его узлов из публичного доступа, можно использовать Nginx в качестве обратного прокси-сервера (reverse proxy) с SSL-терминацией.

## 1. Подготовка

Перед настройкой Nginx убедитесь, что:
1.  Есть сетевая связность между сервером Nginx и всеми узлами кластера Consul по их внутренним (серым) IP-адресам.
2.  Порт Consul (по умолчанию `8500`) доступен с сервера Nginx.
3.  На ваше доменное имя (например, `consul.your-domain.com`) настроена A-запись, указывающая на публичный IP-адрес сервера Nginx.

## 2. Конфигурация Nginx

Создайте конфигурационный файл для вашего домена, например, `/etc/nginx/conf.d/consul.conf`.

### 2.1. Определение Upstream

Сначала определим группу `upstream`, в которую включим все серверы Consul.

```nginx
upstream consul_backend {
    server consul-1_private_ip:8500;
    server consul-2_private_ip:8500;
    server consul-3_private_ip:8500;
}
```

### 2.2. Основной блок Server (HTTPS)

Этот блок будет обрабатывать HTTPS-трафик.

```nginx
server {
    listen 443 ssl http2;
    server_name consul.your-domain.com;

    # Пути к SSL-сертификатам (будут получены позже)
    ssl_certificate /etc/nginx/ssl/consul/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/consul/privkey.pem;

    # Подключение общих параметров SSL
    include /etc/nginx/ssl.conf;

    # Заголовок HSTS для безопасности
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        proxy_pass http://consul_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Опционально: можно закрыть доступ к определенным путям
    location /v1/agent {
        deny all;
        return 403;
    }
}
```

### 2.3. Общие параметры SSL

Рекомендуется вынести общие параметры SSL в отдельный файл, например, `/etc/nginx/ssl.conf`, чтобы переиспользовать их для других сайтов.

```nginx
# /etc/nginx/ssl.conf

ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384';
ssl_prefer_server_ciphers off;

ssl_session_cache shared:SSL:10m;
ssl_session_timeout 1d;
ssl_session_tickets off;
```

### 2.4. Редирект с HTTP на HTTPS

Добавьте блок `server` для перенаправления всего HTTP-трафика на HTTPS.

```nginx
server {
    listen 80;
    server_name consul.your-domain.com;
    return 301 https://$host$request_uri;
}
```

## 3. Получение SSL-сертификата

Для получения сертификата можно использовать `certbot`.

1.  **Установите Certbot:**
    ```bash
    sudo apt update
    sudo apt install certbot python3-certbot-nginx
    ```

2.  **Получите сертификат:**
    Перед запуском команды временно остановите Nginx, если `certbot` будет использовать 80-й порт для проверки.
    ```bash
    sudo systemctl stop nginx
    sudo certbot certonly --standalone -d consul.your-domain.com --agree-tos -m your-email@example.com
    ```
    *Certbot* создаст сертификаты в `/etc/letsencrypt/live/consul.your-domain.com/`. Вам нужно либо указать эти пути в конфигурации Nginx, либо скопировать их в директорию, указанную ранее (`/etc/nginx/ssl/consul/`).

## 4. Завершение

После создания конфигурации и получения сертификатов:
1.  Проверьте синтаксис конфигурации Nginx: `sudo nginx -t`.
2.  Запустите или перезагрузите Nginx: `sudo systemctl start nginx` или `sudo systemctl reload nginx`.

После этого UI Consul должен быть доступен по адресу `https://consul.your-domain.com` через защищенное соединение.

## 5. Практический пример: Пошаговая настройка

Этот раздел содержит полезные команды из практического сценария настройки.

### Проверка сетевой связности
Перед настройкой убедитесь, что ваш Nginx-сервер "видит" узлы Consul по их внутренним адресам.

```bash
# Проверяем доступность по ICMP
ping consul-1_private_ip

# Проверяем доступность порта 8500
# nc -v consul-1_private_ip 8500
# или
telnet consul-1_private_ip 8500
```

### Процесс получения сертификата
Если `certbot` использует метод `standalone`, ему потребуется занять 80-й порт, который обычно слушает Nginx.

```bash
# 1. Временно останавливаем Nginx
sudo systemctl stop nginx

# 2. Запрашиваем сертификат
sudo certbot certonly --standalone \
  -d consul.your-domain.com \
  --agree-tos \
  -m your-email@example.com \
  --non-interactive

# 3. Проверяем конфигурацию Nginx с новыми путями к сертификатам
sudo nginx -t

# 4. Запускаем Nginx обратно
sudo systemctl start nginx
```

### Рекомендация по безопасности
После того как вы убедились, что доступ к Consul через Nginx работает корректно, **отключите публичные IP-адреса** у виртуальных машин самого кластера Consul.

Это можно сделать, например, в конфигурации Terraform, изменив параметр `nat = false` для сетевого интерфейса ВМ и применив изменения.

```hcl
# terraform/main.tf (пример)

resource "yandex_compute_instance" "consul_node" {
  # ...
  network_interface {
    subnet_id = var.default_subnet_id
    nat       = false # Отключаем публичный IP
  }
  # ...
}
```
 Этот шаг значительно сокращает поверхность атаки, так как прямой доступ к узлам Consul извне становится невозможен.
