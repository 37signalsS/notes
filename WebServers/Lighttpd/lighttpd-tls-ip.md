# Настройка TLS для IP-адреса в Lighttpd

---

## Определения

**Lighttpd** — легковесный, высокопроизводительный веб-сервер, оптимизированный для окружений с ограниченными ресурсами.

**TLS для IP-адреса** — метод защиты трафика с использованием легитимного сертификата Let's Encrypt (профиль `shortlived`), выданного напрямую на IPv4 или IPv6-адрес без использования доменного имени.

## Базовые концепции

### Особенности сертификатов для IP (Let's Encrypt 2026)

С 15 января 2026 года Let's Encrypt официально поддерживает выпуск доверенных сертификатов для публичных IP-адресов. Основные характеристики:

*   **Профиль shortlived:** Единственный доступный профиль для IP-адресов. Срок действия сертификата составляет **6 дней**.
*   **Автоматизация:** Требует обязательного использования ACME-клиентов (Certbot, acme.sh) с частым циклом обновления (каждые 3–6 часов).
*   **Валидация:** Используется метод `HTTP-01` (через порт 80) или `TLS-ALPN-01` (через порт 443).
*   **Доверие:** Сертификаты принимаются всеми современными браузерами и ОС без установки дополнительных корневых сертификатов.

### Архитектура TLS в Lighttpd

Lighttpd использует модуль `mod_openssl` (реже `mod_gnutls`) для обработки шифрования. В версии 2026 года рекомендуется:
1.  Использование **TLS 1.3** как приоритетного протокола.
2.  Применение **ECDHE** для обеспечения Perfect Forward Secrecy (PFS).
3.  Обязательная настройка **OCSP Stapling** для ускорения проверки статуса короткоживущих сертификатов.

## Практические сценарии

### Сценарий 1: Базовая настройка сервера и TLS на IP

Этот сценарий описывает процесс развертывания защищенного сайта на «голом» IP-адресе с использованием Lighttpd.

#### 1. Подготовка сервера

Первоначальная настройка ОС (Ubuntu/Debian):

```bash
# Обновление пакетов
sudo apt update && sudo apt upgrade -y

# Синхронизация времени (критично для проверки валидности shortlived сертификатов)
sudo timedatectl set-timezone Europe/Moscow
```

#### 2. Настройка Firewall (UFW)

Защита SSH и открытие веб-портов:

1.  Разрешите SSH и веб-порты:
    ```bash
    sudo ufw allow 22/tcp
    sudo ufw allow 80/tcp
    sudo ufw allow 443/tcp
    sudo ufw enable
    ```

#### 3. Установка веб-сервера и Certbot

```bash
sudo apt install lighttpd -y
sudo snap install --classic certbot
```

#### 4. Получение сертификата для IP

Использование профиля `shortlived` для выпуска доверенного сертификата на IP (замените `<YOUR_IP>` на реальный адрес):

```bash
sudo certbot certonly \
  --preferred-profile shortlived \
  --ip-address <YOUR_IP> \
  --webroot --webroot-path /var/www/html/
```
*Сертификаты сохраняются в: `/etc/letsencrypt/live/<YOUR_IP>/`*

#### 5. Конфигурация Lighttpd для HTTPS (TLS 1.3)

Отредактируйте `/etc/lighttpd/lighttpd.conf`:

```lighttpd
server.modules += ("mod_openssl")

$SERVER["socket"] == ":443" {
    ssl.engine = "enable"
    ssl.pemfile = "/etc/letsencrypt/live/<YOUR_IP>/fullchain.pem"
    ssl.privkey = "/etc/letsencrypt/live/<YOUR_IP>/privkey.pem"
    
    # Настройки безопасности 2026
    ssl.openssl.ssl-conf-cmd = ("MinProtocol" => "TLSv1.2") # Поддержка legacy, TLS 1.3 активен по умолчанию
    ssl.honor-cipher-order = "enable"
    ssl.cipher-list = "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384"
}
```

Перезапуск сервера:
```bash
sudo systemctl restart lighttpd
```

#### 6. Автоматизация обновления (Cron)

Для `shortlived` сертификатов проверка должна быть частой:

```bash
# Добавьте в sudo crontab -e
0 */3 * * * certbot renew --quiet --deploy-hook "systemctl restart lighttpd"
```

### Сценарий 2: Принудительный редирект HTTP -> HTTPS

Настройка автоматического перенаправления всех незащищенных запросов.

В `/etc/lighttpd/lighttpd.conf` добавьте:

```lighttpd
server.modules += ("mod_redirect")

$SERVER["socket"] == ":80" {
    $HTTP["host"] =~ "([0-9a-fA-F.:]+)" {
        url.redirect = ( "^/(.*)" => "https://%1/$1" )
    }
}
```
*Регулярное выражение адаптировано для IPv4 и IPv6.*

### Сценарий 3: Настройка заголовков безопасности (HSTS и защита)

Для усиления защиты добавьте модуль `mod_setenv` и настройте заголовки в блоке порт 443:

```lighttpd
server.modules += ("mod_setenv")

$SERVER["socket"] == ":443" {
    # ... существующие настройки ssl ...
    
    setenv.add-response-header = (
        "Strict-Transport-Security" => "max-age=15768000; includeSubDomains",
        "X-Frame-Options" => "DENY",
        "X-Content-Type-Options" => "nosniff",
        "Referrer-Policy" => "no-referrer"
    )
}
```

## Дополнительная информация

### OCSP Stapling

Для короткоживущих сертификатов (`shortlived`) крайне рекомендуется включить OCSP Stapling, чтобы браузеры не тратили время на запросы к серверам Let's Encrypt:

```lighttpd
ssl.stapling-file = "/etc/letsencrypt/live/<YOUR_IP>/ocsp.der"
```
*Примечание: Требуется предварительная генерация файла ocsp.der через скрипт-хук certbot.*

### IPv6 поддержка

Если сервер имеет IPv6, сертификат можно получить аналогичным образом. В конфиге Lighttpd для IPv6 используется отдельный сокет:

```lighttpd
$SERVER["socket"] == "[::]:443" {
    ssl.engine = "enable"
    # те же настройки, что и для IPv4
}
```

### См. также
*   **[Let's Encrypt и Certbot: общие принципы](../Concepts/https_with_certbot.md)**
*   **[Протокол TLS](../../Networking/Protocols/tls.md)**
*   **[Настройка TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**
*   **[Инфраструктура открытых ключей (PKI)](../../Security/Concepts/pki_overview.md)**

