# Приватный Apt-репозиторий с reprepro: Дополнительная информация

## Определения

Ниже приведены термины, описывающие расширенные аспекты управления репозиториями, обеспечения их безопасности и альтернативные подходы.

**Управление жизненным циклом GPG-ключей** — регламентированные процессы создания, ротации (продления), отзыва и защиты секретных ключей, используемых для подтверждения целостности репозитория.

**Снапшот (Snapshot)** — фиксированный «снимок» состояния репозитория на определенный момент времени. Позволяет обеспечить воспроизводимость сборок инфраструктуры, фиксируя версии всех пакетов.

**Альтернативы reprepro** — программные инструменты для организации APT-репозиториев (Advanced Package Tool), обладающие специфическими функциями, такими как наличие REST API (Representational State Transfer Application Programming Interface) или встроенная поддержка снапшотов.

**Hook-скрипты (хуки)** — исполняемые файлы, которые `reprepro` вызывает на определённых этапах обработки пакетов (до или после добавления, удаления). Используются для интеграции с CI/CD, отправки уведомлений, запуска дополнительных проверок.

**Override-файлы (конфигурационные переопределения)** — механизм, позволяющий изменить метаданные пакета (приоритет, секцию, источник) без пересборки `.deb`-файла. Реализуется через команду `reprepro override` или файл `conf/override`.

**Целостность репозитория (Repository Integrity)** — гарантия того, что опубликованные пакеты не были изменены после подписи и соответствуют заявленным исходным файлам. Обеспечивается через цепочку: GPG-подпись Release → контрольные суммы в Packages → хеши в pool/.

---

## Основные концепции

### Продвинутое управление GPG

Для обеспечения максимальной безопасности в корпоративной среде рекомендуется использовать иерархическую структуру ключей:

1. **Главный ключ (Master Key)**: Используется только для создания субключей и сертификации. Хранится в офлайн-режиме (на зашифрованном USB или смарт-карте).
2. **Субключ для подписи (Signing Subkey)**: Используется непосредственно `reprepro` для подписания файлов `Release`. Именно этот ключ импортируется на сервер репозитория.
3. **Автоматизация паролей**: При использовании CI/CD секретный ключ часто хранится без парольной фразы (не рекомендуется для Prod) или управляется через `gpg-agent` с предварительно загруженным кэшем паролей.

#### Ротация GPG-ключей

Ротация требуется при:
- Истечении срока действия ключа
- Компрометации секретного ключа
- Смене ответственного лица или политики безопасности

**Процедура ротации (без прерывания работы репозитория):**

```bash
# 1. Генерация нового субключа на офлайн-машине
gpg --edit-key $OLD_KEY_ID
gpg> addkey
# Выберите тип: RSA (sign only), 4096 бит, срок действия по необходимости
gpg> save

# 2. Распространение нового публичного ключа
gpg --armor --export $NEW_KEY_ID > repo-key-new.pub
# Распространите repo-key-new.pub на все клиентские машины

# 3. Переключение reprepro на новый ключ
# В conf/distributions замените SignWith на новый fingerprint
sed -i 's/SignWith: .*/SignWith: $NEW_KEY_ID/' conf/distributions

# 4. Перегенерация индексов (подписываются новым ключом)
reprepro export

# 5. Обновление публичного ключа на сервере
gpg --armor --export $NEW_KEY_ID > /var/www/repo/repo-key.pub

# 6. Отзыв старого ключа (после распространения нового)
gpg --edit-key $OLD_KEY_ID
gpg> revkey
gpg> save
gpg --armor --export $OLD_KEY_ID > repo-key-revoked.asc
```

**Важно:** transitional период должен обеспечивать overlap подписи, чтобы клиенты успели обновить ключ. Храните старый ключ действительным минимум 2 недели после распространения нового.

#### Отзыв и компрометация ключей

При компрометации секретного ключа:
```bash
# 1. Немедленный отзыв (на любой машине с доступом к секретному ключу)
gpg --edit-key $COMPROMISED_KEY_ID
gpg> revkey
gpg> save

# 2. Отправка отзыва на ключевые серверы
gpg --keyserver hkps://keys.openpgp.org --send-keys $COMPROMISED_KEY_ID

# 3. Перегенерация всех индексов с новым ключом
# (см. процедуру ротации выше)

# 4. Уведомление всех команд о замене ключа
```

#### Хранение секретных ключей

**Рекомендуемые методы:**
- **Offline master key**: Главный ключ хранится на аппаратном токене (YubiKey) или зашифрованном носителе, не подключенном к сети.
- **HSM (Hardware Security Module)**: Для критически важных репозиторий используйте HSM или smartcard через `gpg-agent` с `pcscd`.
- **Многоподпись (M-of-N)**: Для enterprise-среды используйте схему, где для подписи Release требуется несколько ключей.

```bash
# Пример настройки gpg-agent для использования YubiKey
cat > ~/.gnupg/gpg-agent.conf << 'EOF'
pinentry-program /usr/bin/pinentry-curses
default-cache-ttl 600
max-cache-ttl 7200
allow-loopback-pinentry
EOF
gpg-connect-agent reloadagent /bye
```

---

### Внутреннее устройство Berkeley DB

`reprepro` использует Berkeley DB (BDB) версии 1.85 для хранения состояния репозитория. Это критически важно понимать при резервном копировании и восстановлении.

#### Структура базы данных

Директория `dbs/` содержит файлы состояния:
```text
dbs/
├── packages.db          # Основная информация о пакетах
├── contents.db          # Индексы содержимого (для apt-file)
├── references.db        # Ссылки между дистрибутивами
└── __db.*               # Временные и журнальные файлы BDB
```

**Важно:** Файлы `__db.*` — это внутренние структуры BDB. Их удаление при активном `reprepro` приведёт к повреждению базы. Никогда не удаляйте их вручную во время работы.

#### Блокировки и конкурентный доступ

`reprepro` использует файловые блокировки для предотвращения повреждения БД при одновременном доступе:

```bash
# Проверка блокировок
lsof +L1 | grep reprepro
# или
fuser -v /path/to/repo/dbs/packages.db
```

**Правило:** Никогда не запускайте две команды `reprepro` параллельно. Для автоматизации используйте:
- Очереди задач (systemd с `Type=oneshot` и `After=`)
- Файловые блокировки в скриптах (`flock -n /var/lock/reprepro.lock`)

```bash
# Пример безопасного запуска через flock
flock -n /var/lock/reprepro.lock -c "reprepro -b /srv/repo includedeb noble /tmp/package.deb"
```

#### Восстановление BDB после сбоев

При нештатном завершении `reprepro` (отключение питания, `kill -9`) база может остаться в несогласованном состоянии.

```bash
# 1. Проверка целостности БД
cd /srv/repo
reprepro -V check
# → Everything seems to be correct
# или ошибки повреждения

# 2. Восстановление из резервной копии БД
cp -a dbs/ dbs.corrupted
cp -a /backup/repo/dbs/ dbs/

# 3. Если резервной копии нет — попытка восстановления
# reprepro не имеет встроенной команды db recover, но можно:
reprepro export  # Принудительная перегенерация индексов
reprepro dumpdb  # Проверка, что данные читаются

# 4. Полное перестроение (крайняя мера)
# Переместите pool/ и dists/ в безопасное место
# Пересоздайте репозиторий с нуля
mkdir -p conf dbs
cat > conf/distributions << EOF
...
EOF
reprepro export
# Перенесите пакеты обратно через includedeb
```

**Предупреждение:** BDB версии 1.85 устарела. В будущих версиях reprepro возможен переход на SQLite. При обновлении инструмента проверяйте notes к релизу на предмет миграции формата БД.

---

### Hook-скрипты (внешние интеграции)

`reprepro` поддерживает вызов внешних программ через параметры в `conf/distributions`:

| Параметр | Вызывается | Типичное использование |
|----------|-----------|------------------------|
| `PreIncomingHook` | Перед обработкой incoming | Проверка подписи, статический анализ |
| `PostIncomingHook` | После успешного добавления | Уведомление Slack, запуск сканирования |
| `PreDeleteHook` | Перед удалением пакета | Бэкап metadata, логгирование |
| `PostDeleteHook` | После удаления | Очистка кэшей, уведомление |

#### Пример: Hook для отправки уведомлений

```bash
cat > /usr/local/bin/reprepro-notify.sh << 'EOF'
#!/bin/bash
REPO="$1"
DISTRIBUTION="$2"
PACKAGE="$3"
VERSION="$4"
ACTION="$5"

# Отправка уведомления в Slack (через webhook)
SLACK_WEBHOOK="https://hooks.slack.com/services/XXX/YYY/ZZZ"
MESSAGE="{\"text\":\"Package $PACKAGE $VERSION $ACTION in $REPO/$DISTRIBUTION\"}"

curl -X POST -H 'Content-Type: application/json' -d "$MESSAGE" "$SLACK_WEBHOOK"

# Логгирование в локальный файл
echo "$(date +%Y-%m-%dT%H:%M:%S) $ACTION $PACKAGE $VERSION $DISTRIBUTION" >> /var/log/reprepro-actions.log
EOF
chmod +x /usr/local/bin/reprepro-notify.sh
```

```text
# conf/distributions
Codename: noble
...
PostIncomingHook: /usr/local/bin/reprepro-notify.sh
```

#### Пример: Hook для интеграции с Jenkins

```bash
cat > /usr/local/bin/reprepro-trigger-jenkins.sh << 'EOF'
#!/bin/bash
REPO="$1"
DISTRIBUTION="$2"
PACKAGE="$3"
VERSION="$4"
ACTION="$5"

if [ "$ACTION" = "add" ]; then
    # Триггер джобы в Jenkins для тестирования нового пакета
    curl -X POST -u jenkins-user:api-token \
        "http://jenkins.internal:8080/job/test-pipeline/buildWithParameters" \
        --data "PACKAGE=$PACKAGE" --data "VERSION=$VERSION" --data "DISTRIBUTION=$DISTRIBUTION"
fi
EOF
```

---

### Производительность и масштабирование

#### Файловая система и расположение пула

`reprepro` чувствителен к скорости файловой системы из-за частых операций с BDB и pool:

- **Ext4/XFS**: Рекомендуются для production. XFS лучше справляется с большим количеством файлов в одном каталоге.
- **tmpfs**: Для временных операций (перегенерация индексов) можно использовать tmpfs, но требует достаточного объема RAM.
- **Антоним (hardlinks)**: reprepro использует hardlinks для дедупликации файлов в pool между дистрибутивами. Файловая система должна поддерживать hardlinks (ext4, xfs, btrfs).

#### Работа с большими репозиториями

При количестве пакетов >10 000:
- Используйте `reprepro export` вместо `--fast` для полной перегенерации индексов периодически
- Настройте `Contents` в `conf/distributions` только если нужен `apt-file`
- Разделите репозиторий по компонентам (`main`, `restricted`, `private`) для параллельной обработки

```bash
# Мониторинг размера репозитория
du -sh /srv/repo/pool/
du -sh /srv/repo/dists/
find /srv/repo/pool/ -type f | wc -l

# Очистка неиспользуемых источников
reprepro -b /srv/repo --delete unusedsources
```

---

### Безопасность и соответствие требованиям

#### Аудит доступа к репозиторию

Для отслеживания, кто и когда изменял репозиторий:

```bash
# Включение аудита в gpg-agent
cat > ~/.gnupg/gpg-agent.conf << 'EOF'
log-file /var/log/gpg-agent.log
debug-level advanced
EOF

# Явное логирование операций reprepro через wrapper
cat > /usr/local/bin/reprepro-audit.sh << 'EOF'
#!/bin/bash
REPO_PATH="/srv/repo"
USER="$USER"
COMMAND="$@"
TIMESTAMP=$(date +%Y-%m-%dT%H:%M:%S%z)

echo "$TIMESTAMP user=$USER command=\"$COMMAND\"" >> /var/log/reprepro-audit.log

# Запуск фактической команды
exec "$@"
EOF

# Использование wrapper вместо прямого вызова reprepro
alias reprepro='/usr/local/bin/reprepro-audit.sh -b /srv/repo'
```

#### Изоляция и минимальные привилегии

**Пользователь reprepro:**
```bash
# Создание отдельного пользователя без shell-доступа
useradd -r -s /usr/sbin/nologin reprepro
usermod -L reprepro  # Блокировка пароля

# Настройка прав
chown -R reprepro:reprepro /srv/repo
chmod 0700 /srv/repo/conf
chmod 0700 /srv/repo/dbs
chmod 0755 /srv/repo/pool
chmod 0755 /srv/repo/dists
chmod 0755 /srv/repo/incoming

# Ограничение sudo (если требуется удалённое управление)
cat > /etc/sudoers.d/reprepro << 'EOF'
reprepro ALL=(reprepro) NOPASSWD: /usr/bin/reprepro -b /srv/repo *
EOF
```

---

## Практические сценарии

### Сценарий: Полное резервное копирование и восстановление

#### Требования
- Регулярный бэкап: ежедневный для активных репозиториев
- Хранение: отдельный диск/сервер, не на том же физическом носителе
- Тестирование восстановления: ежемесячно

#### Структура резервной копии

```bash
BACKUP_DIR="/mnt/backup/repo"
REPO_DIR="/srv/repo"
DATE=$(date +%Y-%m-%d)

mkdir -p "$BACKUP_DIR"

# 1. Остановка операций записи (если возможно)
# reprepro не требует остановки для бэкапа pool/ и dists/
# БД BDB копируется лучше всего при отсутствии активных операций

# 2. Полное резервное копирование
tar czf "$BACKUP_DIR/repo-full-$DATE.tar.gz" \
    --exclude='dbs/__db.*' \
    --exclude='incoming' \
    -C "$REPO_DIR" .

# 3. Отдельный бэкап БД (опционально, для быстрого восстановления)
cp -a "$REPO_DIR/dbs" "$BACKUP_DIR/dbs-$DATE"

# 4. Экспорт метаданных для верификации
reprepro -b "$REPO_DIR" dumpdb > "$BACKUP_DIR/dumpdb-$DATE.txt"
reprepro -b "$REPO_DIR" list > "$BACKUP_DIR/list-$DATE.txt"
```

#### Восстановление из резервной копии

```bash
# 1. Остановка веб-сервера
systemctl stop nginx

# 2. Восстановление полной копии
tar xzf "$BACKUP_DIR/repo-full-YYYY-MM-DD.tar.gz" -C /srv/repo/

# 3. Восстановление БД
rm -rf /srv/repo/dbs
cp -a "$BACKUP_DIR/dbs-YYYY-MM-DD" /srv/repo/dbs

# 4. Проверка целостности
reprepro -b /srv/repo check
reprepro -b /srv/repo verify
reprepro -b /srv/repo dumpdb

# 5. Запуск веб-сервера
systemctl start nginx
```

#### Инкрементальное резервное копирование с rsync

```bash
# Первоначальный базовый бэкап
rsync -avz --delete /srv/repo/ /mnt/backup/repo/

# Ежедневное обновление
rsync -avz --delete /srv/repo/ /mnt/backup/repo/

# Создание снапшотов с hardlinks (схема Time Machine)
SNAPSHOT_DIR="/mnt/backup/snapshots"
LATEST=$(ls -1t "$SNAPSHOT_DIR" | head -1)
rsync -avz --delete --link-dest="$SNAPSHOT_DIR/$LATEST" /srv/repo/ "$SNAPSHOT_DIR/$(date +%Y-%m-%d)"
```

---

### Сценарий: Миграция с Aptly на reprepro

#### Причины миграции
- Снижение требований к инфраструктуре (aptly требует БД, reprepro — статику)
- Упрощение резервного копирования (файлы вместо БД)
- Меньше зависимостей

#### Процедура миграции

```bash
# 1. На целевой машине: установка reprepro
apt-get update && apt-get install -y reprepro gnupg

# 2. Создание структуры
mkdir -p /srv/repo/{conf,dists,pool,incoming}
cd /srv/repo

# 3. Копирование существующих пакетов из aptly
# Aptly хранит пакеты в ~/.aptly/pool/
rsync -avz aptly-host:~/.aptly/pool/ /srv/repo/pool/

# 4. Перенос GPG-ключа
# На aptly-хосте:
gpg --armor --export default > aptly-repo-key.pub
gpg --armor --export-secret-keys default > aptly-repo-key.sec
# Перенесите на новую машину и импортируйте:
gpg --import aptly-repo-key.sec

# 5. Создание conf/distributions на основе существующих дистрибутивов aptly
cat > conf/distributions << EOF
Origin: CompanyCorp
Label: Internal Repository
Codename: noble
Architectures: amd64 arm64 all source
Components: main
Description: Internal tools (migrated from aptly)
SignWith: $(gpg --list-secret-keys --keyid-format LONG | grep 'sec' | awk '{print $2}' | cut -d'/' -f2)
EOF

# 6. Перегенерация индексов
reprepro export

# 7. Верификация
reprepro list noble
# → noble|main|amd64: package-name 1.0
```

---

### Сценарий: Интеграция с CI/CD (GitLab CI/Jenkins)

#### GitLab CI: Автоматическое добавление пакетов

```yaml
# .gitlab-ci.yml
stages:
  - build
  - publish

variables:
  REPO_DIR: "/srv/repo"
  GPG_KEY_ID: "ABCDEF1234567890"

before_script:
  - apt-get update -qq && apt-get install -y -qq reprepro gnupg2 curl
  - echo "$GPG_PRIVATE_KEY" | gpg --import
  - echo "$GPG_PASSPHRASE" | gpg --batch --passphrase-fd 0 --pinentry-mode loopback --yes --sign <<< "test"

build:
  stage: build
  script:
    - dpkg-buildpackage -us -uc -b
  artifacts:
    paths:
      - ../*.deb
      - ../*.changes
    expire_in: 1 week

publish:
  stage: publish
  only:
    - main
    - tags
  script:
    - reprepro -b "$REPO_DIR" includedeb noble ../${CI_PROJECT_NAME}_*.deb
    - ssh repo-server " reprepro -b $REPO_DIR export"
  environment:
    name: repository
```

#### Jenkins: Pipeline с артефактами

```groovy
pipeline {
    agent any
    environment {
        REPO_DIR = '/srv/repo'
        GPG_KEY_ID = credentials('repo-gpg-key-id')
        GPG_KEY = credentials('repo-gpg-private-key')
        REPO_HOST = 'repo.internal'
    }
    stages {
        stage('Build') {
            agent { label 'debian-builder' }
            steps {
                sh 'dpkg-buildpackage -us -uc -b'
                archiveArtifacts artifacts: '*.deb', fingerprint: true
            }
        }
        stage('Publish to Repository') {
            steps {
                withCredentials([string(credentialsId: 'repo-gpg-passphrase', variable: 'GPG_PASSPHRASE')]) {
                    sh '''
                        echo "$GPG_KEY" | gpg --import
                        gpg --batch --passphrase "$GPG_PASSPHRASE" --pinentry-mode loopback --yes --sign <<< "test"
                        reprepro -b $REPO_DIR includedeb noble ../${JOB_NAME}_*.deb
                    '''
                }
            }
        }
        stage('Update Repository Indices') {
            steps {
                sshagent(['repo-ssh-key']) {
                    sh "ssh $REPO_HOST 'reprepro -b $REPO_DIR export'"
                }
            }
        }
    }
}
```

---

### Сценарий: Расширенная диагностика и устранение неисправностей

#### Диагностика целостности репозитория

```bash
REPO_DIR="/srv/repo"

# 1. Проверка синтаксиса конфигурации
reprepro -V -b "$REPO_DIR" check
# Ожидаемый результат: "Everything seems to be correct"

# 2. Проверка целостности БД
reprepro -b "$REPO_DIR" verify
# Проверяет контрольные суммы всех файлов в pool/

# 3. Поиск неиспользуемых источников
UNUSED=$(reprepro -b "$REPO_DIR" --delete unusedsources)
echo "$UNUSED"

# 4. Сверка метаданных с фактическими файлами
# Проверка, что все .deb в pool/ упомянуты в БД
find "$REPO_DIR/pool" -name '*.deb' | while read deb; do
    pkg=$(dpkg-deb -f "$deb" Package)
    ver=$(dpkg-deb -f "$deb" Version)
    arch=$(dpkg-deb -f "$deb" Architecture)
    if ! reprepro -b "$REPO_DIR" list | grep -q "$pkg.*$ver.*$arch"; then
        echo "Ораphaned package: $deb"
    fi
done

# 5. Проверка GPG-подписи на клиенте
apt-get update
# → GPG error: The following signatures were invalid
gpg --list-packets /var/lib/apt/lists/*Release*
# Проверка срока действия ключа
gpg --list-keys --keyid-format LONG
# Проверка отзыва
gpg --list-sigs $KEY_ID
```

#### Типичные проблемы и решения

**Проблема: "Database is locked"**

Причины:
- Параллельный запуск reprepro
- Нештатное завершение предыдущей операции
- Проблемы с NFS (если репозиторий на сетевой ФС)

Решение:
```bash
# 1. Проверка блокировок
lsof +L1 | grep reprepro
fuser -v /srv/repo/dbs/packages.db

# 2. Если процесса нет — удаление устаревших lock-файлов
find /srv/repo/dbs -name '__db.??-lock' -delete
find /srv/repo/dbs -name 'log.*' -delete  # Только при уверенности, что reprepro не работает

# 3. Перегенерация
reprepro -b /srv/repo export
```

**Проблема: "GPG error: The following signatures were invalid"**

Причины:
- Неверный ключ на клиенте
- Истёкший срок действия ключа
- Несинхронизированное время (NTP)
- Повреждённые индексы

Решение:
```bash
# 1. Проверка времени
timedatectl status
ntpdate -q pool.ntp.org

# 2. Проверка ключа на сервере
gpg --list-keys --keyid-format LONG
gpg --check-secret-keys

# 3. Проверка подписи Release файла
gpg --verify /srv/repo/dists/noble/InRelease

# 4. Перегенерация индексов
reprepro -b /srv/repo export

# 5. Распространение нового публичного ключа
gpg --armor --export $KEY_ID > /var/www/repo/repo-key.pub
```

**Проблема: Недостаточно энтропии (Not enough entropy)**

```bash
# Диагностика
cat /proc/sys/kernel/random/entropy_avail
# Если < 1000 — проблема

# Решение: установка haveged
apt-get install -y haveged
systemctl enable --now haveged

# Проверка
cat /proc/sys/kernel/random/entropy_avail
# → 3000+ (норма)
```

**Проблема: Файлы .deb не добавляются**

```bash
# 1. Проверка архитектуры
dpkg-deb -f package.deb Architecture
# Должна совпадать с Architectures в conf/distributions

# 2. Проверка подписи .changes файла
gpg --verify package.changes

# 3. Проверка прав доступа к incoming
ls -la /srv/repo/incoming/
# Должна быть доступна пользователю, под которым работает reprepro

# 4. Детальный вывод
reprepro -V -b /srv/repo includedeb noble package.deb 2>&1
```

---

### Сценарий: Обслуживание и диагностика

В процессе долгосрочной эксплуатации `reprepro` могут потребоваться сервисные операции.

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `reprepro -V check` | Проверка синтаксиса `conf/` | `Everything seems to be correct` |
| `reprepro export` | Принудительная регенерация индексов | Обновление `Packages.gz`, `Release` |
| `reprepro verify` | Проверка контрольных сумм в пуле | Подтверждение целостности файлов `.deb` |
| `reprepro dumpdb` | Просмотр содержимого базы данных | Список всех версий и связей в BDB |
| `reprepro unusedsources` | Поиск неиспользуемых исходных кодов | Список файлов для удаления |
| `reprepro -V list` | Детальный листинг с отладкой | Полная информация о пакетах |
| `reprepro -V includedeb` | Добавление с детальным выводом | Лог добавления пакета |

---

### Сценарий: Выбор инструментария (SRE Decision Matrix)

Сравнение инструментов для выбора оптимальной стратегии хранения пакетов.

| Критерий | reprepro | aptly | Artifact Registry (Cloud) |
| :--- | :--- | :--- | :--- |
| **Сложность** | Низкая (статические файлы) | Средняя (требует БД) | Зависит от провайдера |
| **API** | Нет | Да (полнофункциональный) | Да |
| **Снапшоты** | Только через внешние скрипты | Встроены (первоклассная функция) | Версионирование артефактов |
| **Зеркалирование** | Базовое (через Updates) | Продвинутое | Нет |
| **Лучшее применение** | Небольшие/средние репозитории | Крупные среды, CI/CD пайплайны | Облачные (Cloud-native) среды |

**Рекомендации SRE:**
- **< 5 000 пакетов, статический контент** → reprepro
- **> 5 000 пакетов, сложные правила зеркалирования** → aptly
- **Требуется REST API, сложная автоматизация** → aptly или специализированные решения

---

### Сценарий: Мониторинг и алертинг

#### Метрики для мониторинга

```bash
#!/bin/bash
# /usr/local/bin/repo-health-check.sh

REPO_DIR="/srv/repo"
LOG_FILE="/var/log/repo-health.log"

check_repo() {
    local exit_code=0
    
    # 1. Проверка целостности
    if ! reprepro -V -b "$REPO_DIR" check > /dev/null 2>&1; then
        echo "$(date) CRITICAL: Repository configuration is invalid" >> "$LOG_FILE"
        exit_code=1
    fi
    
    # 2. Проверка БД
    if ! reprepro -b "$REPO_DIR" verify > /dev/null 2>&1; then
        echo "$(date) CRITICAL: Package integrity check failed" >> "$LOG_FILE"
        exit_code=1
    fi
    
    # 3. Проверка свободного места
    local avail=$(df -h "$REPO_DIR" | tail -1 | awk '{print $5}' | sed 's/%//')
    if [ "$avail" -gt 90 ]; then
        echo "$(date) WARNING: Disk usage above 90%" >> "$LOG_FILE"
    fi
    
    # 4. Проверка срока действия GPG-ключа
    local expiry=$(gpg --list-keys --keyid-format LONG | grep 'expires' | head -1)
    if [ -n "$expiry" ]; then
        echo "$(date) INFO: GPG key expires $expiry" >> "$LOG_FILE"
    fi
    
    return $exit_code
}

check_repo
exit $?
```

#### Интеграция с Prometheus (Node Exporter)

```bash
# textfile collector для node_exporter
cat > /etc/node_exporter/textfile_collector/repo.prom << 'EOF'
# HELP repo_packages_total Total number of packages in repository
# TYPE repo_packages_total gauge
repo_packages_total $(reprepro -b /srv/repo list | wc -l)

# HELP repo_disk_usage_bytes Disk usage of repository in bytes
# TYPE repo_disk_usage_bytes gauge
repo_disk_usage_bytes $(du -sb /srv/repo | cut -f1)

# HELP repo_gpg_key_valid GPG key validity (1=valid, 0=invalid/expired)
# TYPE repo_gpg_key_valid gauge
repo_gpg_key_valid 1
EOF
```

---

### Сценарий: Управление несколькими дистрибутивами и архитектурами

#### Организация репозитория для мультидистрибутивной среды

```text
# Структура
srv/repo/
├── conf/
│   └── distributions
├── pool/
│   └── main/
│       ├── a/
│       │   └── app/
│       │       ├── app_1.0_amd64.deb
│       │       └── app_1.0_all.deb
│       └── n/
│           └── nginx/
│               └── nginx_1.24_amd64.deb
└── dists/
    ├── bookworm/
    │   └── main/
    │       ├── binary-amd64/
    │       │   └── Packages
    │       ├── binary-arm64/
    │       │   └── Packages
    │       └── source/
    │           └── Sources
    └── noble/
        └── main/
            ├── binary-amd64/
            │   └── Packages
            └── binary-all/
                └── Packages
```

#### Пример conf/distributions для нескольких ОС

```text
Origin: CompanyCorp
Label: Internal Repository
Codename: bookworm
Architectures: amd64 arm64 all source
Components: main
Description: Internal tools for Debian 12 (Bookworm)
SignWith: ABCDEF1234567890

Origin: CompanyCorp
Label: Internal Repository
Codename: noble
Architectures: amd64 arm64 all source
Components: main
Description: Internal tools for Ubuntu 24.04 (Noble)
SignWith: ABCDEF1234567890
```

#### Добавление пакета для нескольких дистрибутивов

```bash
# Добавление одного .deb в два дистрибутива
reprepro -b /srv/repo includedeb bookworm /tmp/app_1.0_amd64.deb
reprepro -b /srv/repo includedeb noble /tmp/app_1.0_amd64.deb

# Или массовое добавление
for dist in bookworm noble; do
    reprepro -b /srv/repo includedeb "$dist" /tmp/*.deb
done
```

---

### Сценарий: Продвинутое зеркалирование (Updates) с фильтрацией

#### Настройка фильтрованных зеркал

```bash
cat > /srv/repo/conf/updates << 'EOF'
Name: ubuntu-noble-main
Method: http://archive.ubuntu.com/ubuntu/
Suite: noble
Components: main
Architectures: amd64 arm64
VerifyRelease: gpg
# Фильтр: только пакеты, начинающиеся с 'lib' или 'nginx'
FilterFormula: Package (gt 'k' & lt 'm') | Package (== nginx) | Package (== curl)
# ИЛИ более точный фильтр по версии
# Filter:Package (== nginx) | Package (== curl) | Package (== python3*)
EOF
```

```text
# conf/distributions
Codename: noble
...
Update: ubuntu-noble-main
```

```bash
# Синхронизация
reprepro -b /srv/repo update noble
# → Exporting indices...
# → Deleting obsolete files...
```

#### Зеркало с использованием debmirror (альтернативный подход)

```bash
# Для полного зеркала с debmirror
apt-get install -y debmirror
debmirror --host=archive.ubuntu.com --root=/ubuntu \
    --dist=noble --section=main,universe,multiverse \
    --arch=amd64,arm64 --method=http \
    --progress --nosource \
    /srv/mirror/ubuntu-noble
```

---

### Сценарий: Аудит соответствия (Compliance)

#### Отслеживание происхождения пакетов

```bash
# Генерация отчёта о всех пакетах
reprepro -b /srv/repo list noble main amd64 > /tmp/report.txt

# Форматированный отчёт
cat > /usr/local/bin/repo-compliance-report.sh << 'EOF'
#!/bin/bash
REPO_DIR="/srv/repo"
REPORT="/var/www/repo/compliance-report.txt"

{
    echo "=== Repository Compliance Report ==="
    echo "Generated: $(date)"
    echo ""

    echo "--- GPG Key Information ---"
    gpg --list-keys --keyid-format LONG | grep -E 'pub|sub|fpr|uid'
    echo ""

    echo "--- Package Manifest ---"
    reprepro -b "$REPO_DIR" list
    echo ""

    echo "--- Integrity Check ---"
    reprepro -b "$REPO_DIR" verify
    echo ""

    echo "--- Disk Usage ---"
    du -sh "$REPO_DIR"
} > "$REPORT"

# Подпись отчёта GPG-ключом репозитория
gpg --armor --detach-sign "$REPORT"
EOF
chmod +x /usr/local/bin/repo-compliance-report.sh
```

---

## Дополнительная информация

### Ограничения и известные проблемы

1. **Блокировка БД**: `reprepro` не поддерживает конкурентный доступ. Все операции должны быть последовательными.
2. **BDB 1.85**: Устаревшая версия Berkeley DB. При обновлении до новых версий `reprepro` возможна миграция на SQLite.
3. **Отсутствие API**: Управление только через CLI. Для автоматизации используйте SSH с ограниченными командами или очереди задач.
4. **Пулы на сетевых ФС**: Не рекомендуется размещать `dbs/` на NFS из-за проблем с файловыми блокировками BDB. Директории `pool/` и `dists/` можно синхронизировать через rsync.

### Лучшие практики

1. **Инфраструктура как код**: Храните `conf/distributions`, `conf/updates`, `conf/incoming` в Git. Развёртывайте через Ansible/Chef/Puppet.
2. **Резервное копирование**: Делайте бэкап `dbs/` отдельно от `pool/` и `dists/`. Тестируйте восстановление не реже раза в квартал.
3. **Мониторинг**: Настройте проверки `reprepro check` и `reprepro verify` через cron/systemd timer.
4. **Гранулярность доступа**: Используйте отдельного пользователя `reprepro` с ограниченными правами. Через `sudoers` разрешайте только необходимые команды.
5. **Аудит**: Ведите лог всех операций через wrapper-скрипты или hook-скрипты.
6. **Ключи**: Используйте иерархические ключи с офлайн мастер-ключом. Ротация ключей — раз в год или при смене персонала.

### Связанные документы

- **[Определения и концепции](./definitions_and_concepts.md)** — архитектура и описание файлов конфигурации.
- **[Практические сценарии](./practical_scenarios.md)** — инструкции по развертыванию, управлению пакетами и автоматизации.
- **[Apt Pinning](../deb_apt_pinning.md)** — управление приоритетами на стороне клиента.
- **[Nginx: Настройка репозитория](../../../WebServers/Nginx/Scenarios/secure_apt_repository_guide.md)** — защита репозитория на сетевом уровне с mTLS.
- **[GPG и OpenPGP](../../Linux/Security/Tools/gpg_and_openpgp.md)** — общие принципы работы с криптографическими ключами.
