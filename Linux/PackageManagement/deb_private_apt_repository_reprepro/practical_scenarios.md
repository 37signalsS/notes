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
- **Энтропия**: В виртуализированных или облачных средах рекомендуется установить `haveged` или `rng-tools` для предотвращения блокировок при генерации GPG-ключей.
- **Безопасность**: Файлы в директории `conf/` и база данных `dbs/` содержат чувствительную информацию и должны быть исключены из раздачи веб-сервером.

---

## Практические сценарии

### Сценарий 1: Развертывание и базовая настройка

#### 1. Установка и подготовка структуры

```bash
sudo apt-get update && sudo apt-get install -y reprepro gnupg
mkdir -p ~/my-repo/{conf,incoming,dists,pool} && cd ~/my-repo
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

Извлечение ID ключа для конфигурации:
```bash
KEY_ID=$(gpg --list-secret-keys --keyid-format LONG | grep 'sec' | awk '{print $2}' | cut -d'/' -f2)
echo $KEY_ID
# → ABCDEF1234567890 (пример)
```

#### 3. Настройка дистрибутивов

Создайте файл `conf/distributions`, описывающий целевые ОС (например, Debian 12 и Ubuntu 24.04):

```bash
cat > conf/distributions << EOF
Origin: CompanyCorp
Label: Internal Repository
Codename: bookworm
Architectures: amd64 arm64 source
Components: main
Description: Internal tools for Debian 12
SignWith: $KEY_ID

Codename: noble
Architectures: amd64 arm64 source
Components: main
Description: Internal tools for Ubuntu 24.04
SignWith: $KEY_ID
EOF
```

#### 4. Конфигурация Nginx

Пример защищенной конфигурации:

```nginx
server {
    listen 80;
    server_name repo.example.com;
    root /home/user/my-repo;

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

---

### Сценарий 2: Управление пакетами

#### Добавление пакета вручную
```bash
# Добавление бинарного .deb пакета в дистрибутив noble
reprepro includedeb noble /tmp/my-app_1.0_amd64.deb
# → Exporting indices...

# Добавление из файла .changes (включая исходный код)
reprepro include noble /tmp/my-app_1.0_amd64.changes
```

#### Удаление пакета
```bash
# Удаление конкретного пакета по имени
reprepro remove noble my-app
# → Deleting my-app...
```

#### Листинг и диагностика
```bash
# Просмотр всех пакетов в дистрибутиве
reprepro list noble
# → noble|main|amd64: my-app 1.0

# Проверка целостности базы данных и файлов в пуле
reprepro verify
```

---

### Сценарий 3: Селективное зеркалирование (Updates)

Механизм `Updates` позволяет импортировать выбранные пакеты из внешних источников.

1. Создайте `conf/updates`:
```bash
cat > conf/updates << EOF
Name: upstream-security
Method: http://security.ubuntu.com/ubuntu
VerifyRelease: 0x871920D1991BC93C # Официальный ключ Ubuntu
Suite: noble-security
Components: main
FilterFormula: Package (== nginx) | Package (== curl)
EOF
```

2. Обновите `conf/distributions`, добавив поле `Update`:
```text
Codename: noble
...
Update: upstream-security
```

3. Запустите синхронизацию:
```bash
reprepro update noble
```

---

### Сценарий 4: Автоматизация импорта (Incoming)

Использование директории `incoming/` для автоматического разбора пакетов, загруженных по SSH или FTP.

1. Настройте `conf/incoming`:
```bash
cat > conf/incoming << EOF
Name: default
IncomingDir: incoming
TempDir: tmp
Allow: noble>main bookworm>main
Cleanup: on_accept
EOF
```

2. Выполните обработку:
```bash
reprepro processincoming default
```

---

### Сценарий 5: Настройка клиента (Modern APT)

Современный стандарт (Debian 12+, Ubuntu 22.04+) запрещает использование `apt-key`.

#### 1. Экспорт ключа на сервере
```bash
gpg --export --armor $KEY_ID > ~/my-repo/repo-key.pub
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

---

## Дополнительная информация

### Типовые ошибки

- **"Not enough entropy"**: Если генерация ключа или подписание индексов зависают, убедитесь, что в системе запущен `haveged` или `rng-tools`.
- **"Database is locked"**: `reprepro` не поддерживает конкурентный доступ. Убедитесь, что ни одна другая команда `reprepro` не запущена в данный момент.
- **"GPG error: The following signatures were invalid"**: Проверьте, что на клиенте установлен корректный публичный ключ и время на сервере/клиенте синхронизировано через NTP.

### Связанные документы

- **[Определения и концепции](./definitions_and_concepts.md)** — архитектура, структура каталогов и описание файлов конфигурации.
- **[Дополнительная информация](./advanced_topics.md)** — продвинутое управление GPG, обслуживание базы данных и сравнение с аналогами.
- **[Apt Pinning](../deb_apt_pinning.md)** — управление приоритетами для гарантированной установки пакетов из внутреннего репозитория.
- **[Nginx: Настройка репозитория](../../../WebServers/Nginx/Scenarios/secure_apt_repository_guide.md)** — детальный пример конфигурации веб-сервера с mTLS.
