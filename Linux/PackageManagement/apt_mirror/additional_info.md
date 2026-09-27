# Зеркалирование APT: Дополнительная информация

## Определения

Определения терминов приведены в документе **[Определения](./definitions.md)**. Система APT используется для управления пакетами в Debian и Ubuntu.

---

## Основные концепции

Обзор архитектуры и принципов работы доступен в файле **[Основные понятия](./basic_concepts.md)**.

---

## Практические сценарии

Пошаговые инструкции по настройке зеркала приведены в файле **[Практические сценарии](./practical_scenarios.md)**.

---

## Дополнительная информация

### Расчёт ресурсов и планирование

#### Дисковое пространство
Объём данных зависит от количества поддерживаемых релизов, архитектур и компонентов.

| Дистрибутив | Полное зеркало (x1 релиз) | Частичное (main only) |
| :--- | :--- | :--- |
| **Ubuntu 24.04** | ~300 GB | ~80 GB |
| **Ubuntu 22.04** | ~220 GB | ~60 GB |
| **Debian 12** | ~450 GB | ~90 GB |

**Рекомендации:**
- **Файловая система**: Используйте XFS или Ext4. При эксплуатации `aptly` критически важно следить за количеством инод (inodes), так как база данных и пул создают миллионы мелких файлов и жестких ссылок.
- **Разделение данных**: Выносите директории `/var/spool/aptly` или `/var/spool/apt-mirror` на отдельные логические тома (LVM) для предотвращения остановки системных сервисов при заполнении диска.

#### Сетевые настройки и прокси
Если сервер зеркалирования находится за корпоративным прокси-сервером:

- **Для apt-mirror**: Добавьте в `mirror.list`:
  ```bash
  set http_proxy http://proxy.example.com:3128
  set proxy_user username
  set proxy_password password
  ```
- **Для aptly**: Используйте стандартные переменные окружения:
  ```bash
  export http_proxy=http://proxy.example.com:3128
  aptly mirror update <mirror-name>
  ```

### Оптимизация и обслуживание

#### Оптимизация aptly
- **Использование S3**: `aptly` поддерживает хранение пула пакетов в объектных хранилищах (AWS S3, Ceph RGW), что решает проблему нехватки инод и масштабирования диска.
- **Очистка базы (Cleanup)**: Регулярно запускайте `aptly db cleanup`. Это удаляет неиспользуемые пакеты из пула, которые больше не привязаны ни к одному снимку или зеркалу.
- **Snapshot-менеджмент**: Не храните более 3–5 снимков для одного релиза (Stable, Testing, Previous). Большое количество снимков замедляет работу БД.

#### Оптимизация apt-mirror
- **Многопоточность**: Опция `set nthreads 20` позволяет значительно ускорить первичную синхронизацию.
- **Bandwidth Limit**: Для предотвращения утилизации всего канала используйте `set bandwidth_limit 10m`.

### Мониторинг и логирование

#### Мониторинг целостности
Для отслеживания состояния зеркала рекомендуется использовать связку **Prometheus + Node Exporter** с механизмом `Textfile Collector`.

Пример скрипта для генерации метрик:
```bash
#!/bin/bash
# Путь к файлу Release актуального дистрибутива
RELEASE_FILE="/var/www/html/ubuntu/dists/noble/Release"
AGE=$(stat -c %Y "$RELEASE_FILE")
SIZE=$(du -sb /var/spool/aptly | cut -f1)

echo "apt_mirror_last_update_timestamp $AGE" > /var/lib/node_exporter/apt_mirror.prom
echo "apt_mirror_size_bytes $SIZE" >> /var/lib/node_exporter/apt_mirror.prom
```

#### Управление логами
Синхронизация может генерировать большой объем логов. Настройте `logrotate` (`/etc/logrotate.d/apt-mirror`):
```text
/var/log/apt-mirror.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
```

### Решение типичных проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Hash Sum mismatch** | Индексы в upstream обновились в процессе скачивания. | Запустить синхронизацию повторно. В `aptly` использовать `-force-update`. |
| **GPG: NO_PUBKEY** | Отсутствует ключ подписи в системе клиента. | Импортировать ключ: `gpg --no-default-keyring --keyring /usr/share/keyrings/mirror.gpg --import key.asc`. |
| **DB is locked** | Другой процесс aptly упал, не сняв блокировку. | Убедиться, что процессы aptly не запущены, и удалить `~/.aptly/db/LOCK`. |
| **Slow apt update** | Слишком много PDiffs (дельта-патчей). | На клиенте: `Acquire::PDiffs "false";` в `/etc/apt/apt.conf.d/99custom`. |

### Безопасность раздачи пакетов

Зеркало обычно раздаётся через Nginx или Apache. Безопасность веб-сервера — обязательный элемент, так как репозиторий может стать точкой компрометации целой инфраструктуры.

#### Ограничение доступа на сетевом уровне
```bash
iptables -A INPUT -p tcp --dport 443 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j DROP
```

В Nginx используйте директивы `allow/deny`:
```nginx
location /ubuntu {
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    deny all;
}
```

#### Жёсткая конфигурация HTTPS
```nginx
server {
    listen 443 ssl http2;
    server_name mirror.internal.local;

    ssl_certificate /etc/ssl/certs/mirror.crt;
    ssl_certificate_key /etc/ssl/private/mirror.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5:!RC4;
    ssl_prefer_server_ciphers on;

    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy no-referrer always;

    root /var/www/html;
    location / {
        autoindex off;
        add_header Cache-Control "public, max-age=3600";
    }
}
```

Если требуется клиентская аутентификация (mTLS):
```nginx
ssl_client_certificate /etc/ssl/certs/mirror-ca.crt;
ssl_verify_client on;
ssl_verify_depth 2;
```

#### Практики обслуживания ключей
- Храните ключи подписи репозитория отдельно от данных (`~/.aptly/` должен быть на отдельном носителе или в шифрованном хранилище).
- Ротация ключа: экспортируйте старый ключ, сгенерируйте новый, переподпишите текущий snapshot, обновите клиентские trust stores.

#### Защита веб-сервера
- Отключите `autoindex` — случайный листинг каталога раскрывает структуру репозитория.
- Запретите выполнение CGI/PHP в корне зеркала.
- Включите логирование доступа: `access_log /var/log/nginx/apt.access.log combined;`.
- Ограничьте методы запроса: `limit_except GET HEAD { deny all; }`.

---

### Хранение и файловые системы

APT-репозиторий состоит из миллионов мелких файлов (`Packages.gz`, `Packages.xz`, `Release`, `InRelease`) и жёстких ссылок в `pool/`. Выбор файловой системы и её настройка напрямую влияют на стабильность зеркала.

#### Квотирование и контроль инодов
```bash
df -i /var/spool/aptly
find /var/spool/aptly/pool -xdev | wc -l
```

Настройте оповещение при >80% использования инодов. Для Ext4/XFS используйте `xfs_quota` или `edquota`.

#### Выбор файловой системы
| Файловая система | Преимущества | Недостатки | Рекомендация |
| :--- | :--- | :--- | :--- |
| **XFS** | Высокая производительность на больших каталогах, стабильность | Ограниченный inlining для мелких файлов | Подходит для больших зеркал (>500GB) |
| **Ext4** | Широкое распространение, простота | Медленнее при миллионах файлов | Подходит для небольших инфраструктур |
| **Btrfs** | Встроенные снапшоты, compression, dedup | Меньшая зрелость в высоконагруженных сценариях | Подходит, если требуется частое бэкапирование на уровне ФС |
| **ZFS** | Надёжность, end-to-end checksumming, снапшоты, replication | Высокое потребление RAM | Подходит для критичных инфраструктур с отдельным резервным пулом |

#### Практика работы с пулом пакетов
- Никогда не изменяйте файлы в `pool/` напрямую. Изменения должны проходить через `aptly` или `apt-mirror`, чтобы сохранить целостность индексов.
- Для инкрементального бэкапа используйте `rsync --link-dest`, чтобы не дублировать неизменённые `.deb`:
```bash
rsync -avz --link-dest=/mnt/backup/aptly-latest /var/spool/aptly /mnt/backup/aptly-$(date +%F)
```
- Перед первым sync проверьте SMART-статус дисков: `smartctl -a /dev/sda`.

---

### Резервное копирование и аварийное восстановление

Помимо базового бэкапа `~/.aptly`, требуется процедура, позволяющая восстановить зеркало на новом сервере за минимальное время.

#### Пошаговый playbook восстановления
```text
1. Диагностика scope
   - Определите, какая часть данных потеряна: весь диск, каталог пула, база данных.
   - Проверьте последний успешный бэкап: ls -ltr /mnt/backup/

2. Развёртывание нового сервера
   - Установите ту же версию ОС и пакетов aptly (или apt-mirror).
   - Восстановите конфигурацию: /etc/aptly.conf, mirror.list, конфиг веб-сервера.

3. Восстановление данных
   - Для ZFS: zfs rollback pool/aptly@pre-update
   - Для rsync: rsync -avz /mnt/backup/aptly-latest/ /var/spool/aptly/
   - Для tar: tar -xzf aptly-backup.tar.gz -C /var/spool/
   - Запустите aptly db recover при повреждении SQLite.

4. Верификация
   - Проверьте целостность базы: aptly db verify.
   - Проверьте количество пакетов: aptly repo show noble-main | grep 'Number of packages'.
   - Запустите smoke-test: apt-get update -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/mirror-test.list.

5. Переключение трафика
   - Обновите DNS или балансировщик на новый сервер.
   - Убедитесь, что клиенты получают HTTP 200.
```

#### Миграция с apt-mirror на aptly
Если существующее зеркало ведётся через `apt-mirror`, но требуется снимки:
1. Остановите `apt-mirror`.
2. Импортируйте существующий `pool/` и индексы в `aptly`:
```bash
aptly repo create noble-main
aptly repo add noble-main /var/spool/apt-mirror/mirror/archive.ubuntu.com/ubuntu/pool/
```
3. Создайте snapshot и опубликуйте.

#### Восстановление после сбоя обновления
Если `aptly mirror update` завершился с ошибкой:
1. Не запускайте повторно без очистки: `aptly db drop-lock` (если нужно).
2. Откатитесь на предыдущий snapshot:
```bash
aptly publish switch noble noble-snap-$(date -d "yesterday" +%F)
```
3. Удалите повреждённый snapshot: `aptly snapshot drop noble-main-broken`.

---

### Продвинутый мониторинг и оповещения

Базовый скрипт метрик дополняется правилами алертинга и внешними проверками.

#### Prometheus Alertmanager правила
```yaml
# /etc/prometheus/rules/apt-mirror.yml
groups:
  - name: apt_mirror
    rules:
      - alert: AptMirrorDataAgeHigh
        expr: time() - apt_mirror_last_update_seconds > 86400
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Данные зеркала устарели ({{ $value | humanizeDuration }})"
          runbook: "https://wiki.internal/runbooks/apt-mirror#data-age"

      - alert: AptMirrorDiskSpaceHigh
        expr: (node_filesystem_avail_bytes{mountpoint="/var/spool/aptly"} / node_filesystem_size_bytes{mountpoint="/var/spool/aptly"}) < 0.15
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "На диске зеркала осталось менее 15% свободного места"

      - alert: AptMirrorInodeExhaustion
        expr: (node_filesystem_files_free{mountpoint="/var/spool/aptly"} / node_filesystem_files{mountpoint="/var/spool/aptly"}) < 0.20
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "На диске зеркала осталось менее 20% свободных инодов"

      - alert: AptMirrorHTTPErrors
        expr: rate(nginx_http_5xx_count[5m]) / rate(nginx_http_requests_total[5m]) > 0.01
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Доля 5xx ответов зеркала превышает 1%"
```

#### Внешние синтетические проверки
Используйте Blackbox Exporter или простой cron-скрипт на удалённом сервере:
```bash
#!/bin/bash
MIRROR="http://mirror.internal/ubuntu/dists/noble/Release"
if ! curl -sfI "$MIRROR" | grep -q "200 OK"; then
    echo "Mirror is down" | mail -s "ALERT: APT Mirror" oncall@internal
fi
```

#### Логирование и трассировка запросов
- Включите `$request_id` в логах Nginx для отслеживания запросов.
- Для долгой синхронизации добавьте в `aptly.conf`:
```json
{
  "log": {
    "level": "info",
    "format": "json"
  }
}
```
- Используйте `journalctl -u aptly-mirror -f` для наблюдения за процессом обновления.

---

### Жизненный цикл и эксплуатационные паттерны

#### Immutable Mirror (Неизменяемое зеркало)
Вместо перезаписи опубликованного каталога создаётся новый snapshot и производится атомарное переключение симлинка:
```bash
aptly snapshot create noble-main-$(date +%F) from mirror noble-main
aptly publish snapshot -distribution="noble" noble-main-$(date +%F) /repo/noble-$(date +%F)
ln -sfn /repo/noble-$(date +%F) /repo/noble
```
Клиенты всегда подключаются к `/repo/noble`. Атомарность `ln -sfn` исключает состояние, когда часть пакетов обновлена, а часть нет.

#### Canary-обновление
Для снижения риска перед полным переходом:
1. Опубликуйте новый snapshot на отдельном пути: `/repo/noble-canary`.
2. Настройте несколько клиентских групп: основная группа остаётся на stable, pilot-группа переключается на canary через `sources.list`.
3. Мониторьте ошибки обновления и установки пакетов в pilot-группе.
4. При отсутствии проблем — переключите основной симлинк.

#### Release Train Management
Для инфраструктур с несколькими релизами:
- **Stable track**: актуальные пакеты `-security` и `-updates`.
- **Testing track**: зеркало `-proposed` или `-backports` для тестирования.
- **Previous track**: предыдущий LTS для серверов, ожидающих апгрейда.

Каждый track должен иметь отдельный snapshot и отдельный каталог публикации. Не смешивайте `-proposed` и `-security` в одном каталоге.

#### Жизненный цикл snapshot
```bash
# Храните не более 7 дневных снапшотов для stable
# Храните 3 снапшота для testing
# Удаляйте старые снапшоты
aptly snapshot drop noble-main-$(date -d "8 days ago" +%F)
aptly db cleanup
```

---

### Автоматизация и CI/CD

#### Systemd Path/Timer вместо Cron
Для автоматической синхронизации используйте `systemd` вместо `cron`, чтобы иметь единый журнал и управление зависимостями:
```ini
# /etc/systemd/system/aptly-sync.timer
[Unit]
Description=Sync apt mirror daily

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=3600

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/aptly-sync.service
[Unit]
Description=Update aptly mirror and publish

[Service]
Type=oneshot
ExecStartPre=/usr/local/bin/aptly-snapshot-pre.sh
ExecStart=/usr/bin/aptly mirror update noble-main
ExecStartPost=/usr/local/bin/aptly-smoke-test.sh
```

#### Pre-update hook (снимок перед обновлением)
```bash
#!/bin/bash
# /usr/local/bin/aptly-snapshot-pre.sh
SNAPNAME="pre-update-$(date +%F)"
aptly snapshot create "$SNAPNAME" from mirror noble-main
# Храните последние 3 снимка
aptly snapshot drop pre-update-$(date -d "4 days ago" +%F) || true
```

#### Post-update smoke test
```bash
#!/bin/bash
# /usr/local/bin/aptly-smoke-test.sh
set -e
# Проверяем, что индекс доступен и содержит пакеты
aptly publish list | grep -q "noble"
# Проверяем целостность Release файла
grep -q 'MD5Sum' /var/www/html/ubuntu/dists/noble/Release
echo "Smoke test passed"
```

#### Ansible-фрагмент
```yaml
- name: Install aptly
  apt:
    name: aptly
    state: present

- name: Deploy aptly config
  copy:
    src: aptly.conf
    dest: /etc/aptly.conf
    mode: "0644"

- name: Create mirror
  command: aptly mirror create noble-main http://archive.ubuntu.com/ubuntu/ noble main restricted universe multiverse
  args:
    creates: /var/spool/aptly/mirrors/noble-main

- name: Deploy systemd timer
  copy:
    src: aptly-sync.service
    dest: /etc/systemd/system/aptly-sync.service
  notify: systemd daemon-reload
```

#### GitOps-паттерн
Используйте вебхук для автоматического запуска обновления после коммита в репозиторий с конфигурацией зеркала:
```bash
#!/bin/bash
# /usr/local/bin/aptly-gitops-webhook.sh
cd /opt/aptly-config
git pull origin main
aptly mirror update noble-main
aptly snapshot create noble-main-$(date +%F) from mirror noble-main
aptly publish switch noble noble-main-$(date +%F)
```

---

### Расширенная диагностика и устранение неисправностей

Используйте последовательную проверку от клиента к upstream, чтобы локализовать проблему.

#### Playbook диагностики
```bash
# 1. Проверка доступности upstream
curl -I http://archive.ubuntu.com/ubuntu/dists/noble/Release

# 2. Проверка локального зеркала
curl -I http://mirror.internal/ubuntu/dists/noble/Release

# 3. Проверка целостности индексов
apt-get clean
rm -rf /var/lib/apt/lists/*
apt-get update -o Acquire::Retries=5 -o Acquire::http::No-Cache=True

# 4. Проверка GPG цепочки
apt-key list
gpg --no-default-keyring --keyring /usr/share/keyrings/ubuntu-archive-keyring.gpg --check-options no-auto-check-trustdb

# 5. Проверка места и инодов
df -h /var/spool/aptly
df -i /var/spool/aptly
```

#### Типичные неочевидные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Hash Sum mismatch при update** | Промежуточный прокси или CDN изменяет контент. | Установите `Acquire::http::Pipeline-Depth "0";` и `Acquire::http::No-Cache "true";`. Проверьте `mtr --tcp --port 80 archive.ubuntu.com`. |
| **404 на Packages.gz** | Архитектура не включена в зеркало. | Проверьте `dpkg --print-architecture` и `dpkg --print-foreign-architectures`. Убедитесь, что архитектура указана в `mirror.list`. |
| **GPG: NO_PUBKEY** | Ключ подписи отсутствует в trust store клиента. | Импортируйте ключ: `apt-key adv --keyserver keyserver.ubuntu.com --recv-keys <KEYID>`. |
| **DB is locked** | Аварийное завершение процесса. | `rm -f ~/.aptly/db/LOCK` после остановки всех процессов aptly. |
| **Slow apt update** | Большое количество PDiffs. | Отключите PDiffs: `Acquire::PDiffs "false";`. |
| **Низкая скорость скачивания** | Ограничение bandwidth на сервере. | Проверьте `set bandwidth_limit` в `mirror.list` или `tc` на сервере. |
| **Ошибка `No space left on device` при обновлении** | Исчерпание инодов, а не диска. | `df -i` покажет проблему. Увеличьте inode ratio при форматировании или очистите старые snapshot. |

#### Проверка после восстановления
```bash
# Верификация базы данных
aptly db verify

# Сравнение количества пакетов с upstream
UPSTREAM_COUNT=$(curl -s http://archive.ubuntu.com/ubuntu/dists/noble/main/binary-amd64/Packages.gz | zgrep -c '^Package:')
LOCAL_COUNT=$(aptly repo show noble-main | grep 'Number of packages' | awk '{print $4}')
if [ "$UPSTREAM_COUNT" -eq "$LOCAL_COUNT" ]; then
    echo "OK"
else
    echo "MISMATCH: upstream=$UPSTREAM_COUNT local=$LOCAL_COUNT"
fi
```

---

## Связанные документы

- **[Приватный APT-репозиторий](../deb_private_apt_repository_reprepro/practical_scenarios.md)** — публикация собственных пакетов.
- **[Apt Pinning](../deb_apt_pinning.md)** — управление приоритетами источников.
- [Nginx: Настройка репозитория](../../../WebServers/Nginx/Scenarios/secure_apt_repository_guide.md) — безопасная раздача пакетов.
- **[Управление пакетами Linux](../linux_package_management_overview.md)** — общие принципы.
