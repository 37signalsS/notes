# CRL Distribution Points — настройка HTTP-сервера для распространения CRL

## Определения

**CRL Distribution Point (CDP)** — расширение X.509 сертификата (RFC 5280), указывающее URL, по которому клиент может загрузить CRL (Certificate Revocation List) для проверки статуса отзыва сертификата.

**CRL (Certificate Revocation List)** — подписанный CA список серийных номеров отозванных сертификатов. Клиент загружает CRL и проверяет, находится ли сертификат в списке отзыва.

**Freshest CRL (Delta CRL)** — расширение, указывающее URL дельта-CRL, содержащей только изменения с момента публикации основной CRL. Позволяет клиентам загружать меньше данных.

---

## Теоретический блок

### Зачем нужен CDP

Без расширения `crlDistributionPoints` в сертификате клиент:
- Не знает, где скачать CRL
- Не может проверить статус отзыва
- Для public CA это критично; для internal CA — вопрос политики

### Типы CDP

| Тип URL | Описание | Использование |
| :--- | :--- | :--- |
| `http://` | HTTP-сервер | Самый распространённый, прост в настройке |
| `ldap://` | LDAP-сервер | Корпоративные среды с Active Directory |
| `file://` | Локальный файл | Только для testing, не для production |
| `https://` | HTTPS-сервер | Рекомендуется для production (защита от MITM) |

### Архитектура CDP

```text
┌──────────────┐
│ Intermediate │
│     CA       │
└──────┬───────┘
       │
       │ публикует CRL
       ▼
┌──────────────────┐     ┌──────────────────┐
│  HTTP-сервер     │     │  LDAP-сервер     │
│  (nginx/apache)  │     │  (опционально)   │
│                  │     │                  │
│  /crl/           │     │  cn=CRL,dc=...   │
│  ├── ca.crl      │     │                  │
│  └── delta.crl   │     │                  │
└────────┬─────────┘     └──────────────────┘
         │
    клиент загружает
    при проверке
```

### Периодичность публикации CRL

- Рекомендуется: каждые 24 часа (стандарт)
- Minimum: зависит от `nextUpdate` в самой CRL
- При отзыве сертификата: немедленная публикация новой CRL

---

## Практический блок

### Шаг 1: Добавление расширения CDP в сертификаты

#### В openssl.cnf (рекомендуется)

```ini
# Добавить в секцию [v3_intermediate_ca] или [v3_server_cert]

# Основной CRL Distribution Point
crlDistributionPoints = URI:http://crl.internal/ca.crl

# Delta CRL (опционано)
freshestCRL = URI:http://crl.internal/ca-delta.crl
```

#### При подписании через -extfile

```bash
cat > crl_ext.cnf << 'EOF'
crlDistributionPoints = URI:http://crl.internal:8080/ca.crl
EOF

openssl ca -config openssl.cnf \
  -extensions v3_server_cert \
  -extfile crl_ext.cnf \
  -in leaf.csr \
  -out leaf.crt \
  -days 90
```

#### Проверка наличия CDP в сертификате

```bash
openssl x509 -in leaf.crt -text | grep -A2 "CRL Distribution"
# → X509v3 CRL Distribution Points:
# →   Full Name:
# →     URI:http://crl.internal:8080/ca.crl
```

### Шаг 2: Генерация CRL

```bash
# Генерация CRL на Intermediate CA
openssl ca -config openssl.cnf \
  -gencrl \
  -out /var/www/crl/ca.crl

# Просмотр CRL
openssl crl -in /var/www/crl/ca.crl -text -noout

# Проверка подписи CRL
openssl crl -in /var/www/crl/ca.crl -CAfile intermediate.crt -noout -verify
# → verify OK
```

### Шаг 3: Автоматическая публикация CRL через cron

```bash
# /etc/cron.d/ca-crl-publish
# Публикация CRL каждые 24 часа
0 2 * * * ca-operator /opt/ca/scripts/publish_crl.sh
```

```bash
#!/bin/bash
# /opt/ca/scripts/publish_crl.sh

CA_DIR="/opt/ca/intermediate"
CRL_DIR="/var/www/crl"
LOG="/var/log/ca/crl-publish.log"

cd "$CA_DIR" || exit 1

# Генерация CRL
openssl ca -config openssl.cnf \
  -gencrl \
  -out "${CRL_DIR}/ca.crl" 2>> "$LOG"

# Проверка подписи
if openssl crl -in "${CRL_DIR}/ca.crl" -CAfile intermediate.crt -noout -verify 2>> "$LOG"; then
    logger -t ca-crl "CRL published successfully"
else
    logger -t ca-crl -p daemon.err "CRL signature verification failed"
    exit 1
fi
```

```bash
chmod +x /opt/ca/scripts/publish_crl.sh
mkdir -p /var/log/ca
```

### Шаг 4: Настройка HTTP-сервера для CRL

#### Вариант A: Nginx (рекомендуется)

```nginx
# /etc/nginx/conf.d/crl.conf
server {
    listen 8080;
    server_name crl.internal;

    # Read-only доступ к CRL
    location / {
        root /var/www/crl;
        autoindex off;

        # MIME-тип для CRL
        types {
            application/pkix-crl crl;
        }

        # Кэширование (CRL обновляется раз в сутки)
        add_header Cache-Control "public, max-age=86400";
        add_header Content-Type "application/pkix-crl";

        # Запрет кэширования просроченных CRL
        if ($time_iso8601 ~ "^(\d{4})-(\d{2})-(\d{2})T(\d{2})") {
            set $year $1;
        }

        # Доступ только для чтения
        limit_except GET {
            deny all;
        }
    }

    # Запрет доступа к скрытым файлам
    location ~ /\. {
        deny all;
    }
}
```

```bash
# Проверка конфигурации
nginx -t && systemctl reload nginx
```

#### Вариант B: Apache

```apache
# /etc/apache2/sites-available/crl.conf
<VirtualHost *:8080>
    ServerName crl.internal
    DocumentRoot /var/www/crl

    <Directory /var/www/crl>
        Require all granted
        Options -Indexes
    </Directory>

    # MIME-тип
    AddType application/pkix-crl .crl

    # Кэширование
    Header set Cache-Control "public, max-age=86400"
</VirtualHost>
```

#### Вариант C: Python (для тестов)

```python
#!/usr/bin/env python3
# /opt/ca/scripts/crl_server.py
import http.server
import os

CRL_DIR = "/var/www/crl"
PORT = 8080

class CRLHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=CRL_DIR, **kwargs)

    def guess_type(self, path):
        if path.endswith('.crl'):
            return 'application/pkix-crl'
        return super().guess_type(path)

if __name__ == '__main__':
    with http.server.HTTPServer(('0.0.0.0', PORT), CRLHandler) as httpd:
        print(f"CRL server on port {PORT}")
        httpd.serve_forever()
```

### Шаг 5: Тестирование загрузки CRL

```bash
# Загрузка CRL с HTTP-сервера
curl -o ca.crl http://crl.internal:8080/ca.crl
# → загружает файл

# Просмотр загруженной CRL
openssl crl -in ca.crl -text -noout | head -20
# → Version: v2 (2)
# → Signature Algorithm: ...
# → Issuer: ...
# → Last Update: ...
# → Next Update: ...

# Проверка, что CRL соответствует CA
openssl crl -in ca.crl -CAfile intermediate.crt -noout -verify
# → verify OK
```

### Шаг 6: Интеграция с Nginx (ssl_crl)

```nginx
server {
    listen 443 ssl;
    server_name my-service.local;

    ssl_certificate     /etc/ssl/certs/leaf.crt;
    ssl_certificate_key /etc/ssl/private/leaf.key;

    # Проверка отзыва через CRL
    ssl_crl /etc/ssl/crl/ca.crl;

    # Или CRL на HTTP (через proxy)
    # ssl_crl http://crl.internal:8080/ca.crl;
}
```

```bash
# Обновление CRL на Nginx-сервере
scp crl.internal:/var/www/crl/ca.crl /etc/ssl/crl/ca.crl
nginx -t && systemctl reload nginx
```

### Шаг 7: Дистрибуция CRL на клиентские узлы (Ansible)

```yaml
- name: Distribute CRL to web servers
  hosts: web_servers
  tasks:
    - name: Ensure CRL directory exists
      file:
        path: /etc/ssl/crl
        state: directory
        mode: '0755'

    - name: Fetch latest CRL from CA
      fetch:
        src: /var/www/crl/ca.crl
        dest: /etc/ssl/crl/ca.crl
        flat: yes
      delegate_to: ca-server.internal

    - name: Reload Nginx if CRL changed
      systemd:
        name: nginx
        state: reloaded
      when: crl_changed | default(false)
```

---

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `unable to get local issuer certificate` (code 20) | Клиент не может скачать CRL по URL из CDP | Проверьте доступность HTTP-сервера, DNS-резолв, firewall |
| `CRL has expired` | `nextUpdate` в CRL прошёл | Перегенерируйте CRL (`openssl ca -gencrl`) |
| `CRL signature failure` | CRL подписана другим ключом | Убедитесь, что CRL подписана тем же ключом, что и сертификаты |
| `incorrect CRL number` | Номер CRL не монотонно растёт | Проверьте файл `crlnumber`, не откатывайте его |
| `certificate revoked but not in CRL` | Сертификат отозван, но CRL не обновлена | Перегенерируйте и опубликуйте CRL |

---

## Лучшие практики

1. **HTTPS для CDP:** Используйте `https://` вместо `http://` для защиты от MITM (подмена CRL)
2. **Высокая доступность:** Разместите CRL-сервер за load balancer или используйте CDN
3. **Кэширование:** Устанавливайте `Cache-Control` на 12–24 часа, чтобы снизить нагрузку
4. **Автоматизация:** Публикуйте CRL через cron + скрипт с проверкой подписи
5. **Мониторинг:** Добавьте Blackbox Exporter probe для проверки доступности CDP URL
6. **Дельта-CRL:** Используйте `freshestCRL` для сред с высоким темпом отзыва сертификатов
7. **Резервное копирование:** Храните CRL-файлы в backup, чтобы не потерять историю отзывов

---

## Дополнительная информация

- **RFC 5280** — [Internet X.509 PKI Certificate Profile (CRL Extensions)](https://datatracker.ietf.org/doc/html/rfc5280)
- **[OCSP Responder](./ocsp_responder.md)** — альтернативный/дополнительный механизм проверки отзыва
- **[Обзор PKI](../../Concepts/pki_overview.md)** — базовые понятия PKI
- **[Blackbox Exporter](../../../Prometheus/Exporters/blackbox/blackbox_exporter_overview.md)** — мониторинг доступности CDP URL
- **[Nginx TLS](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_virtual_host_config.md)** — настройка ssl_crl
