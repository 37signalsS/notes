# WebDAV: Обзор и настройка

---

## Определения

**WebDAV (Web Distributed Authoring and Versioning)** — расширение протокола HTTP, позволяющее клиентам создавать, изменять и перемещать файлы на веб-сервере. Стандарт RFC 4918, построенный поверх HTTP/1.1 с использованием методов PROPFIND, MKCOL, COPY, MOVE, LOCK, UNLOCK.

**PROPFIND** — HTTP-метод для получения свойств файлов и директорий (метаданные, структура каталога). Заменяет LIST для FTP.

**LOCK/UNLOCK** — механизмы предотвращения конфликтов при одновременном редактировании файлов несколькими клиентами (аналог файловых блокировок).

**ETag** — идентификатор версии ресурса, используемый для проверки целостности при обновлении (conditional PUT с `If-Match`).

**RFC 5842 Binding Extensions** — расширение для управления связями (ссылками) между ресурсами, поддерживающее жёсткие и символические ссылки.

---

## Основные концепции

### Архитектура и протокол

WebDAV работает поверх HTTP/HTTPS и использует расширенные HTTP-методы:

| Метод | Назначение | Аналог в FTP |
| :--- | :--- | :--- |
| **GET/PUT** | Чтение/запись файла | RETR/STOR |
| **DELETE** | Удаление файла | DELE |
| **MKCOL** | Создание директории | MKD |
| **COPY/MOVE** | Копирование/перемещение | RNFR/RNTO |
| **PROPFIND** | Запрос метаданных и структуры | LIST/NLST |
| **LOCK/UNLOCK** | Блокировка файла для редактирования | — |

### Преимущества перед FTP

| Характеристика | WebDAV | FTP |
| :--- | :--- | :--- |
| **Порты** | 80/443 (HTTP/HTTPS) | 21 + динамические порты |
| **Шифрование** | Встроено через HTTPS | Требует FTPS (дополнительная настройка) |
| **NAT/Firewall** | Работает без проблем | Проблемы с пассивным режимом |
| **Блокировки** | Встроенные (LOCK/UNLOCK) | Нет стандарта |
| **Метаданные** | PROPFIND (XML) | LIST (текстовый) |
| **Аутентификация** | Basic, Digest,证书, OAuth | Локальная, PAM, LDAP |
| **Веб-клиенты** | Браузеры, облачные хранилища | Специализированные FTP-клиенты |

### Реализации WebDAV-серверов

| Сервер | Тип | Особенности |
| :--- | :--- | :--- |
| **Apache `mod_dav`** | Модуль | Полнофункциональный, поддерживает Locking, Digest auth. Стандарт для Linux. |
| **Nginx** | Модуль | Только проксирование (нет встроенного WebDAV). Требует `nginx-dav-ext-module`. |
| **Rclone** | Клиент/сервер | Монтирование облачных хранилищ (S3, Google Drive) как WebDAV. |
| **Caddy** | Встроенный | Автоматический HTTPS, встроенный WebDAV. |
| **lighttpd** | Модуль | `mod_webdav`, легковесный. |

### Безопасность

1. **Шифрование:** Используйте только HTTPS (TLS 1.2+). Отключите HTTP.
2. **Аутентификация:** Digest auth или клиентские сертификаты (mTLS). Basic auth только через HTTPS.
3. **Авторизация:** Ограничьте методы (`LimitExcept`) и директории через конфигурацию сервера.
4. **Блокировки:** Включите `LockScope` для предотвращения concurrent writes.

---

## Практические сценарии

### 1. Apache mod_dav (Debian/Ubuntu)

#### Установка и базовая настройка

```bash
sudo apt update
sudo apt install apache2 libapache2-mod-dav2 -y
sudo a2enmod dav dav_fs auth_digest
sudo systemctl restart apache2
```

#### Конфигурация WebDAV-директории

```apache
# /etc/apache2/sites-available/webdav.conf
<VirtualHost *:443>
    ServerName webdav.example.com
    
    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/webdav.pem
    SSLCertificateKeyFile /etc/ssl/private/webdav.key
    
    # WebDAV директория
    <Directory /var/www/webdav>
        Dav On
        AuthType Digest
        AuthName "WebDAV"
        AuthDigestProvider file
        AuthUserFile /etc/apache2/webdav.digest
        Require valid-user
        
        # Ограничение методов
        <LimitExcept GET POST OPTIONS>
            Require valid-user
        </LimitExcept>
    </Directory>
    
    # Отключение автоиндекса
    Options -Indexes
</VirtualHost>
```

#### Создание пользователя и директории

```bash
# Создание директории
sudo mkdir -p /var/www/webdav
sudo chown www-data:www-data /var/www/webdav
sudo chmod 755 /var/www/webdav

# Создание Digest-файла пользователей
sudo htdigest -c /etc/apache2/webdav.digest WebDAV admin

# Проверка конфигурации
sudo apachectl configtest
sudo systemctl restart apache2
```

#### Проверка доступности

```bash
# PROPFIND для проверки структуры
curl -u admin:password -X PROPFIND https://webdav.example.com/ \
  -H "Depth: 1" \
  -H "Content-Type: application/xml" \
  -k

# Загрузка файла
curl -u admin:password -T /path/to/file.txt https://webdav.example.com/file.txt -k

# Скачивание файла
curl -u admin:password -o local.txt https://webdav.example.com/file.txt -k
```

### 2. Клиенты для работы с WebDAV

#### Linux (davfs2)

```bash
# Установка
sudo apt install davfs2 -y

# Монтирование
sudo mount -t davfs https://webdav.example.com /mnt/webdav

# Автомонтирование в fstab
# https://webdav.example.com /mnt/webdav davfs user,noauto 0 0
```

#### macOS (встроенный)

```bash
# Finder → Connect to Server (Cmd+K)
# URL: https://webdav.example.com

# Или через командную строку
mount_webdav -s -v webdav https://webdav.example.com /Volumes/webdav
```

#### Windows (встроенный)

```
# Проводник → Этот компьютер → Подключить диск
# URL: https://webdav.example.com

# Или через net use
net use W: https://webdav.example.com /user:admin password
```

#### rclone (универсальный клиент)

```bash
# Установка
sudo apt install rclone -y

# Конфигурация
rclone config
# → new remote → name: webdav → type: webdav
# → url: https://webdav.example.com
# → vendor: other
# → user: admin
# → pass: (encrypted)

# Копирование файлов
rclone copy /local/path webdav:/remote/path
rclone sync /local/path webdav:/remote/path
```

### 3. Интеграция с Nextcloud/ownCloud

Nextcloud и ownCloud предоставляют WebDAV-интерфейс по умолчанию:

```bash
# URL для подключения
https://cloud.example.com/remote.php/dav/files/username/

# Или через rclone
rclone config
# → type: webdav
# → url: https://cloud.example.com/remote.php/dav/files/username/
# → vendor: nextcloud
```

---

## Дополнительная информация

### Диагностика

```bash
# Проверка PROPFIND
curl -v -u user:pass -X PROPFIND https://host/ \
  -H "Depth: 1" \
  -H "Content-Type: application/xml" 2>&1 | grep -E "HTTP|DAV"

# Проверка поддерживаемых методов
curl -I -u user:pass https://host/ 2>&1 | grep -i "Allow"

# Логи Apache
sudo tail -f /var/log/apache2/access.log | grep -E "PROPFIND|MKCOL|LOCK"
sudo tail -f /var/log/apache2/error.log
```

### Частые ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **405 Method Not Allowed** | WebDAV не активирован | Проверьте `Dav On` в конфигурации |
| **401 Unauthorized** | Неверная аутентификация | Проверьте `AuthUserFile` и имя ресурса |
| **403 Forbidden** | Неверные права на директорию | `chown www-data:www-data /var/www/webdav` |
| **LOCK не работает** | Locking не поддерживается | Убедитесь, что `mod_dav` загружен |

### Сравнение WebDAV с альтернативами

| Протокол | Использование | Преимущество |
| :--- | :--- | :--- |
| **WebDAV** | Веб-приложения, облачные хранилища | Работает через HTTP/HTTPS, NAT-friendly |
| **SFTP** | SSH-интеграция | Шифрование по умолчанию, один порт |
| **SMB/CIFS** | Windows-сети | Нативная поддержка Windows |
| **NFS** | Unix/Linux-сети | Высокая производительность |

### Связанные темы

- **[Apache: обзор](../../WebServers/Apache/apache_overview.md)** — настройка веб-сервера
- **[Nginx: reverse proxy](../../WebServers/Nginx/Proxy/nginx_l4_proxying.md)** — проксирование WebDAV
- **[SFTP vs FTPS](./ftp_server_comparison.md)** — сравнение протоколов передачи файлов
