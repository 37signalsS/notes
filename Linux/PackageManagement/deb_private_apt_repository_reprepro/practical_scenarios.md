# Приватный Apt-репозиторий с reprepro: Практические сценарии

## Сценарий 1: Настройка репозитория с нуля

### Шаг 1: Установка `reprepro` и создание структуры

```bash
sudo apt-get update
sudo apt-get install reprepro

# Создать директорию репозитория
mkdir -p ~/my-repo/conf
cd ~/my-repo
```

### Шаг 2: Создание GPG-ключа для подписи

```bash
# Генерация ключа (интерактивно)
gpg --gen-key

# Определение ID ключа (длинный формат)
gpg --list-secret-keys --keyid-format LONG

# Пример вывода:
# sec   rsa4096/ABCDEF1234567890 2024-01-01 [SC]
#       ABCDEF1234567890...
# uid                 [ultimate] Your Name <you@example.com>

# Экспорт публичного ключа для распространения
gpg --export -a "ABCDEF1234567890" > ~/my-repo/repo.key
```

**Параметры ключа (рекомендации):**

- **Тип:** RSA
- **Размер:** 4096 бит
- **Срок действия:** 2-3 года (или без ограничения)
- **Comment:** `APT Repository Key`

### Шаг 3: Конфигурация репозитория

Создание `~/my-repo/conf/distributions`:

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

### Шаг 4: Добавление пакетов

```bash
cd ~/my-repo

# Добавить .deb пакет в репозиторий
reprepro includedeb focal /path/to/your/package_1.0_amd64.deb

# Добавить пакет с исходниками
reprepro includesource focal /path/to/your/package_1.0.dsc

# Добавить несколько пакетов
reprepro includedeb focal *.deb

# Удалить пакет из репозитория
reprepro removepackage focal package-name
```

`reprepro` автоматически:

- Создаёт структуру `dists/` и `pool/`
- Обновляет метаданные (`Packages.gz`, `Release`)
- Подписывает репозиторий GPG-ключом

### Шаг 5: Публикация репозитория (Nginx)

Репозиторий состоит из статических файлов и может быть опубликован любым веб-сервером.

**Конфигурация Nginx:**

```bash
sudo apt-get install nginx

sudo tee /etc/nginx/sites-available/repo << 'EOF'
server {
    listen 80;
    server_name repo.your.domain;
    root /home/user/my-repo;  # Путь к корневой директории репозитория

    location / {
        autoindex on;         # Включение листинга директорий
        autoindex_format html;
        autoindex_localtime on;
    }

    # Блокировка доступа к служебным файлам
    location ~ /conf { deny all; }
    location ~ /dbs { deny all; }
}
EOF

sudo ln -s /etc/nginx/sites-available/repo /etc/nginx/sites-enabled/repo
sudo nginx -t && sudo systemctl reload nginx
```

**Конфигурация Apache:**

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

### Шаг 6: Настройка клиента

1. **Скопируйте публичный GPG-ключ (`repo.key`)** на клиентскую машину:

    ```bash
    scp user@repo.server:~/my-repo/repo.key /tmp/
    ```

2. **Добавьте ключ в доверенные** (современный метод):

    ```bash
    sudo cp /tmp/repo.key /etc/apt/keyrings/my-repo.gpg
    ```

3. **Создайте файл списка источников** `/etc/apt/sources.list.d/my-repo.list`:

    ```bash
    echo "deb [signed-by=/etc/apt/keyrings/my-repo.gpg] http://repo.your.domain focal main" | \
        sudo tee /etc/apt/sources.list.d/my-repo.list
    ```

4. **Обновите список пакетов:**

    ```bash
    sudo apt-get update
    ```

5. **Установите пакет из приватного репозитория:**

    ```bash
    sudo apt-get install your-package
    ```

---

## Сценарий 2: Обновление репозитория

```bash
cd ~/my-repo

# Добавить новую версию пакета
reprepro includedeb focal new-package_2.0_amd64.deb

# Удалить старую версию (опционально)
reprepro removepackage focal old-package

# Проверить целостность репозитория
reprepro verify

# Показать содержимое репозитория
reprepro list focal
```

---

## Сценарий 3: Автоматизация с CI/CD

**Пример скрипта для публикации пакетов:**

```bash
#!/bin/bash
# publish-to-repo.sh

set -e

REPO_DIR="/home/user/my-repo"
DISTRIBUTION="focal"
PACKAGE_PATH="$1"

if [ -z "$PACKAGE_PATH" ]; then
    echo "Usage: $0 <package.deb>"
    exit 1
fi

cd "$REPO_DIR"

# Добавить пакет
reprepro includedeb "$DISTRIBUTION" "$PACKAGE_PATH"

# Обновить права доступа
chmod -R g+r "$REPO_DIR"

echo "Package published successfully"
```

**Интеграция с GitHub Actions:**

```yaml
# .github/workflows/publish-repo.yml
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
          # Настроить SSH-ключ для доступа к серверу
          echo "${{ secrets.SSH_KEY }}" > /tmp/key
          chmod 600 /tmp/key

          # Скопировать пакет и опубликовать
          scp -i /tmp/key package-amd64.deb user@repo.server:/tmp/
          ssh -i /tmp/key user@repo.server \
              "reprepro includedeb focal /tmp/package-amd64.deb"
```

---

## Сценарий 4: Синхронизация с официальным репозиторием

```bash
# Создать зеркало выбранных пакетов
reprepro includepattern focal "nginx-*"

# Импортировать пакет из другого репозитория
reprepro pull focal other-repo focal main nginx
```

---

## Ссылки

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Дополнительная информация](./advanced_topics.md) — управление ключами, безопасность
