# Создание приватного Apt-репозитория с reprepro

## Определения

**`reprepro`** — утилита для создания и управления репозиториями `.deb` пакетов (Debian, Ubuntu). Инструмент позволяет организовать доставку собственного ПО или создать зеркало существующих пакетов.

Эта заметка является частью цикла статей по [управлению пакетами в Linux](../../Linux/PackageManagement/linux_package_management_overview.md).

## Основные понятия

### Подпись репозитория (GPG)

Apt-репозитории должны быть подписаны GPG-ключом. Это криптографическая мера для проверки подлинности пакетов клиентами. Без доверенного ключа `apt` откажется устанавливать пакеты.

### Конфигурация дистрибутивов

Файл `conf/distributions` — основной конфигурационный файл `reprepro`. Он описывает обслуживаемые репозиторием дистрибутивы (`Codename`), компоненты (`Components`) и архитектуры (`Architectures`).

*   `Origin`, `Label`: Идентификаторы репозитория для клиента (например, для [настройки приоритетов Apt Pinning](./deb_apt_pinning.md)).
*   `Codename`: Кодовое имя релиза ОС (например, `focal` для Ubuntu 20.04).
*   `SignWith`: ID GPG-ключа для подписи репозитория.

## Практические сценарии

### Настройка репозитория с нуля

### Шаг 1: Установка `reprepro` и создание структуры

Установка утилиты и базовой структуры директорий.

```bash
sudo apt-get update
sudo apt-get install reprepro

mkdir -p my-repo/conf
```

### Шаг 2: Создание GPG-ключа для подписи

Генерация нового GPG-ключа.

```bash
gpg --gen-key
```

Определение ID ключа:

```bash
# Вывести список секретных ключей в длинном формате ID
gpg --list-secret-keys --keyid-format LONG
```

Экспорт публичной части ключа (`repo.key`) для распространения на клиентские машины. Замените `<ID_ВАШЕГО_GPG_КЛЮЧА>` на реальный ID.

```bash
gpg --export -a "<ID_ВАШЕГО_GPG_КЛЮЧА>" > my-repo/repo.key
```

### Шаг 3: Конфигурация репозитория

Создание `my-repo/conf/distributions`. Замените `<ID_ВАШЕГО_GPG_КЛЮЧА>` на свой.

```
# my-repo/conf/distributions
Origin: MyRepo
Label: My Private APT Repository
Codename: focal
Architectures: amd64
Components: main
Description: My private package repository
SignWith: <ID_ВАШЕГО_GPG_КЛЮЧА>
```

### Шаг 4: Добавление пакетов

Добавление подготовленного `.deb` пакета в репозиторий. Перейдите в директорию `my-repo`.

```bash
cd my-repo
reprepro includedeb focal /path/to/your/package_1.0_amd64.deb
```
`reprepro` автоматически создает структуру (dists, pool) и обновляет метаданные, запросив пароль от GPG-ключа.

### Шаг 5: Публикация репозитория (Nginx)

Репозиторий состоит из статических файлов и может быть опубликован любым веб-сервером. Пример конфигурации Nginx:

```nginx
server {
    listen 80;
    server_name repo.your.domain;
    root /path/to/your/my-repo; # Путь к корневой директории репозитория

    location / {
        autoindex on; # Включение листинга директорий для просмотра
    }
}
```
Для защиты репозитория можно настроить [аутентификацию по клиентским SSL-сертификатам](../../WebServers/Nginx/ssl_client_certificate_authentication.md).

### Шаг 6: Настройка клиента

Для использования репозитория клиентской машиной:

1.  **Скопируйте публичный GPG-ключ (`repo.key`)** на клиентскую машину и добавьте его в доверенные:
    ```bash
    sudo cp repo.key /etc/apt/trusted.gpg.d/my-repo.asc
    ```

2.  **Создайте файл списка источников** `/etc/apt/sources.list.d/my-repo.list`:
    ```
    # /etc/apt/sources.list.d/my-repo.list
    deb [arch=amd64] http://repo.your.domain focal main
    ```

3.  **Обновите список пакетов:**
    ```bash
    sudo apt-get update
    ```
Теперь пакеты из приватного репозитория доступны для установки: `sudo apt-get install your-package`.