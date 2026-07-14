# Установка Angie

## Определения

**Angie** — эффективный и масштабируемый веб-сервер, форк Nginx, созданный для расширения функциональности при сохранении полной обратной совместимости. Основные отличия включают встроенный HTTP/3, динамические модули и расширенный мониторинг.

## Основные концепции

Существует три основных способа развертывания Angie, выбор которых зависит от целевой среды и требований к поддержке:

1. **Установка из официальных репозиториев:** Рекомендуемый метод для серверных ОС (ALMA-Linux, Ubuntu, Debian), обеспечивающий простую установку и обновление через системные пакетные менеджеры (`dnf`, `apt`).
2. **Контейнеризация (Docker):** Использование официальных образов для изоляции веб-сервера от хостовой системы. Подходит для микросервисных архитектур и сред оркестрации.
3. **Коммерческая версия (Angie Pro):** Требует лицензии и предоставляет дополнительные функции (Active Health Checks, Feedback Balancing). Использует защищенные репозитории.

## Практические сценарии

### Сценарий 1: Установка на AlmaLinux (RHEL-based)

1. **Подключите репозиторий:**
   Создайте файл `/etc/yum.repos.d/angie.repo`:

   ```ini
   [angie]
   name=angie
   baseurl=https://download.angie.software/rhel/$releasever/$basearch/
   gpgcheck=1
   gpgkey=https://download.angie.software/keys/angie-signing-key.gpg
   enabled=1
   ```

2. **Выполните установку:**

   ```bash
   sudo dnf install -y angie
   ```

3. **Проверьте корректность установки:**

   ```bash
   sudo angie -t
   # → angie: the configuration file /etc/angie/angie.conf syntax is ok
   # → angie: configuration file /etc/angie/angie.conf test is successful

   sudo systemctl enable --now angie
   sudo systemctl status angie
   # → active (running)
   ```

### Сценарий 2: Установка на Ubuntu / Debian

1. **Добавьте ключи и репозиторий:**

   ```bash
   sudo apt update
   sudo apt install -y curl gpg
   curl -o /etc/apt/trusted.gpg.d/angie-signing-key.gpg https://download.angie.software/keys/angie-signing-key.gpg
   echo "deb https://download.angie.software/ubuntu/ `lsb_release -cs` main" | sudo tee /etc/apt/sources.list.d/angie.list >/dev/null
   ```

2. **Выполните установку:**

   ```bash
   sudo apt update
   sudo apt install -y angie
   ```

3. **Запустите сервис и проверьте статус:**

   ```bash
   sudo systemctl status angie
   # → active (running)
   ```

### Сценарий 3: Запуск в Docker-контейнере

1. **Установите Docker:**
   Для установки Docker Engine следуйте руководству: **[Установка Docker на Ubuntu](../../Docker/docker_install_ubuntu.md)**.

2. **Запустите контейнер Angie:**
   Для сохранения конфигурации и данных рекомендуется использовать **[тома Docker (Volumes)](../../Docker/Docker_fs/docker_volumes.md)**.

   ```bash
   # Создание директорий на хосте
   mkdir -p ~/angie_config ~/angie_html
   
   # Копирование дефолтной конфигурации из временного контейнера
   docker run --rm --entrypoint cat docker.ngsoftware/angie:latest /etc/angie/angie.conf > ~/angie_config/angie.conf

   # Запуск постоянного контейнера
   docker run -d --name angie \
     -p 80:80 \
     -v ~/angie_html:/usr/share/nginx/html:ro \
     -v ~/angie_config/angie.conf:/etc/angie/angie.conf:ro \
     --restart always \
     docker.ngsoftware/angie:latest
   ```

3. **Применение изменений конфигурации:**
   При изменении `angie.conf` на хосте, отправьте сигнал `HUP` процессу в контейнере:

   ```bash
   docker exec -it angie angie -s reload
   ```

### Сценарий 4: Установка Angie Pro

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

3. **Активация лицензии:**
   Разместите файл `license.pem` в `/etc/angie/` и выполните `sudo systemctl reload angie`.

### Сценарий 5: Сборка из исходных кодов

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

**Связанные темы:**

- [Обзор возможностей Angie](./angie_overview.md)
- [Миграция с Nginx на Angie](./migration_from_nginx.md)
- [Настройка TLS в Angie](./angie_tls_setup.md)
- [Мониторинг Angie](./angie_monitoring/angie_monitoring_concepts.md)
