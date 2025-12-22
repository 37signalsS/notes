# Установка и базовая настройка Nginx

## 1. Определения

**Nginx** — это веб-сервер и обратный прокси-сервер, используемый для обслуживания веб-контента, балансировки нагрузки, кэширования и многого другого.

**Виртуальный хост (Server Block)** — блок конфигурации, описывающий отдельный сайт (домен). Позволяет одному серверу Nginx обслуживать множество сайтов.

> Для более глубокого обзора архитектуры и ключевых концепций обратитесь к файлу **[[./nginx_overview.md|Обзор Nginx]]**.

---

## 2. Базовые концепции: Структура конфигурации

Понимание структуры конфигурационных файлов является ключом к работе с Nginx.

*   **Главный файл:** `/etc/nginx/nginx.conf`. Это точка входа, которая подключает остальные файлы. Содержит глобальные настройки, такие как `user` и `worker_processes`.

*   **Конфигурация сайтов (Виртуальных хостов):**
    *   **Debian/Ubuntu:** Используется система `sites-available` / `sites-enabled`.
        *   `/etc/nginx/sites-available/`: Содержит файлы конфигурации для всех сайтов.
        *   `/etc/nginx/sites-enabled/`: Содержит символические ссылки на файлы в `sites-available`, которые вы хотите активировать. Nginx читает только эту директорию.
    *   **CentOS/RHEL:** Используется директория `conf.d`.
        *   `/etc/nginx/conf.d/*.conf`: Nginx автоматически подключает все `.conf` файлы из этой директории. Сюда помещаются конфигурации всех сайтов.

---

## 3. Практические сценарии

### 3.1. Установка

#### Debian / Ubuntu
```bash
sudo apt update
sudo apt install nginx
```

#### CentOS / RHEL
```bash
# CentOS 7
sudo yum install epel-release && sudo yum install nginx

# CentOS 8+ / RHEL 8+
sudo dnf install epel-release && sudo dnf install nginx
```
*Замечание: В CentOS/RHEL пакет Nginx находится в репозитории EPEL (Extra Packages for Enterprise Linux), который может потребоваться установить.*

### 3.2. Управление сервисом

После установки Nginx обычно не запускается автоматически (особенно в CentOS/RHEL).

*   **Проверить статус:** `sudo systemctl status nginx`
*   **Запустить сервис:** `sudo systemctl start nginx`
*   **Добавить в автозагрузку:** `sudo systemctl enable nginx`
*   **Остановить сервис:** `sudo systemctl stop nginx`
*   **Перезагрузить конфигурацию:** `sudo systemctl reload nginx`
*   **Перезапустить сервис:** `sudo systemctl restart nginx`

### 3.3. Пример базовой конфигурации сайта

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

5.  **Проверьте и перезагрузите Nginx (см. раздел "Продвинутые детали"):**
    ```bash
    sudo nginx -t
    sudo systemctl reload nginx
    ```

Теперь при обращении к `http://example.com` (если DNS настроен) вы должны увидеть "Hello from Nginx!".

---

## 4. Продвинутые детали: Применение изменений

Nginx считывает конфигурацию только при запуске. Чтобы изменения вступили в силу, необходимо дать ему сигнал перечитать файлы.

**Правильная процедура:**

1.  **Проверка синтаксиса (Обязательно!):**
    Всегда проверяйте конфигурацию на наличие ошибок перед ее применением. Это защитит работающий сервер от сбоев.
    ```bash
    sudo nginx -t
    ```
    Если все в порядке, вы увидите `syntax is ok` и `test is successful`.

2.  **Грациозная перезагрузка (`reload`):**
    Эта команда плавно применяет новую конфигурацию, обеспечивая **нулевое время простоя (zero downtime)**. Мастер-процесс Nginx читает новую конфигурацию и запускает новые рабочие процессы, в то время как старые рабочие процессы завершают обслуживание текущих запросов и после этого gracefully завершаются.
    ```bash
    sudo systemctl reload nginx
    ```

3.  **Полный перезапуск (`restart`):**
    **Никогда не используйте `restart`** для простого применения изменений конфигурации. Эта команда полностью останавливает все процессы Nginx и запускает их заново, что приводит к кратковременному простою и обрыву всех текущих соединений. `restart` следует использовать только в крайних случаях, например, при обновлении версии Nginx или если `reload` не помогает.

---
## Смотри также
*   [[./nginx_overview.md|Обзор Nginx]]
*   [[./nginx_location_directive.md|Глубокое погружение в директиву location]]
*   [[./nginx_rewrite_rules_and_try_files.md|Правила Rewrite, Redirect и Директива try_files]]
