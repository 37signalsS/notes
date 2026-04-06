# Приватный Apt-репозиторий с reprepro: Практические сценарии

## Определения

**Публикация пакета** — процесс добавления `.deb`-пакета в репозиторий, обновления метаданных и подписи репозитория GPG-ключом.

**Клиентская настройка** — конфигурация APT на клиентской машине для работы с приватным репозиторием (доверенный ключ, sources.list).

Подробные определения и концепции: [Определения и концепции](./definitions_and_concepts.md).

## Основные понятия

### Рабочий процесс

1. **Создание GPG-ключа** → RSA 4096 бит, срок 2-3 года
2. **Конфигурация `conf/distributions`** → определение дистрибутивов, архитектур, компонентов
3. **Добавление пакетов** → `reprepro includedeb`, автоматическое обновление метаданных
4. **Публикация** → веб-сервер (Nginx/Apache) со статическими файлами
5. **Клиентская настройка** → установка ключа, добавление источника, `apt-get update`

### Требования к инфраструктуре

- Веб-сервер (Nginx/Apache) или файловый доступ
- GPG-ключ для подписи репозитория
- CI/CD для автоматизации публикации

## Практические сценарии

### Сценарий 1: Настройка репозитория с нуля

#### Установка и создание структуры

```bash
sudo apt-get update && sudo apt-get install reprepro
mkdir -p ~/my-repo/conf && cd ~/my-repo
```

#### Создание GPG-ключа

```bash
# Генерация ключа (интерактивно)
gpg --gen-key

# Определение ID ключа
gpg --list-secret-keys --keyid-format LONG

# Экспорт публичного ключа
gpg --export -a "ABCDEF1234567890" > ~/my-repo/repo.key
```

Параметры ключа: RSA 4096 бит, срок 2-3 года, comment `APT Repository Key`.

#### Конфигурация репозитория

Файл `~/my-repo/conf/distributions`:

```bash
cat > ~/my-repo/conf/distributions << 'EOF'
Origin: MyRepo
Label: My Private APT Repository
Codename: focal
Architectures: amd64 arm64
Components: main
Description: My private package repository for Ubuntu 20.04
SignWith: ABCDEF1234567890

Codename: jammy
Architectures: amd64 arm64
Components: main
Description: My private package repository for Ubuntu 22.04
SignWith: ABCDEF1234567890

Codename: bullseye
Architectures: amd64
Components: main
Description: My private package repository for Debian 11
SignWith: ABCDEF1234567890
EOF
```

#### Добавление пакетов

```bash
cd ~/my-repo

# Добавить .deb пакет
reprepro includedeb focal /path/to/package_1.0_amd64.deb

# Добавить пакет с исходниками
reprepro includesource focal /path/to/package_1.0.dsc

# Удалить пакет
reprepro removepackage focal package-name
```

`reprepro` автоматически создаёт `dists/` и `pool/`, обновляет `Packages.gz` и `Release`, подписывает репозиторий.

#### Публикация (Nginx)

```bash
sudo apt-get install nginx

sudo tee /etc/nginx/sites-available/repo << 'EOF'
server {
    listen 80;
    server_name repo.your.domain;
    root /home/user/my-repo;

    location / {
        autoindex on;
        autoindex_format html;
        autoindex_localtime on;
    }

    location ~ /conf { deny all; }
    location ~ /dbs { deny all; }
}
EOF

sudo ln -s /etc/nginx/sites-available/repo /etc/nginx/sites-enabled/repo
sudo nginx -t && sudo systemctl reload nginx
```

Блокировка `/conf` и `/dbs` обязательна — там хранятся конфиденциальные данные.

#### Публикация (Apache)

```bash
sudo apt-get install apache2

sudo tee /etc/apache2/sites-available/repo.conf << 'EOF'
<VirtualHost *:80>
    ServerName repo.your.domain
    DocumentRoot /home/user/my-repo

    <Directory /home/user/my-repo>
        Options +Indexes
        Require all granted
    </Directory>
</VirtualHost>
EOF

sudo a2ensite repo.conf
sudo apache2ctl configtest && sudo systemctl reload apache2
```

#### Настройка клиента

1. Скопировать публичный ключ: `scp user@repo.server:~/my-repo/repo.key /tmp/`
2. Добавить в доверенные: `sudo cp /tmp/repo.key /etc/apt/keyrings/my-repo.gpg`
3. Создать `/etc/apt/sources.list.d/my-repo.list`:

    ```bash
    echo "deb [signed-by=/etc/apt/keyrings/my-repo.gpg] http://repo.your.domain focal main" | \
        sudo tee /etc/apt/sources.list.d/my-repo.list
    ```

4. Обновить и установить: `sudo apt-get update && sudo apt-get install your-package`

### Сценарий 2: Обновление репозитория

```bash
cd ~/my-repo

# Добавить новую версию
reprepro includedeb focal new-package_2.0_amd64.deb

# Проверить целостность
reprepro verify

# Показать содержимое
reprepro list focal
```

### Сценарий 3: Автоматизация с CI/CD

Скрипт `publish-to-repo.sh`:

```bash
#!/bin/bash
set -e

REPO_DIR="/home/user/my-repo"
DISTRIBUTION="focal"
PACKAGE_PATH="$1"

[ -z "$PACKAGE_PATH" ] && { echo "Usage: $0 <package.deb>"; exit 1; }

cd "$REPO_DIR"
reprepro includedeb "$DISTRIBUTION" "$PACKAGE_PATH"
chmod -R g+r "$REPO_DIR"
echo "Package published successfully"
```

Интеграция с GitHub Actions:

```yaml
name: Publish to APT Repository
on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Download .deb package
        uses: actions/download-release-artifact@v3
        with:
          name: package-amd64.deb
      - name: Publish to repository
        run: |
          echo "${{ secrets.SSH_KEY }}" > /tmp/key
          chmod 600 /tmp/key
          scp -i /tmp/key package-amd64.deb user@repo.server:/tmp/
          ssh -i /tmp/key user@repo.server \
              "reprepro includedeb focal /tmp/package-amd64.deb"
```

### Сценарий 4: Синхронизация с официальным репозиторием

```bash
# Зеркало выбранных пакетов
reprepro includepattern focal "nginx-*"

# Импорт из другого репозитория
reprepro pull focal other-repo focal main nginx
```

## Дополнительная информация

Связанные файлы: [Определения и концепции](./definitions_and_concepts.md) (архитектура, конфигурация), [Дополнительная информация](./advanced_topics.md) (управление ключами, безопасность, альтернативы).
