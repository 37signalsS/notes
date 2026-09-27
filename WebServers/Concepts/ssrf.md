# SSRF: Server-Side Request Forgery для веб-серверов

## Определения

**SSRF (Server-Side Request Forgery)** — класс уязвимостей, при котором злоумышленник заставляет веб-сервер или приложение отправить HTTP/внутренний запрос к ресурсу, к которому сам сервер имеет доступ, но клиент получить не может. Веб-сервер выступает как прокси для атаки на внутреннюю инфраструктуру.

**Internal Network (Внутренняя сеть)** — сеть, недоступная из интернета, но доступная с веб-сервера: метаданные облака (169.254.169.254), внутренние API, базы данных, кэш, мониторинг.

**Metadata Service** — сервис метаданных в облачных окружениях (AWS 169.254.169.254, GCP 169.254.169.254, Azure 169.254.169.254). Частая цель SSRF-атак.

**Blind SSRF** — вариант SSRF, при котором сервер не возвращает ответ атакующему, но запрос доставляется. Обнаруживается через out-of-band каналы (DNS rebind, OAST).

**DNS rebind** — техника, при которой злоумышленник контролирует DNS-ответ и перенаправляет запрос с внешнего домена на внутренний IP после первого запроса.

## Основные концепции

### Векторы SSRF

| Вектор | Пример | Ущерб |
| :--- | :--- | :--- |
| **URL параметр** | `?url=http://internal-api/admin` | Доступ к внутреннему API |
| **Прокси/редирект** | `?next=http://169.254.169.254/latest/meta-data/` | Кража metadata |
| **Webhook** | `https://attacker.com/webhook` → внутренний запрос | Exfiltration данных |
| **PDF/Image генерация** | `?url=http://internal-service:6379/` | Доступ к Redis без auth |
| **SSRF в Cloud** | `http://169.254.169.254/latest/meta-data/` | Кража IAM credentials |

### Внутренние цели SSRF

| Цель | Адрес | Данные |
| :--- | :--- | :--- |
| **AWS Metadata** | 169.254.169.254 | IAM credentials, instance metadata |
| **GCP Metadata** | 169.254.169.254 | Access token, service account |
| **Azure Metadata** | 169.254.169.254 | Access token, managed identity |
| **Kubernetes API** | 10.96.0.1:443 | Секреты, конфигурации |
| **etcd** | 2379 | Ключи, пароли |
| **Redis** | 6379 | Данные, конфигурация |
| **Memcached** | 11211 | Данные сессий |
| **Внутренние API** | 10.x.x.x:8080 | Пользовательские данные |
| **Database** | 3306, 5432 | Данные, схема |

### Защита от SSRF

| Метод | Механизм | Эффективность |
| :--- | :--- | :--- |
| **Whitelist** | Разрешить только доверенные домены/IP | Высокая |
| **Blacklist** | Блокировать внутренние IP (127.0.0.1, 169.254.0.0/16) | Средняя (обход через rebind) |
| **DNS rebind protection** | Не разрешать CNAME на внутренние IP | Высокая |
| **Network segmentation** | Отделить веб-сервер от внутренней сети | Высокая |
| **Firewall** | Ограничить исходящие трафик веб-сервера | Высокая |
| **Proxy** | Внешние запросы через кастомный proxy с фильтрацией | Средняя |

### Ограничения веб-серверов против SSRF

| Компонент | Защита | Ограничение |
| :--- | :--- | :--- |
| **Nginx** | `resolver` с DNSSEC, `proxy_pass` с валидацией | Не валидирует внутренние IP в `proxy_pass` |
| **Apache** | `ProxyPass` с `allow/deny` | Уязвим к DNS rebind |
| **HAProxy** | `http-request deny` по ACL | Требует явной конфигурации ACL |

## Практические сценарии

### Сценарий 1: Валидация URL в Nginx

```nginx
# Разрешить только внешние домены
map $request_uri $is_internal {
    default                          0;
    ~*169\.254\.169\.254            1;  # AWS Metadata
    ~*10\.\d+\.\d+\.\d+             1;  # RFC1918
    ~*172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+  1;  # 172.16-31
    ~*192\.168\.\d+\.\d+            1;  # RFC1918
    ~*127\.\d+\.\d+\.\d+            1;  # Loopback
    ~*0\.\d+\.\d+\.\d+              1;  # Current network
}

server {
    listen 80;
    server_name example.com;

    location /proxy {
        if ($is_internal) { return 403; }
        proxy_pass http://$arg_url;
    }
}
```

**Валидация:**
- `curl "http://example.com/proxy?url=http://169.254.169.254/latest/meta-data/"` — `403 Forbidden`.
- `curl "http://example.com/proxy?url=http://example.com/"` — разрешено.

### Сценарий 2: Ограничение исходящих запросов Nginx

```nginx
# Разрешить исходящие запросы только к внешним IP
resolver 8.8.8.8 1.1.1.1 valid=300s;

# DNS rebind protection: не разрешать CNAME на внутренние IP
resolver 8.8.8.8 1.1.1.1 valid=300s ipv6=off;
resolver_timeout 5s;

server {
    listen 80;
    server_name example.com;

    location /proxy {
        # Блокировать внутренние IP
        if ($proxy_host ~* "(169\.254|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.|192\.168\.|127\.|0\.)") {
            return 403;
        }
        proxy_pass http://$proxy_host;
    }
}
```

### Сценарий 3: Защита внутренних сервисов

```nginx
# Внутренний сервис, который не должен приниматься извне
server {
    listen 127.0.0.1:8080;
    server_name internal-api;

    location / {
        deny all;
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        allow 192.168.0.0/16;
    }
}
```

### Сценарий 4: Обнаружение Blind SSRF

```bash
# Внешний сервер для OAST (Out-of-Band Application Security Testing)
# Используйте Burp Collaborator, interactsh, или свой сервер

# Проверка DNS rebind
dig +short attacker.com
# Должен вернуть внешний IP, а не внутренний

# Проверка с curl
curl -v "http://example.com/proxy?url=http://169.254.169.254/latest/meta-data/iam/security-credentials/"
```

## Лучшие практики

1. **Whitelist вместо blacklist:** всегда разрешайте только доверенные домены/IP, а не блокируйте внутренние.
2. **Network segmentation:** веб-сервер должен иметь доступ только к необходимым внутренним сервисам.
3. **Firewall исходящих запросов:** ограничьте исходящие порты веб-сервера (только 80, 443).
4. **DNS rebind protection:** используйте DNSSEC и валидируйте DNS-ответы.
5. **Metadata service hardening:** отключите metadata service или ограничьте доступ через IAM.
6. **WAF с SSRF-правилами:** ModSecurity CRS включает правила против SSRF (Rule 941).
7. **Не передавайте пользовательский URL в `proxy_pass` без валидации:** всегда проверяйте схему, хост, порт.
8. **Используйте HTTP proxy с SSRF-защитой:** например, Squid с ACL.

## Граничные случаи и ограничения

1. **DNS rebind обходит blacklist:** если злоумышленник контролирует DNS, он может вернуть внутренний IP после первого запроса.
2. **IPv6:** внутренние IPv6-адреса (::1, fc00::/7) могут быть упущены в blacklist.
3. **Cloud metadata:** в некоторых облаках metadata service доступен через IPv6 (fd00:ec2::254).
4. **HTTP redirects:** внутренний сервис может вернуть 302 на внутренний ресурс. Следуйте редиректам с осторожностью.
5. **Chained SSRF:** один SSRF ведёт к другому (например, сначала на metadata, потом на внутренний API).
6. **Blind SSRF трудно обнаружить:** требует OAST-инструментов (Burp Collaborator, interactsh).

## Дополнительная информация

- **[Безопасность HTTP в продакшене](../../Networking/Protocols/HTTP/http_security_hardening.md)** — WAF, request smuggling, OWASP Top 10.
- **[ModSecurity и NAXSI](../../Networking/Protocols/HTTP/http_security_hardening.md)** — правила против SSRF.
- **[OWASP SSRF](https://owasp.org/www-community/attacks/Server_Side_Request_Forgery)** — руководство по SSRF.
