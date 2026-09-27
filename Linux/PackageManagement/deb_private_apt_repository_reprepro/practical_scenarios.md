# Приватный Apt-репозиторий с reprepro: Практические сценарии

## Определения

Ниже приведены термины, непосредственно относящиеся к процессам развертывания и эксплуатации внутренних репозиториев программного обеспечения.

**Публикация пакета** — регламентированный процесс добавления файла формата `.deb` (Debian Package) или `.changes` (Source Package) в структуру репозитория, включающий автоматическую переиндексацию и наложение цифровой подписи GPG.

**GPG-ключ репозитория** — пара ключей (открытый и закрытый), используемая для подписания файлов `Release`. Открытый ключ должен быть распространен на все клиентские машины для проверки подлинности пакетов.

Подробное описание архитектуры и базовых терминов приведено в документе **[Определения и концепции](./definitions_and_concepts.md)**.

---

## Основные концепции

### Типовой рабочий процесс SRE

Жизненный цикл управления репозиторием в промышленной среде включает:

1. **Генерация ключей (Automation-friendly)** — использование неинтерактивных методов (batch mode) для создания ключей в CI/CD.
2. **Конфигурация (Infrastructure as Code)** — хранение файлов `conf/distributions`, `conf/updates` и `conf/incoming` в системе контроля версий.
3. **Наполнение (Ingestion)** — добавление артефактов через `includedeb` (для бинарных пакетов) или автоматизированный импорт через `processincoming`.
4. **Безопасная публикация** — раздача через веб-сервер с обязательным запретом доступа к служебным метаданным (`conf/`, `dbs/`).
5. **Ротация ключей** — плановая замена GPG-ключей при истечении срока действия или компрометации.

### Требования к инфраструктуре

- **Веб-сервер**: Nginx или Apache для раздачи статического контента (Pool и индексы).
- **Энтропия**: В виртуализированных средах или на серверах с ограниченным доступом к аппаратному генератору случайных чисел рекомендуется установить `haveged` или `rng-tools` для предотвращения блокировок при генерации GPG-ключей и подписании индексов.
- **Безопасность**: Файлы в директории `conf/` и база данных `dbs/` содержат чувствительную информацию и должны быть исключены из раздачи веб-сервером.

---

## Предварительные требования

### Аппаратные и программные требования

| Компонент | Требование | Примечание |
| :--- | :--- | :--- |
| **ОС** | Debian 12 (Bookworm), Ubuntu 22.04/24.04 (Jammy/Noble) | Другие дистрибутивы на основе Debian также поддерживаются |
| **Пакеты** | `reprepro` (≥ 5.4), `gnupg` (≥ 2.2), `gnupg-agent`, `curl` | `gnupg2` на Ubuntu 22.04+ |
| **Веб-сервер** | Nginx (≥ 1.18) или Apache 2.4 | Требуется для раздачи статических файлов из `dists/` и `pool/` |
| **Энтропия** | ≥ 1000 бит в `/proc/sys/kernel/random/entropy_avail` | На виртуальных машинах без `haveged` генерация ключей может зависнуть |
| **Файловая система** | ext4 или xfs с поддержкой hardlinks | Не рекомендуется размещать `dbs/` на NFS из-за файловых блокировок BDB |
| **Права доступа** | Отдельный пользователь `reprepro` без shell-доступа | Минимизация поверхности атаки |

### Начальное состояние системы

Перед началом работы убедитесь, что система обновлена и не имеет конфликтующих служб:

```bash
# Обновление индексов и установка зависимостей
sudo apt-get update && sudo apt-get install -y reprepro gnupg2 curl haveged

# Включение и запуск haveged (рекомендуется на виртуальных машинах)
sudo systemctl enable --now haveged

# Проверка энтропии
cat /proc/sys/kernel/random/entropy_avail
# → 3000+ (норма)
```

### Создание dedicated пользователя

```bash
# Создание пользователя без shell-доступа
sudo useradd -r -s /usr/sbin/nologin -m -d /srv/repo reprepro

# Или, если репозиторий уже существует:
sudo chown -R reprepro:reprepro /srv/repo
```

---

## Практические сценарии

### Сценарий 1: Развертывание и базовая настройка

#### 1. Установка и подготовка структуры

```bash
# Установка пакетов
sudo apt-get update && sudo apt-get install -y reprepro gnupg2 curl haveged

# Создание структуры каталогов (отдельный пользователь reprepro)
sudo mkdir -p /srv/repo/{conf,incoming,dists,pool,tmp}
sudo chown -R reprepro:reprepro /srv/repo
sudo chmod 0700 /srv/repo/conf
sudo chmod 0700 /srv/repo/dists
sudo chmod 0755 /srv/repo/pool
sudo chmod 0755 /srv/repo/incoming

# Переключение на пользователя reprepro (опционально, если работаете под root)
sudo -u reprepro -i
cd /srv/repo
```

**Валидация:**
```bash
ls -la /srv/repo/
# → drwx------ conf/  drwx------ dists/  drwxr-xr-x pool/  drwxr-xr-x incoming/
```

**Очистка/откат:**
```bash
# Удаление репозитория
sudo rm -rf /srv/repo
sudo userdel reprepro
```

#### 2. Генерация GPG-ключа (неинтерактивный метод)

Для использования в CI/CD или автоматизированных скриптах подготовьте файл параметров:

```bash
cat > gpg-params << 'EOF'
%echo Generating a basic OpenPGP key
Key-Type: RSA
Key-Length: 4096
Subkey-Type: RSA
Subkey-Length: 4096
Name-Real: Repository Manager
Name-Email: repo@example.com
Expire-Date: 0
%no-ask-passphrase
%no-protection
%commit
%echo done
EOF

gpg --batch --generate-key gpg-params
```

**Параметры:**
- `Key-Type: RSA` — алгоритм RSA (совместим со всеми версиями APT).
- `Key-Length: 4096` — длина ключа. Минимум 4096 бит для новых ключей (NIST recommendation).
- `Expire-Date: 0` — бессрочный ключ. В production рекомендуется устанавливать срок (например, `2y`) и настроить ротацию.
- `%no-ask-passphrase` — отключение парольной фразы для автоматизации. **Не используйте в production без hardware security module (HSM) или gpg-agent с кэшированием.**

Извлечение ID ключа для конфигурации:
```bash
KEY_ID=$(gpg --list-secret-keys --keyid-format LONG | grep 'sec' | awk '{print $2}' | cut -d'/' -f2)
echo $KEY_ID
# → ABCDEF1234567890 (пример)
```

**Валидация:**
```bash
gpg --list-keys --keyid-format LONG $KEY_ID
# → pub   rsa4096/ABCDEF1234567890 2024-01-01 [SC]
# →      Fingerprint = XXXX XXXX XXXX XXXX XXXX  XXXX XXXX XXXX XXXX XXXX
```

**Edge cases:**
- Если генерация зависает — проверьте энтропию (`cat /proc/sys/kernel/random/entropy_avail`). Установите `haveged`.
- На headless серверах без `pinentry` используйте `--pinentry-mode loopback`.

#### 3. Настройка дистрибутивов

Создайте файл `conf/distributions`, описывающий целевые ОС (например, Debian 12 и Ubuntu 24.04):

```bash
cat > conf/distributions << EOF
Origin: CompanyCorp
Label: Internal Repository
Codename: bookworm
Architectures: amd64 arm64 all source
Components: main
Description: Internal tools for Debian 12
SignWith: $KEY_ID

Codename: noble
Architectures: amd64 arm64 all source
Components: main
Description: Internal tools for Ubuntu 24.04
SignWith: $KEY_ID
EOF
```

**Параметры:**
- `Origin` — имя организации, издающей репозиторий. Используется в файле `Release`.
- `Label` — человекочитаемое название.
- `Codename` — кодовое имя дистрибутива (например, `bookworm`, `noble`).
- `Architectures` — список поддерживаемых архитектур. `all` — архитектурно-независимые пакеты (скрипты, документация). `source` — исходные пакеты.
- `Components` — компоненты репозитория (аналог `main`, `contrib`, `non-free` в Debian).
- `SignWith` — fingerprint GPG-ключа для подписи.

**Валидация:**
```bash
reprepro -V check
# → Everything seems to be correct
```

#### 4. Первичная экспорт и проверка индексов

```bash
# Генерация начальных индексов (Packages, Sources, Release)
reprepro export

# Проверка подписи Release файла
gpg --verify dists/bookworm/Release
# → Good signature from "Repository Manager <repo@example.com>"
```

#### 5. Конфигурация Nginx

Пример защищенной конфигурации:

```nginx
server {
    listen 80;
    server_name repo.example.com;
    root /srv/repo;

    # Редирект на HTTPS (если используется TLS)
    # return 301 https://$host$request_uri;

    location / {
        autoindex on; # Разрешить листинг для удобства (опционально)
    }

    # Блокировка доступа к чувствительным данным
    location ~ ^/(conf|dbs) {
        deny all;
        return 404;
    }
}
```

**Валидация:**
```bash
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
sudo systemctl reload nginx

# Проверка доступности
curl -s http://repo.example.com/dists/bookworm/Release | head -n 5
# → Origin: CompanyCorp
# → Label: Internal Repository
# → ...
```

**Лучшие практики:**
- Размещайте репозиторий на отдельном логическом разделе или диске для упрощения мониторинга и бэкапа.
- Используйте HTTPS с валидным сертификатом (или mTLS для внутренних репозиториев — см. **[Nginx: Настройка репозитория](../../../WebServers/Nginx/Scenarios/secure_apt_repository_guide.md)**).
- Настройте `log_format` в Nginx для отслеживания доступа к пакетам.

**Edge cases:**
- Если Nginx возвращает 403 на `pool/` — проверьте права доступа к файлам `.deb`. Пользователь `www-data` должен иметь права на чтение.
- При использовании SELinux добавьте контексты: `semanage fcontext -a -t httpd_sys_content_t "/srv/repo(/.*)?" && restorecon -Rv /srv/repo`.

---

### Сценарий 2: Управление пакетами

#### Добавление пакета вручную

```bash
# Добавление бинарного .deb пакета в дистрибутив noble
reprepro -b /srv/repo includedeb noble /tmp/my-app_1.0_amd64.deb
# → Exporting indices...

# Добавление из файла .changes (включая исходный код)
reprepro -b /srv/repo include noble /tmp/my-app_1.0_amd64.changes
```

**Параметры:**
- `-b /srv/repo` — базовый путь к репозиторию. Рекомендуется всегда указывать явно для автоматизации.
- `includedeb` — добавляет только бинарный пакет (`.deb`).
- `include` — добавляет пакет из `.changes` файла, включая исходный код (`.dsc`, `.tar.*`).

**Валидация:**
```bash
# Проверка наличия пакета в репозитории
reprepro -b /srv/repo list noble | grep my-app
# → noble|main|amd64: my-app 1.0

# Проверка метаданных
reprepro -b /srv/repo list noble main amd64
# → noble|main|amd64: my-app 1.0

# Проверка физического файла в pool/
ls -la /srv/repo/pool/main/m/my-app/
```

#### Удаление пакета

```bash
# Удаление конкретного пакета по имени
reprepro -b /srv/repo remove noble my-app
# → Deleting my-app...

# Принудительное удаление с очисткой пустых каталогов
reprepro -b /srv/repo --delete removable noble my-app
```

**Валидация:**
```bash
reprepro -b /srv/repo list noble | grep my-app
# → (пусто)
```

**Очистка:**
```bash
# Удаление неиспользуемых источников (source packages без бинарников)
reprepro -b /srv/repo --delete unusedsources

# Удаление устаревших файлов из pool/
reprepro -b /srv/repo --delete clean
```

#### Override метаданных пакета

Если требуется изменить секцию, приоритет или источник без пересборки `.deb`:

```bash
# Просмотр текущих метаданных
reprepro -b /srv/repo list noble main amd64

# Изменение секции/приоритета
reprepro -b /srv/repo override my-app 1.0 << EOF
Section: restricted
Priority: optional
EOF
```

Подробнее об override-файлах: **[Дополнительная информация](./advanced_topics.md)**.

#### Листинг и диагностика

```bash
# Просмотр всех пакетов в дистрибутиве
reprepro -b /srv/repo list noble
# → noble|main|amd64: my-app 1.0

# Проверка целостности базы данных и файлов в пуле
reprepro -b /srv/repo verify
```

**Валидация:**
```bash
# Детальный листинг с отладкой
reprepro -V -b /srv/repo list noble main amd64
# → Вывод: версия, архитектура, размер, путь в pool

# Проверка контрольных сумм .deb файлов
find /srv/repo/pool -name '*.deb' -exec dpkg-deb -I {} \;
```

**Edge cases:**
- **Дублирование версий**: `reprepro` по умолчанию отклоняет повторное добавление той же версии. Используйте `--ignore=wrongdist` или удалите старую версию перед добавлением.
- **Несоответствие архитектуры**: Если `.deb` имеет архитектуру `amd64`, а в `conf/distributions` указано только `arm64`, пакет будет отклонен. Проверяйте архитектуру: `dpkg-deb -f package.deb Architecture`.
- **Поврежденный `.changes` файл**: Убедитесь, что `.changes` файл подписан тем же ключом, что и репозиторий.

---

### Сценарий 3: Селективное зеркалирование (Updates)

Механизм `Updates` позволяет импортировать выбранные пакеты из внешних источников во внутренний репозиторий, применяя фильтры по имени, версии или архитектуре. Это снижает нагрузку на внешние зеркала и дает контроль над зависимостями.

#### 1. Создание `conf/updates`

```bash
cat > conf/updates << EOF
Name: upstream-security
Method: http://security.ubuntu.com/ubuntu
VerifyRelease: yes
Suite: noble-security
Components: main
Architectures: amd64 arm64
FilterFormula: Package (== nginx) | Package (== curl) | Package (== openssl)
EOF
```

**Параметры:**
- `Name` — уникальное имя конфигурации обновления.
- `Method` — URL внешнего репозитория.
- `VerifyRelease` — `yes` для проверки GPG-подписи внешнего репозитория (рекомендуется), `no` для отключения (не рекомендуется).
- `Suite` — целевая секция внешнего репозитория (например, `noble-security`).
- `Components` — компоненты для импорта.
- `Architectures` — фильтр архитектур.
- `FilterFormula` — логическое выражение для выбора пакетов. Поддерживает: `Package`, `Version`, `Architecture`.

#### 2. Обновление `conf/distributions`, добавив поле `Update`:

```text
Codename: noble
...
Update: upstream-security
```

#### 3. Запустите синхронизацию:

```bash
reprepro -b /srv/repo update noble
# → Exporting indices...
# → Deleting obsolete files...
```

**Валидация:**
```bash
# Проверка списка импортированных пакетов
reprepro -b /srv/repo list noble | grep -E 'nginx|curl|openssl'
# → noble|main|amd64: nginx 1.24.0-2ubuntu3.1

# Проверка версии и происхождения
reprepro -b /srv/repo list noble main amd64 | grep nginx
# Сравните с версией в upstream: apt-cache policy nginx (на клиенте с доступом к upstream)
```

**Edge cases:**
- **Изменение фильтра**: При изменении `FilterFormula` reprepro не удаляет пакеты, уже добавленные ранее. Для полной пересинхронизации удалите дистрибутив и запустите `update` заново (или используйте `reprepro export` после ручного удаления пакетов).
- **Сетевые таймауты**: При проблемах с сетью добавьте в `/etc/apt/apt.conf.d/99retries`:
  ```conf
  Acquire::http::Timeout "120";
  Acquire::http::Retries "5";
  ```
- **Проверка GPG внешнего репозитория**: Убедитесь, что ключ подписи upstream присутствует в связке ключей:
  ```bash
  gpg --list-keys --keyid-format LONG
  # Должен содержать ключ, указанный в VerifyRelease (или используйте VerifyRelease: yes для автоматической проверки через /usr/share/keyrings)
  ```

---

### Сценарий 4: Автоматизация импорта (Incoming)

Использование директории `incoming/` для автоматического разбора пакетов, загруженных по SSH, SFTP или через общую файловую систему.

#### 1. Настройте `conf/incoming`:

```bash
cat > conf/incoming << EOF
Name: default
IncomingDir: incoming
TempDir: tmp
Allow: noble>main bookworm>main
Cleanup: on_accept
EOF
```

**Параметры:**
- `Name` — уникальное имя конфигурации.
- `IncomingDir` — относительный путь к каталогу приема (относительно базового пути репозитория).
- `TempDir` — каталог для временных файлов во время обработки.
- `Allow` — правила доступа: `дистрибутив>компонент`. Можно указать несколько правил через пробел.
- `Cleanup: on_accept` — удалять файлы из `incoming/` после успешной обработки. Другие значения: `on_failure` (только при ошибке), `never`.

#### 2. Выполните обработку:

```bash
reprepro -b /srv/repo processincoming default
# → Принимает все файлы из incoming/, проверяет подписи, перемещает в pool/
```

**Безопасность:**
- Директория `incoming/` должна быть доступна для записи только доверенным пользователям/сервисам.
- Рекомендуется настроить `PreIncomingHook` для проверки подписи `.changes` файлов перед принятием (см. **[Дополнительная информация](./advanced_topics.md)**).

**Валидация:**
```bash
# Проверка, что пакеты перемещены в pool и проиндексированы
reprepro -b /srv/repo list noble
# → noble|main|amd64: my-app 1.0

# Проверка, что incoming пуст
ls -la /srv/repo/incoming/
# → (должен быть пуст, если Cleanup: on_accept)
```

**Очистка:**
```bash
# Удаление неудачно обработанных файлов
reprepro -b /srv/repo --delete clean
```

**Edge cases:**
- **Отсутствие подписи `.changes`**: `reprepro` требует, чтобы `.changes` файл был подписан. Для тестирования можно использовать `--allow=untrusted` в `conf/incoming` (не рекомендуется для production).
- **Некорректные права доступа**: Если `reprepro` запускается от отдельного пользователя, убедитесь, что он имеет права на запись в `incoming/` и `tmp/`.
- **Одновременная загрузка**: При загрузке нескольких пакетов одновременно используйте файловые блокировки (`flock`) для предотвращения гонок.

---

### Сценарий 5: Настройка клиента (Modern APT)

Современный стандарт (Debian 12+, Ubuntu 22.04+) запрещает использование `apt-key add`. Ключи должны храниться в `/etc/apt/keyrings/` с привязкой к конкретному репозиторию через `signed-by`.

#### 1. Экспорт ключа на сервере

```bash
gpg --export --armor $KEY_ID > /srv/repo/repo-key.pub
```

#### 2. Конфигурация на клиенте

```bash
# 1. Загрузка ключа в доверенное хранилище (keyrings)
sudo curl -fsSL http://repo.example.com/repo-key.pub | gpg --dearmor | \
    sudo tee /etc/apt/keyrings/company-repo.gpg > /dev/null

# 2. Добавление репозитория с привязкой к ключу (signed-by)
echo "deb [signed-by=/etc/apt/keyrings/company-repo.gpg] http://repo.example.com noble main" | \
    sudo tee /etc/apt/sources.list.d/company-repo.list

sudo apt-get update
```

**Параметры:**
- `signed-by=/etc/apt/keyrings/company-repo.gpg` — путь к ключу, которому доверяет APT для этого конкретного репозитория.
- `http://repo.example.com` — URL репозитория. В production используйте HTTPS.

**Валидация:**
```bash
# Проверка источника
apt-cache policy
# → company-repo:
# →   500 http://repo.example.com noble/main amd64 Packages
# →   100 /var/lib/dpkg/status

# Список доступных пакетов из репозитория
apt list | grep company
# → my-app/noble 1.0 amd64

# Проверка подписи индексов
apt-get update 2>&1 | grep -i gpg
# → (должен отсутствовать вывод об ошибках подписи)
```

**Лучшие практики:**
- Используйте HTTPS для передачи пакетов, чтобы предотвратить атаки man-in-the-middle.
- Настройте **Apt Pinning** для управления приоритетом пакетов из внутреннего репозитория (см. **[Apt Pinning](../deb_apt_pinning.md)**).
- Храните ключ репозитория в системе управления секретами (HashiCorp Vault, Ansible Vault) и распространяйте через automation.

**Troubleshooting:**
```bash
# Ошибка GPG: неверный ключ
sudo rm /etc/apt/keyrings/company-repo.gpg
# Повторите загрузку ключа и apt-get update

# Ошибка 404 при apt-get update
curl -I http://repo.example.com/dists/noble/Release
# Проверьте корректность URL и codename в sources.list

# Ошибка "The following signatures were invalid"
# 1. Проверьте время на клиенте: timedatectl status
# 2. Проверьте срок действия ключа на сервере: gpg --list-keys --keyid-format LONG
# 3. Перегенерируйте индексы: reprepro -b /srv/repo export
```

---

### Сценарий 6: Резервное копирование и восстановление

Кратковременное руководство. Полная процедура с инкрементальными бэкапами и восстановлением BDB описана в **[Дополнительная информация](./advanced_topics.md)**.

```bash
REPO_DIR="/srv/repo"
BACKUP_DIR="/mnt/backup/repo"
DATE=$(date +%Y-%m-%d)

# 1. Остановка веб-сервера (опционально, для консистентности)
sudo systemctl stop nginx

# 2. Полное резервное копирование (исключая временные файлы BDB)
tar czf "$BACKUP_DIR/repo-full-$DATE.tar.gz" \
    --exclude='dbs/__db.*' \
    --exclude='incoming' \
    -C "$REPO_DIR" .

# 3. Отдельный бэкап БД
cp -a "$REPO_DIR/dbs" "$BACKUP_DIR/dbs-$DATE"

# 4. Экспорт метаданных для верификации
reprepro -b "$REPO_DIR" dumpdb > "$BACKUP_DIR/dumpdb-$DATE.txt"
reprepro -b "$REPO_DIR" list > "$BACKUP_DIR/list-$DATE.txt"

# 5. Запуск веб-сервера
sudo systemctl start nginx
```

**Восстановление:**
```bash
sudo systemctl stop nginx
rm -rf /srv/repo/dbs
tar xzf "$BACKUP_DIR/repo-full-YYYY-MM-DD.tar.gz" -C /srv/repo/
cp -a "$BACKUP_DIR/dbs-YYYY-MM-DD" /srv/repo/dbs
reprepro -b /srv/repo check
reprepro -b /srv/repo verify
sudo systemctl start nginx
```

**Edge cases:**
- **Активные операции записи**: `reprepro` не требует полной остановки для бэкапа `pool/` и `dists/`, но копирование `dbs/` во время записи может дать несогласованную копию. Остановите записи или используйте `flock` для эксклюзивного доступа.
- **Восстановление после сбоя**: Если `reprepro` завершился с `kill -9`, выполните `reprepro -V check` и `reprepro export` перед восстановлением из бэкапа.

### Сценарий 7: Автоматизация и предотвращение гонок

При интеграции `reprepro` в CI/CD pipeline или скрипты важна эксклюзивность операций.

#### Использование `flock`

```bash
# Блокировка файла на время операции
flock -n /var/lock/reprepro.lock -c "reprepro -b /srv/repo includedeb noble /tmp/package.deb"

# В systemd unit
# Type=oneshot
# ExecStart=/usr/bin/flock -n /var/lock/reprepro.lock /usr/bin/reprepro -b /srv/repo export
```

#### Wrapper-скрипт для аудита

```bash
cat > /usr/local/bin/reprepro-audit.sh << 'EOF'
#!/bin/bash
REPO_PATH="/srv/repo"
USER="${SUDO_USER:-$USER}"
TIMESTAMP=$(date +%Y-%m-%dT%H:%M:%S%z)

echo "$TIMESTAMP user=$USER args=\"$*\"" >> /var/log/reprepro-audit.log

exec /usr/bin/reprepro -b "$REPO_PATH" "$@"
EOF
chmod +x /usr/local/bin/reprepro-audit.sh
```

**Лучшие практики:**
- Используйте `flock` во всех автоматизированных вызовах `reprepro`.
- Настройте `sudoers` для ограничения команд, которые может выполнять CI/CD сервер:
  ```bash
  # /etc/sudoers.d/reprepro-ci
  ci-user ALL=(reprepro) NOPASSWD: /usr/bin/reprepro -b /srv/repo includedeb *
  ci-user ALL=(reprepro) NOPASSWD: /usr/bin/reprepro -b /srv/repo export
  ```
- Ведите лог всех операций для compliance и аудита (см. **[Дополнительная информация](./advanced_topics.md)**).

**Edge cases:**
- **NFS**: Если `dbs/` размещен на NFS, файловые блокировки BDB могут не работать корректно. Размещайте `dbs/` на локальном SSD, а `pool/` синхронизируйте через `rsync`.
- **Параллельные CI джобы**: Гарантируйте, что только один job может опубликовать пакеты в репозиторий одновременно (через `flock` или очередь задач).

---

## Дополнительная информация

### Типовые ошибки и диагностика

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **"Not enough entropy"** | Недостаточно энтропии для генерации ключей GPG | Установите `haveged` (`sudo apt install haveged && sudo systemctl enable --now haveged`). Проверьте: `cat /proc/sys/kernel/random/entropy_avail` → должно быть > 1000. |
| **"Database is locked"** | Параллельный запуск `reprepro` или незавершенная предыдущая операция | Проверьте процессы: `lsof +L1 \| grep reprepro`. Убедитесь, что только одна команда `reprepro` выполняется одновременно. Используйте `flock` в скриптах. |
| **"GPG error: The following signatures were invalid"** | Неверный/истекший ключ, рассинхронизация времени, поврежденные индексы | 1. Проверьте время: `timedatectl status`. 2. Проверьте ключ: `gpg --list-keys --keyid-format LONG`. 3. Перегенерируйте индексы: `reprepro -b /srv/repo export`. 4. Распространите актуальный публичный ключ. |
| **"No such file or directory" при `includedeb`** | Пакет уже существует, или путь указан неверно | Проверьте: `reprepro -b /srv/repo list noble`. Для перезаписи версии удалите старую: `reprepro -b /srv/repo remove noble my-app`. |
| **404 при `apt-get update` на клиенте** | Отсутствует `dists/<codename>/Release` или неверный codename | Проверьте URL: `curl -I http://repo.example.com/dists/noble/Release`. Убедитесь, что codename в `sources.list` совпадает с `conf/distributions`. |
| **"Hash Sum mismatch"** | Несогласованность индексов и пула (обычно после нештатного обновления) | Очистите кэш APT: `sudo apt clean && sudo rm -rf /var/lib/apt/lists/*`. Перегенерируйте индексы на сервере: `reprepro -b /srv/repo export`. |

### Лучшие практики (SRE/Sysadmin)

1. **Инфраструктура как код (IaC)**: Храните `conf/distributions`, `conf/updates`, `conf/incoming` в Git. Разворачивайте через Ansible, Chef или Puppet. Никогда не изменяйте конфигурацию вручную на production-сервере без синхронизации с репозиторием.
2. **Минимальные привилегии**: Запускайте `reprepro` от отдельного пользователя `reprepro` с `nologin` shell. Через `sudoers` разрешайте только необходимые команды.
3. **Резервное копирование**: Делайте бэкап `dbs/` отдельно от `pool/` и `dists/`. Тестируйте восстановление не реже раза в квартал. Храните бэкапы на отдельном физическом носителе.
4. **Мониторинг**: Настройте `systemd` timer или `cron` для периодического запуска `reprepro check` и `reprepro verify`. Интегрируйте с Prometheus/node_exporter (см. **[Дополнительная информация](./advanced_topics.md)**).
5. **Ротация ключей**: Планируйте ротацию GPG-ключей раз в 1–2 года. Используйте иерархическую структуру (master key + subkey) с офлайн-хранением master key.
6. **Логирование**: Ведите аудит всех операций `reprepro` через wrapper-скрипты или hook-скрипты (`PostIncomingHook`, `PostDeleteHook`).
7. **Изоляция сети**: Размещайте репозиторий во внутренней сети. При публичном доступе используйте mTLS (см. **[Nginx: Настройка репозитория](../../../WebServers/Nginx/Scenarios/secure_apt_repository_guide.md)**).
8. **Тестирование**: Все новые пакеты тестируйте в изолированном тестовом репозитории перед публикацией в production.

### Ограничения и edge cases

- **Конкурентный доступ**: `reprepro` не поддерживает параллельные операции с одной базой данных. Все изменения должны быть последовательными. Используйте очереди задач (systemd, RabbitMQ) или файловые блокировки (`flock`).
- **BDB 1.85**: Встроенная Berkeley DB версии 1.85 устарела. В будущих версиях `reprepro` возможен переход на SQLite. При обновлении инструмента проверяйте notes к релизу. **Никогда не удаляйте файлы `__db.*` во время работы `reprepro`**.
- **NFS и сетевые ФС**: Директория `dbs/` не должна размещаться на NFS из-за проблем с файловыми блокировками. Директории `pool/` и `dists/` можно синхронизировать через `rsync` для read-only зеркал.
- **Отсутствие API**: Управление только через CLI. Для автоматизации используйте SSH с ограниченными командами (forced commands) или REST API промежуточного сервиса (например, `aptly` имеет REST API).
- **Хардлинки**: `reprepro` использует hardlinks для дедупликации файлов в `pool/` между дистрибутивами. Файловая система должна поддерживать hardlinks (ext4, xfs, btrfs). На FAT32/NTFS hardlinks не поддерживаются.
- **Исходные коды (Sources)**: При добавлении пакетов через `.changes` убедитесь, что все исходные файлы (`.tar.*`, `.dsc`) присутствуют. В противном случае `repro` выдаст ошибку.

### Очистка и деcommissioning

```bash
# 1. Удаление всех пакетов из дистрибутива
for pkg in $(reprepro -b /srv/repo list noble | awk '{print $3}'); do
    reprepro -b /srv/repo remove noble "$pkg"
done

# 2. Удаление неиспользуемых источников
reprepro -b /srv/repo --delete unusedsources

# 3. Удаление репозитория
sudo rm -rf /srv/repo
sudo rm -f /etc/apt/sources.list.d/company-repo.list
sudo rm -f /etc/apt/keyrings/company-repo.gpg
sudo userdel reprepro
```

### Связанные документы

- **[Определения и концепции](./definitions_and_concepts.md)** — архитектура, структура каталогов и описание файлов конфигурации.
- **[Дополнительная информация](./advanced_topics.md)** — продвинутое управление GPG, обслуживание базы данных, сравнение с аналогами, полные сценарии резервного копирования, миграции, CI/CD, мониторинга и аудита.
- **[Apt Pinning](../deb_apt_pinning.md)** — управление приоритетами для гарантированной установки пакетов из внутреннего репозитория.
- **[Nginx: Настройка репозитория](../../../WebServers/Nginx/Scenarios/secure_apt_repository_guide.md)** — детальный пример конфигурации веб-сервера с mTLS.
- **[GPG и OpenPGP](../../Linux/Security/Tools/gpg_and_openpgp.md)** — общие принципы работы с криптографическими ключами (если существует в вашей базе знаний).
