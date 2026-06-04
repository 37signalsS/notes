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
