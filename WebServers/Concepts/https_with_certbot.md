---
reliability: 10
updated: 2026-09-24
---

# Let's Encrypt и Certbot — HTTPS для веб-серверов

## Определения

**Let's Encrypt** — некоммерческий центр сертификации (CA, Certificate Authority), предоставляющий бесплатные SSL/TLS сертификаты через протокол ACME (RFC 8555). Основан EFF, Mozilla и другими организациями. Выпускает только DV (Domain Validation) сертификаты с 90-дневным сроком действия.

**ACME (Automated Certificate Management Environment)** — протокол автоматизированного управления сертификатами: получение, обновление, отзыв TLS-сертификатов без участия человека. В 2026 году используется ACME v2 (`acme-v02.api.letsencrypt.org`). ACME v1 устарел и не поддерживается.

**ACME v2 Endpoint (Production)** — `https://acme-v02.api.letsencrypt.org/directory`

**ACME v2 Endpoint (Staging)** — `https://acme-staging-v02.api.letsencrypt.org/directory`

**Certbot** — официальный инструмент EFF (Electronic Frontier Foundation) для автоматического получения и обновления сертификатов Let's Encrypt. Поддерживает плагины для Nginx, Apache и методы webroot, standalone, manual. Актуальная версия на 2026 год: **5.8.0**.

**Webroot** — метод авторизации ACME: проверочный файл размещается в `.well-known/acme-challenge/` на веб-сервере.

**Standalone** — метод авторизации, при котором Certbot запускает временный веб-сервер на порту 80 или 443 для прохождения ACME challenge. Требует, чтобы порт был свободен.

**ARI (Automated Renewal Information, RFC 9773)** — расширение протокола ACME, позволяющее центру сертификации рекомендовать клиенту обновить сертификат раньше срока действия. В Certbot 4.1.0+ включен по умолчанию.

**CT (Certificate Transparency)** — технология регистрации всех выданных сертификатов в публичных логах. ACME-клиенты (включая Certbot) добавляют SCT (Signed Certificate Timestamp) автоматически.

### Типы ключей: ECDSA и RSA

**ECDSA (Elliptic Curve Digital Signature Algorithm)** — ключ на основе эллиптических кривых. Certbot 5.x+: ECDSA (P-256) — тип по умолчанию. Обеспечивает высокий уровень безопасности при меньшей нагрузке на CPU.

**RSA (Rivest–Shamir–Adleman)** — классический тип ключа. Рекомендуемые размеры: 2048 (минимум), 4096 (высокая безопасность).

### Лимиты запросов Let's Encrypt (Rate Limits)

| Лимит | Значение |
| :--- | :--- |
| Повторные сертификаты (Duplicate Certificate Limit) | 50 сертификатов на домен в неделю |
| Регистрация аккаунтов (Registration Rate Limit) | 5 регистраций на IP в час |
| Проверки авторизации (Verification Rate Limit) | 30 проверок на домен в час |

### Сертификаты для IP-адресов (Профиль shortlived)

Начиная с Certbot 5.3.0, Let's Encrypt поддерживает выдачу сертификатов для IPv4-адресов через профиль **shortlived**.

* **Срок действия:** 6 дней (требует частой ротации).
* **Команда:**
```bash
sudo certbot certonly \
  --preferred-profile shortlived \
  --ip-address <ВАШ_IP> \
  --standalone
```

### Цепочки доверия Let's Encrypt

**ISRG Root X1** — корневой сертификат Let's Encrypt. Корневой сертификат является самоподписанным и хранится в операционных системах. Промежуточные сертификаты:

* **R3 (RSA)** — промежуточный для RSA-сертификатов.
* **E1 (ECDSA)** — промежуточный для ECDSA-сертификатов.

**ISRG Root X2** — новый корневой сертификат Let's Encrypt (включен в системы начиная с 2025–2026 годов).

**Цепочки R10-R14 (RSA) и E5-E9 (ECDSA)** — новые цепочки доверия, которые короче и быстрее загружаются.

### CAA-записи

**CAA (Certification Authority Authorization, RFC 8657)** — DNS-запись, разрешающая конкретным CA выпускать сертификаты для домена.

```dns
example.com.  IN  CAA  0 issue "letsencrypt.org"
```

## Основные концепции

### Жизненный цикл сертификата

1. **Получение:** Certbot запрашивает сертификат у CA через ACME-протокол.
2. **Валидация:** CA проверяет контроль над доменом через HTTP-01, DNS-01 или другой метод.
3. **Установка:** Certbot сохраняет сертификат в `/etc/letsencrypt/live/<domain>/`, обновляет конфигурацию веб-сервера.
4. **Автообновление:** Certbot автоматически обновляет сертификат до истечения срока действия.
5. **Отзыв:** `certbot revoke` отзывает сертификат (если ключ скомпрометирован или сертификат больше не нужен).

### Методы авторизации

**HTTP-01** — проверка владения доменом через размещение файла по протоколу HTTP в директории `.well-known/acme-challenge/`.

* Требует открытый 80 порт
* Не поддерживает wildcard (групповые сертификаты)
* Для обычных доменных сертификатов

**DNS-01** — проверка через TXT-запись `_acme-challenge.example.com` в DNS.

* Поддерживает wildcard (`*.example.com`)
* Не требует доступности сервера
* Требует API DNS-провайдера

**TLS-ALPN-01** — проверка через TLS-соединение на 443 порту с расширением ALPN `acme-tls/1`.

* Требует открытый 443 порт
* Подходит для CDN и reverse-proxy, где 80 порт закрыт
* Не поддерживает wildcard

> **Лучшие практики:** Рекомендуется использовать ECDSA (P-256). Let's Encrypt перешел на новые цепочки доверия (R10-R14 для RSA и E5-E9 для ECDSA), которые короче и быстрее. Поддержка ARI (Automated Renewal Information) позволяет Certbot автоматически обновлять сертификаты, если CA рекомендует это сделать раньше срока.

### Директория сертификатов

```
/etc/letsencrypt/
├── live/<domain>/
│   ├── cert.pem            # Сертификат (сторонние инструменты часто используют fullchain.pem)
│   ├── chain.pem           # Промежуточные сертификаты
│   ├── fullchain.pem       # Сертификат + промежуточные (используется в веб-сервере)
│   └── privkey.pem         # Приватный ключ
├── archive/<domain>/
│   ├── cert1.pem
│   ├── chain1.pem
│   ├── fullchain1.pem
│   └── privkey1.pem
├── renewal/                # Конфигурации для автообновления
│   └── <domain>.conf
└── csr/                    # Временные запросы на сертификаты
```

## Практические сценарии

### Сценарий 1: Установка Certbot (Рекомендуемый способ — Snap)

Использование **snapd** является официальной рекомендацией EFF, так как позволяет всегда иметь актуальную версию клиента и плагинов.

**Предварительная подготовка (Debian/Ubuntu/CentOS):**

```bash
# 1. Установка snapd (если не установлен)
sudo apt install snapd        # Debian/Ubuntu
sudo dnf install snapd        # CentOS/RHEL

# 2. Удаление старых версий (если были установлены через apt/dnf)
sudo apt-get remove certbot

# 3. Установка через snap
sudo snap install --classic certbot

# 4. Подготовка команды certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot
```

**Установка плагина для Nginx:**

```bash
sudo snap set certbot trust-plugin-with-root=ok
sudo snap install certbot-dns-cloudflare
```

**Проверка установки:**

```bash
certbot --version
# → certbot 5.8.0
```

### Сценарий 2: Получение сертификата (Nginx)

**Базовый сценарий:**

```bash
sudo certbot --nginx -d example.com -d www.example.com
```

Certbot запросит email, согласование условий и предложит редирект HTTP → HTTPS (рекомендуется `Redirect`). Сертификаты сохраняются в `/etc/letsencrypt/live/example.com/`, конфигурация Nginx обновляется автоматически.

**Продвинутый сценарий (ECDSA + RSA):**

```bash
# ECDSA (по умолчанию в Certbot 5.x+)
sudo certbot certonly --webroot -w /var/www/certbot \
    --key-type ecdsa \
    -d example.com -d www.example.com

# RSA (отдельно, для совместимости)
sudo certbot certonly --webroot -w /var/www/certbot \
    --key-type rsa --rsa-key-size 2048 \
    -d example.com -d www.example.com
```

**Nginx для двух сертификатов:**

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    # ECDSA (Основной)
    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # RSA (Для старых клиентов, если выпущен отдельно)
    # ssl_certificate /etc/letsencrypt/live/example.com-rsa/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/example.com-rsa/privkey.pem;
}
```

**Валидация перед использованием:**

```bash
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

sudo systemctl reload nginx
```

### Сценарий 3: Получение сертификата (Apache)

**Установка Certbot (Legacy apt):**

```bash
sudo apt update
sudo apt install certbot python3-certbot-apache
```

**Получение сертификата:**

```bash
sudo certbot --apache -d example.com -d www.example.com
```

**Ручная установка (certonly):**

```bash
sudo certbot certonly --webroot -w /var/www/html \
    -d example.com -d www.example.com
```

**Конфигурация Apache (VirtualHost):**

```apache
<VirtualHost *:443>
    ServerName example.com
    ServerAlias www.example.com

    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/example.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/example.com/privkey.pem

    DocumentRoot /var/www/html
</VirtualHost>
```

**Валидация:**

```bash
sudo apachectl configtest
# → Syntax OK

sudo systemctl reload httpd
```

### Сценарий 4: Wildcard-сертификат через DNS-01

**Подготовка API ключа (Cloudflare):**

```bash
export CF_Key="your_cloudflare_api_key"
export CF_Email="your_cloudflare_email"
```

**Получение wildcard-сертификата:**

```bash
# ECDSA
sudo certbot certonly --dns-cloudflare \
    -d example.com \
    -d "*.example.com" \
    --key-type ecdsa

# RSA (отдельно, для совместимости)
sudo certbot certonly --dns-cloudflare \
    -d example.com \
    -d "*.example.com" \
    --key-type rsa --rsa-key-size 2048
```

**Поддерживаемые DNS-провайдеры (плагины certbot-dns-*):**

* `certbot-dns-cloudflare`
* `certbot-dns-route53` (AWS)
* `certbot-dns-google`
* `certbot-dns-digitalocean`
* `certbot-dns-ovh`
* `certbot-dns-rfc2136` (Bind9, PowerDNS)
* `certbot-dns-linode`
* `certbot-dns-godaddy`
* И более 30 других.

### Сценарий 5: Standalone (без веб-сервера)

**Использование socat для временного сервера:**

```bash
# Установка socat
sudo apt install socat

# Получение сертификата
sudo certbot certonly --standalone \
    -d example.com -d www.example.com
```

**Для Nginx на порту 80/443 требуется остановка перед запуском:**

```bash
sudo systemctl stop nginx
sudo certbot certonly --standalone -d example.com
sudo systemctl start nginx
```

### Сценарий 6: Автоматическое обновление

**При установке через Snap:** таймер настраивается автоматически. Проверка:

```bash
sudo systemctl list-timers | grep certbot
# → snap.certbot.renew.service

sudo systemctl status snap.certbot.renew.service
# → Active: active (exited)
```

**Классический метод (Legacy):**
* **Debian/Ubuntu:** таймер `systemd` (`certbot.timer`).
* **CentOS:** задача в `cron`.

**Ручная проверка продления:**

```bash
sudo certbot renew --dry-run
```

**Принудительное продление:**

```bash
sudo certbot renew --force-renewal
```

**Post-hooks (выполнение команд после обновления):**

```bash
sudo certbot renew --post-hook "systemctl reload nginx"
```

Или в конфигурации `/etc/letsencrypt/renewal/<domain>.conf`:

```ini
post_hook = systemctl reload nginx
```

### Сценарий 7: Firewall и SELinux/AppArmor

**UFW (Uncomplicated Firewall):**

```bash
sudo ufw allow http/tcp
sudo ufw allow https/tcp
sudo ufw status
# → Status: active

# → http      ALLOW IN    Anywhere
# → https     ALLOW IN    Anywhere
```

**firewalld (CentOS/RHEL):**

```bash
sudo firewall-cmd --permanent --add-service={http,https}
sudo firewall-cmd --reload

sudo firewall-cmd --list-all
# → services: http, https, ssh
```

**SELinux (CentOS/RHEL):**

```bash
# Проверка контекста
sudo ls -la /etc/letsencrypt/live/
# → system_u:object_r:cert_t:s0

# Разрешение веб-серверу читать сертификаты
sudo restorecon -Rv /etc/letsencrypt/
sudo chmod -R o+rx /etc/letsencrypt/live/

# Для Nginx
sudo setsebool -P httpd_read_user_content 1
sudo setsebool -P httpd_can_network_connect 1
```

**AppArmor (Ubuntu/Debian):**

```bash
sudo aa-status | grep nginx
# → nginx confined by /etc/apparmor.d/usr.sbin.nginx

sudo aa-complain /usr/sbin/nginx
sudo systemctl reload nginx
```

### Сценарий 8: Резервное копирование сертификатов

```bash
# Архивирование директории letsencrypt
sudo tar czf /backup/letsencrypt-$(date +%F).tar.gz \
    /etc/letsencrypt/ \
    /var/lib/snapd/certs/

# Резервное копирование конкретного домена
sudo tar czf /backup/cert-example.com-$(date +%F).tar.gz \
    -C /etc/letsencrypt/live/example.com .
```

### Сценарий 9: Мониторинг сроков действия

```bash
#!/bin/bash
# cert-monitor.sh — мониторинг сроков действия сертификатов

DOMAINS=("example.com" "www.example.com")
DAYS_WARN=30
DAYS_CRIT=7

for DOMAIN in "${DOMAINS[@]}"; do
    EXP_DATE=$(echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null | \
      openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)

    if [ -z "$EXP_DATE" ]; then
      echo "CRITICAL: Unable to fetch certificate for $DOMAIN"
      continue
    fi

    EXP_EPOCH=$(date -d "$EXP_DATE" +%s)
    NOW_EPOCH=$(date +%s)
    DAYS_LEFT=$(( ($EXP_EPOCH - $NOW_EPOCH) / 86400 ))

    if [ "$DAYS_LEFT" -lt "$DAYS_CRIT" ]; then
      echo "CRITICAL: Certificate for $DOMAIN expires in $DAYS_LEFT days"
    elif [ "$DAYS_LEFT" -lt "$DAYS_WARN" ]; then
      echo "WARNING: Certificate for $DOMAIN expires in $DAYS_LEFT days"
    else
      echo "OK: Certificate for $DOMAIN expires in $DAYS_LEFT days"
    fi
done
```

### Сценарий 10: SSL Labs тестирование

```bash
# Проверка через openssl
echo | openssl s_client -connect example.com:443 -servername example.com -status 2>&1 | \
  grep -E "Protocol|Cipher|OCSP"

# Проверка версии OpenSSL
openssl version -a
# → OpenSSL 3.5.0 15 Oct 2026

# Проверка цепочки сертификатов
echo | openssl s_client -connect example.com:443 -servername example.com -showcerts 2>&1 | \
  grep -E "s:|i:"
```

## Операции и команды

### Основные команды

| Команда | Назначение |
| :--- | :--- |
| `certbot --nginx -d <domain>` | Получение и автоматическая установка сертификата в Nginx |
| `certbot --apache -d <domain>` | Получение и автоматическая установка сертификата в Apache |
| `certbot certonly --webroot -w <path> -d <domain>` | Получение сертификата без установки (webroot метод) |
| `certbot certonly --standalone -d <domain>` | Получение сертификата через временный сервер (standalone) |
| `certbot certonly --dns-<provider> -d <domain>` | Получение сертификата через DNS-01 |
| `certbot renew` | Обновление всех сертификатов, близких к истечению |
| `certbot renew --dry-run` | Тестовое обновление без реальной замены |
| `certbot renew --force-renewal` | Принудительное обновление всех сертификатов |
| `certbot renew --post-hook "<cmd>"` | Выполнение команды после обновления |
| `certbot certificates` | Список всех сертификатов и сроков действия |
| `certbot revoke --cert-path <path>` | Отзыв сертификата |
| `certbot delete -d <domain>` | Удаление сертификата из базы Certbot |
| `certbot register --update-registration` | Обновление email аккаунта |
| `certbot plugins` | Список доступных плагинов |
| `certbot --staging --nginx -d <domain>` | Получение тестового сертификата (staging) |

### Диагностические команды

| Команда | Назначение |
| :--- | :--- |
| `openssl x509 -in <file> -text -noout` | Детали сертификата |
| `openssl x509 -in <file> -enddate -noout` | Дата истечения срока действия |
| `openssl s_client -connect <host>:443 -servername <host>` | Проверка TLS-рукопожатия |
| `openssl s_client -connect <host>:443 -status` | Проверка OCSP Stapling |
| `echo | openssl s_client -connect <host>:443 -reconnect 5 \| grep "Reused"` | Проверка session resumption |
| `certbot renew --force-renewal --post-hook "systemctl reload nginx"` | Принудительное обновление с перезагрузкой Nginx |
| `systemctl list-timers \| grep certbot` | Проверка таймера автоматического обновления |
| `journalctl -u snap.certbot.renew.service --since "1 hour ago"` | Логи автообновления Certbot |
| `nginx -t` | Проверка синтаксиса Nginx |
| `apachectl configtest` | Проверка синтаксиса Apache |

## Диагностика ошибок

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **DNS error** | DNS-запись не обновилась | Подождать 1–5 минут (учитывая TTL), проверить `dig TXT _acme-challenge.example.com` |
| **404 Not Found** | Неправильный webroot / конфигурация location | Проверить путь, конфигурацию `location` у веб-сервера, права доступа |
| **Rate limit exceeded** | Превышен лимит CA | Прекратить попытки, устранить причину, дождаться сброса. Для тестов использовать staging |
| **Connection refused** | 80 порт закрыт | Открыть 80 порт или использовать DNS-01 |
| **Invalid response** | CA не может получить доступ к проверочному файлу | Проверить файрвол, CDN, WAF; убедиться что запрос `http://example.com/.well-known/acme-challenge/` возвращает 200 |
| **CAA record blocks** | CAA-запись не разрешает выпуск | Добавить `example.com. IN CAA 0 issue "letsencrypt.org"` |
| **OCSP response parse error** | Нестандартное кодирование OCSP (криптография 5.8.0) | Откатиться на certbot 5.7.x или подождать исправления; не влияет на валидность сертификата |

### Методология диагностики

1. **Локализация проблемы:** определите, является ли проблема связанной с DNS, файрволом, конфигурацией веб-сервера или правами доступа.
2. **Проверка доступности:** `curl -I http://example.com/.well-known/acme-challenge/` должен возвращать 200.
3. **Проверка файрвола:** `sudo ufw status` / `sudo firewall-cmd --list-all`.
4. **Проверка конфигурации веб-сервера:** `nginx -t` / `apachectl configtest`.
5. **Проверка логов:** `journalctl -u nginx --since "1 hour ago"` / `sudo tail /var/log/letsencrypt/letsencrypt.log`.

### Диагностические команды

```bash
# Проверка доступности проверочного URL
curl -I http://example.com/.well-known/acme-challenge/test

# Проверка синтаксиса Nginx
sudo nginx -t

# Проверка синтаксиса Apache
sudo apachectl configtest

# Логи Nginx
sudo tail -f /var/log/nginx/error.log

# Логи Certbot
sudo tail -f /var/log/letsencrypt/letsencrypt.log

# Логи systemd
journalctl -u snap.certbot.renew.service --since "1 hour ago"

# Проверка DNS
dig TXT _acme-challenge.example.com

# Проверка порта 80
sudo ss -tlnp | grep ':80'
```

## Рекомендации

### Чеклист SRE/SysAdmin для управления сертификатами

- [ ] **Базовый firewall:** Открыты порты 80 и 443. Проверено `sudo ufw status` / `sudo firewall-cmd --list-all`.
- [ ] **Валидация перед использованием:** Всегда выполняйте `nginx -t` или `apachectl configtest` перед reload.
- [ ] **Тестирование:** Используйте staging (`--staging`) перед боевым запуском. Не повторяйте команду без устранения причины.
- [ ] **Email аккаунта:** Обновите email в `/etc/letsencrypt/renewal/<domain>.conf` для получения уведомлений об отзыве сертификатов.
- [ ] **CAA-запись:** Создайте CAA-запись для ограничения CA, которые могут выпускать сертификаты.
- [ ] **HSTS:** Включите HSTS (`Strict-Transport-Security`) для предотвращения Downgrade-атак.
- [ ] **OCSP Stapling:** Включите OCSP Stapling в веб-сервере для ускорения проверки статуса сертификата.
- [ ] **Резервное копирование:** Автоматическое резервное копирование `/etc/letsencrypt/` перед каждой ротацией.
- [ ] **Мониторинг:** Настройте мониторинг сроков действия сертификатов (за 30, 14 и 7 дней до истечения).
- [ ] **Сеть:** Убедитесь, что нет прокси или CDN, блокирующих доступ к `.well-known/acme-challenge/`.

### Безопасность

* Храните приватные ключи (`privkey.pem`) в секретных менеджерах или с ограниченными правами доступа (`600`).
* Используйте ECDSA (P-256) по умолчанию. RSA (2048/4096) — для совместимости с очень старыми клиентами.
* Ограничьте доступ к `/etc/letsencrypt/` только root-пользователем.
* Включите уведомления Let's Encrypt о проблемах с сертификатом через email.
* Для внутренних сервисов рассмотрите Private CA (HashiCorp Vault, step-ca) вместо публичных CA.
* Создайте CAA-запись для ограничения CA, которые могут выпускать сертификаты.
* Включите HSTS (`Strict-Transport-Security`) для предотвращения Downgrade-атак.
* Включите OCSP Stapling в веб-сервере.

### Операционная поддержка

**Валидация после изменений:**

```bash
# 1. Проверка синтаксиса
sudo nginx -t

# 2. Применение
sudo systemctl reload nginx

# 3. Логи
sudo journalctl -u nginx --since "1 minute ago"

# 4. Метрики TLS
echo | openssl s_client -connect example.com:443 -servername example.com -status 2>&1 | \
  grep -E "Protocol|Cipher|OCSP"
```

**Откат изменений:**

```bash
# Если reload вызвал проблемы
git checkout /etc/nginx/conf.d/example.com.conf  # или восстановите из бэкапа
sudo systemctl reload nginx
```

**Резервное копирование:**

```bash
# Резервное копирование конфигурации
sudo tar czf /backup/nginx-vhosts-$(date +%F).tar.gz /etc/nginx/conf.d/

# Резервное копирование сертификатов
sudo tar czf /backup/letsencrypt-$(date +%F).tar.gz /etc/letsencrypt/
```

**Восстановление из резервной копии:**

```bash
sudo tar xzf /backup/letsencrypt-2026-09-24.tar.gz -C /
sudo systemctl reload nginx
```

### Wildcard-сертификаты

**Wildcard-сертификат** (`*.example.com`) защищает основной домен и все поддомены первого уровня. Certbot поддерживает wildcard только через DNS-01, что требует API DNS-провайдера. Для wildcard рекомендуется **[acme.sh](./acme_sh.md)** с поддержкой 110+ DNS API.

### Сравнение с альтернативами

* **acme.sh** — легковесный ACME-клиент на bash. Детали: [acme.sh — ACME-клиент для TLS-сертификатов](./acme_sh.md).
* **Angie** — веб-сервер со встроенным ACME-модулем. Детали: [Автоматические TLS-сертификаты в Angie: модуль ACME](../Angie/angie_acme_module.md).
* **Traefik** — reverse proxy с автоматическим Let's Encrypt. Детали: [Traefik — ACME и автоматические сертификаты](../Traefik/traefik_overview.md).

## Дополнительная информация

**См. также:**
* [acme.sh — ACME-клиент для TLS-сертификатов](./acme_sh.md) — легковесная альтернатива Certbot
* [Автоматические TLS-сертификаты в Angie: модуль ACME](../Angie/angie_acme_module.md) — встроенный ACME без внешних утилит
* [Настройка TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md) — оптимальная конфигурация TLS

**Официальные ресурсы:**
* [Официальный сайт Let's Encrypt](https://letsencrypt.org)
* [Официальный сайт Certbot](https://certbot.eff.org)
* [Документация ACME (RFC 8555)](https://datatracker.ietf.org/doc/rfc8555/)
* [Staging Environment](https://letsencrypt.org/docs/staging-environment/)
* [Официальный репозиторий Certbot](https://github.com/certbot/certbot)
