# GPG и OpenPGP

## Определения

**OpenPGP** — открытый стандарт и протокол шифрования на основе асимметричных алгоритмов, предназначенный для шифрования, дешифрования и создания цифровых подписей сообщений и файлов. Является развитием оригинальной программы PGP (Pretty Good Privacy).

**GnuPG (GPG)** — свободная программная реализация стандарта OpenPGP (RFC 4880). Обеспечивает высокий уровень защиты данных через интерфейс командной строки и интеграцию с графическими утилитами.

Связано: [PKI — инфраструктура открытых ключей](../../../Security/Concepts/pki_overview.md)

### Стандарты и RFC

OpenPGP формализован в следующих документах:

- **RFC 4880** — основной стандарт OpenPGP (сентябрь 2007). Определяет формат сообщений, пакеты, алгоритмы по умолчанию (RSA, AES, SHA-2).
- **RFC 4880 (Appendix A)** — реестр поддерживаемых алгоритмов.
- **RFC 6637** — эллиптические кривые для OpenPGP (ECDH, ECDSA), включая Curve25519.
- **RFC 9580** — обновлённый стандарт OpenPGP (апрель 2024): добавлены ECC по умолчанию, улучшена безопасность, поддержка AEAD (AES-GCM), синтаксис пакетов, устранены устаревшие алгоритм.
- **RFC 5584** — поддержка AES-GCM и AES-CCM в OpenPGP.
- **RFC 6921** — улучшение производительности через обмен ключами с эфемерными ключами.

GnuPG с версии 2.3+ поддерживает RFC 9580 (предварительно). Проверка совместимости: `gpg --version` показывает поддерживаемые алгоритмы.

## Базовые концепции

### Типы шифрования

| Характеристика | Симметричное | Асимметричное |
| :--- | :--- | :--- |
| **Ключи** | Один (общий секрет) | Пара (публичный + приватный) |
| **Скорость** | Высокая | Относительно низкая |
| **Управление** | Сложное (безопасная передача ключа) | Простое (публичный ключ открыт) |
| **Применение** | Шифрование больших объемов данных | Обмен ключами, цифровые подписи |

### Гибридное шифрование

GPG использует комбинацию обоих методов:
1.  Генерируется случайный одноразовый **симметричный ключ сессии**.
2.  Данные шифруются этим ключом (быстро).
3.  Ключ сессии шифруется **публичным ключом** получателя (асимметрично).
4.  Получатель расшифровывает ключ сессии своим **приватным ключом**, а затем расшифровывает сами данные.

### Структура ключей: Мастер-ключ и подключи

Для повышения безопасности в GPG используется иерархическая структура:

*   **Мастер-ключ (Certify - C):**
    *   Предназначен только для управления: создания/отзыва подключей и подписи чужих ключей.
    *   **Должен храниться офлайн** (на зашифрованном USB-накопителе или аппаратном токене).
*   **Подключи (Subkeys):**
    *   **Sign (S):** создание цифровых подписей (коммиты Git, файлы).
    *   **Encrypt (E):** шифрование данных.
    *   **Authenticate (A):** аутентификация (SSH, PAM).
    *   Могут быть отозваны отдельно без смены мастер-ключа.

### Сеть доверия (Web of Trust) и уровни доверия

OpenPGP использует децентрализованную модель вместо иерархических CA. Участники подтверждают подлинность ключей друг друга.

**Уровни доверия владельцу (Trust levels):**
1.  **Unknown (Неизвестно):** уровень не установлен.
2.  **None (Нет доверия):** вы не доверяете этому человеку в вопросе подписи других ключей.
3.  **Marginal (Ограниченное):** требуется 3 таких подписи для подтверждения ключа.
4.  **Full (Полное):** вы полностью доверяете человеку проверку других ключей.
5.  **Ultimate (Абсолютное):** для своих собственных ключей.

### Алгоритмы шифрования (2026)

| Алгоритм | Тип | Статус | Комментарий |
| :--- | :--- | :--- | :--- |
| **RSA** | Асимметричный | Устаревший (legacy) | Рекомендуемый размер: 4096 бит. Медленнее ECC, рекомендуется к замене. |
| **Ed25519 (EdDSA)** | Подпись | Рекомендуемый | Эллиптическая кривая, высокая производительность, устойчивость к side-channel. |
| **Curve25519 (ECDH)** | Шифрование | Рекомендуемый | Обмен ключами, совместим с age (X25519). |
| **AES-256** | Симметричный | Рекомендуемый | Симметричное шифрование данных, стандарт по умолчанию. |
| **ChaCha20-Poly1305** | AEAD | Современный | Альтернатива AES-GCM, оптимизирован для мобильных/software-реализаций. |
| **SHA-512** | Хэш | Рекомендуемый | Хэш-функция по умолчанию для подписей и отпечатков. |
| **SHA-256** | Хэш | Совместимость | Используется при совместимости с устаревшими системами. |
| **Blowfish** | Симметричный | Устаревший | Заменён AES. |
| **CAST5** | Симметричный | Устаревший | Заменён AES. |
| **MD5** | Хэш | Запрещён | Уязвим к коллизиям, не использовать. |

**Рекомендации по алгоритмам (GnuPG 2.3+):**
- Использовать только Ed25519 + Curve25519 + AES-256 + SHA-512.
- Отказаться от RSA при возможности.
- Проверить поддержку AEAD: `gpg --version` показывает `AEAD: yes`.

### Уровни шифрования и защита от перехвата

GPG поддерживает три режима шифрования:

1.  **Симметричное (symmetric):** `gpg -c file`. Данные шифруются паролем. Подходит для обмена с теми, у кого нет публичного ключа.
2.  **Асимметричное (public-key):** `gpg -e -r recipient file`. Использует публичный ключ получателя.
3.  **AEAD (Authenticated Encryption with Associated Data):** Доступно в GnuPG 2.3+ по RFC 9580. Обеспечивает конфиденциальность, целостность и аутентичность. Режим по умолчанию в новых версиях.

**Режимы шифрования (gpg --encrypt --wrap-mode):**
- `--wrap-mode 0` — шифрование без MAC (устаревший).
- `--wrap-mode 1` — шифрование с MAC (по умолчанию в старых версиях).
- `--wrap-mode 2` — AEAD (GnuPG 2.3+, рекомендуется).

### Жизненный цикл ключа

GPG-ключ проходит типовые фазы: генерация → публикация → использование → ротация → отзыв → уничтожение.

1.  **Генерация:** Создание мастер-ключа (C) и подключей (S, E, A). Рекомендуется использовать `--full-generate-key --expert` с ECC Ed25519.
2.  **Публикация:** Загрузка публичного ключа на ключевой сервер (`gpg --send-keys`) или размещение в WKD (Web Key Directory).
3.  **Использование:** Ежедневные операции — подпись коммитов, шифрование писем/файлов, аутентификация через SSH.
4.  **Ротация (expiration):** Установка срока действия ключа (1-2 года). По истечении срока ключ не может использоваться для новых операций, но старые подписи остаются валидными. Продление: `gpg --edit-key <ID>` → `expire`.
5.  **Отзыв (revocation):** При утере или компрометации ключа используется сертификат отзыва (`revoke.asc`). Отзыв публикуется на сервере ключей.
6.  **Уничтожение:** Удаление приватного ключа из keyring после безопасного стирания носителя.

**Сроки жизни (рекомендации):**
- Мастер-ключ (C): бессрочный, хранится оффлайн.
- Подключи (S, E, A): 1-2 года, ротируются отдельно.
- Субпартии (subkeys): 1 год для подписантов, до 5 лет для основных.

### Аппаратные токены и HSM

Для защиты мастер-ключа и подключей используются:

- **YubiKey 5 Series (FIDO2/OpenPGP):** Поддержка OpenPGP-аппаратных ключей (PIV, FIDO2). Ключи генерируются на устройстве и не покывают его границы.
- **Smartcards (PC/SC):** Стандартные карты с чипом (Gemalto, Identiv). Подключаются через `pcscd`.
- **HSM (Hardware Security Module):** Аппаратные модули безопасности (Thales, Utimaco, AWS CloudHSM). Используются в enterprise-средах для защиты корневых ключей.
- **TPM 2.0:** Встроенный в материнскую плату модуль. Поддержка через `tpm2-tools` и `gpg` с помощью бэкенда.

**Настройка YubiKey:**
```bash
# Переключение в OpenPGP-режим
ykcli openpgp:setup --pin 123456 --admin-pin 1234567890

# Загрузка ключа на токен (генерация на устройстве)
gpg --edit-key <Master_Key_ID>
# gpg> toggle
# gpg> key <Subkey_ID>
# gpg> keytocard
# gpg> save
```

**Проверка статуса токена:**
```bash
gpg --card-status
# → показывает серийный номер, доступные слоты, тип токена
```

## Практические сценарии

### Настройка конфигурации (`~/.gnupg/gpg.conf`)

```ini
# Использовать длинные ID и отпечатки (защита от коллизий)
keyid-format long
with-fingerprint

# Скрывать идентификаторы получателей
throw-keyids

# Выбор серверов ключей
keyserver hkps://keys.openpgp.org

# Предпочтительные алгоритмы (ECC/AES256/SHA512)
personal-cipher-preferences AES256 AES192 AES
personal-digest-preferences SHA512 SHA384 SHA256
cert-digest-algo SHA512
default-preference-list SHA512 SHA384 SHA256 AES256 AES192 AES ZLIB BZIP2 ZIP Uncompressed
```

### Настройка агента (`~/.gnupg/gpg-agent.conf`)

```ini
# Время кэширования пароля (2 часа)
default-cache-ttl 7200
max-cache-ttl 86400

# Включение поддержки SSH
enable-ssh-support

# Выбор пин-ентри (консольный или GUI)
pinentry-program /usr/bin/pinentry-curses
```

### Генерация и управление ключами

```bash
# Создание ключа в экспертном режиме (рекомендуется ECC Ed25519)
gpg --full-generate-key --expert
# → (9) ECC (sign and encrypt) -> (1) Curve 25519

# Добавление подключа аутентификации (SSH)
gpg --edit-key <Key_ID>
# gpg> addkey -> (11) ECC (set own capabilities) -> включить Authenticate
# save

# Список ключей с отпечатками
gpg --list-keys --keyid-format LONG
```

### Резервное копирование

```bash
# Экспорт публичного ключа
gpg --export -a <Key_ID> > public.asc

# Экспорт приватной связки (ХРАНИТЬ В СЕЙФЕ)
gpg --export-secret-keys -a <Key_ID> > private_full.asc

# Генерация сертификата отзыва (на случай потери ключа)
gpg --gen-revoke <Key_ID> > revoke.asc
```

### Работа с серверами ключей и WKD

```bash
# Отправка ключа на сервер
gpg --send-keys <Key_ID>

# Обновление ключей из сети
gpg --refresh-keys

# Получение ключа по email (WKD - Web Key Directory)
gpg --locate-keys torbrowser@torproject.org
```

### Шифрование и подпись

```bash
# Шифрование файла для получателя
gpg -e -a -r recipient@example.com document.pdf

# Симметричное шифрование (только пароль)
gpg -c document.pdf

# Проверка подписи официального релиза (напр. Linux Kernel)
gpg --verify linux-x.y.z.tar.sign linux-x.y.z.tar

# Локальная подпись ключа (доверие без публикации подписи)
gpg --lsign-key <Other_Key_ID>
```

### Интеграция с SSH и Git

**GPG как SSH-агент:**
1. В `.bashrc` / `.zshrc`:
```bash
export SSH_AUTH_SOCK=$(gpgconf --list-dirs agent-ssh-socket)
gpgconf --launch gpg-agent
```
2. Узнать Keygrip подключа аутентификации: `gpg -K --with-keygrip`
3. Добавить его в `~/.gnupg/sshcontrol`.

**Подпись коммитов Git:**
```bash
git config --global user.signingkey <Subkey_ID_Sign>!
git config --global commit.gpgsign true
```

### Автоматизация (CI/CD, cron, systemd)

GPG часто используется в неполномерных сценариях, где нет интерактивного ввода пароля. Для этого есть два подхода:

**Вариант 1: Batch mode + passphrase-file (риск: пароль на диске)**
```bash
# Создание ключа без пароля (только для CI/тестовых сред)
gpg --batch --passphrase '' --quick-gen-key \
  "CI Bot <ci@company.com>" default default 0

# Шифрование с паролем из файла
echo "$PASSPHRASE" > /tmp/.pass
gpg --batch --yes --passphrase-file /tmp/.pass \
  --symmetric --cipher-algo AES256 secret.txt
```

**Вариант 2: Cache passphrase в gpg-agent (рекомендуется)**
```ini
# ~/.gnupg/gpg-agent.conf
default-cache-ttl 7200
max-cache-ttl 86400
allow-pem-passphrase
```

**Пример в GitHub Actions:**
```yaml
- name: Import GPG key
  run: |
    echo "${{ secrets.GPG_PRIVATE_KEY }}" | gpg --batch --import -
    echo "${{ secrets.GPG_PASSPHRASE }}" | gpg \
      --batch --pinentry-mode loopback \
      --passphrase-fd 0 \
      --decrypt backup.gpg > private_full.asc
    gpg --batch --import private_full.asc
    rm private_full.asc
```

**Пример в systemd-сервисе:**
```ini
# /etc/systemd/system/gpg-daemon.service
[Unit]
Description=GPG Agent
After=network.target

[Service]
Type=forking
ExecStart=/usr/bin/gpg-agent --daemon
Environment=GPG_TTY=/dev/tty1
Restart=always
```

### Подпись и верификация релизов (CI/CD)

**Сценарий: подпись артефактов на CI-пайплайне**
```bash
# Генерация ключа на CI (одноразовый, short-lived)
gpg --batch --passphrase '' --quick-gen-key \
  "Release Signer <release@company.com>" ed25519 sign 0

# Подпись артефакта
gpg --batch --yes --local-sign <Key_ID> \
  --output artifact.tar.gz.sig artifact.tar.gz

# Публикация ключа для проверки
gpg --export -a <Key_ID> > public_release.asc
```

**Верификация на стороне получателя:**
```bash
# Импорт ключа проверки
gpg --import public_release.asc

# Проверка подписи
gpg --verify artifact.tar.gz.sig artifact.tar.gz
# → Good signature от "Release Signer"
```

### Почтовая интеграция (MUA)

GPG интегрируется с почтовыми клиентами через бэкенд:

- **Enigmail (Thunderbird):** Устаревший, заменяется нативной поддержкой OpenPGP в Thunderbird 78+ (RNP).
- **K-9 Mail / FairEmail (Android):** Поддержка OpenPGP через OpenKeychain.
- **Claws Mail + pgp plugin:** Локальная интеграция.
- **ProtonMail / Tuta:** Нативная поддержка OpenPGP (шифрование по умолчанию).

**Командная строка для почты:**
```bash
# Шифрование письма
gpg --encrypt --armor --recipient recipient@example.com \
  --output message.eml.asc < message.txt

# Подпись письма
gpg --sign --armor --detach --output message.asc message.txt
```

## Дополнительная информация

### Диагностика и решение проблем

*   **Ошибка `Inappropriate ioctl for device`**: Часто возникает при работе через SSH без графической сессии. Решение: `export GPG_TTY=$(tty)` в `.bashrc`.
*   **Агент не видит смарт-карту (YubiKey)**: Проверьте `gpg --card-status`. Если не работает, убедитесь, что `pcscd` запущен, а в `gpg-agent.conf` нет конфликтующих опций.
*   **Права доступа**: GPG очень чувствителен к правам.
    ```bash
    chmod 700 ~/.gnupg
    chmod 600 ~/.gnupg/*
    ```

### Ротация и обновление ключей

**Сценарий: замена подключа (subkey) без изменения мастер-ключа**
```bash
# Редактирование ключа
gpg --edit-key <Master_Key_ID>

# Выбор существующего подключа для удаления
gpg> key <Old_Subkey_ID>
gpg> delkey

# Генерация нового подключа
gpg> addkey
# → (12) ECC (sign only) или (13) ECC (encrypt only)

# Сохранение изменений
gpg> save
```

**Сценарий: обновление предпочтительных алгоритмов без смены ключа**
```bash
# Изменить предпочтения алгоритмов в ключе
gpg --edit-key <Key_ID>
gpg> showpref
gpg> setpref AES256 SHA512 ECC Ed25519 Curve25519
gpg> save
```

**Сценарий: обновление ключей в SOPS**
```bash
# Перешифровать файл с новыми ключами
sops updatekeys secrets.enc.yaml
```

### Безопасность gpg-agent

**Риски и меры защиты:**

| Риск | Мера защиты |
| :--- | :--- |
| Кэширование пароля | `default-cache-ttl 600` (10 минут) |
| Утечка через environment | Не использовать `GPG_TTY` в скриптах |
| Удалённый доступ к агенту | `export GPG_AGENT_INFO` только в безопасной сессии |
| Проблемы с pinentry | Использовать `pinentry-bwrap` для изоляции |

**Рекомендуемая конфигурация для production:**
```ini
# ~/.gnupg/gpg-agent.conf
# Короткое время жизни кэша (10 минут)
default-cache-ttl 600
max-cache-ttl 1800

# Использовать loopback pinentry для скриптов
# (пароль вводится через stdin, без GUI)
pinentry-mode loopback

# Запретить неиспользуемые сокеты
no-allow-stub
no-sandbox

# Логирование для аудита
log-file /var/log/gpg-agent.log
verbose
```

**Проверка активного агента:**
```bash
gpgconf --list-dirs
# → agent-socket, agent-info, etc.
```

### Сравнение с современными альтернативами (age)

| Функция | GPG/OpenPGP | age (Actually Good Encryption) |
| :--- | :--- | :--- |
| **Сложность** | Высокая (Legacy, WoT) | Низкая (Unix-way) |
| **Размер ключей** | Большой | Маленький (X25519) |
| **Настройка** | Требует gpg-agent | Не требует настройки |
| **Применение** | Почта, Git, SSH, Репозитории | Скрипты, автоматизация, бэкапы |

### Многополучатели (Multi-recipient)

GPG позволяет шифровать один файл для нескольких получателей одновременно:

```bash
# Шифрование для нескольких получателей
gpg --encrypt --recipient alice@example.com \
  --recipient bob@example.com \
  --recipient carol@example.com \
  --output multi.enc document.pdf

# Каждый получатель может расшифровать своими ключами
gpg --decrypt multi.enc > document.pdf
```

**Использование в сценариях:**
- Рассылка конфиденциальных отчётов команде.
- Резервное копирование с дублированием доступа (админ + запасной админ).
- Доступ к секретам для ротации персонала.

### Модели доверия (Trust Models)

GPG поддерживает несколько моделей проверки ключей через `--trust-model`:

| Модия | Описание | Использование |
| :--- | :--- | :--- |
| **interactive** | По умолчанию. Запрашивает подтверждение при каждой проверке. | Ручная работа, интерактивные сессии. |
| **always** | Принимает ключи без проверки. | CI/CD, тестовые среды, доверенные внутренние сети. |
| **auto** | Автоматическая проверка с учётом уровня доверия. | Смешанный режим, автоматизация. |
| **classic** | Старая модель (до GnuPG 2.1). | Совместимость с устаревшими системами. |
| **tofu** | Trust On First Use. Ключ запоминается при первом контакте. | Безопаснее `always`, проще `interactive`. |
| **tofu+pgp** | TOFU + levels of trust. | Современный стандарт, рекомендуется. |

**Рекомендация:** Использовать `--trust-model tofu+pgp` в production-средах.

### Проверка отпечатков (Out-of-band)

Перед тем как доверить ключ, необходимо проверить отпечаток (fingerprint) через независимый канал:

```bash
# Получить отпечаток ключа
gpg --with-fingerprint --list-keys <Key_ID>
# → 4A8B 1234 CDEF 5678 90AB  CDEF 1234 5678 90AB 1234

# Сравнить с публикацией на сайте (HTTPS), в личном общении, или через video-конференцию
# → Проверить первые 8 и последние 8 символов

# Проверить ключ через WKD (Web Key Directory)
gpg --locate-keys --verbose user@example.com
```

### Поддержка платформ

**macOS:**
```bash
# Установка через Homebrew
brew install gnupg pinentry-mac

# Настройка pinentry для macOS
# ~/.gnupg/gpg-agent.conf
pinentry-program /opt/homebrew/bin/pinentry-mac
```

**Windows (WSL2):**
```bash
# Установка в WSL
sudo apt install gnupg pinentry-curses

# Использование консольного pinentry
pinentry-program /usr/bin/pinentry-curses
```

**Linux (systemd):**
```ini
# Запуск gpg-agent через systemd
[Unit]
Description=GnuPG Agent
After=local-fs.target

[Service]
Type=forking
PIDFile=/run/gpg-agent.pid
ExecStart=/usr/bin/gpg-agent --daemon
Restart=always
```

### GPG-TAR (архивация с шифрованием)

```bash
# Создание зашифрованного архива
gpgtar --encrypt --recipient recipient@example.com directory/
# → directory.tar.gz.gpg

# Расшифровка и распаковка
gpgtar --decrypt directory.tar.gz.gpg
```

**Особенности:**
- Использует tar+gzip по умолчанию.
- Поддерживает рекурсивное шифрование.
- Альтернатива ручному `tar | gpg`.

### Интеграция с пакетными менеджерами

GPG используется для проверки подлинности пакетов в APT, RPM и других системах.

**APT (Debian/Ubuntu):**
```bash
# Импорт ключа репозитория
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg

# Добавление репозитория с проверкой
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list

# Обновление и установка
sudo apt update && sudo apt install vault
```

**RPM (RHEL/CentOS/Fedora):**
```bash
# Импорт ключа
rpm --import https://www.elrepo.org/RPM-GPG-KEY-elrepo.org

# Установка пакета с проверкой
rpm --checksig package.rpm
```

**Собственный репозиторий (GPG-подпись пакетов):**
```bash
# Подпись пакета своим ключом
rpmsign --addsign /var/www/repo/x86_64/package.rpm

# Проверка подписи
rpm --checksig --verbose package.rpm
```

### Security Hardening (усиление безопасности)

**Меры защиты при компрометации:**

| Ситуация | Действие |
| :--- | :--- |
| Утеря ключа | Немедленно опубликовать сертификат отзыва (`gpg --gen-revoke`). |
| Подозрение на утечку | Проверить логи (`gpg-agent.log`), отключить агента, сгенерировать новые ключи. |
| Подмена ключа | Использовать out-of-band проверку отпечатков (phone, video, личная встреча). |
| Старые подписи | Проверить `gpg --list-sigs` на наличие неизвестных подписей. |

**Блокировка агента при ошибке ввода:**
```ini
# ~/.gnupg/gpg-agent.conf
# Блокировка после 3 неудачных попыток
max-cache-ttl 600
default-cache-ttl 600
pinentry-retry 3
```

**Настройка для высоконадёжных сред (HSM):**
```bash
# Использование HSM вместо локального ключа
# Требует настройки PKCS#11 бэкенда
gpg --agent-program /usr/lib/opensc-pkcs11-tool
gpg --card-status
```

### Связанные темы

*   **[SOPS](../../../Security/Tools/sops_overview.md)** — шифрование секретов в YAML/JSON через GPG.
*   **[MFA и аппаратные ключи](../../../Security/Concepts/mfa_totp.md)** — использование токенов (YubiKey) в эшелонированной защите.
*   **[Artifact Signing](../../../Security/Supply_Chain_Security/artifact_signing.md)** — подпись пакетов и ISO.

### Лучшие практики

1.  **ECC Ed25519**: Переходите с RSA на эллиптические кривые. Они быстрее и безопаснее при меньшей длине ключа.
2.  **Срок действия**: Устанавливайте срок жизни ключа (например, 1-2 года) и продлевайте его по необходимости. Это гарантирует актуальность бэкапов.
3.  **Автономный мастер-ключ**: Храните основной ключ `C` на отдельном USB/карте. В системе должны быть только подключи `S, E, A`.
4.  **WKD**: Используйте Web Key Directory для автоматического поиска ключей вместо старых и ненадежных серверов SKS.
5.  **Документация**: [GnuPG Manual](https://gnupg.org/documentation/manuals/gnupg/Invoking-GPG.html).

### Production-чеклист (настройка за 1 час)

**Шаг 1: Подготовка окружения**
```bash
# Установка (Debian/Ubuntu)
sudo apt update && sudo apt install -y gnupg gnupg-agent pinentry-curses pcscd

# Создание безопасной директории
mkdir -p ~/.gnupg
chmod 700 ~/.gnupg

# Настройка GPG_TTY для сессий без GUI
echo 'export GPG_TTY=$(tty)' >> ~/.bashrc
```

**Шаг 2: Генерация ключа (с отдельным мастер-ключом)**
```bash
# Генерация мастер-ключа (только C)
gpg --full-generate-key --expert
# → (4) ECC (sign only) -> (1) Curve 25519
# → (12) ECC (set own capabilities) -> убрать E, оставить S
# → expires: 2y

# Генерация подключа для шифрования
gpg --edit-key <Master_Key_ID>
gpg> addkey
# → (12) ECC (encrypt only) -> (1) Curve 25519
# → expires: 1y

# Генерация подключа для аутентификации (SSH)
gpg> addkey
# → (11) ECC (set own capabilities) -> убрать S, E, оставить A
# → expires: 1y
gpg> save
```

**Шаг 3: Резервное копирование и отзыв**
```bash
# Экспорт публичного ключа
gpg --export -a <Key_ID> > public.asc

# Экспорт приватного ключа (шифрование!)
gpg --export-secret-keys -a <Key_ID> > private_full.asc
gpg --symmetric --cipher-algo AES256 private_full.asc
# → private_full.asc.gpg (хранить в зашифрованном виде)

# Генерация сертификата отзыва
gpg --gen-revoke <Key_ID> > revoke.asc
# → Хранить отдельно от ключа!
```

**Шаг 4: Публикация и доверие**
```bash
# Отправка на ключевой сервер
gpg --send-keys <Key_ID>

# Подтверждение ключей коллег (WoT)
gpg --receive-keys <Other_Key_ID>
gpg --sign-key <Other_Key_ID>
# → Установить уровень доверия: trust level 4 (Full)
```

**Шаг 5: Проверка работоспособности**
```bash
# Проверка отпечатков
gpg --list-keys --with-fingerprint --keyid-format LONG

# Проверка совместимости с RFC 9580
gpg --version | grep -i aead

# Тест: шифрование и расшифровка
echo "test" | gpg --encrypt --armor --recipient <Key_ID> \
  | gpg --decrypt
# → test
```

### Cleartext signatures и текстовые форматы

**Cleartext signature (подпись в открытом тексте):**
```bash
# Подпись с сохранением исходного текста
gpg --clearsign --output message.asc message.txt
# → Файл содержит исходный текст и ASCII-армированную подпись
```

**Detached signature (отдельная подпись):**
```bash
# Создание отдельного сигнатурного файла
gpg --detach-sign --armor --output document.pdf.asc document.pdf
# → Проверка: gpg --verify document.pdf.asc document.pdf
```

**ASCII-армирование (base64):**
```bash
# Шифрование с преобразованием в ASCII
gpg --encrypt --armor --recipient recipient@example.com document.pdf
# → Результат: document.pdf.asc (текстовый файл)
```

### Шифрование бэкапов и архивов

**Сценарий: шифрование бэкапа баз данных**
```bash
# Генерация одноразового ключа для бэкапа
gpg --symmetric --cipher-algo AES256 --batch \
  --passphrase "RANDOM_$(openssl rand -hex 32)" \
  --output backup.tar.gz.gpg backup.tar.gz

# Расшифровка при восстановлении
gpg --decrypt --batch --passphrase "$PASSPHRASE" \
  backup.tar.gz.gpg | tar -xzf -
```

**Сценарий: шифрование с помощью публичного ключа администратора**
```bash
# Шифрование бэкапа для администратора
gpg --encrypt --trust-model always \
  --recipient admin@company.com \
  --output backup.tar.gz.gpg backup.tar.gz

# Расшифровка администратором
gpg --decrypt backup.tar.gz.gpg | tar -xzf -
```
