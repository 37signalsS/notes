# Установка и базовая настройка Nginx

Этот документ описывает установку, базовую настройку и управление сервисом Nginx в популярных дистрибутивах Linux.

> Для обзора архитектуры, ключевых концепций и карты документации, обратитесь к файлу **[[nginx_overview|Обзор Nginx]]**.

## 1. Установка

### Debian / Ubuntu
```bash
sudo apt update
sudo apt install nginx
```

### CentOS / RHEL
```bash
# CentOS 7
sudo yum install epel-release && sudo yum install nginx

# CentOS 8+ / RHEL 8+
sudo dnf install epel-release && sudo dnf install nginx
```
*Замечание: В CentOS/RHEL пакет Nginx находится в репозитории EPEL (Extra Packages for Enterprise Linux), который может потребоваться установить.*

## 2. Управление сервисом

После установки Nginx обычно не запускается автоматически (особенно в CentOS/RHEL).

*   **Проверить статус:**
    ```bash
    sudo systemctl status nginx
    ```
*   **Запустить сервис:**
    ```bash
    sudo systemctl start nginx
    ```
*   **Добавить в автозагрузку:**
    ```bash
    sudo systemctl enable nginx
    ```
*   **Остановить сервис:**
    ```bash
    sudo systemctl stop nginx
    ```

### Применение изменений конфигурации

Nginx считывает конфигурацию только при запуске. Чтобы изменения вступили в силу, необходимо дать ему сигнал перечитать файлы.

**Правильная процедура:**

1.  **Проверка синтаксиса (Обязательно!):**
    Всегда проверяйте конфигурацию на наличие ошибок перед ее применением. Это защитит работающий сервер от сбоев.
    ```bash
    sudo nginx -t
    ```
    Если все в порядке, вы увидите `syntax is ok` и `test is successful`.

2.  **Грациозная перезагрузка (Graceful Reload):**
    Эта команда плавно применяет новую конфигурацию, обеспечивая **нулевое время простоя (zero downtime)**.
    ```bash
    sudo systemctl reload nginx
    ```
    **Никогда не используйте `restart`** для применения изменений конфигурации, так как это приводит к полной остановке и перезапуску сервера, обрывая текущие соединения.

## 3. Структура конфигурационных файлов

*   **Главный файл:** `/etc/nginx/nginx.conf`. Это точка входа, которая подключает остальные файлы. Содержит глобальные настройки, такие как `user` и `worker_processes`.

*   **Конфигурация сайтов:**
    *   **Debian/Ubuntu:** Используется система `sites-available` / `sites-enabled`.
        *   `/etc/nginx/sites-available/`: Содержит файлы конфигурации для всех сайтов.
        *   `/etc/nginx/sites-enabled/`: Содержит символические ссылки на файлы в `sites-available`, которые вы хотите активировать. Nginx читает только эту директорию.
    *   **CentOS/RHEL:** Используется директория `conf.d`.
        *   `/etc/nginx/conf.d/*.conf`: Nginx автоматически подключает все `.conf` файлы из этой директории. Сюда помещаются конфигурации всех сайтов.

## 4. Пример базовой конфигурации сайта

Это минимальная конфигурация для обслуживания статического сайта.

1.  **Создайте файл конфигурации:**
    *   На Ubuntu: `sudo nano /etc/nginx/sites-available/example.com`
    *   На CentOS: `sudo nano /etc/nginx/conf.d/example.com.conf`

2.  **Добавьте содержимое:**
    ```nginx
    server {
        listen 80;
        listen [::]:80;

        server_name example.com www.example.com;

        root /var/www/example.com;
        index index.html;

        location / {
            try_files $uri $uri/ =404;
        }
    }
    ```

3.  **Создайте корневую директорию и тестовый файл:**
    ```bash
    sudo mkdir -p /var/www/example.com
    echo "Hello from Nginx!" | sudo tee /var/www/example.com/index.html
    ```

4.  **Активируйте сайт (только для Debian/Ubuntu):**
    ```bash
    sudo ln -s /etc/nginx/sites-available/example.com /etc/nginx/sites-enabled/
    ```

5.  **Проверьте и перезагрузите Nginx:**
    ```bash
    sudo nginx -t
    sudo systemctl reload nginx
    ```

Теперь при обращении к `http://example.com` (если DNS настроен) вы должны увидеть "Hello from Nginx!".

---
За более подробной информацией о концепциях, таких как `server` блоки, `location` и `try_files`, обратитесь к **[[nginx_overview|Обзору Nginx]]** и связанным документам.
