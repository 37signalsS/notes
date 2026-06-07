# Приватный Apt-репозиторий с reprepro: Практические сценарии

## Определения

Ниже приведены термины, непосредственно относящиеся к процессам развертывания и эксплуатации внутренних репозиториев программного обеспечения.

**Публикация пакета** — регламентированный процесс добавления файла формата `.deb` (Debian Package) в структуру репозитория, включающий автоматическое обновление индексных файлов и наложение цифровой подписи GPG (GNU Privacy Guard).

**Клиентская настройка** — комплекс мер по конфигурации менеджера пакетов APT (Advanced Package Tool) на целевых машинах, включающий установку доверенного ключа и добавление записи в список источников `sources.list`.

Подробное описание архитектуры и базовых терминов приведено в документе **[Определения и концепции](./definitions_and_concepts.md)**.

---

## Основные концепции

### Типовой рабочий процесс

Жизненный цикл управления репозиторием включает следующие этапы:

1. **Подготовка безопасности** — генерация ключевой пары RSA (Rivest-Shamir-Adleman) разрядностью 4096 бит.
2. **Конфигурация инфраструктуры** — описание дистрибутивов, архитектур процессоров и компонентов в файле `conf/distributions`.
3. **Наполнение** — добавление пакетов через команду `reprepro includedeb`, что инициирует обновление метаданных.
4. **Доставка** — публикация статического контента через веб-сервер (Nginx или Apache).
5. **Валидация** — проверка доступности пакетов на клиентской стороне после обновления кэша.

### Требования к среде

- Наличие установленного веб-сервера для раздачи статических файлов.
- Изолированное хранилище для секретного ключа GPG.
- Настроенная система автоматизации (CI/CD — Continuous Integration / Continuous Deployment) для исключения ручных ошибок при публикации.

---

## Практические сценарии

### Сценарий 1: Развертывание репозитория с нуля

#### 1. Установка и инициализация

```bash
sudo apt-get update && sudo apt-get install reprepro
mkdir -p ~/my-repo/conf && cd ~/my-repo
```

#### 2. Управление ключами GPG

Для подписи репозитория необходимо сгенерировать идентификатор (ID).

```bash
# Генерация ключа (рекомендуется RSA 4096 бит)
gpg --gen-key

# Определение LONG ID ключа
gpg --list-secret-keys --keyid-format LONG

# Экспорт публичной части для клиентов
gpg --export -a "ID_ВАШЕГО_КЛЮЧА" > ~/my-repo/repo.key
```

#### 3. Настройка дистрибутивов

Создайте конфигурацию в файле `~/my-repo/conf/distributions`:

```bash
cat > ~/my-repo/conf/distributions << 'EOF'
Origin: MyRepo
Label: My Private APT Repository
Codename: focal
Architectures: amd64 arm64
Components: main
Description: My private package repository for Ubuntu 20.04
SignWith: ID_ВАШЕГО_КЛЮЧА

Codename: noble
Architectures: amd64 arm64
Components: main
Description: My private package repository for Ubuntu 24.04
SignWith: ID_ВАШЕГО_КЛЮЧА
EOF
```

#### 4. Публикация через веб-сервер Nginx

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
    }

    # Запрет доступа к служебным данным reprepro
    location ~ /conf { deny all; }
    location ~ /dbs { deny all; }
}
EOF

sudo ln -s /etc/nginx/sites-available/repo /etc/nginx/sites-enabled/repo
sudo nginx -t && sudo systemctl reload nginx
```

#### 5. Конфигурация клиента

На целевом сервере выполните:

1. Импорт ключа в доверенное хранилище:

   ```bash
   sudo cp /tmp/repo.key /etc/apt/keyrings/my-repo.gpg
   ```

2. Добавление репозитория в `/etc/apt/sources.list.d/my-repo.list`:

   ```bash
   echo "deb [signed-by=/etc/apt/keyrings/my-repo.gpg] http://repo.your.domain focal main" | \
       sudo tee /etc/apt/sources.list.d/my-repo.list
   ```

---

### Сценарий 2: Регламентные операции с пакетами

```bash
cd ~/my-repo

# Добавление нового пакета в дистрибутив
reprepro includedeb focal /path/to/app_2.0_amd64.deb

# Проверка целостности базы данных и файлов
reprepro verify

# Просмотр списка всех пакетов в конкретном релизе
reprepro list focal
```

---

### Сценарий 3: Интеграция с GitHub Actions (CI/CD)

Пример автоматизации доставки через SSH (Secure Shell).

```yaml
name: Publish to APT Repository
on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - name: Download artifact
        uses: actions/download-release-artifact@v3
        with:
          name: app-amd64.deb
      - name: Deploy via SSH
        run: |
          echo "${{ secrets.SSH_PRIVATE_KEY }}" > /tmp/id_rsa
          chmod 600 /tmp/id_rsa
          scp -i /tmp/id_rsa app-amd64.deb user@repo.server:/tmp/
          ssh -i /tmp/id_rsa user@repo.server \
              "reprepro -b /home/user/my-repo includedeb focal /tmp/app-amd64.deb"
```

---

## Дополнительная информация

### Диагностика и отладка

При возникновении ошибок на стороне клиента («The following signatures were invalid») проверьте соответствие ID ключа в `conf/distributions` и фактически использованного при подписи.

### Связанные документы

- **[Определения и концепции](./definitions_and_concepts.md)** — архитектура и параметры `reprepro`.
- **[Дополнительная информация](./advanced_topics.md)** — безопасность ключей и сравнение с `aptly`.
- **[Apt Pinning](../deb_apt_pinning.md)** — управление приоритетами установленных пакетов.
- **[Управление репозиториями DEB](../deb_repositories_sources_list.md)** — общие принципы настройки источников.
