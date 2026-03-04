# Создание приватного Apt-репозитория с reprepro

## Определения

**`reprepro`** — утилита для создания и управления репозиториями `.deb` пакетов (Debian, Ubuntu). Позволяет организовать доставку собственного ПО, создать зеркало существующих пакетов или поддерживать приватный репозиторий для внутренней инфраструктуры.

**GPG-подпись репозитория** — криптографическая подпись метаданных репозитория (`Release`, `InRelease` файлов). Гарантирует подлинность пакетов и защищает от MitM-атак. Без доверенного ключа `apt` откажется устанавливать пакеты.

**Дистрибутив (в контексте reprepro)** — логическое разделение репозитория по версиям ОС (например, `focal`, `bullseye`). Один экземпляр `reprepro` может обслуживать несколько дистрибутивов.

**Компонент** — категория пакетов внутри дистрибутива (например, `main`, `contrib`, `non-free`).

## Основные понятия

### Архитектура репозитория

```
my-repo/
├── conf/
│   └── distributions      # Конфигурация дистрибутивов
├── dbs/                   # Внутренняя база данных reprepro
├── dists/                 # Метаданные для каждого дистрибутива
│   └── <codename>/
│       ├── main/
│       └── Release
├── pool/                  # Фактические .deb пакеты
│   └── main/
│       └── <package>/
└── <codename>/            # Символические ссылки для совместимости
```

### Конфигурация дистрибутивов

Файл `conf/distributions` — основной конфигурационный файл `reprepro`. Описывает обслуживаемые репозиторием дистрибутивы.

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| **Origin** | Идентификатор источника | `MyRepo` |
| **Label** | Человекочитаемое имя | `My Private APT Repository` |
| **Codename** | Кодовое имя релиза ОС | `focal`, `bullseye` |
| **Architectures** | Поддерживаемые архитектуры | `amd64`, `arm64`, `source` |
| **Components** | Компоненты репозитория | `main`, `contrib` |
| **Description** | Описание репозитория | `My private package repository` |
| **SignWith** | ID GPG-ключа для подписи | `ABCDEF1234567890` |
| **NotAutomatic** | Предупреждение при установке | `yes` (опционально) |

### Интеграция с Apt Pinning

Параметры `Origin` и `Label` из конфигурации `reprepro` используются для идентификации репозитория в [Apt Pinning](./deb_apt_pinning.md). Это позволяет управлять приоритетами пакетов из приватного репозитория.

## Практические сценарии

### Сценарий 1: Настройка репозитория с нуля

#### Шаг 1: Установка `reprepro` и создание структуры

```bash
sudo apt-get update
sudo apt-get install reprepro

# Создать директорию репозитория
mkdir -p ~/my-repo/conf
cd ~/my-repo
```

#### Шаг 2: Создание GPG-ключа для подписи

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

#### Шаг 3: Конфигурация репозитория

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

#### Шаг 4: Добавление пакетов

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

#### Шаг 5: Публикация репозитория (Nginx)

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

#### Шаг 6: Настройка клиента

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

### Сценарий 2: Обновление репозитория

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

### Сценарий 3: Автоматизация с CI/CD

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

### Сценарий 4: Синхронизация с официальным репозиторием

```bash
# Создать зеркало выбранных пакетов
reprepro includepattern focal "nginx-*"

# Импортировать пакет из другого репозитория
reprepro pull focal other-repo focal main nginx
```

## Дополнительная информация

### Управление ключами

```bash
# Проверить срок действия ключа
gpg --list-keys --with-colons | grep -E "^pub|^fpr"

# Продлить срок действия ключа
gpg --edit-key ABCDEF1234567890
> expire
> save

# Отозвать ключ (если скомпрометирован)
gpg --gen-revoke ABCDEF1234567890
```

### Отладка и диагностика

```bash
# Проверить конфигурацию
reprepro -V check

# Показать информацию о пакете в репозитории
reprepro show focal package-name

# Показать все пакеты в репозитории
reprepro list focal

# Экспорт метаданных для отладки
reprepro export focal
```

### Безопасность

1. **Храните секретный ключ в безопасности** — ограничьте доступ к файлу `~/.gnupg/`
2. **Используйте отдельный ключ для репозитория** — не используйте личный ключ
3. **Регулярно обновляйте ключ** — меняйте ключ каждые 2-3 года
4. **Настройте мониторинг** — отслеживайте попытки несанкционированного доступа
5. **Используйте HTTPS** — публикуйте репозиторий через HTTPS для защиты трафика

### Альтернативы reprepro

| Инструмент | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **aptly** | Современный, REST API, снапшоты | Сложнее в настройке |
| **debmirror** | Зеркалирование существующих репо | Не для собственных пакетов |
| **simple-repo** | Минималистичный | Нет подписи, ограниченный функционал |

### Связанные темы

* **[Управление репозиториями DEB](./deb_repositories_sources_list.md)** — файл `sources.list`
* **[Apt Pinning](./deb_apt_pinning.md)** — управление приоритетами пакетов
* **[Сборка пакетов](./package_building.md)** — создание собственных DEB-пакетов
* **[Локальное зеркало репозитория](./local_repository_mirror.md)** — создание зеркал для APT
