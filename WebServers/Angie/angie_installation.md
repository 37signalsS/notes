# Установка Angie

## Определения

**Angie** — эффективный и масштабируемый веб-сервер, форк Nginx, созданный для расширения функциональности при сохранении полной обратной совместимости. Продукт включен в реестр российского ПО и оптимизирован для работы в высоконагруженных системах и импортозамещающих инфраструктурах.

## Основные концепции

Развертывание Angie адаптировано под различные сценарии эксплуатации:

1. **Установка из официальных репозиториев:** Рекомендуемый метод для серверных ОС (AlmaLinux, Ubuntu, Debian), а также специализированных российских дистрибутивов (**Astra Linux**, **ALT Linux**, **РЕД ОС**).
2. **Контейнеризация (Docker):** Использование официальных образов в реестре `docker.angie.software`.
3. **Коммерческая версия (Angie Pro):** Требует лицензии и предоставляет расширенные функции (Active Health Checks, динамическое управление апстримами).
4. **Сборка из исходных кодов:** Необходима для кастомных сборок с нестандартными TLS-библиотеками (BoringSSL, QuicTLS).

## Практические сценарии

### Сценарий 1: Установка на RHEL-совместимые системы (AlmaLinux, Rocky, RedOS)

1. **Подключите репозиторий:**
   Создайте файл `/etc/yum.repos.d/angie.repo`:

   ```ini
   [angie]
   name=angie
   baseurl=https://download.angie.software/angie/el/$releasever/$basearch/
   gpgcheck=1
   gpgkey=https://angie.software/keys/angie-signing-key.gpg.asc
   enabled=1
   ```

2. **Выполните установку:**

   ```bash
   sudo dnf install -y angie
   ```

### Сценарий 2: Установка на Ubuntu / Debian

1. **Добавьте ключи и репозиторий:**

   ```bash
   sudo apt update
   sudo apt install -y ca-certificates curl gnupg2 lsb-release
   
   # Импорт ключа подписи
   sudo curl -o /etc/apt/trusted.gpg.d/angie-signing.gpg https://angie.software/keys/angie-signing.gpg
   
   # Добавление репозитория
   echo "deb https://download.angie.software/angie/$(. /etc/os-release && echo "$ID/$VERSION_ID $VERSION_CODENAME") main" \
   | sudo tee /etc/apt/sources.list.d/angie.list > /dev/null
   ```

2. **Выполните установку:**

   ```bash
   sudo apt update
   sudo apt install -y angie
   ```

### Сценарий 3: Установка на российские ОС (Astra Linux, ALT Linux)

#### Astra Linux (Special Edition)
Процесс аналогичен Debian, но требует учета версии и режима безопасности.
1. Добавьте репозиторий Angie, используя кодовое имя `1.7` или `1.8` (в зависимости от версии Astra).
2. В системах с замкнутой программной средой установите пакет `angie-digsig-key` для проверки подписей.

#### ALT Linux (Сизиф, p10, p11)
Angie включен в официальные репозитории «Альт».
```bash
sudo apt-get update
sudo apt-get install -y angie
```

### Сценарий 4: Запуск в Docker-контейнере

1. **Установите Docker:**
   Для установки Docker Engine следуйте руководству: **[Установка Docker на Ubuntu](../../Docker/docker_install_ubuntu.md)**.

2. **Запустите контейнер Angie:**
   Для сохранения конфигурации и данных рекомендуется использовать **[тома Docker (Volumes)](../../Docker/Docker_fs/docker_volumes.md)**.

   ```bash
   # Создание директорий на хосте
   mkdir -p ~/angie_config ~/angie_html
   
   # Копирование дефолтной конфигурации из временного контейнера
   docker run --rm --entrypoint cat docker.angie.software/angie:latest /etc/angie/angie.conf > ~/angie_config/angie.conf

   # Запуск постоянного контейнера
   docker run -d --name angie \
     -p 80:80 \
     -v ~/angie_html:/usr/share/nginx/html:ro \
     -v ~/angie_config/angie.conf:/etc/angie/angie.conf:ro \
     --restart always \
     docker.angie.software/angie:latest
   ```

3. **Применение изменений конфигурации:**
   При изменении `angie.conf` на хосте, отправьте сигнал `HUP` процессу в контейнере:

   ```bash
   docker exec -it angie angie -s reload
   ```

### Сценарий 5: Установка Angie Pro

Установка коммерческой версии требует наличия файлов лицензии (`angie-repo.crt`, `angie-repo.key`).

1. **Настройка аутентификации (Debian/Ubuntu):**
   Разместите ключи в `/etc/ssl/angie/` (права `600`) и настройте `apt`:

   ```bash
   # /etc/apt/apt.conf.d/90angie-pro
   Acquire::https::download.angie.software {
       Verify-Peer "true";
       Verify-Host "true";
       Ssl-Certificate "/etc/ssl/angie/angie-repo.crt";
       Ssl-Key "/etc/ssl/angie/angie-repo.key";
   };
   ```

2. **Установка пакета:**

   ```bash
   sudo apt update
   sudo apt install -y angie-pro
   ```

### Сценарий 6: Сборка из исходных кодов

Сборка из исходников необходима при использовании кастомных TLS-библиотек (например, BoringSSL или AWS-LC), специфических сторонних модулей или при необходимости изменить параметры компиляции, недоступные в пакетной версии.

#### 1. Подготовка зависимостей

Для сборки требуются библиотеки для регулярных выражений (PCRE), сжатия (Zlib), шифрования (OpenSSL) и стандартный набор инструментов разработки.

**"Ленивый" метод (через официальный репозиторий):**
Если в системе уже подключен официальный репозиторий Angie, можно автоматически установить все зависимости, необходимые для сборки текущей версии.

```bash
# Включите репозиторий исходного кода (deb-src) в /etc/apt/sources.list.d/angie.list
sudo sed -i 's/^deb /deb-src /' /etc/apt/sources.list.d/angie.list
sudo apt update

# Установка всех зависимостей сборки одной командой
sudo apt build-dep angie
```

**Ручной метод (минимальный набор):**
```bash
sudo apt install build-essential libpcre3-dev zlib1g-dev libssl-dev
```

#### 2. Конфигурация (`configure`)

Рекомендуется использовать параметры конфигурации от стандартного пакета как базу, чтобы сохранить пути к логам и конфигам.

```bash
# Получение текущих параметров
angie -V 2>&1 | grep "configure arguments"

# Пример запуска с кастомным OpenSSL
./configure --with-openssl=/path/to/openssl-src \
            --with-http_v3_module \
            --prefix=/etc/angie \
            --sbin-path=/usr/sbin/angie \
            --conf-path=/etc/angie/angie.conf
```

**Ключевые особенности конфигурации:**
*   **Статическая линковка:** `--with-openssl=/path/` заставит компилятор включить библиотеку непосредственно в бинарный файл.
*   **Динамические модули:** `--with-http_module=dynamic` создаст отдельный `.so` файл, который нужно подключать через `load_module` в конфиге.
*   **Сторонние модули:** `--add-module=/path/to/module` или `--add-dynamic-module=/path/to/module`.

> **Важно:** Если при повторном запуске `configure` после установки недостающих библиотек ошибки сохраняются, попробуйте удалить кэш (директория `angie_fch_cache` или аналогичная, если она была указана в параметрах).

#### 3. Сборка сторонних модулей (на примере Brotli)

Некоторые модули требуют предварительной сборки своих библиотек-зависимостей.

```bash
# Клонирование и сборка библиотеки Brotli
git clone --recursive https://github.com/google/ngx_brotli
cd ngx_brotli/deps/brotli
mkdir out && cd out
cmake -DCMAKE_BUILD_TYPE=Release ..
make && make install
cd ../../../..

# Сборка Angie с модулем Brotli
./configure --add-module=../ngx_brotli
make -j$(nproc)
```

#### 4. Установка и упаковка

Вместо прямого `make install` (который не создает системных юнитов и затрудняет удаление), рекомендуется использовать упаковку.

**Метод 1: CheckInstall (быстрый DEB-пакет)**
Создает простой пакет, который можно легко удалить через `apt remove`.
```bash
sudo apt install checkinstall
sudo checkinstall --pkgname=angie-custom --pkgversion=1.x.x
```

**Метод 2: Сборка из Source-пакета (полноценный метод)**
Позволяет создать пакет, идентичный официальному, с корректными `systemd` юнитами и правами доступа.
```bash
apt source angie
cd angie-1.x.x
# Отредактируйте файл debian/rules, добавив свои параметры в секцию конфига
dpkg-buildpackage -b -us -uc
```

## Дополнительная информация

### Динамические модули

Angie поддерживает установку популярных модулей (Brotli, ModSecurity) в виде готовых пакетов, что исключает необходимость компиляции. Пакеты имеют префикс `angie-module-`.

**Пример установки и подключения:**

```bash
# Установка модуля Brotli
sudo apt install angie-module-brotli

# Подключение в /etc/angie/angie.conf
load_module modules/ngx_http_brotli_filter_module.so;
```

## См. также

- [Обзор возможностей Angie](./angie_overview.md)
- [Миграция с Nginx на Angie](./migration_from_nginx.md)
- [Настройка TLS в Angie](./angie_tls_setup.md)
