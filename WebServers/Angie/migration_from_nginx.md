# Миграция с Nginx на Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x / Nginx 1.24.x – 1.28.x

## Определения

*   **Миграция с Nginx на Angie** — регламентированный комплекс инженерных процедур по переводу инфраструктуры обслуживания веб-трафика с веб-сервера Nginx на его форк [Angie](./angie_overview.md), включающий предварительный аудит параметров сборки и модулей, конвертацию каталогов и конфигураций, функциональное тестирование в изоляции, переключение сетевого трафика с нулевым или минимальным временем простоя и пост-миграционную оптимизацию.
*   **Angie** — высокопроизводительный масштабируемый веб-сервер, обратный прокси-сервер (reverse proxy), почтовый прокси и L4/L7-балансировщик нагрузки с открытым исходным кодом. Разработан компанией ООО «Веб-сервер» командой ключевых экс-разработчиков Nginx. Зарегистрирован в Едином реестре российского ПО (запись № 17604).
*   **Drop-in замена (Drop-in Replacement)** — архитектурная совместимость программного обеспечения, при которой Angie может исполнять существующие конфигурационные файлы Nginx без модификации логики маршрутизации, синтаксиса директив и протоколов взаимодействия с бэкендами.
*   **ABI-несовместимость динамических модулей (ABI Incompatibility)** — несовместимость скомпилированных разделяемых библиотек динамических модулей (`.so`) между Nginx и Angie на уровне бинарного интерфейса (Application Binary Interface). Требует обязательной переустановки модулей из репозитория Angie либо их пересборки под заголовки Angie.
*   **Плавное переключение трафика (Graceful Cutover / Zero-Downtime Migration)** — методология перевода сетевых сокетов и клиентских запросов с работающего процесса Nginx на процесс Angie без обрыва активных соединений (in-flight requests) и без отбрасывания пакетов TCP SYN.
*   **Runbook отката (Rollback Plan)** — детерминированный алгоритм экстренного возврата трафика на ранее функционировавший сервис Nginx в случае деградации метрик обслуживания (SLO/SLA) после переключения.
*   **Встроенные модули замещения** — функциональные блоки Angie (`prometheus`, `acme`, `upstream_discovery`, `goto`, `status_zone`), замещающие внешние вспомогательные утилиты Nginx (Certbot, `nginx-prometheus-exporter`, сторонние шаблонизаторы consul-template).
*   **Зоны разделяемой памяти (Shared Memory Zones)** — выделяемые master-процессом сегменты оперативной памяти ядра ОС (`shmget`/`mmap`), доступные всем рабочим процессам (`worker`) для синхронизации метрик, таблиц соединений и кэшей без межпроцессных блокировок.

---

## Базовые концепции и архитектура

### 1. Архитектурная совместимость и отличия файловой иерархии

Веб-сервер Angie спроектирован как drop-in замена Nginx. Внутренняя архитектура событийного цикла (Event Loop на базе `epoll` в Linux) и процессная модель (Master/Worker) идентичны Nginx. Однако пакеты Angie изолированы от Nginx на уровне файловой системы, системных учетных записей и юнитов `systemd`, что исключает конфликты пакетов и позволяет обоим серверам одновременно находиться в операционной системе.

| Параметр / Компонент | Nginx | Angie | Примечания для SRE / Sysadmin |
|---|---|---|---|
| Главный файл конфигурации | `/etc/nginx/nginx.conf` | `/etc/angie/angie.conf` | Angie по умолчанию загружает `angie.conf`. |
| Каталог конфигураций | `/etc/nginx/conf.d/` | `/etc/angie/conf.d/` | Поддерживается директива `include /etc/angie/conf.d/*.conf;`. |
| Системный пользователь/группа | `nginx:nginx` или `www-data:www-data` | `angie:angie` | Требуется корректировка прав на SSL-ключи, кэш и сокеты. |
| Каталог динамических модулей | `/usr/lib/nginx/modules/` | `/usr/lib/angie/modules/` (Debian)<br>`/usr/lib64/angie/modules/` (RHEL) | Модули Nginx несовместимы по ABI. |
| Симлинк на модули | `/etc/nginx/modules` | `/etc/angie/modules` | Указывает на актуальный системный каталог модулей Angie. |
| Исполняемый файл | `/usr/sbin/nginx` | `/usr/sbin/angie` | Параллельный запуск возможен на разных сокетах. |
| Каталог журналов (logs) | `/var/log/nginx/` | `/var/log/angie/` | Ротация настраивается через `/etc/logrotate.d/angie`. |
| Каталог кэша и временных файлов | `/var/cache/nginx/` | `/var/cache/angie/` | Владелец каталога: `angie:angie`. |
| PID-файл мастер-процесса | `/run/nginx.pid` | `/run/angie.pid` | Управляется соответствующим сервисом `systemd`. |
| Служба systemd | `nginx.service` | `angie.service` | Названия сервисов независимы. |
| Корневой каталог документов | `/usr/share/nginx/html/` | `/usr/share/angie/html/` | Страницы стандартных ошибок и заглушки. |

### 2. Динамические модули и ограничения совместимости

*   **Динамические модули (`.so`):** Бинарные модули Nginx **не могут** быть загружены в Angie. При попытке загрузки мастер-процесс Angie завершится с фатальной ошибкой ABI mismatch:
    ```
    angie: [emerg] module "/usr/lib/nginx/modules/ngx_http_geoip2_module.so" is not binary compatible in /etc/angie/angie.conf:1
    ```
    Все необходимые динамические модули (Brotli, GeoIP2, ModSecurity, NJS, Auth LDAP и др.) устанавливаются из репозитория Angie в виде пакетов `angie-module-<name>` либо компилируются с исходными кодами соответствующей версии Angie.
*   **Синтаксис базовых директив:** 100% директив стандартного ядра Nginx (`proxy_pass`, `fastcgi_pass`, `limit_req`, `rewrite`, `ssl_certificate`, `upstream`, `map`) поддерживаются Angie без изменений.
*   **Директива `user`:** В дистрибутивных пакетах Angie по умолчанию задан пользователь `user angie;`. Если в переносимой конфигурации остался `user nginx;`, Angie продолжит работать, только если пользователь `nginx` существует в `/etc/passwd`. Рекомендуется стандартизировать пользователя на `angie`.

### 3. Топологии переключения трафика (Cutover Topologies)

В корпоративных средах применяются четыре архитектурных сценария переключения трафика:

```
Топология A: Локальное переключение сокетов (In-Place Cutover)
[ Клиенты ] ──TCP:80/443──► [ Host ] ──► (Stop Nginx) ──► (Start Angie)
                                             └─ Окно переключения: 100–300 мс

Топология B: Сетевое перенаправление с нулевым простоем (nftables/iptables)
[ Клиенты ] ──TCP:80/443──► [ Host Prerouting ]
                                  │
                       ┌──────────┴──────────┐
                  (до переключения)    (момент cutover)
                       ▼                     ▼
               [ Nginx :80/:443 ]     [ Angie :8080/:8443 ]
                       │                     │
                       └─ Graceful drain ────┘

Топология C: Отказоустойчивый кластер с Keepalived / VRRP
[ Клиенты ] ──VIP (L2/L3)──► [ Node 1 (Master): Nginx ] ──► [ Node 2 (Backup): Angie ]
                                        │                               ▲
                                        └────── Failover VIP ───────────┘

Топология D: Контейнеризированные окружения (Docker / Compose)
[ Reverse Proxy / Traefik / Балансировщик ]
                   │
         ┌─────────┴─────────┐
    (Blue: Nginx)      (Green: Angie) ──► Rolling switch via Docker Compose
```

---

## Практические сценарии

### Предварительный скрипт аудита Nginx (Pre-flight Audit)

Перед изменением инфраструктуры выполните скрипт аудита на сервере Nginx для фиксации версий, модулей, сокетов и структуры конфигураций:

```bash
#!/usr/bin/env bash
# /usr/local/bin/nginx-to-angie-audit.sh
# Скрипт аудита перед миграцией на Angie
set -euo pipefail

echo "=== 1. Проверка версии и параметров сборки Nginx ==="
nginx -V 2>&1

echo -e "\n=== 2. Список динамических модулей (load_module) ==="
grep -rE '^\s*load_module\s+' /etc/nginx/ || echo "Динамические модули не обнаружены в /etc/nginx/"

echo -e "\n=== 3. Проверка активных слушающих сокетов ==="
ss -tulpn | grep -E ':(80|443|8080|8443)\b'

echo -e "\n=== 4. Проверка системного пользователя в конфигурации ==="
grep -rE '^\s*user\s+' /etc/nginx/ || echo "Директива 'user' не переопределена (используется дефолт Nginx)"

echo -e "\n=== 5. Поиск жестко прописанных путей /etc/nginx и /var/log/nginx ==="
grep -rEo '(/etc/nginx|/var/log/nginx|/var/cache/nginx|/run/nginx\.pid)' /etc/nginx/ | sort | uniq -c

echo -e "\n=== 6. Проверка валидности текущей конфигурации Nginx ==="
nginx -t
```

Запуск скрипта и сохранение эталонного слепка:

```bash
sudo bash /usr/local/bin/nginx-to-angie-audit.sh > /root/nginx_pre_migration_state.txt
cat /root/nginx_pre_migration_state.txt | head -n 25
# → === 1. Проверка версии и параметров сборки Nginx ===
# → nginx version: nginx/1.24.0 (Ubuntu)
# → built with OpenSSL 3.0.13 30 Jan 2024
# → TLS SNI support enabled
# → configure arguments: --with-cc-opt=... --with-http_ssl_module --with-http_v2_module
```

---

### Сценарий 1: Пошаговая миграция на Bare-Metal серверах и виртуальных машинах (VM)

Сценарий применим для дистрибутивов Debian/Ubuntu, а также RHEL-совместимых ОС (AlmaLinux, Rocky Linux, РЕД ОС, Astra Linux Special Edition).

#### Этап 1: Подключение репозитория и установка пакетов Angie

1. **Установите репозиторий Angie:**
   Подробный алгоритм для всех ОС описан в руководстве по [установке Angie](./angie_installation.md).

   ```bash
   # Для Debian / Ubuntu:
   sudo apt-get update
   sudo apt-get install -y ca-certificates curl gnupg lsb-release
   sudo mkdir -p /etc/apt/keyrings
   curl -fsSL https://download.angie.software/angie/pubkey.gpg | sudo gpg --dearmor -o /etc/apt/keyrings/angie-archive-keyring.gpg
   echo "deb [signed-by=/etc/apt/keyrings/angie-archive-keyring.gpg] https://download.angie.software/angie/$(lsb_release -is | tr '[:upper:]' '[:lower:]')/ $(lsb_release -cs) main" \
       | sudo tee /etc/apt/sources.list.d/angie.list
   sudo apt-get update
   ```

2. **Установите пакет Angie и необходимые динамические модули:**

   ```bash
   # Установка сервера и популярных аналогов модулей Nginx
   sudo apt-get install -y angie angie-module-brotli angie-module-geoip2
   # → Setting up angie (1.12.0-1~jammy) ...
   ```

3. **Запретите автозапуск сервиса Angie до завершения переноса конфигураций:**
   Пакетный менеджер может попытаться запустить Angie сразу после установки. Поскольку порты 80 и 443 заняты Nginx, сервис Angie завершится ошибкой или перейдет в статус `failed`. Это ожидаемое поведение:

   ```bash
   sudo systemctl status angie --no-pager
   # → Active: failed (Result: exit-code) ... bind() to 0.0.0.0:80 failed (98: Address already in use)

   sudo systemctl stop angie
   sudo systemctl disable angie
   # → Removed /etc/systemd/system/multi-user.target.wants/angie.service.
   ```

#### Этап 2: Перенос и автоматизированная адаптация конфигурации

1. **Создайте резервную копию конфигурации Nginx:**

   ```bash
   sudo cp -r /etc/nginx /root/nginx_backup_$(date +%F)
   ```

2. **Синхронизируйте конфигурационные файлы в `/etc/angie/`:**
   Используйте `rsync`, исключая дефолтный `angie.conf`, созданный установщиком:

   ```bash
   sudo mv /etc/angie/angie.conf /etc/angie/angie.conf.rpmnew_or_orig
   sudo rsync -av --exclude="*.pid" /etc/nginx/ /etc/angie/
   # → sending incremental file list
   # → nginx.conf
   # → conf.d/
   ```

3. **Переименуйте главный конфигурационный файл в `angie.conf`:**

   ```bash
   if [ -f /etc/angie/nginx.conf ]; then
       sudo mv /etc/angie/nginx.conf /etc/angie/angie.conf
   fi
   ```

4. **Массовая автоматическая адаптация путей, PID и логов:**

   ```bash
   # Замена путей конфигураций и директив include
   sudo find /etc/angie/ -type f -name "*.conf" -exec sed -i 's|/etc/nginx|/etc/angie|g' {} +

   # Замена путей журналов доступа и ошибок
   sudo find /etc/angie/ -type f -name "*.conf" -exec sed -i 's|/var/log/nginx|/var/log/angie|g' {} +

   # Замена путей каталогов кэширования
   sudo find /etc/angie/ -type f -name "*.conf" -exec sed -i 's|/var/cache/nginx|/var/cache/angie|g' {} +

   # Замена директивы PID мастер-процесса
   sudo sed -i 's|pid\s\+/run/nginx\.pid;|pid /run/angie.pid;|g' /etc/angie/angie.conf
   sudo sed -i 's|pid\s\+/var/run/nginx\.pid;|pid /run/angie.pid;|g' /etc/angie/angie.conf

   # Замена пользователя на angie (если в конфиге задан user nginx;)
   sudo sed -i 's|^\(\s*user\s\+\)nginx;|\1angie;|g' /etc/angie/angie.conf
   ```

5. **Адаптация директив загрузки динамических модулей (`load_module`):**
   Замените пути к модулям Nginx на пути к модулям Angie:

   ```bash
   # Debian / Ubuntu:
   sudo sed -i 's|/usr/lib/nginx/modules/|/usr/lib/angie/modules/|g' /etc/angie/angie.conf
   # RHEL / AlmaLinux / Rocky:
   sudo sed -i 's|/usr/lib64/nginx/modules/|/usr/lib64/angie/modules/|g' /etc/angie/angie.conf
   # Универсальный вариант с использованием символической ссылки:
   sudo sed -i 's|modules/ngx_|/etc/angie/modules/ngx_|g' /etc/angie/angie.conf
   ```

#### Этап 3: Настройка прав доступа, каталогов и политик безопасности

1. **Создайте необходимые каталоги времени выполнения и назначьте права:**

   ```bash
   sudo mkdir -p /var/log/angie /var/cache/angie/proxy /var/cache/angie/fastcgi /var/cache/angie/client_temp
   sudo chown -R angie:angie /var/log/angie /var/cache/angie
   sudo chmod 750 /var/log/angie /var/cache/angie
   ```

2. **Проверьте права на SSL/TLS сертификаты и ключи:**
   Пользователь `angie` должен иметь право чтения приватных ключей:

   ```bash
   # Проверка доступа к приватному ключу
   sudo -u angie test -r /etc/ssl/private/example.com.key && echo "OK" || echo "ACCESS DENIED"
   # → OK
   ```

3. **Настройка SELinux (для RHEL / AlmaLinux / Rocky / РЕД ОС):**

   ```bash
   # Разрешите веб-серверу сетевые исходящие подключения к апстримам
   sudo setsebool -P httpd_can_network_connect 1

   # Назначьте правильный контекст безопасности для каталогов Angie
   sudo semanage fcontext -a -t httpd_config_t "/etc/angie(/.*)?" || true
   sudo semanage fcontext -a -t httpd_log_t "/var/log/angie(/.*)?" || true
   sudo semanage fcontext -a -t httpd_cache_t "/var/cache/angie(/.*)?" || true
   sudo restorecon -Rv /etc/angie /var/log/angie /var/cache/angie
   ```

#### Этап 4: Верификация и тестирование в изоляции

1. **Выполните синтаксическую проверку конфигурации Angie:**

   ```bash
   sudo angie -t
   # → angie: the configuration file /etc/angie/angie.conf syntax is ok
   # → angie: configuration file /etc/angie/angie.conf test is successful
   ```

2. **Запустите тестовый экземпляр на резервном сокете (Canary Test):**
   Создайте временный виртуальный хост на порту `8080` для проверки передачи заголовков и проксирования:

   ```bash
   cat << 'EOF' | sudo tee /etc/angie/conf.d/00-canary-test.conf
   server {
       listen 127.0.0.1:8080;
       server_name localhost;
       location /healthz {
           return 200 'angie-ok\n';
           add_header Content-Type text/plain;
       }
   }
   EOF

   # Проверка синтаксиса
   sudo angie -t
   # → angie: the configuration file /etc/angie/angie.conf syntax is ok

   # Удалите тестовый конфиг перед финальным переключением
   sudo rm -f /etc/angie/conf.d/00-canary-test.conf
   ```

#### Этап 5: Переключение сервисов (Switchover)

Для серверов без внешней балансировки переключение выполняется последовательной остановкой Nginx и запуском Angie с минимальным временем ожидания:

```bash
# Атомарная команда переключения
sudo systemctl stop nginx && sudo systemctl start angie

# Проверка статуса сервиса Angie
sudo systemctl status angie --no-pager
# → Active: active (running) since Thu 2026-10-15 09:10:00 UTC; 2s ago
# → Main PID: 24512 (angie)
# → Tasks: 5 (limit: 4915)
# → Memory: 14.2M
```

Проверка ответа веб-сервера через `curl`:

```bash
curl -Iv http://127.0.0.1/
# → HTTP/1.1 200 OK
# → Server: angie
# → Connection: keep-alive
```

#### Этап 6: Фиксация автозапуска и миграция logrotate

1. **Включите автозапуск Angie и отключите Nginx:**

   ```bash
   sudo systemctl disable nginx
   sudo systemctl enable angie
   # → Created symlink /etc/systemd/system/multi-user.target.wants/angie.service → /lib/systemd/system/angie.service.
   ```

2. **Настройка ротации журналов в `/etc/logrotate.d/angie`:**
   Убедитесь в наличии конфигурации ротации, посылающей сигнал `USR1` мастер-процессу Angie:

   ```bash
   cat << 'EOF' | sudo tee /etc/logrotate.d/angie
   /var/log/angie/*.log {
       daily
       missingok
       rotate 14
       compress
       delaycompress
       notifempty
       create 0640 angie adm
       sharedscripts
       postrotate
           if [ -f /run/angie.pid ]; then
               kill -USR1 $(cat /run/angie.pid)
           fi
       endscript
   }
   EOF

   # Тестовый прогон logrotate
   sudo logrotate -d /etc/logrotate.d/angie
   # → reading config file /etc/logrotate.d/angie
   # → Handling 1 logs
   ```

---

### Сценарий 2: Переключение без простоя (Zero-Downtime Cutover) через локальный пакетный фильтр

В критических системах, где недопустима даже секундная задержка на освобождение портов `80`/`443` процессом Nginx, применяется стратегия перенаправления пакетов через `nftables` или `iptables`.

```
Шаг 1: Nginx слушает :80/:443. Angie запускается на портах :8080/:8443.
Шаг 2: Правило PREROUTING REDIRECT атомарно перенаправляет входящие SYN-пакеты в Angie.
Шаг 3: Nginx плавно завершает работу (SIGQUIT), дообслуживая старые сессии.
Шаг 4: Angie перенастраивается на :80/:443, правило REDIRECT удаляется.
```

1. **Настройте Angie на работу на альтернативных портах (8080 и 8443):**

   ```bash
   sudo sed -i 's/listen 80\b/listen 8080/g' /etc/angie/conf.d/*.conf /etc/angie/angie.conf
   sudo sed -i 's/listen 443\b/listen 8443/g' /etc/angie/conf.d/*.conf /etc/angie/angie.conf
   sudo angie -t
   sudo systemctl start angie
   ```

2. **Проверьте параллельную работу обоих серверов:**

   ```bash
   sudo ss -tulpn | grep -E ':(80|443|8080|8443)\b'
   # → tcp LISTEN 0 511 0.0.0.0:80   0.0.0.0:* users:(("nginx",pid=1200,...))
   # → tcp LISTEN 0 511 0.0.0.0:443  0.0.0.0:* users:(("nginx",pid=1200,...))
   # → tcp LISTEN 0 511 0.0.0.0:8080 0.0.0.0:* users:(("angie",pid=2500,...))
   # → tcp LISTEN 0 511 0.0.0.0:8443 0.0.0.0:* users:(("angie",pid=2500,...))
   ```

3. **Атомарно перенаправьте трафик на Angie с помощью `iptables`:**

   ```bash
   sudo iptables -t nat -A PREROUTING -p tcp -m tcp --dport 80 -j REDIRECT --to-ports 8080
   sudo iptables -t nat -A PREROUTING -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 8443
   ```
   *Результат:* Все новые TCP-сессии мгновенно принимает Angie. Старые соединения, открытые до применения правила, штатно дорабатывают в Nginx.

4. **Инициируйте graceful shutdown Nginx:**

   ```bash
   # Отправка сигнала QUIT для плавного завершения Nginx
   sudo nginx -s quit
   # Ожидание завершения воркеров Nginx
   while pgrep -x nginx >/dev/null; do sleep 0.5; done
   echo "Nginx graceful shutdown completed"
   # → Nginx graceful shutdown completed
   ```

5. **Верните Angie на штатные порты 80/443 и удалите правила перенаправления:**

   ```bash
   # Возврат конфигурации портов
   sudo sed -i 's/listen 8080\b/listen 80/g' /etc/angie/conf.d/*.conf /etc/angie/angie.conf
   sudo sed -i 's/listen 8443\b/listen 443/g' /etc/angie/conf.d/*.conf /etc/angie/angie.conf
   sudo angie -t

   # Плавный перезапуск Angie для захвата портов 80 и 443
   sudo systemctl reload angie

   # Удаление правил перенаправления
   sudo iptables -t nat -D PREROUTING -p tcp -m tcp --dport 80 -j REDIRECT --to-ports 8080
   sudo iptables -t nat -D PREROUTING -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 8443
   ```

---

### Сценарий 3: Роллинг-миграция в отказоустойчивом кластере с Keepalived

Для кластера из двух узлов (`node1` и `node2`), объединенных виртуальным IP-адресом (VIP) через Keepalived (подробнее: [Отказоустойчивость Angie с Keepalived](./angie_ha_with_keepalived.md)), миграция осуществляется поочередно.

```
Исходное состояние:
- Node 1 (Master, VIP активен): Nginx
- Node 2 (Backup): Nginx

Шаг 1: Миграция Node 2 на Angie в пассивном режиме.
Шаг 2: Тестирование Node 2 локально по реальному IP.
Шаг 3: Перевод VIP на Node 2 (повышение VRRP-приоритета или остановка Keepalived на Node 1).
Шаг 4: Проверка продакшен-трафика на Node 2 (Angie).
Шаг 5: Миграция Node 1 на Angie.
Шаг 6: Восстановление балансировки кластера.
```

1. **На `node2` (Backup) выполните Сценарий 1:**
   Остановите Nginx, скопируйте и адаптируйте конфигурацию, запустите Angie.
   Поскольку VIP удерживается `node1`, `node2` не обслуживает клиентский трафик.

2. **Проверьте работоспособность `node2` напрямую по физическому IP:**

   ```bash
   curl -Iv --resolve example.com:443:192.168.1.12 https://example.com/healthz
   # → HTTP/2 200
   # → server: angie
   ```

3. **Адаптируйте healthcheck-скрипт Keepalived на `node2`:**
   Замените проверку процесса Nginx на проверку Angie в `/etc/keepalived/keepalived.conf`:

   ```ini
   vrrp_script check_web {
       script "/usr/bin/killall -0 angie"
       interval 2
       weight 2
   }
   ```
   Перезагрузите Keepalived: `sudo systemctl reload keepalived`.

4. **Выполните контролируемый failover VIP на `node2`:**
   На `node1` временно понизьте приоритет или остановите сервис веб-сервера:

   ```bash
   # На node1:
   sudo systemctl stop nginx
   ```
   Keepalived на `node2` переведет статус в `MASTER` и перехватит VIP.

5. **Проверьте трафик через VIP:**

   ```bash
   curl -Iv https://192.168.1.10/
   # → Server: angie
   ```

6. **Мигрируйте `node1` на Angie** аналогично Сценарию 1, обновите healthcheck в Keepalived и запустите Angie.

---

### Сценарий 4: Миграция в Docker и Docker Compose

Для контейнеризированной инфраструктуры процесс миграции заключается в замене базового образа, обновлении путей монтирования volumes и интеграции внутренних проверок здоровья (Healthchecks).

#### 1. Структура каталогов проекта

```
project/
├── docker-compose.yml
├── angie/
│   ├── angie.conf
│   └── conf.d/
│       └── app.conf
└── certs/
```

#### 2. Обновление `docker-compose.yml`

Замените образ `nginx:alpine` на официальный образ Angie из реестра `docker.angie.software`:

```yaml
services:
  web:
    image: docker.angie.software/angie:1.12-alpine
    container_name: production_web
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      # Порт HTTP/3 (QUIC)
      - "443:443/udp"
    volumes:
      # Монтирование каталога конфигурации Angie
      - ./angie:/etc/angie:ro
      # Каталог журналов
      - angie_logs:/var/log/angie
      # SSL-сертификаты
      - ./certs:/etc/ssl/certs:ro
    environment:
      - TZ=Europe/Moscow
    healthcheck:
      test: ["CMD-SHELL", "angie -t && wget -qO- http://127.0.0.1/healthz || exit 1"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s
    networks:
      - internal_net

volumes:
  angie_logs:

networks:
  internal_net:
    driver: bridge
```

#### 3. Адаптация конфигурации внутри `./angie/angie.conf`

```nginx
user angie;
worker_processes auto;
worker_rlimit_nofile 65535;

error_log /var/log/angie/error.log warn;
pid /run/angie.pid;

events {
    worker_connections 8192;
    use epoll;
    multi_accept on;
}

http {
    include /etc/angie/mime.types;
    default_type application/octet-stream;

    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';

    access_log /var/log/angie/access.log main;

    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;

    include /etc/angie/conf.d/*.conf;
}
```

#### 4. Бесшовное развертывание контейнера

```bash
# Предварительная загрузка нового образа
docker compose pull web
# → 1.12-alpine: Pulling from angie
# → Digest: sha256:...
# → Status: Downloaded newer image for docker.angie.software/angie:1.12-alpine

# Пересоздание контейнера с минимальным downtime
docker compose up -d --no-deps --build web
# → Recreating production_web ... done

# Проверка логов контейнера
docker compose logs --tail=20 web
# → 2026/10/15 09:15:00 [notice] 1#1: using the "epoll" event method
# → 2026/10/15 09:15:00 [notice] 1#1: angie/1.12.0
# → 2026/10/15 09:15:00 [notice] 1#1: start worker processes
```

---

### Сценарий 5: Пост-миграционная оптимизация под возможности Angie 1.12+

После стабилизации базовой миграции рекомендуется вывести из эксплуатации внешние сторонние утилиты и перевести конфигурацию на встроенные возможности Angie.

#### 1. Встроенный модуль ACME (полная замена Certbot и `acme.sh`)

Подробная архитектура описана в руководстве по [модулю ACME в Angie](./angie_acme_module.md).
Замените внешние cron-скрипты нативного демона:

```nginx
http {
    # Объявление ACME-клиента на уровне http
    acme_client letsencrypt_prod {
        server https://acme-v02.api.letsencrypt.org/directory;
        contact mailto:sre-team@example.com;
        challenge http-01;
    }

    server {
        listen 80;
        listen 443 ssl;
        server_name example.com www.example.com;

        # Автоматический заказ, верификация и hot-reload сертификата
        ssl_certificate acme:letsencrypt_prod;

        location / {
            proxy_pass http://backend_pool;
        }
    }
}
```

#### 2. Нативный Prometheus-экспортер (замена `nginx-prometheus-exporter`)

Устраняет необходимость в стороннем Go-демоне `nginx-prometheus-exporter`, который опрашивал `stub_status`:

```nginx
server {
    listen 127.0.0.1:9113;
    server_name localhost;

    location /metrics {
        # Экспорт всех метрик сервера, зон статуса и апстримов
        prometheus all;
        
        # Ограничение доступа к метрикам
        allow 127.0.0.1;
        allow 192.168.1.0/24;
        deny all;
    }
}
```

#### 3. Поддержка HTTP/3 (QUIC)

В отличие от Nginx ранних версий, в Angie стек HTTP/3 стабилен из коробки:

```nginx
server {
    # TCP слушатели
    listen 443 ssl;
    # UDP слушатель для QUIC/HTTP3 с reuseport для параллельной обработки воркерами
    listen 443 quic reuseport;
    
    server_name example.com;

    # Информирование браузеров о доступности HTTP/3
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    ssl_certificate     /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
}
```

#### 4. Замена внутренних перенаправлений с `error_page` на `goto`

Директива `goto` позволяет выполнять прямой безусловный переход в именованный `location` без накладных расходов на генерацию внутреннего HTTP-кода ошибки:

```nginx
# Устаревший паттерн Nginx:
# error_page 404 = @fallback;
# location / { try_files $uri $uri/ =404; }

# Чистая архитектура Angie:
location / {
    try_files $uri @app_fallback;
}

location @app_fallback {
    goto @backend_processor;
}

location @backend_processor {
    proxy_pass http://app_cluster;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

---

## Операции и команды

### Предварительная инвентаризация и аудит

```bash
# 1. Извлечение списка динамических модулей Nginx
nginx -V 2>&1 | tr ' ' '\n' | grep -E '^--add-(dynamic-)?module'

# 2. Поиск директив, требующих адаптации путей
grep -rnE '(/etc/nginx|/var/log/nginx|/var/cache/nginx)' /etc/angie/
# → /etc/angie/conf.d/vhost.conf:12: access_log /var/log/nginx/vhost.access.log;

# 3. Проверка используемых upstream-пулов
grep -rn 'upstream ' /etc/angie/
# → /etc/angie/conf.d/upstreams.conf:1:upstream backend_api {

# 4. Проверка слушающих сокетов перед переключением
sudo ss -tulpn | grep -E ':(80|443)\b'
# → tcp LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=1234,fd=6))
```

### Валидация и сравнение конфигураций

```bash
# Синтаксическая валидация конфигурации Angie с детальным выводом
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка полного дампа конфигурации (включая все include)
sudo angie -T > /root/angie_full_dump.conf
# → Проверка отсутствия ошибок парсинга всех файлов

# Сравнение структуры Nginx и Angie (поиск пропущенных файлов)
diff -u <(find /etc/nginx/ -type f -printf "%P\n" | sort) \
        <(find /etc/angie/ -type f -printf "%P\n" | sort)
```

### Мониторинг в момент переключения

```bash
# Непрерывный мониторинг системных журналов Angie
sudo journalctl -u angie -f --no-tail

# Проверка статуса процессов и потоков
ps aux | grep -E '(nginx|angie)'

# Замер задержек клиентских запросов во время cutover
curl -o /dev/null -s -w 'HTTP: %{http_code} | Total time: %{time_total}s | Server: %{header_json}\n' http://127.0.0.1/
```

### Runbook экстренного отката (Emergency Rollback)

Если после переключения трафика фиксируется рост 5xx ошибок, задержек или сбой взаимодействия с бэкендами, примените регламент отката. Время выполнения: < 10 секунд.

```bash
# 1. Экстренная остановка Angie и старт Nginx
sudo systemctl stop angie && sudo systemctl start nginx

# 2. Возврат автозагрузки в systemd
sudo systemctl disable angie
sudo systemctl enable nginx

# 3. Верификация восстановления обслуживания
sudo systemctl status nginx --no-pager
# → Active: active (running) ...

curl -Iv http://127.0.0.1/
# → HTTP/1.1 200 OK
# → Server: nginx

# 4. Анализ причин сбоя по журналам ошибок Angie
sudo tail -n 100 /var/log/angie/error.log
```

---

## Устранение неисправностей

### 1. Ошибка привязки портов: `Address already in use`

*   **Симптом:** При попытке запуска Angie команда `systemctl status angie` сообщает:
    ```
    angie: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)
    angie: [emerg] bind() to 0.0.0.0:443 failed (98: Address already in use)
    ```
*   **Причина:** Порты `80` и `443` удерживаются работающим процессом Nginx, HAProxy или другим веб-демоном.
*   **Решение:**
    ```bash
    # 1. Определите процесс, занимающий сокет
    sudo ss -tulpn | grep -E ':(80|443)\b'
    # → tcp LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=1204,fd=7))

    # 2. Остановите конфликтующий Nginx
    sudo systemctl stop nginx

    # 3. Запустите Angie
    sudo systemctl start angie
    ```

### 2. Ошибка ABI модулей: `is not binary compatible`

*   **Симптом:**
    ```
    angie: [emerg] module "/usr/lib/nginx/modules/ngx_http_brotli_filter_module.so" is not binary compatible in /etc/angie/angie.conf:4
    ```
*   **Причина:** В конфигурации `angie.conf` осталась директива `load_module`, указывающая на бинарный модуль, собранный под Nginx.
*   **Решение:**
    1. Установите модуль для Angie:
       ```bash
       sudo apt-get install -y angie-module-brotli
       ```
    2. Измените путь в `angie.conf`:
       ```nginx
       load_module modules/ngx_http_brotli_filter_module.so;
       load_module modules/ngx_http_brotli_static_module.so;
       ```

### 3. Ошибки прав доступа: `Permission denied` к сертификатам или кэшу

*   **Симптом:**
    ```
    angie: [emerg] cannot load certificate key "/etc/ssl/private/app.key": BIO_new_file() failed (SSL: error:0200100D:system library:fopen:Permission denied)
    [crit] 25012#25012: *1 open() "/var/cache/angie/proxy/..." failed (13: Permission denied)
    ```
*   **Причина:** Рабочие процессы Angie запущены от имени системного пользователя `angie`, в то время как файлы ключей принадлежат `root:ssl-cert` или пользователю `nginx`, а каталоги кэша — `nginx:nginx`.
*   **Решение:**
    ```bash
    # Добавление пользователя angie в доверенную группу чтения сертификатов
    sudo usermod -aG ssl-cert angie || true

    # Исправление владельцев каталогов логов и кэшей
    sudo chown -R angie:angie /var/log/angie /var/cache/angie
    sudo chmod -R 750 /var/cache/angie
    ```

### 4. Блокировки политикой SELinux или Astra Linux ЗПС

*   **Симптом:** Angie возвращает клиенту ошибку `502 Bad Gateway`, при этом в системном аудите фиксируются отказы.
*   **Причина:** Подсистема SELinux запрещает непривилегированному веб-демону открывать сетевые TCP-соединения к локальным или внешним портам апстримов.
*   **Диагностика и решение:**
    ```bash
    # Поиск событий блокировки SELinux
    sudo ausearch -m avc -ts recent | grep angie
    # → type=AVC msg=audit(...): avc: denied { name_connect } for pid=2512 comm="angie" dest=8080 scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:http_port_t:s0 tclass=tcp_socket permissive=0

    # Разрешение исходящих соединений веб-сервера
    sudo setsebool -P httpd_can_network_connect 1

    # В Astra Linux Special Edition при включенном режиме ЗПС (CSE):
    # Убедитесь, что бинарники и модули Angie имеют валидные цифровые подписи
    sudo bsign -c /usr/sbin/angie
    ```

### 5. Сбои ротации журналов и зависание дескрипторов файлов

*   **Симптом:** Логи продолжают расти в ротированный файл `access.log.1`, а свежий `access.log` остается пустым.
*   **Причина:** Утилита `logrotate` обращается к несуществующему файлу `/run/nginx.pid` или скрипт ротации посылает сигнал старому мастер-процессу.
*   **Решение:**
    Проверьте `/etc/logrotate.d/angie` и убедитесь, что используется сигнал `kill -USR1 $(cat /run/angie.pid)`.

---

## Лучшие практики

### 1. Стратегия снижения рисков (Canary и Staging)

*   **Этапность стендов:** Проводите миграцию в строгой последовательности: `Dev` → `Staging` → `Canary-узел продакшена` → `Full Production`.
*   **Инспекция конфигурации в CI/CD:** Перед деплоем обновленных файлов конфигурации валидируйте их через контейнер с Angie с помощью команды `angie -t`.
*   **Запрет ручных правок:** Все изменения каталогов `/etc/angie/` должны фиксироваться в системе контроля версий (Git) и доставляться средствами автоматизации (Ansible, SaltStack, Puppet).

### 2. Инженерные требования безопасности

*   **Принцип наименьших привилегий:** Мастер-процесс запускается от `root` только для захвата портов 80/443, рабочие процессы обязаны работать от изолированного системного пользователя `angie`.
*   **Защита закрытых ключей:** Права на каталоги с приватными ключами TLS должны быть строго ограничены (`chmod 700 /etc/ssl/private`, `chmod 600 /etc/ssl/private/*.key`).
*   **Изоляция каталогов:** Не допускайте перекрестного монтирования или символических ссылок между `/etc/nginx/` и `/etc/angie/`, чтобы исключить случайное чтение устаревших директив.

### 3. Наблюдаемость и валидация SLO/SLA при переключении

*   **Мониторинг Golden Signals SRE:** До переключения трафика настройте дашборды для отслеживания 4 золотых сигналов:
    *   *Latency (Задержка):* Время ответа бэкендов (`$upstream_response_time`) и время обработки запроса (`$request_time`).
    *   *Traffic (Трафик):* Количество запросов в секунду (RPS).
    *   *Errors (Ошибки):* Доля кодов 4xx и 5xx по отношению к 2xx/3xx.
    *   *Saturation (Насыщение):* Очереди соединений и активные воркеры.
*   **Паритет логирования:** Убедитесь, что формат логов `log_format` в `angie.conf` точно совпадает с форматом Nginx, чтобы сборщики логов (Vector, Fluentbit, Logstash) продолжали парсить поля без сбоев.

### 4. Вывод из эксплуатации (Decommissioning) Nginx

*   **Период стабилизации (Soak Period):** Не удаляйте пакеты и конфигурации Nginx сразу после переключения. Выдержите период стабилизации длительностью от 7 до 14 дней для подтверждения стабильности работы всех сервисов.
*   **Корректный демонтаж:**
    ```bash
    # Окончательное отключение сервиса Nginx
    sudo systemctl stop nginx
    sudo systemctl disable nginx
    sudo systemctl mask nginx

    # Архивация финальной конфигурации Nginx
    sudo tar -czf /root/nginx_final_archive_$(date +%F).tar.gz /etc/nginx

    # Удаление пакетов Nginx (после завершения периода стабилизации)
    # Debian / Ubuntu:
    sudo apt-get purge -y nginx nginx-common nginx-core
    # RHEL / AlmaLinux / Rocky:
    sudo dnf remove -y nginx
    ```

---

## Дополнительная информация

### Ссылки на смежную документацию базы знаний

*   [Обзор веб-сервера Angie](./angie_overview.md) — архитектура процессов, лицензирование и ключевые отличия от Nginx.
*   [Установка Angie](./angie_installation.md) — подключение репозиториев для Enterprise Linux, Astra Linux, Debian и Ubuntu.
*   [Минимальная продакшен-конфигурация Angie](./angie-baseline-config.md) — эталонный каркас базовой конфигурации.
*   [Graceful Reload и Binary Upgrade в Angie](./angie-graceful-reload.md) — управление жизненным циклом и перезагрузка без простоя.
*   [Настройка TLS в Angie](./angie_tls_setup.md) — криптографические протоколы, шифры и конфигурация HTTPS.
*   [Автоматические TLS-сертификаты в Angie (модуль ACME)](./angie_acme_module.md) — отказ от внешнего Certbot в пользу встроенного клиента.
*   [Отказоустойчивость Angie с Keepalived](./angie_ha_with_keepalived.md) — архитектура высокой доступности на базе VIP.
*   [Динамические upstream в Angie](./dynamic_upstreams.md) — механизм dynamic upstreams и интеграция с discovery.
*   [Логирование в Angie](./angie_logging.md) — форматы журналов, ротация и экспорт телеметрии.
*   [Концепции мониторинга Angie](./angie_monitoring/angie_monitoring_concepts.md) — встроенный Status API и телеметрия.
*   [Нативный экспорт метрик в Prometheus](./angie_monitoring/angie_monitoring_prometheus.md) — настройка эндпоинта `/metrics` без сторонних экспортеров.
