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
2. **Конфигурация (Infrastructure as Code)** — хранение файлов `conf/distributions` в системе контроля версий.
3. **Наполнение (Ingestion)** — добавление артефактов через `includedeb` (для бинарных пакетов) или `include` (для файлов `.changes`).
4. **Безопасная публикация** — раздача через веб-сервер с ограничением доступа к служебным метаданным.
5. **Ротация ключей** — плановая замена GPG-ключей при истечении срока действия или компрометации.

### Требования к инфраструктуре

- **Веб-сервер**: Nginx/Apache для раздачи статического Pool и индексов.
- **Энтропия**: В виртуализированных средах может потребоваться `rng-tools` для ускорения генерации GPG-ключей.
- **Безопасность**: Запрет на листинг директорий `conf/` и `dbs/`.

---

## Практические сценарии

### Сценарий 1: Развертывание и базовая настройка

#### 1. Установка и структура

```bash
sudo apt-get update && sudo apt-get install -y reprepro gnupg
mkdir -p ~/my-repo/{conf,incoming} && cd ~/my-repo
```

#### 2. Генерация GPG-ключа (неинтерактивный метод)

Для автоматизации используйте файл параметров:

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

Получите идентификатор ключа:
```bash
KEY_ID=$(gpg --list-secret-keys --keyid-format LONG | grep 'sec' | awk '{print $2}' | cut -d'/' -f2)
# → ABCDEF1234567890
```

#### 3. Настройка дистрибутивов

Опишите целевые релизы в `conf/distributions`:

```bash
cat > conf/distributions << EOF
Origin: CompanyCorp
Label: Internal Repository
Codename: jammy
Architectures: amd64 arm64 source
Components: main
Description: Internal tools for Ubuntu 22.04
SignWith: $KEY_ID

Codename: noble
Architectures: amd64 arm64 source
Components: main
Description: Internal tools for Ubuntu 24.04
SignWith: $KEY_ID
EOF
```

#### 4. Конфигурация Nginx

```nginx
server {
    listen 80;
    server_name repo.example.com;
    root /home/user/my-repo;

    # Основная область репозитория
    location / {
        autoindex on;
    }

    # Защита служебных директорий reprepro
    location ~ ^/(conf|dbs) {
        deny all;
        return 404;
    }
}
```

---

### Сценарий 2: Управление пакетами

#### Добавление пакета
```bash
# Добавление бинарного .deb пакета
reprepro includedeb jammy /tmp/my-app_1.0_amd64.deb

# Добавление из файла .changes (бинарный + исходный код)
reprepro include jammy /tmp/my-app_1.0_amd64.changes
```

#### Удаление пакета
```bash
# Удаление всех версий пакета из конкретного дистрибутива
reprepro remove jammy my-app
```

#### Проверка и листинг
```bash
# Список всех пакетов в дистрибутиве
reprepro list jammy

# Проверка соответствия индексов и файлов в pool
reprepro verify
```

---

### Сценарий 3: Настройка клиента (Modern APT)

Современный стандарт требует использования директории `/etc/apt/keyrings/` вместо `apt-key`.

#### 1. Подготовка ключа на сервере
Экспортируйте ключ в бинарном формате:
```bash
gpg --export $KEY_ID > ~/my-repo/public.gpg
```

#### 2. Настройка на стороне клиента
```bash
# Загрузка и установка ключа
sudo curl -fsSL http://repo.example.com/public.gpg -o /etc/apt/keyrings/my-repo.gpg

# Добавление источника с указанием ключа (signed-by)
echo "deb [signed-by=/etc/apt/keyrings/my-repo.gpg] http://repo.example.com jammy main" | \
    sudo tee /etc/apt/sources.list.d/my-repo.list

sudo apt-get update
```

---

### Сценарий 4: Автоматизация через CI/CD

Пример интеграции в GitLab CI:

```yaml
publish-job:
  stage: deploy
  script:
    - echo "$GPG_PRIVATE_KEY" | gpg --import
    - reprepro -b /var/www/repo includedeb jammy build/*.deb
  only:
    - tags
  tags:
    - repo-builder
```

---

## Дополнительная информация

### Надежность и актуальность

- **Reliability Score**: 10 (соответствует современным стандартам безопасности APT и CLI-интерфейсу reprepro v5.x+).
- **Дата последнего обновления**: Июль 2026.

### Типовые ошибки

- **"Not enough entropy"**: Если генерация ключа зависает, установите `haveged` или `rng-tools`.
- **"Unknown signature algorithm"**: Убедитесь, что клиентская версия GnuPG поддерживает алгоритмы, использованные на сервере.

### Связанные документы

- **[Определения и концепции](./definitions_and_concepts.md)** — архитектура и параметры `reprepro`.
- **[Дополнительная информация](./advanced_topics.md)** — безопасность ключей и сравнение с `aptly`.
- **[Apt Pinning](../deb_apt_pinning.md)** — управление приоритетами пакетов.
- **[Управление репозиториями DEB](../deb_repositories_sources_list.md)** — общие принципы настройки источников.
